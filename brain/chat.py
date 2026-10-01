"""Conversation layer: answer from the brain, or hand off to the team and collect contact details.

One session_id = one customer thread (WhatsApp number, call id, email thread).
"""
import re

from . import drafts
from .answer import answer
from .db import connect

PHONE_IN = re.compile(r"(?:\+?91[\s-]?)?\b([6-9]\d{4})[\s-]?(\d{5})\b")
PHONE_US = re.compile(r"(?:\+?1[\s.-]?)?\(?\b([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})\b")
US_SHAPED = re.compile(r"\+1\b|\(\d{3}\)|\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b")
NAME = re.compile(r"\b(?:my name is|i am|i'm|this is|name[:\s]+)\s*([A-Za-z][A-Za-z .]{1,40})", re.I)
WANTS_HUMAN = re.compile(r"\b(human|real person|staff|talk to|speak to|call me|call back|callback)\b", re.I)
DECLINE = re.compile(r"^\s*(no|nope|cancel|stop|no thanks|not now|leave it)\b", re.I)


def _phone(message: str, country: str) -> tuple[str | None, str]:
    """Returns (formatted phone, message with the number removed). Shape decides; bare digits follow the business."""
    us, ind = PHONE_US.search(message), PHONE_IN.search(message)
    explicit_in = "+91" in message
    if us and not explicit_in and (US_SHAPED.search(message) or country == "US" or not ind):
        a, b, c = us.groups()
        return f"+1 {a}-{b}-{c}", message[:us.start()] + message[us.end():]
    if ind:
        return "+91 " + "".join(ind.groups()), message[:ind.start()] + message[ind.end():]
    return None, message


def _extract(message: str, country: str = "IN") -> tuple[str | None, str | None]:
    phone, rest = _phone(message, country)
    name = None
    if m := NAME.search(message):
        name = m.group(1)
    else:
        # A bare reply like "Ravi" or "Ravi Kumar, 98400 12345"
        rest = rest.strip(" ,.-")
        if re.fullmatch(r"[A-Za-z][A-Za-z .]{1,40}", rest) and len(rest.split()) <= 3:
            name = rest
    if name:
        name = re.split(r"\s+(?:and|my|phone|number|mobile)\b", name, flags=re.I)[0].strip(" .").title()
    return name, phone


def _is_question(message: str) -> bool:
    """A bare "ok" or "hmm" is not something to hand to the team; "what about whitening" is."""
    return "?" in message or len(message.split()) >= 3


def _ask_for(missing: list[str]) -> str:
    return {
        ("name", "phone"): "Could you share your name and phone number?",
        ("name",): "May I have your name?",
        ("phone",): "What's the best phone number to reach you on?",
    }[tuple(missing)]


def _country(conn, business_id: str) -> str:
    row = conn.execute("SELECT settings->>'country', settings->>'timezone' FROM businesses WHERE id = %s",
                       (business_id,)).fetchone()
    if row and row[0]:
        return row[0]
    return "US" if row and (row[1] or "").startswith("America/") else "IN"


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
            new_name, new_phone = _extract(message, _country(conn, business_id))
            name, phone = name or new_name, phone or new_phone
            conn.execute("UPDATE handoffs SET name = %s, phone = %s WHERE id = %s", (name, phone, handoff_id))
            if name and phone:
                return _finish(conn, business_id, handoff_id, name, phone)
            if not (new_name or new_phone):
                # The customer asked something else instead. Answer it, then ask again.
                r = answer(business_id, message)
                missing = [f for f, v in (("name", name), ("phone", phone)) if not v]
                if r["answered"]:
                    return {"reply": f"{r['answer']}\n\nFor your earlier question: {_ask_for(missing)}",
                            "state": "collecting_details", "handoff_id": handoff_id, "citations": r["citations"]}
                if _is_question(message):
                    # Another one for the team: same handoff, one call back, and ask for details once.
                    conn.execute("UPDATE handoffs SET question = question || E'\\n' || %s WHERE id = %s",
                                 (message, handoff_id))
                    return {"reply": f"I'll pass that to the team as well. {_ask_for(missing)}",
                            "state": "collecting_details", "handoff_id": handoff_id}
            missing = [f for f, v in (("name", name), ("phone", phone)) if not v]
            return {"reply": _ask_for(missing), "state": "collecting_details", "handoff_id": handoff_id}

        if WANTS_HUMAN.search(message):
            return _start(conn, business_id, session_id, message, "Sure.")

    r = answer(business_id, message)
    if r["answered"]:
        return {"reply": r["answer"], "state": "idle", "citations": r["citations"]}
    with connect() as conn:
        return _start(conn, business_id, session_id, message, "I don't have that information right now, so")
