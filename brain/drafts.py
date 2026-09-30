"""Email drafts. The brain writes them; a human approves and sends. Nothing is sent from here."""
import re

from .db import connect


def _business(conn, business_id: str) -> tuple[str, dict]:
    name, settings = conn.execute("SELECT name, settings FROM businesses WHERE id = %s", (business_id,)).fetchone()
    return name, settings


def _save(conn, business_id: str, to: str, subject: str, body: str, reason: str) -> dict:
    draft_id = conn.execute(
        "INSERT INTO email_drafts (business_id, to_address, subject, body, reason) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (business_id, to, subject, body, reason),
    ).fetchone()[0]
    return {"id": draft_id, "to": to, "subject": subject, "body": body, "reason": reason, "status": "draft"}


def draft_handoff(business_id: str, handoff_id: int) -> dict:
    """Tell the owner a customer is waiting for a human reply."""
    with connect() as conn:
        name, settings = _business(conn, business_id)
        q, cust, phone, session = conn.execute(
            "SELECT question, name, phone, session_id FROM handoffs WHERE id = %s AND business_id = %s",
            (handoff_id, business_id),
        ).fetchone()
        body = (
            f"A customer asked something the assistant could not answer from {name}'s documents.\n\n"
            f"Name:     {cust}\nPhone:    {phone}\nChannel:  {session}\nQuestion: {q}\n\n"
            f"Promised to the customer: {settings.get('callback_promise', 'a call back soon')}.\n"
            f"If this question comes up often, add the answer to your FAQ and the assistant will handle it next time."
        )
        return _save(conn, business_id, settings.get("owner_email", ""), f"Call back {cust}: {q[:60]}", body, "handoff")


def draft_reply(business_id: str, to: str, customer_message: str) -> dict:
    """Draft a reply to a customer email, grounded in the brain. Unanswerable → holding reply."""
    from .answer import answer  # local import: answer imports this module's siblings

    r = answer(business_id, customer_message)
    with connect() as conn:
        name, settings = _business(conn, business_id)
        if r["answered"]:
            text = re.sub(r"\s*\[\d+\]", "", r["answer"]).strip()
            body = f"Hello,\n\nThank you for writing to {name}.\n\n{text}\n\nWarm regards,\n{name}"
            reason = "reply"
        else:
            body = (f"Hello,\n\nThank you for writing to {name}. A member of our team will get back to you "
                    f"with {settings.get('callback_promise', 'an answer soon')}.\n\nWarm regards,\n{name}")
            reason = "reply_needs_human"
        draft = _save(conn, business_id, to, f"Re: your message to {name}", body, reason)
    draft["citations"] = r["citations"]
    return draft


def list_drafts(business_id: str, status: str = "draft") -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, to_address, subject, body, reason, status, created_at FROM email_drafts "
            "WHERE business_id = %s AND status = %s ORDER BY created_at DESC",
            (business_id, status),
        ).fetchall()
    keys = ("id", "to", "subject", "body", "reason", "status", "created_at")
    return [dict(zip(keys, r)) for r in rows]
