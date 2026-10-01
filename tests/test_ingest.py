"""Abbreviated opening hours ("Fri. Closed") must be findable. Run: pytest -q  (needs the local Postgres)"""
from pathlib import Path

import pytest

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
