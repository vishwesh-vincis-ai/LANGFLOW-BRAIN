"""Load the sample businesses. Run: python -m brain.seed"""
import json
from pathlib import Path

from . import booking, db
from .db import connect
from .ingest import ingest

DATA = Path(__file__).parent.parent / "data"

CLINIC = "smile-point"
SALON = "glow-studio"


def seed() -> None:
    db.migrate()
    ingest(CLINIC, "Smile Point Dental", sorted(str(p) for p in (DATA / "sample_clinic").glob("*.md")))
    ingest(SALON, "Glow Studio Salon", [str(DATA / "sample_salon/prices.md")])
    with connect() as conn:
        conn.execute(
            "UPDATE businesses SET settings = %s WHERE id = %s",
            (json.dumps({"owner_email": "frontdesk@smilepoint.example", "timezone": "Asia/Kolkata",
                         "callback_promise": "within 2 working hours"}), CLINIC),
        )
    # Matches faq.md: Mon-Sat 9:30-13:30 and 16:30-20:30, Sunday 10:00-13:00
    week = [(d, "09:30", "13:30") for d in range(6)] + [(d, "16:30", "20:30") for d in range(6)]
    booking.set_hours(CLINIC, week + [(6, "10:00", "13:00")])


if __name__ == "__main__":
    seed()
    print("seeded")
