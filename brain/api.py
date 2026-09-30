"""One API that projects 1, 2 and 3 call. Run: uvicorn brain.api:app --port 8000"""
from fastapi import FastAPI
from pydantic import BaseModel

from . import db
from .answer import answer
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


@app.post("/ingest")
def ingest_endpoint(req: IngestReq):
    return ingest(req.business_id, req.business_name, req.sources)


@app.post("/ask")
def ask_endpoint(req: AskReq):
    return answer(req.business_id, req.question)


@app.get("/health")
def health():
    return {"ok": True}
