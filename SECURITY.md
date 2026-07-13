# Security Policy

SecureVote is a security-engineering portfolio prototype and local evidence
package. It is not a hosted election service, certified election system, or bug
bounty program. Do not use it with real voter data, ballots, credentials, keys,
or election infrastructure.

## Supported scope

Security fixes target the latest commit on `main`. Historical coursework copies,
forks, screenshots, and third-party deployments are not supported by this policy.

In scope:

- vulnerabilities in the source, tests, Docker configuration, or documented local
  demo workflow in this repository;
- flaws that break the documented identity, ballot-authority, anonymity,
  authorization, audit, signing, or production-safety boundaries;
- accidental secret exposure or unsafe instructions in tracked project files;
- accessibility defects that prevent independent review of security-critical
  evidence or warnings.

Out of scope:

- testing against election authorities, voter systems, or third-party services;
- use of real PII, ballot data, election keys, or credentials;
- denial of service, social engineering, phishing, persistence, or destructive
  testing;
- claims about legal compliance, election certification, coercion resistance, or
  production readiness;
- vulnerabilities in dependencies that are already fixed by upgrading to the
  versions pinned on `main`.

## Report privately

Use GitHub's private vulnerability reporting for this repository when available.
If that is not available, email <meidie@mdpstudio.com.au> with the subject
`[Security] SecureVote report`.

Include:

- the affected file, route, or configuration;
- minimal reproduction steps using synthetic local data;
- the expected security impact and affected trust boundary;
- logs or screenshots with tokens, keys, cookies, voter data, and unrelated
  personal information removed;
- a suggested fix, if you have one.

Do not open a public issue containing exploit details or sensitive material. Stop
testing immediately if you encounter data or systems outside your own local
environment.

## Response expectations

This is a personal portfolio project. Credible reports should receive an
acknowledgement within 5 business days and a remediation update after triage.
There is no paid bounty or guaranteed resolution timeline. Please coordinate
public disclosure until a fix or reasonable mitigation is available.

## Security claims boundary

The cryptographic controls, WAF configuration, tests, threat model, and mock
verification ceremony are review evidence, not an independent audit. A passing
test suite or completed rehearsal does not establish that a real election is
private, correct, accessible, legally compliant, or safe to operate.
