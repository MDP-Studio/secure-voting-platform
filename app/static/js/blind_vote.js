/**
 * SecureVote — RSA Blind Signature Voting Client
 *
 * Implements the Chaum blind signature protocol (1983) in the browser
 * using native BigInt and Web Crypto API. No external dependencies.
 *
 * Protocol:
 *   1. Voter picks candidate, creates ballot JSON, generates random nonce
 *   2. Voter computes FDH(ballot) and blinds it: blinded = FDH * r^e mod n
 *   3. Voter sends blinded ballot to authenticated /vote/request-token
 *   4. Server blind-signs and returns blind_signature
 *   5. Voter unblinds: sig = blind_sig * r^(-1) mod n
 *   6. After random delay, voter submits ballot + sig to /vote/cast
 *      with credentials:'omit' (NO cookies — fully anonymous)
 */

'use strict';

// --- BigInt Math Utilities ---

function modPow(base, exp, mod) {
  base = ((base % mod) + mod) % mod;
  let result = 1n;
  while (exp > 0n) {
    if (exp & 1n) result = (result * base) % mod;
    exp >>= 1n;
    base = (base * base) % mod;
  }
  return result;
}

function modInverse(a, m) {
  let [old_r, r] = [a, m];
  let [old_s, s] = [1n, 0n];
  while (r !== 0n) {
    const q = old_r / r;
    [old_r, r] = [r, old_r - q * r];
    [old_s, s] = [s, old_s - q * s];
  }
  return ((old_s % m) + m) % m;
}

function bytesToBigInt(bytes) {
  let hex = '';
  for (const b of bytes) hex += b.toString(16).padStart(2, '0');
  return BigInt('0x' + (hex || '0'));
}

function bigIntToHex(n) {
  const h = n.toString(16);
  return h.length % 2 ? '0' + h : h;
}

function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2)
    bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
  return bytes;
}

// --- Full-Domain Hash (must match server's hash_ballot exactly) ---

async function hashBallot(ballotBytes, n) {
  // 1. seed = SHA-256(ballot)
  const seed = new Uint8Array(await crypto.subtle.digest('SHA-256', ballotBytes));
  // 2. Counter-mode expansion: 8 blocks of SHA-256(seed || i)
  const blocks = [];
  for (let i = 0; i < 8; i++) {
    const data = new Uint8Array(seed.length + 4);
    data.set(seed);
    data[seed.length] = (i >> 24) & 0xff;
    data[seed.length + 1] = (i >> 16) & 0xff;
    data[seed.length + 2] = (i >> 8) & 0xff;
    data[seed.length + 3] = i & 0xff;
    blocks.push(new Uint8Array(await crypto.subtle.digest('SHA-256', data)));
  }
  // 3. Concatenate (256 bytes total)
  const expanded = new Uint8Array(256);
  for (let i = 0; i < 8; i++) expanded.set(blocks[i], i * 32);
  // 4. Convert to BigInt, reduce mod n
  return bytesToBigInt(expanded) % n;
}

// --- Random Blinding Factor ---

function generateBlindingFactor(n) {
  // Generate random BigInt in [2, n-2] using crypto.getRandomValues
  const nBytes = Math.ceil(n.toString(16).length / 2);
  const buf = new Uint8Array(nBytes);
  let r;
  do {
    crypto.getRandomValues(buf);
    r = bytesToBigInt(buf) % n;
  } while (r < 2n);
  return r;
}

// --- Main Protocol ---

async function castBlindVote(candidateId, electionId, statusEl) {
  try {
    statusEl.textContent = 'Preparing ballot...';
    statusEl.className = 'alert alert-info mt-3';
    statusEl.style.display = 'block';

    // 1. Generate random nonce
    const nonceBytes = new Uint8Array(32);
    crypto.getRandomValues(nonceBytes);
    const nonce = Array.from(nonceBytes, b => b.toString(16).padStart(2, '0')).join('');

    // 2. Construct ballot JSON
    const ballot = JSON.stringify({
      candidate_id: candidateId,
      nonce: nonce,
      election_id: electionId
    });
    const ballotBytes = new TextEncoder().encode(ballot);
    const ballotHex = Array.from(ballotBytes, b => b.toString(16).padStart(2, '0')).join('');

    // 3. Fetch public key
    statusEl.textContent = 'Fetching signing key...';
    const keyResp = await fetch('/vote/blind-key');
    if (!keyResp.ok) throw new Error('Failed to fetch signing key');
    const keyData = await keyResp.json();
    const n = BigInt(keyData.n);
    const e = BigInt(keyData.e);

    // 4. Compute FDH(ballot)
    statusEl.textContent = 'Computing ballot hash...';
    const m = await hashBallot(ballotBytes, n);

    // 5. Generate blinding factor r, compute r^e mod n
    const r = generateBlindingFactor(n);
    const rE = modPow(r, e, n);

    // 6. Blind the ballot: blinded = m * r^e mod n
    const blinded = (m * rE) % n;

    // 7. Compute nonce hash for replay prevention
    const nonceHashBuf = await crypto.subtle.digest(
      'SHA-256', new TextEncoder().encode(nonce)
    );
    const nonceHash = Array.from(new Uint8Array(nonceHashBuf),
      b => b.toString(16).padStart(2, '0')).join('');

    // 8. Request blind signature (authenticated)
    statusEl.textContent = 'Requesting blind signature...';
    const tokenResp = await fetch('/vote/request-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', // Send session cookie
      body: JSON.stringify({
        blinded_ballot: bigIntToHex(blinded),
        nonce_hash: nonceHash
      })
    });

    if (!tokenResp.ok) {
      const err = await tokenResp.json().catch(() => ({}));
      throw new Error(err.error || 'Token request failed');
    }

    const tokenData = await tokenResp.json();
    const blindSig = BigInt(tokenData.blind_signature);

    // 9. Unblind the signature: sig = blind_sig * r^(-1) mod n
    statusEl.textContent = 'Unblinding signature...';
    const rInv = modInverse(r, n);
    const signature = (blindSig * rInv) % n;

    // 10. Random delay (5-30 seconds) to defeat timing correlation
    const delayMs = 5000 + (crypto.getRandomValues(new Uint16Array(1))[0] % 25000);
    const delaySec = Math.ceil(delayMs / 1000);
    for (let i = delaySec; i > 0; i--) {
      statusEl.textContent = `Securing anonymous ballot... (${i}s)`;
      await new Promise(r => setTimeout(r, 1000));
    }

    // 11. Cast ballot anonymously (NO cookies, NO session)
    statusEl.textContent = 'Casting anonymous ballot...';
    const castResp = await fetch('/vote/cast', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'omit', // NO cookies — fully anonymous
      body: JSON.stringify({
        ballot: ballotHex,
        signature: bigIntToHex(signature)
      })
    });

    if (!castResp.ok) {
      const err = await castResp.json().catch(() => ({}));
      throw new Error(err.error || 'Ballot submission failed');
    }

    statusEl.textContent = 'Vote cast successfully! Your ballot is anonymous.';
    statusEl.className = 'alert alert-success mt-3';

    // Reload after 2 seconds to show updated dashboard
    setTimeout(() => window.location.reload(), 2000);

  } catch (err) {
    statusEl.textContent = 'Error: ' + err.message;
    statusEl.className = 'alert alert-danger mt-3';
    console.error('Blind vote error:', err);
  }
}

// --- Wire up buttons ---

document.addEventListener('DOMContentLoaded', () => {
  const statusEl = document.getElementById('blind-vote-status');
  document.querySelectorAll('.blind-vote-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const candidateId = parseInt(btn.dataset.candidateId);
      const electionId = parseInt(btn.dataset.electionId || '0');
      const candidateName = btn.dataset.candidateName || 'this candidate';

      if (!confirm(`Cast your anonymous vote for ${candidateName}? This action is final and cannot be undone.`)) {
        return;
      }

      // Disable all vote buttons
      document.querySelectorAll('.blind-vote-btn').forEach(b => b.disabled = true);
      castBlindVote(candidateId, electionId, statusEl);
    });
  });
});
