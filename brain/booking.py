"""Calendar tool: availability, book, reschedule, cancel.

Backed by Postgres so it works today. A Google Calendar provider can sit behind the same
functions later; callers (voice agent, WhatsApp agent) won't change.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg

from .db import connect


class SlotUnavailable(Exception):
    pass


def _tz(conn, business_id: str) -> ZoneInfo:
    row = conn.execute("SELECT settings->>'timezone' FROM businesses WHERE id = %s", (business_id,)).fetchone()
    return ZoneInfo((row and row[0]) or "Asia/Kolkata")


def set_hours(business_id: str, hours: list[tuple[int, str, str]]) -> None:
    """hours: [(weekday 0=Mon, "09:30", "13:30"), ...]. Replaces the whole week."""
    with connect() as conn, conn.transaction():
        conn.execute("DELETE FROM opening_hours WHERE business_id = %s", (business_id,))
        for wd, opens, closes in hours:
            conn.execute(
                "INSERT INTO opening_hours (business_id, weekday, opens, closes) VALUES (%s, %s, %s, %s)",
                (business_id, wd, opens, closes),
            )


def free_slots(business_id: str, day: date, duration_min: int = 30, now: datetime | None = None) -> list[datetime]:
    with connect() as conn:
        tz = _tz(conn, business_id)
        now = now or datetime.now(tz)
        blocks = conn.execute(
            "SELECT opens, closes FROM opening_hours WHERE business_id = %s AND weekday = %s ORDER BY opens",
            (business_id, day.weekday()),
        ).fetchall()
        day_start = datetime.combine(day, time.min, tz)
        busy = conn.execute(
            "SELECT starts_at, ends_at FROM appointments "
            "WHERE business_id = %s AND status = 'booked' AND starts_at < %s AND ends_at > %s",
            (business_id, day_start + timedelta(days=1), day_start),
        ).fetchall()

    step, length, slots = timedelta(minutes=30), timedelta(minutes=duration_min), []
    for opens, closes in blocks:
        t, end = datetime.combine(day, opens, tz), datetime.combine(day, closes, tz)
        while t + length <= end:
            if t > now and not any(t < b_end and t + length > b_start for b_start, b_end in busy):
                slots.append(t)
            t += step
    return slots


def _within_hours(conn, business_id: str, start: datetime, end: datetime) -> bool:
    local_start, local_end = start.astimezone(_tz(conn, business_id)), end.astimezone(_tz(conn, business_id))
    return conn.execute(
        "SELECT 1 FROM opening_hours WHERE business_id = %s AND weekday = %s AND opens <= %s AND closes >= %s",
        (business_id, local_start.weekday(), local_start.time(), local_end.time()),
    ).fetchone() is not None


def book(business_id: str, starts_at: datetime, service: str, name: str, phone: str,
         duration_min: int = 30) -> dict:
    ends_at = starts_at + timedelta(minutes=duration_min)
    with connect() as conn:
        if not _within_hours(conn, business_id, starts_at, ends_at):
            raise SlotUnavailable("outside opening hours")
        if starts_at <= datetime.now(starts_at.tzinfo):
            raise SlotUnavailable("in the past")
        try:
            appt_id = conn.execute(
                "INSERT INTO appointments (business_id, starts_at, ends_at, service, name, phone) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (business_id, starts_at, ends_at, service, name, phone),
            ).fetchone()[0]
        except psycopg.errors.ExclusionViolation:
            raise SlotUnavailable("slot already booked") from None
    return {"id": appt_id, "starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat(),
            "service": service, "name": name, "phone": phone}


def cancel(business_id: str, appointment_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = %s AND business_id = %s AND status = 'booked'",
            (appointment_id, business_id),
        )
        return cur.rowcount == 1


def reschedule(business_id: str, appointment_id: int, new_start: datetime) -> dict:
    """Atomic: the old slot is released only if the new one is successfully taken."""
    with connect() as conn, conn.transaction():
        row = conn.execute(
            "SELECT service, name, phone, extract(epoch FROM ends_at - starts_at)::int / 60 "
            "FROM appointments WHERE id = %s AND business_id = %s AND status = 'booked' FOR UPDATE",
            (appointment_id, business_id),
        ).fetchone()
        if not row:
            raise SlotUnavailable("appointment not found")
        service, name, phone, minutes = row
        new_end = new_start + timedelta(minutes=minutes)
        if not _within_hours(conn, business_id, new_start, new_end):
            raise SlotUnavailable("outside opening hours")
        conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = %s", (appointment_id,))
        try:
            with conn.transaction():
                new_id = conn.execute(
                    "INSERT INTO appointments (business_id, starts_at, ends_at, service, name, phone) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (business_id, new_start, new_end, service, name, phone),
                ).fetchone()[0]
        except psycopg.errors.ExclusionViolation:
            raise SlotUnavailable("slot already booked") from None
    return {"id": new_id, "replaces": appointment_id, "starts_at": new_start.isoformat(), "service": service}
