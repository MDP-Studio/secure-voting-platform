"""Accessibility and behaviour evidence for the public mock ceremony."""

from html.parser import HTMLParser
from pathlib import Path


class CeremonyMarkupParser(HTMLParser):
    """Collect the small set of semantics this page guarantees."""

    def __init__(self):
        super().__init__()
        self.checkboxes = []
        self.heading_levels = []
        self.labels_for = set()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if tag == "input" and attributes.get("type") == "checkbox":
            self.checkboxes.append(attributes)
        if tag == "label" and attributes.get("for"):
            self.labels_for.add(attributes["for"])
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_levels.append(int(tag[1]))


def _parse(response):
    parser = CeremonyMarkupParser()
    parser.feed(response.get_data(as_text=True))
    return parser


def test_verification_ceremony_is_public_and_data_free(client):
    response = client.get("/verification-ceremony")
    content = " ".join(response.get_data(as_text=True).split())

    assert response.status_code == 200
    assert "Set-Cookie" not in response.headers
    assert b"Election Verification Rehearsal" in response.data
    assert "does not load, verify, transmit, or store real election data" in content
    assert "not a real election verification" in content


def test_verification_ceremony_rejects_submission(client):
    response = client.post("/verification-ceremony", data={"result": "approved"})

    assert response.status_code == 405


def test_checkboxes_have_programmatic_labels_and_native_controls(client):
    response = client.get("/verification-ceremony")
    parser = _parse(response)

    assert len(parser.checkboxes) == 6
    assert all(checkbox.get("id") in parser.labels_for for checkbox in parser.checkboxes)
    assert all("data-ceremony-check" in checkbox for checkbox in parser.checkboxes)
    assert any(tag == "button" and attrs.get("type") == "reset" for tag, attrs in parser.elements)
    assert not any("onclick" in attrs for _, attrs in parser.elements)
    assert not any(int(attrs.get("tabindex", "0")) > 0 for _, attrs in parser.elements)


def test_page_has_screen_reader_status_and_progress_semantics(client):
    response = client.get("/verification-ceremony")
    parser = _parse(response)

    assert any(
        tag == "output"
        and attrs.get("role") == "status"
        and attrs.get("aria-live") == "polite"
        for tag, attrs in parser.elements
    )
    assert any(
        tag == "progress"
        and attrs.get("max") == "6"
        and attrs.get("aria-describedby") == "ceremony-status"
        for tag, attrs in parser.elements
    )
    assert any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.elements)


def test_page_uses_a_single_h1_without_heading_level_skips(client):
    response = client.get("/verification-ceremony")
    parser = _parse(response)

    assert parser.heading_levels.count(1) == 1
    assert parser.heading_levels[0] == 1
    assert all(
        current <= previous + 1
        for previous, current in zip(parser.heading_levels, parser.heading_levels[1:])
    )


def test_page_documents_trust_assumptions_and_failure_cases(client):
    response = client.get("/verification-ceremony")
    content = " ".join(response.get_data(as_text=True).split())

    assert "Trust assumptions for a real ceremony" in content
    assert "Package identifier or digest mismatch" in content
    assert "Missing key or invalid result signature" in content
    assert "Tally or audit chain does not reconcile" in content
    assert "cannot reproduce or access a check" in content
    assert "end-to-end verifiable" in content


def test_browser_script_updates_and_resets_accessible_state():
    script = (
        Path(__file__).parents[1]
        / "app"
        / "static"
        / "js"
        / "verification_ceremony.js"
    ).read_text(encoding="utf-8")

    assert 'form.addEventListener("change", updateCeremonyState)' in script
    assert 'form.addEventListener("reset"' in script
    assert "progress.value = completed" in script
    assert "completion.hidden = completed !== total" in script
    assert "firstCheck.focus()" in script
    assert "No real election has been verified" in script
