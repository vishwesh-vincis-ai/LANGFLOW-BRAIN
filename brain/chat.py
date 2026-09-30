"""Conversation layer: answer from the brain, or hand off to the team and collect contact details.

One session_id = one customer thread (WhatsApp number, call id, email thread).
"""
import re

from . import drafts
from .answer import answer
from .db import connect

PHONE = re.compile(r"(?:\+?91[\s-]?)?([6-9]\d{4}[\s-]?\d{5})\b")
NAME = re.compile(r"\b(?:my name is|i am|i'm|this is|name[:\s]+)\s*([A-Za-z][A-Za-z .]{1,40})", re.I)
WANTS_HUMAN = re.compile(r"\b(human|real person|staff|talk to|speak to|call me|call back|callback)\b", re.I)
DECLINE = re.compile(r"^\s*(no|nope|cancel|stop|no thanks|not now|leave it)\b", re.I)


def _extract(message: str) -> tuple[str | None, str | None]:
    phone = None
    if m := PHONE.search(message):
        phone = "+91 " + re.sub(r"[\s-]", "", m.group(1))
    name = None
    if m := NAME.search(message):
        name = m.group(1)
    else:
        # A bare reply like "Ravi" or "Ravi Kumar, 98400 12345"
        rest = PHONE.sub("", message).strip(" ,.-")
        if re.fullmatch(r"[A-Za-z][A-Za-z .]{1,40}", rest) and len(rest.split()) <= 3:
            name = rest
    if name:
        name = re.split(r"\s+(?:and|my|phone|number|mobile)\b", name, flags=re.I)[0].strip(" .").title()
    return name, phone


def _ask_for(missing: list[str]) -> str:
    return {
        ("name", "phone"): "Could you share your name and phone number?",
        ("name",): "May I have your name?",
        ("phone",): "What's the best phone number to reach you on?",
    }[tuple(missing)]


def _promise(conn, business_id: str) -> str:
    row = conn.execute("SELECT settings->>'callback_promise' FROM businesses WHERE id = %s", (business_id,)).fetchone()
    return (row and row[0]) or "soon"


def _open_handoff(conn, business_id: str, session_id: str):
    return conn.execute(
        "SELECT id, question, name, phone FROM handoffs "
        "WHERE business_id = %s AND session_id = %s AND status = 'collecting' ORDER BY id DESC LIMIT 1",
        (business_id, session_id),
    ).fetchone()


def _known_contact(conn, business_id: str, session_id: str) -> tuple[str | None, str | None]:
    """Never ask twice: reuse details this customer already gave in an earlier handoff."""
    row = conn.execute(
        "SELECT name, phone FROM handoffs WHERE business_id = %s AND session_id = %s "
        "AND name IS NOT NULL AND phone IS NOT NULL ORDER BY id DESC LIMIT 1",
        (business_id, session_id),
    ).fetchone()
    return row if row else (None, None)


def _finish(conn, business_id: str, handoff_id: int, name: str, phone: str, returning: bool = False) -> dict:
    conn.execute(
        "UPDATE handoffs SET name = %s, phone = %s, status = 'open' WHERE id = %s", (name, phone, handoff_id)
    )
    draft = drafts.draft_handoff(business_id, handoff_id)
    return {
        "reply": (f"I don't have that information right now, so I've passed this question to our team too. "
                  f"They will call you on {phone} {_promise(conn, business_id)}, {name}." if returning else
                  f"Thank you, {name}. I've passed this to our team and they will call you on {phone} "
                  f"{_promise(conn, business_id)}."),
        "state": "handoff_open",
        "handoff_id": handoff_id,
        "draft_id": draft["id"],
    }


def _start(conn, business_id: str, session_id: str, question: str, prefix: str) -> dict:
    handoff_id = conn.execute(
        "INSERT INTO handoffs (business_id, session_id, question) VALUES (%s, %s, %s) RETURNING id",
        (business_id, session_id, question),
    ).fetchone()[0]
    name, phone = _known_contact(conn, business_id, session_id)
    if name and phone:
        return _finish(conn, business_id, handoff_id, name, phone, returning=True)
    return {"reply": f"{prefix} I'll connect you with our team. {_ask_for(['name', 'phone'])}",
            "state": "collecting_details", "handoff_id": handoff_id}


def chat(business_id: str, session_id: str, message: str) -> dict:
    with connect() as conn:
        pending = _open_handoff(conn, business_id, session_id)
        if pending:
            handoff_id, question, name, phone = pending
            if DECLINE.match(message):
                conn.execute("UPDATE handoffs SET status = 'closed' WHERE id = %s", (handoff_id,))
                return {"reply": "No problem. Is there anything else I can help you with?", "state": "idle"}
            new_name, new_phone = _extract(message)
            name, phone = name or new_name, phone or new_phone
            conn.execute("UPDATE handoffs SET name = %s, phone = %s WHERE id = %s", (name, phone, handoff_id))
            if name and phone:
                return _finish(conn, business_id, handoff_id, name, phone)
            if not (new_name or new_phone):
                # The customer asked something else instead. Answer it, then ask again.
                r = answer(business_id, message)
                if r["answered"]:
                    missing = [f for f, v in (("name", name), ("phone", phone)) if not v]
                    return {"reply": f"{r['answer']}\n\nFor your earlier question: {_ask_for(missing)}",
                            "state": "collecting_details", "handoff_id": handoff_id, "citations": r["citations"]}
            missing = [f for f, v in (("name", name), ("phone", phone)) if not v]
            return {"reply": _ask_for(missing), "state": "collecting_details", "handoff_id": handoff_id}

        if WANTS_HUMAN.search(message):
            return _start(conn, business_id, session_id, message, "Sure.")

    r = answer(business_id, message)
    if r["answered"]:
        return {"reply": r["answer"], "state": "idle", "citations": r["citations"]}
    with connect() as conn:
        return _start(conn, business_id, session_id, message, "I don't have that information right now, so")
