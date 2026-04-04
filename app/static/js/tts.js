/**
 * SecureVote — Text-to-Speech Accessibility Module
 *
 * Uses the browser's built-in Web Speech API (speechSynthesis).
 * No external dependencies or API keys required.
 *
 * Features:
 * - Floating TTS control button (bottom-right corner)
 * - Click any text element to have it read aloud
 * - "Read page" button reads the entire main content
 * - Keyboard shortcut: Alt+T to toggle TTS mode
 * - Respects prefers-reduced-motion
 */

'use strict';

(function() {
  if (!('speechSynthesis' in window)) return; // Unsupported browser

  let ttsActive = false;
  let currentUtterance = null;

  // --- Create floating control panel ---
  const panel = document.createElement('div');
  panel.id = 'sv-tts-panel';
  panel.innerHTML = `
    <button id="sv-tts-toggle" title="Toggle Text-to-Speech (Alt+T)" aria-label="Toggle text-to-speech mode">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
        <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
      </svg>
    </button>
    <div id="sv-tts-controls" style="display:none">
      <button id="sv-tts-read-page" title="Read entire page">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15z"></path></svg>
        Read Page
      </button>
      <button id="sv-tts-stop" title="Stop reading">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>
        Stop
      </button>
    </div>
  `;
  document.body.appendChild(panel);

  // --- Styles ---
  const style = document.createElement('style');
  style.textContent = `
    #sv-tts-panel {
      position: fixed;
      bottom: 1.5rem;
      right: 1.5rem;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: .5rem;
      font-family: 'Inter', system-ui, sans-serif;
    }
    #sv-tts-panel button {
      background: #6366f1;
      color: #fff;
      border: none;
      border-radius: 12px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: .4rem;
      font-size: .8rem;
      font-weight: 500;
      transition: background .15s, transform .1s;
      box-shadow: 0 4px 12px rgba(99,102,241,.3);
    }
    #sv-tts-panel button:hover {
      background: #4f46e5;
      transform: translateY(-1px);
    }
    #sv-tts-toggle {
      width: 48px;
      height: 48px;
      border-radius: 50%;
      justify-content: center;
      padding: 0;
    }
    #sv-tts-toggle.active {
      background: #10b981;
      box-shadow: 0 4px 12px rgba(16,185,129,.3);
    }
    #sv-tts-toggle.active:hover { background: #059669; }
    #sv-tts-controls button {
      padding: .5rem .75rem;
    }
    #sv-tts-controls {
      display: flex;
      flex-direction: column;
      gap: .35rem;
      align-items: flex-end;
    }
    .sv-tts-highlight {
      outline: 3px solid #6366f1 !important;
      outline-offset: 2px;
      border-radius: 4px;
      cursor: pointer;
    }
    body.sv-tts-mode * {
      cursor: crosshair;
    }
    body.sv-tts-mode .sv-tts-highlight {
      cursor: pointer;
    }
    @media (prefers-reduced-motion: reduce) {
      #sv-tts-panel button { transition: none; }
    }
  `;
  document.head.appendChild(style);

  const toggleBtn = document.getElementById('sv-tts-toggle');
  const controls = document.getElementById('sv-tts-controls');
  const readPageBtn = document.getElementById('sv-tts-read-page');
  const stopBtn = document.getElementById('sv-tts-stop');

  // --- Speak text ---
  function speak(text) {
    speechSynthesis.cancel();
    if (!text || !text.trim()) return;

    const utterance = new SpeechSynthesisUtterance(text.trim());
    utterance.rate = 0.95;
    utterance.pitch = 1;
    utterance.lang = 'en-AU';
    currentUtterance = utterance;

    utterance.onend = () => { currentUtterance = null; };
    utterance.onerror = () => { currentUtterance = null; };

    speechSynthesis.speak(utterance);
  }

  // --- Click handler for TTS mode ---
  function handleTTSClick(e) {
    if (!ttsActive) return;

    // Don't intercept clicks on the TTS panel itself
    if (e.target.closest('#sv-tts-panel')) return;

    e.preventDefault();
    e.stopPropagation();

    const el = e.target.closest('h1, h2, h3, h4, h5, h6, p, td, th, li, span, a, button, label, .alert, .sv-stat-card, .sv-badge, .card-body, .card-header');
    if (el) {
      speak(el.textContent);
    }
  }

  // --- Hover highlight ---
  let lastHighlight = null;
  function handleTTSHover(e) {
    if (!ttsActive) return;
    if (e.target.closest('#sv-tts-panel')) return;

    const el = e.target.closest('h1, h2, h3, h4, h5, h6, p, td, th, li, span, a, button, label, .alert, .sv-stat-card, .sv-badge, .card-body, .card-header');

    if (lastHighlight && lastHighlight !== el) {
      lastHighlight.classList.remove('sv-tts-highlight');
    }
    if (el) {
      el.classList.add('sv-tts-highlight');
      lastHighlight = el;
    }
  }

  // --- Toggle TTS mode ---
  function toggleTTS() {
    ttsActive = !ttsActive;
    toggleBtn.classList.toggle('active', ttsActive);
    controls.style.display = ttsActive ? 'flex' : 'none';
    document.body.classList.toggle('sv-tts-mode', ttsActive);

    if (ttsActive) {
      speak('Text to speech enabled. Click any text to hear it read aloud.');
      document.addEventListener('click', handleTTSClick, true);
      document.addEventListener('mouseover', handleTTSHover);
    } else {
      speechSynthesis.cancel();
      document.removeEventListener('click', handleTTSClick, true);
      document.removeEventListener('mouseover', handleTTSHover);
      if (lastHighlight) {
        lastHighlight.classList.remove('sv-tts-highlight');
        lastHighlight = null;
      }
    }
  }

  // --- Read full page ---
  function readPage() {
    const main = document.getElementById('main-content');
    if (main) {
      speak(main.textContent);
    }
  }

  // --- Event listeners ---
  toggleBtn.addEventListener('click', toggleTTS);
  readPageBtn.addEventListener('click', readPage);
  stopBtn.addEventListener('click', () => { speechSynthesis.cancel(); });

  // Keyboard shortcut: Alt+T
  document.addEventListener('keydown', (e) => {
    if (e.altKey && e.key === 't') {
      e.preventDefault();
      toggleTTS();
    }
  });
})();
