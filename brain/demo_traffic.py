"""Replay a week's worth of scripted customers through the real brain, so the dashboard has real output to show.

Every answer, handoff, draft and booking below is produced by the system itself; only the customers are scripted.
The dashboard labels this data as demo traffic. Usage: python -m brain.demo_traffic
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import booking, dashboard
from .chat import chat
from .db import connect
from .seed import CLINIC, seed

IST = ZoneInfo("Asia/Kolkata")

# (customer session, messages). Questions come from the eval set; handoffs end with the customer's details.
CONVERSATIONS = [
    ("wa:+919840011001", ["How much does a dental implant cost?", "When is the implant crown fitted?"]),
    ("wa:+919840011002", ["Root canal price for a molar?", "Does a root canal hurt?"]),
    ("wa:+919840011003", ["What are your opening hours on Saturday?"]),
    ("wa:+919840011004", ["How much is laser teeth whitening?", "Do you have a take-home whitening kit and what does it cost?"]),
    ("wa:+919840011005", ["Do you do hair transplants?", "Meena, 98400 11005"]),
    ("wa:+919840011006", ["Is EMI available for braces?", "What do metal braces cost?"]),
    ("wa:+919840011007", ["How late can I cancel my appointment?"]),
    ("wa:+919840011008", ["How much do porcelain veneers cost?", "Arjun 98400 11008"]),
    ("wa:+919840011009", ["How much is a zirconia crown?"]),
    ("wa:+919840011010", ["I am pregnant, is a dental cleaning safe?"]),
    ("wa:+919840011011", ["What is the price of wisdom tooth extraction?", "What should I avoid after a tooth extraction?"]),
    ("wa:+919840011012", ["Do you offer home visits?", "My name is Lakshmi and my number is 98400 11012"]),
    ("wa:+919840011013", ["Clear aligners price?", "Which doctor handles orthodontics and aligners?"]),
    ("wa:+919840011014", ["Are you open on Sunday?"]),
    ("wa:+919840011015", ["How much is a tooth coloured filling?"]),
    ("wa:+919840011016", ["How much do porcelain veneers cost?", "Karthik, 98400 11016"]),
    ("wa:+919840011017", ["What should I bring on my first visit?", "Can I book on WhatsApp?"]),
    ("wa:+919840011018", ["Do you have a branch in Coimbatore?", "Divya 98400 11018"]),
    ("wa:+919840011019", ["Price of complete dentures for both jaws?"]),
    ("wa:+919840011020", ["Is there parking for cars?", "Does the doctor speak Tamil?"]),
    ("wa:+919840011021", ["What does a full mouth X-ray cost?"]),
    ("wa:+919840011022", ["Can I talk to a real person?", "Suresh 98400 11022"]),
    ("wa:+919840011023", ["My gums bleed when I brush. What should I do?"]),
    ("wa:+919840011024", ["What happens if I miss appointments without telling you?"]),
    ("wa:+919840011025", ["How much does a consultation cost?", "How many visits does a root canal take?"]),
    ("wa:+919840011026", ["Do you do hair transplants?", "no thanks"]),
    ("wa:+919840011027", ["What is the price of scaling and polishing?"]),
    ("wa:+919840011028", ["How much is a check-up for my 8 year old child?"]),
    ("wa:+919840011029", ["What if I arrive late for my appointment?"]),
    ("wa:+919840011030", ["How much do porcelain veneers cost?", "Farhan, 98400 11030"]),
]

BOOKINGS = [  # (days from today, HH:MM, service, minutes, name, phone)
    (1, "10:00", "Scaling and polishing", 45, "Priyanka R", "+91 9840012345"),
    (1, "17:00", "Root canal (molar)", 60, "Ravi Kumar", "+91 9840011002"),
    (2, "11:30", "Consultation", 30, "Anitha S", "+91 9840011010"),
    (2, "18:30", "Braces review", 30, "Vikram P", "+91 9840011006"),
    (3, "09:30", "Implant consultation", 30, "Gopal N", "+91 9840011001"),
    (3, "16:30", "Laser whitening", 60, "Nisha M", "+91 9840011004"),
    (4, "12:00", "Child check-up", 30, "Aarav (parent: Kavya)", "+91 9840011028"),
    (5, "10:30", "Wisdom tooth extraction", 45, "Sanjay T", "+91 9840011011"),
    (6, "19:00", "Consultation", 30, "Harini V", "+91 9840011013"),
]


def _open_slot(day: date, hhmm: str) -> datetime:
    """The scripted time, or the next open-hours slot if that day/time is closed (e.g. a Sunday)."""
    t = datetime.combine(day, time.fromisoformat(hhmm), IST)
    slots = booking.free_slots(CLINIC, day)
    return t if t in slots else (slots[0] if slots else t)


def run() -> None:
    seed()
    with connect() as conn:
        for table in ("queries", "handoffs", "email_drafts", "appointments"):
            conn.execute(f"DELETE FROM {table} WHERE business_id = %s", (CLINIC,))

    for session, messages in CONVERSATIONS:
        for m in messages:
            chat(CLINIC, session, m)

    for days, hhmm, service, minutes, name, phone in BOOKINGS:
        day = date.today() + timedelta(days=days)
        booking.book(CLINIC, _open_slot(day, hhmm), service, name, phone, minutes)

    # The owner has already worked a little of the inbox.
    snap = dashboard.snapshot(CLINIC)
    open_handoffs = [h for h in snap["handoffs"] if h["status"] == "open"]
    if open_handoffs:
        dashboard.close_handoff(CLINIC, open_handoffs[-1]["id"])
    pending = [d for d in snap["drafts"] if d["status"] == "draft"]
    if pending:
        dashboard.set_draft_status(CLINIC, pending[-1]["id"], "approved")

    s = dashboard.snapshot(CLINIC)["questions"]
    print(f"{s['total']} questions, {s['answered']} answered, {s['handed_off']} declined; "
          f"{len(BOOKINGS)} bookings")


if __name__ == "__main__":
    run()
