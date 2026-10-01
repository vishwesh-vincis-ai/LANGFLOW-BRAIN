"""Everything the owner dashboard shows, computed from the brain's own tables. One call, one business."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import booking, config
from .db import connect

RESULTS = Path(__file__).parent.parent / "showcase" / "results.json"
LATENCY_BUCKETS = [250, 500, 1000, 2000, 4000]   # ms upper bounds; last bucket is "over 4 s"


def businesses() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name FROM businesses ORDER BY created_at").fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


def snapshot(business_id: str, days: int = 7) -> dict:
    with connect() as conn:
        name, settings = conn.execute("SELECT name, settings FROM businesses WHERE id = %s", (business_id,)).fetchone()

        q = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE answered), "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM queries WHERE business_id = %s",
            (business_id,),
        ).fetchone()
        latencies = [r[0] for r in conn.execute(
            "SELECT latency_ms FROM queries WHERE business_id = %s", (business_id,)).fetchall()]

        topics = conn.execute(
            """SELECT c.heading, d.title, count(*) FROM queries q, unnest(q.cited_chunk_ids) cid
               JOIN chunks c ON c.id = cid JOIN documents d ON d.id = c.document_id
               WHERE q.business_id = %s GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT 8""",
            (business_id,),
        ).fetchall()

        gaps = conn.execute(
            """SELECT question, count(*), max(created_at) FROM queries WHERE business_id = %s AND NOT answered
               GROUP BY question ORDER BY 2 DESC, 3 DESC LIMIT 8""",
            (business_id,),
        ).fetchall()

        recent = conn.execute(
            """SELECT q.question, q.answered, q.answer, q.latency_ms, q.created_at,
                      (SELECT c.heading FROM chunks c WHERE c.id = q.cited_chunk_ids[1])
               FROM queries q WHERE q.business_id = %s ORDER BY q.id DESC LIMIT 15""",
            (business_id,),
        ).fetchall()

        handoffs = conn.execute(
            """SELECT id, question, name, phone, status, session_id, created_at FROM handoffs
               WHERE business_id = %s AND status <> 'collecting' ORDER BY created_at DESC LIMIT 20""",
            (business_id,),
        ).fetchall()
        collecting = conn.execute(
            "SELECT count(*) FROM handoffs WHERE business_id = %s AND status = 'collecting'", (business_id,)
        ).fetchone()[0]

        drafts = conn.execute(
            """SELECT id, to_address, subject, body, reason, status, created_at FROM email_drafts
               WHERE business_id = %s ORDER BY created_at DESC LIMIT 20""",
            (business_id,),
        ).fetchall()

        start = datetime.combine(date.today(), datetime.min.time())
        appts = conn.execute(
            """SELECT id, starts_at, ends_at, service, name, phone FROM appointments
               WHERE business_id = %s AND status = 'booked' AND starts_at >= %s AND starts_at < %s
               ORDER BY starts_at""",
            (business_id, start, start + timedelta(days=days)),
        ).fetchall()

        docs = conn.execute(
            """SELECT d.title, d.source_uri, d.synced_at, count(c.id), count(c.embedding)
               FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
               WHERE d.business_id = %s GROUP BY d.id ORDER BY d.title""",
            (business_id,),
        ).fetchall()

    week = []
    for i in range(days):
        d = date.today() + timedelta(days=i)
        week.append({"day": d.isoformat(), "free_slots": len(booking.free_slots(business_id, d)),
                     "booked": sum(1 for a in appts if a[1].date() == d)})

    hist = [0] * (len(LATENCY_BUCKETS) + 1)
    for ms in latencies:
        hist[next((i for i, b in enumerate(LATENCY_BUCKETS) if ms <= b), len(LATENCY_BUCKETS))] += 1

    evals = None
    if RESULTS.exists():
        r = json.loads(RESULTS.read_text())
        evals = {"generated_at": r["generated_at"], "mode": r["mode"], "pass": r["evals"]["pass"],
                 "total": r["evals"]["total"], "by_category": r["evals"]["by_category"],
                 "cases": [{k: c[k] for k in ("id", "category", "question", "pass", "why", "answered", "answer",
                                             "citations", "latency_ms")} for c in r["evals"]["cases"]],
                 "latency_p50_ms": r["evals"]["latency_p50_ms"], "latency_p95_ms": r["evals"]["latency_p95_ms"],
                 "conversations": r.get("conversations", [])}

    total, answered, p50, p95 = q
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "business": {"id": business_id, "name": name, "settings": settings},
        "mode": {"llm": config.LLM_PROVIDER, "embeddings": config.EMBED_PROVIDER,
                 "llm_model": config.NVIDIA_CHAT_MODEL if config.LLM_PROVIDER == "nvidia" else config.LLM_PROVIDER},
        "questions": {"total": total, "answered": answered, "handed_off": total - answered,
                      "p50_ms": round(p50 or 0), "p95_ms": round(p95 or 0),
                      "latency_hist": {"buckets": LATENCY_BUCKETS, "counts": hist}},
        "topics": [{"section": t[0], "doc": t[1], "count": t[2]} for t in topics],
        "recent": [{"question": r[0], "answered": r[1], "answer": r[2], "latency_ms": r[3],
                    "created_at": r[4].isoformat(), "cited": r[5]} for r in recent],
        "faq_gaps": [{"question": g[0], "count": g[1], "last": g[2].isoformat()} for g in gaps],
        "handoffs": [{"id": h[0], "question": h[1], "name": h[2], "phone": h[3], "status": h[4], "channel": h[5],
                      "created_at": h[6].isoformat()} for h in handoffs],
        "collecting": collecting,
        "drafts": [{"id": d[0], "to": d[1], "subject": d[2], "body": d[3], "reason": d[4], "status": d[5],
                    "created_at": d[6].isoformat()} for d in drafts],
        "appointments": [{"id": a[0], "starts_at": a[1].isoformat(), "ends_at": a[2].isoformat(), "service": a[3],
                          "name": a[4], "phone": a[5]} for a in appts],
        "week": week,
        "documents": [{"title": d[0], "source": Path(d[1]).name, "synced_at": d[2].isoformat(), "sections": d[3],
                       "embedded": d[4]} for d in docs],
        "evals": evals,
    }


def set_draft_status(business_id: str, draft_id: int, status: str) -> bool:
    with connect() as conn:
        return conn.execute(
            "UPDATE email_drafts SET status = %s WHERE id = %s AND business_id = %s AND status = 'draft'",
            (status, draft_id, business_id),
        ).rowcount == 1


def close_handoff(business_id: str, handoff_id: int) -> bool:
    with connect() as conn:
        return conn.execute(
            "UPDATE handoffs SET status = 'closed' WHERE id = %s AND business_id = %s AND status = 'open'",
            (handoff_id, business_id),
        ).rowcount == 1
