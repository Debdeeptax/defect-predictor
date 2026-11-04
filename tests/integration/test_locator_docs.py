"""Keeps docs/selenium-locators.md in sync with the templates: every data-testid used in
app/templates must be documented (dynamic parts as <placeholders>)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "app" / "templates"
DOC = ROOT / "docs" / "selenium-locators.md"

JINJA = re.compile(r"\{%.*?%\}.*?\{%.*?%\}|\{\{.*?\}\}")
PLACEHOLDER = re.compile(r"<[^>]+>")


def template_testids() -> set[str]:
    ids = set()
    for path in TEMPLATE_DIR.rglob("*.html"):
        for raw in re.findall(r'data-testid="([^"]+)"', path.read_text(encoding="utf-8")):
            norm = JINJA.sub("*", raw)
            if norm.startswith("*"):  # fully dynamic (macro prefix) – documented by concrete prefixes
                continue
            ids.add(norm)
    return ids


def documented_testids() -> set[str]:
    text = DOC.read_text(encoding="utf-8").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # fenced code would break `pairing`
    ids = set()
    for token in re.findall(r"`([^`]+)`", text):
        if re.fullmatch(r"[a-z0-9<>\-]+", token) and "-" in token:
            ids.add(PLACEHOLDER.sub("*", token))
    return ids


def test_every_template_testid_is_documented():
    missing = sorted(template_testids() - documented_testids())
    assert not missing, "Add these to docs/selenium-locators.md: " + ", ".join(missing)


def test_macro_generated_testids_are_documented():
    # risk_badge(prefix=...) / status_marker generate these families.
    doc = documented_testids()
    for family in ("risk-badge-*", "unit-risk-badge-*-*", "compare-risk-a-*", "compare-risk-b-*",
                   "status-done", "status-failed", "status-running"):
        assert family in doc, family
