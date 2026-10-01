"""Handoff conversation, calendar and drafts. Run: pytest -q  (needs the local Postgres)"""
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from brain import booking, drafts
from brain.chat import _extract, chat
from brain.db import connect
from brain.seed import CLINIC, SALON, seed

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="session", autouse=True)
def _seed():
    seed()
    with connect() as conn:
        conn.execute("DELETE FROM appointments WHERE business_id = %s", (CLINIC,))


def sid() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def next_weekday(wd: int) -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


# --- handoff -----------------------------------------------------------------

@pytest.mark.parametrize("msg,name,phone", [
    ("My name is Ravi Kumar and my number is 98400 12345", "Ravi Kumar", "+91 9840012345"),
    ("Ravi, +91 98400-12345", "Ravi", "+91 9840012345"),
    ("I'm Meena", "Meena", None),
    ("9840012345", None, "+91 9840012345"),
    ("what time do you open", None, None),
])
def test_extract(msg, name, phone):
    assert _extract(msg) == (name, phone)


@pytest.mark.parametrize("msg,country,name,phone", [
    ("Maria Lopez, 512 555 0142", "IN", "Maria Lopez", "+1 512-555-0142"),   # US shape wins anywhere
    ("James Carter 512-555-0187", "US", "James Carter", "+1 512-555-0187"),
    ("(512) 555-0119", "US", None, "+1 512-555-0119"),
    ("+1 512 555 0100", "IN", None, "+1 512-555-0100"),
    ("5125550100", "US", None, "+1 512-555-0100"),                          # bare digits follow the business
    ("9840012345", "IN", None, "+91 9840012345"),
    ("98400 12345", "US", None, "+91 9840012345"),                         # Indian shape wins anywhere
])
def test_extract_us_and_indian_numbers(msg, country, name, phone):
    assert _extract(msg, country) == (name, phone)


def test_unanswerable_question_hands_off_and_collects_details():
    s = sid()
    r = chat(CLINIC, s, "Do you do hair transplants?")
    assert r["state"] == "collecting_details"
    assert "connect you with our team" in r["reply"] and "name and phone" in r["reply"]

    r = chat(CLINIC, s, "I'm Anitha")
    assert r["state"] == "collecting_details" and "phone" in r["reply"]

    r = chat(CLINIC, s, "98400 55555")
    assert r["state"] == "handoff_open"
    assert "Anitha" in r["reply"] and "+91 9840055555" in r["reply"] and "2 working hours" in r["reply"]

    draft = next(d for d in drafts.list_drafts(CLINIC) if d["id"] == r["draft_id"])
    assert draft["to"] == "frontdesk@smilepoint.example"
    assert "hair transplants" in draft["body"] and "Anitha" in draft["body"]


def test_customer_can_ask_something_else_mid_handoff():
    s = sid()
    chat(CLINIC, s, "Do you offer home visits?")
    r = chat(CLINIC, s, "What does a zirconia crown cost?")
    assert "14,000" in r["reply"] and "name and phone" in r["reply"]
    assert r["state"] == "collecting_details"


@pytest.fixture
def no_hours_tenant(tmp_path):
    """A business whose documents say nothing about hours or prices."""
    from brain.ingest import ingest

    biz = f"test-{uuid.uuid4().hex[:8]}"
    src = tmp_path / "parking.md"
    src.write_text("# Lakeside Dental\n\n## Parking\nFree parking behind the office.\n")
    ingest(biz, "Lakeside Dental", [str(src)])
    yield biz
    with connect() as conn:
        conn.execute("DELETE FROM businesses WHERE id = %s", (biz,))


def test_second_unanswerable_question_joins_the_same_handoff(no_hours_tenant):
    s = sid()
    first = chat(no_hours_tenant, s, "Are you open on Saturdays?")
    assert first["state"] == "collecting_details"

    r = chat(no_hours_tenant, s, "How much is a cleaning without insurance?")
    assert r["state"] == "collecting_details" and r["handoff_id"] == first["handoff_id"]
    assert "pass that to the team as well" in r["reply"]
    assert r["reply"].count("name and phone") == 1
    with connect() as conn:
        rows = conn.execute("SELECT question FROM handoffs WHERE business_id = %s AND session_id = %s",
                            (no_hours_tenant, s)).fetchall()
    assert len(rows) == 1
    assert "Saturdays" in rows[0][0] and "cleaning without insurance" in rows[0][0]

    r = chat(no_hours_tenant, s, "Maria Lopez, 512 555 0142")
    assert r["state"] == "handoff_open"
    draft = next(d for d in drafts.list_drafts(no_hours_tenant) if d["id"] == r["draft_id"])
    assert "Saturdays" in draft["body"] and "cleaning without insurance" in draft["body"]


def test_customer_can_decline_handoff():
    s = sid()
    chat(CLINIC, s, "Do you offer home visits?")
    assert chat(CLINIC, s, "no thanks")["state"] == "idle"


def test_never_asks_for_details_twice():
    s = sid()
    chat(CLINIC, s, "Do you offer home visits?")
    chat(CLINIC, s, "Suresh 98400 11111")
    r = chat(CLINIC, s, "Do you have a branch in Coimbatore?")
    assert r["state"] == "handoff_open" and "Suresh" in r["reply"]


def test_asking_for_a_human_hands_off():
    r = chat(CLINIC, sid(), "Can I talk to a real person?")
    assert r["state"] == "collecting_details"


def test_answerable_question_does_not_hand_off():
    r = chat(CLINIC, sid(), "How much is a zirconia crown?")
    assert r["state"] == "idle" and "14,000" in r["reply"]


# --- calendar ----------------------------------------------------------------

def test_slots_follow_opening_hours():
    monday = next_weekday(0)
    slots = booking.free_slots(CLINIC, monday)
    times = {s.strftime("%H:%M") for s in slots}
    assert "09:30" in times and "13:00" in times and "16:30" in times and "20:00" in times
    assert "13:30" not in times and "14:00" not in times  # lunch break
    sunday = {s.strftime("%H:%M") for s in booking.free_slots(CLINIC, next_weekday(6))}
    assert max(sunday) == "12:30"


def test_book_then_slot_disappears_and_double_booking_is_refused():
    day = next_weekday(1)
    start = datetime.combine(day, datetime.strptime("10:00", "%H:%M").time(), IST)
    appt = booking.book(CLINIC, start, "Cleaning", "Lakshmi", "+91 9840022222")
    assert start not in booking.free_slots(CLINIC, day)
    with pytest.raises(booking.SlotUnavailable, match="already booked"):
        booking.book(CLINIC, start + timedelta(minutes=15), "Check-up", "Arun", "+91 9840033333")
    assert booking.cancel(CLINIC, appt["id"])
    assert start in booking.free_slots(CLINIC, day)


def test_booking_outside_hours_is_refused():
    lunch = datetime.combine(next_weekday(2), datetime.strptime("14:00", "%H:%M").time(), IST)
    with pytest.raises(booking.SlotUnavailable, match="opening hours"):
        booking.book(CLINIC, lunch, "Cleaning", "Lakshmi", "+91 9840022222")


def test_reschedule_is_atomic():
    day = next_weekday(3)
    a = datetime.combine(day, datetime.strptime("17:00", "%H:%M").time(), IST)
    b = datetime.combine(day, datetime.strptime("18:00", "%H:%M").time(), IST)
    first = booking.book(CLINIC, a, "Root canal", "Divya", "+91 9840044444", 60)
    blocker = booking.book(CLINIC, b, "Cleaning", "Karan", "+91 9840066666")
    with pytest.raises(booking.SlotUnavailable):
        booking.reschedule(CLINIC, first["id"], b)
    assert a not in booking.free_slots(CLINIC, day)  # failed reschedule kept the original booking
    moved = booking.reschedule(CLINIC, first["id"], b + timedelta(hours=1))
    assert moved["replaces"] == first["id"] and a in booking.free_slots(CLINIC, day)
    booking.cancel(CLINIC, blocker["id"]), booking.cancel(CLINIC, moved["id"])


def test_calendars_are_isolated_per_business():
    with pytest.raises(booking.SlotUnavailable):  # salon has no hours configured
        booking.book(SALON, datetime.combine(next_weekday(1), datetime.min.time(), IST).replace(hour=11),
                     "Haircut", "X", "+91 9840077777")


# --- drafts ------------------------------------------------------------------

def test_draft_reply_is_grounded_or_holds():
    ok = drafts.draft_reply(CLINIC, "patient@example.com", "How much is a zirconia crown?")
    assert "14,000" in ok["body"] and ok["reason"] == "reply" and "[1]" not in ok["body"]
    hold = drafts.draft_reply(CLINIC, "patient@example.com", "Do you do hair transplants?")
    assert hold["reason"] == "reply_needs_human" and "2 working hours" in hold["body"]


# --- ingest --------------------------------------------------------------------

def test_adding_an_embedding_key_later_backfills_unchanged_sources(tmp_path, monkeypatch):
    from brain import config, ingest, providers

    biz = f"test-{uuid.uuid4().hex[:8]}"
    src = tmp_path / "faq.md"
    src.write_text("# FAQ\n\n## Parking\nFree parking behind the clinic.\n")
    monkeypatch.setattr(config, "EMBED_PROVIDER", "none")
    assert ingest.ingest(biz, "Test", [str(src)])["added"] == 1

    monkeypatch.setattr(config, "EMBED_PROVIDER", "fake")
    monkeypatch.setattr(providers, "embed", lambda texts, task="passage": [[0.1] * config.EMBED_DIM for _ in texts])
    assert ingest.ingest(biz, "Test", [str(src)])["updated"] == 1  # same text, but now embedded
    assert ingest.ingest(biz, "Test", [str(src)])["unchanged"] == 1
    with connect() as conn:
        missing = conn.execute(
            "SELECT count(*) FROM chunks WHERE business_id = %s AND embedding IS NULL", (biz,)).fetchone()[0]
        conn.execute("DELETE FROM businesses WHERE id = %s", (biz,))
    assert missing == 0
