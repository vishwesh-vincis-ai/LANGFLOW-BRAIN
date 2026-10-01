"""Abbreviated opening hours ("Fri. Closed") must be findable. Run: pytest -q  (needs the local Postgres)"""
import hashlib
import uuid
from pathlib import Path

import pytest

from brain import config, providers
from brain.db import connect
from brain.ingest import chunk, ingest, normalize
from brain.retrieve import search

FIXTURE = Path(__file__).parent / "fixtures" / "us_dental_home.md"
TENANT = "test-us-hours"


@pytest.mark.parametrize("raw,expected", [
    ("Fri. Closed. Sat. Closed.", "Friday Closed. Saturday Closed."),
    ("Mon. 8am – 5pm. Tue. 8am – 5pm.", "Monday 8am – 5pm. Tuesday 8am – 5pm."),
    ("Mon - Thu: 8am - 5pm", "Monday - Thursday: 8am - 5pm"),
    ("Tues 9-5, Thurs 9-5", "Tuesday 9-5, Thursday 9-5"),
    ("We open Wed 10am", "We open Wednesday 10am"),
    ("Sun 10:00 AM to 1:00 PM", "Sunday 10:00 AM to 1:00 PM"),
    ("Wear sun protection. Sat on the chair.", "Wear sun protection. Sat on the chair."),  # not days
    ("Monday to Saturday: 9:30 AM", "Monday to Saturday: 9:30 AM"),                    # already full
    # The last day of a range is a day even with no time after it.
    ("Open Mon–Sat", "Open Monday–Saturday"),
    ("Mon thru Fri 9-5", "Monday thru Friday 9-5"),
    ("Closed Sat/Sun", "Closed Saturday/Sunday"),
    ("Mon.–Fri. 9am–5pm", "Monday–Friday 9am–5pm"),
    ("Monday to Sat", "Monday to Saturday"),
    # Punctuation alone does not make a day: a range needs a day on both sides.
    ("Sun-kissed balayage", "Sun-kissed balayage"),
    ("Sun & Sand Spa package", "Sun & Sand Spa package"),
    ("Sun, sea and sand", "Sun, sea and sand"),
    ("Sun/UV protection advice", "Sun/UV protection advice"),
    ("Sat-nav directions", "Sat-nav directions"),
    ("Relax in the Sun. Then rest.", "Relax in the Sun. Then rest."),
])
def test_normalize_expands_day_abbreviations(raw, expected):
    assert normalize(raw) == expected


def test_schedule_section_is_labelled_as_hours():
    sections = dict(chunk(normalize(FIXTURE.read_text())))
    assert any("hours" in h.lower() for h in sections if "Schedule" in h)
    # A section that merely mentions one day is not a schedule.
    assert "hours" not in " ".join(h.lower() for h in sections if h == "Featured Services")


@pytest.fixture(scope="module")
def _hours_tenant():
    ingest(TENANT, "Lakeside Family Dental", [str(FIXTURE)])


@pytest.mark.parametrize("question", [
    "Are you open on Fridays?",
    "What are your hours?",
    "Are you open Saturday?",
    "When are you open?",
])
def test_hours_questions_retrieve_the_schedule(_hours_tenant, question):
    hits = search(TENANT, question)
    assert hits, f"nothing retrieved for {question!r}"
    assert "Schedule" in hits[0].heading, [h.heading for h in hits]


def test_chunker_upgrade_rebuilds_only_documents_whose_chunks_change(tmp_path, monkeypatch):
    """A new normalize() must not re-embed every tenant: documents it leaves alone keep their embeddings."""
    biz = f"test-{uuid.uuid4().hex[:8]}"
    plain, hours = tmp_path / "parking.md", tmp_path / "hours.md"
    plain.write_text("# FAQ\n\n## Parking\nFree parking behind the clinic.\n")
    hours.write_text("# FAQ\n\n## Schedule\nFri. Closed.\n")
    embedded: list[str] = []

    def fake_embed(texts, task="passage"):
        embedded.extend(texts)
        return [[0.1] * config.EMBED_DIM for _ in texts]

    monkeypatch.setattr(config, "EMBED_PROVIDER", "fake")
    monkeypatch.setattr(providers, "embed", fake_embed)
    assert ingest(biz, "Test", [str(plain), str(hours)])["added"] == 2

    # Make the rows look like the previous release wrote them: hash of the raw text, un-normalized chunks.
    with connect() as conn:
        for f in (plain, hours):
            conn.execute("UPDATE documents SET content_hash = %s WHERE business_id = %s AND source_uri = %s",
                         (hashlib.sha256(f.read_text().encode()).hexdigest(), biz, str(f.resolve())))
        conn.execute("UPDATE chunks SET body = 'Fri. Closed.\n' WHERE business_id = %s AND body LIKE 'Friday%%'",
                     (biz,))
    embedded.clear()
    try:
        stats = ingest(biz, "Test", [str(plain), str(hours)])
        assert (stats["unchanged"], stats["updated"]) == (1, 1)
        assert embedded and all("Friday" in t for t in embedded), embedded
        embedded.clear()
        assert ingest(biz, "Test", [str(plain), str(hours)])["unchanged"] == 2 and not embedded
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM businesses WHERE id = %s", (biz,))
