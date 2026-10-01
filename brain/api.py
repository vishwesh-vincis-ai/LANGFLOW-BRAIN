"""One API that projects 1, 2 and 3 call. Run: uvicorn brain.api:app --port 8000"""
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import booking, dashboard, db, drafts
from .answer import answer
from .chat import chat
from .ingest import ingest

app = FastAPI(title="Business Brain")
db.migrate()


class IngestReq(BaseModel):
    business_id: str
    business_name: str
    sources: list[str]


class AskReq(BaseModel):
    business_id: str
    question: str


class ChatReq(BaseModel):
    business_id: str
    session_id: str
    message: str


class BookReq(BaseModel):
    business_id: str
    starts_at: datetime          # ISO 8601 with offset, e.g. 2026-10-05T10:00:00+05:30
    service: str
    name: str
    phone: str
    duration_min: int = 30


class RescheduleReq(BaseModel):
    business_id: str
    appointment_id: int
    new_start: datetime


class CancelReq(BaseModel):
    business_id: str
    appointment_id: int


class ReplyReq(BaseModel):
    business_id: str
    to: str
    message: str


@app.post("/ingest")
def ingest_endpoint(req: IngestReq):
    return ingest(req.business_id, req.business_name, req.sources)


@app.post("/ask")
def ask_endpoint(req: AskReq):
    """Stateless Q&A: cited answer or "I don't know"."""
    return answer(req.business_id, req.question)


@app.post("/chat")
def chat_endpoint(req: ChatReq):
    """Stateful: answers, or hands off to the team and collects name + phone."""
    return chat(req.business_id, req.session_id, req.message)


@app.get("/calendar/slots")
def slots_endpoint(business_id: str, day: date, duration_min: int = 30):
    return {"slots": [s.isoformat() for s in booking.free_slots(business_id, day, duration_min)]}


@app.post("/calendar/book")
def book_endpoint(req: BookReq):
    try:
        return booking.book(req.business_id, req.starts_at, req.service, req.name, req.phone, req.duration_min)
    except booking.SlotUnavailable as e:
        raise HTTPException(409, str(e))


@app.post("/calendar/reschedule")
def reschedule_endpoint(req: RescheduleReq):
    try:
        return booking.reschedule(req.business_id, req.appointment_id, req.new_start)
    except booking.SlotUnavailable as e:
        raise HTTPException(409, str(e))


@app.post("/calendar/cancel")
def cancel_endpoint(req: CancelReq):
    if not booking.cancel(req.business_id, req.appointment_id):
        raise HTTPException(404, "no booked appointment with that id")
    return {"cancelled": req.appointment_id}


@app.post("/drafts/reply")
def draft_reply_endpoint(req: ReplyReq):
    return drafts.draft_reply(req.business_id, req.to, req.message)


@app.get("/drafts")
def drafts_endpoint(business_id: str, status: str = "draft"):
    return drafts.list_drafts(business_id, status)


class DraftStatusReq(BaseModel):
    business_id: str
    status: Literal["approved", "discarded"]


class BusinessReq(BaseModel):
    business_id: str


DASHBOARD = Path(__file__).parent.parent / "dashboard" / "index.html"


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    """Owner console. The page is a body fragment (it is also published as a static snapshot), so wrap it."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>'
            + DASHBOARD.read_text() + "</body></html>")


@app.get("/dashboard/businesses")
def dashboard_businesses():
    return dashboard.businesses()


@app.get("/dashboard/data")
def dashboard_data(business_id: str):
    return dashboard.snapshot(business_id)


@app.post("/drafts/{draft_id}/status")
def draft_status_endpoint(draft_id: int, req: DraftStatusReq):
    if not dashboard.set_draft_status(req.business_id, draft_id, req.status):
        raise HTTPException(404, "no pending draft with that id")
    return {"id": draft_id, "status": req.status}


@app.post("/handoffs/{handoff_id}/close")
def close_handoff_endpoint(handoff_id: int, req: BusinessReq):
    if not dashboard.close_handoff(req.business_id, handoff_id):
        raise HTTPException(404, "no open handoff with that id")
    return {"id": handoff_id, "status": "closed"}


@app.get("/health")
def health():
    return {"ok": True}
