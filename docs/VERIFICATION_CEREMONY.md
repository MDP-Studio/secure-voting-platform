# Mock Election Verification Ceremony

The public `/verification-ceremony` page is a data-free rehearsal for the human
process around election-result evidence. It helps reviewers practise an
independent comparison, record stop conditions, and explain what remains
unproven.

It is not an election verifier, certification ceremony, usability study, or
production election workflow. It does not fetch, accept, validate, transmit, or
store ballots, result files, cryptographic keys, signatures, voter data, or
observer notes.

## Rehearsal sequence

Two or more observers should:

1. Confirm that the exercise uses no real election data.
2. Practise obtaining an evidence package through independent channels.
3. Compare a hypothetical identifier and digest character by character.
4. Identify the expected authority key, verifier, and invalid-signature output.
5. Rehearse tally and audit-chain reconciliation, including a stop decision.
6. Have an independent observer explain the evidence limits before closing.

The page records checklist state only in the current document. It does not use
cookies, local storage, network requests, or server-side persistence.

## Stop conditions

Observers stop the ceremony and preserve the evidence when:

- package identifiers or digests differ;
- a verification key is missing or cannot be authenticated independently;
- a result signature is missing or invalid;
- published totals do not reconcile with accepted and rejected records;
- an audit-chain verification fails;
- an observer cannot reproduce or access an essential check.

A restart is appropriate only after the discrepancy and any evidence replacement
are documented. Completion by a majority does not override a failed check.

## Trust assumptions

A real ceremony would still depend on assumptions outside this prototype:

- the published verification key belongs to the stated authority;
- observers receive complete and unmodified evidence packages;
- verifier software and observer devices are trustworthy;
- accepted, rejected, and challenged ballots are governed and accounted for;
- custody, registration, availability, accessibility, voter intent, and coercion
  risks are addressed through independent controls;
- qualified independent reviewers assess the full cryptographic protocol and
  election process.

## Evidence limits

Completing the rehearsal shows only that a reviewer can follow the documented
sequence in the prototype UI. It does not prove that:

- any ballot was cast, recorded, counted, or kept secret;
- the authority key or result package is authentic;
- voter devices or election infrastructure were uncompromised;
- the system provides end-to-end verifiability or coercion resistance;
- the workflow meets electoral law, certification, governance, or operational
  requirements;
- every user can complete the flow with their assistive technology.

## Accessibility verification

The page uses native checkboxes, a native reset button, a labelled progress
element, an announced status region, semantic headings and landmarks, visible
focus styles, 44-pixel label targets, and source-order instructions. It does not
depend on colour to communicate decisions.

Automated structural and behaviour checks run with the existing pytest stack:

```bash
python -m pytest tests/test_verification_ceremony.py -q
```

The tests cover public access, semantic labels, heading order, native interactive
controls, the live status region, prototype limitations, and the browser script's
progress, completion, and reset behaviour.

Automated checks do not replace manual testing. Before making a broader
accessibility claim, test the page with:

- keyboard-only navigation at desktop and mobile widths;
- NVDA with Firefox or Chrome on Windows;
- VoiceOver with Safari on macOS or iOS;
- 200 percent zoom and browser text enlargement;
- Windows High Contrast or forced-colours mode;
- reduced-motion settings.

Manual assistive-technology validation has not been claimed by this repository.

## Review evidence

- Route: `app/routes/main.py`
- Template: `app/templates/verification_ceremony.html`
- Browser behaviour: `app/static/js/verification_ceremony.js`
- Focus, target, and responsive styles: `app/static/css/theme.css`
- Automated checks: `tests/test_verification_ceremony.py`
- Related trust boundaries: `app/templates/threat_model.html`
