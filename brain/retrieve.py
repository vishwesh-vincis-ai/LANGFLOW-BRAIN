"""Hybrid retrieval: Postgres full-text + pgvector, fused with reciprocal rank fusion."""
import re
from dataclasses import dataclass

import numpy as np

from . import config, providers
from .db import connect

RRF_K = 60


@dataclass
class Hit:
    chunk_id: int
    source_uri: str
    title: str
    heading: str
    body: str
    score: float
    keyword_rank: float | None
    vector_sim: float | None


def _or_query(question: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", question.lower())
    return " | ".join(dict.fromkeys(w for w in words if len(w) > 1))


def search(business_id: str, question: str, k: int = config.TOP_K) -> list[Hit]:
    rows: dict[int, dict] = {}
    with connect() as conn:
        tsq = _or_query(question)
        if tsq:
            for rank, r in enumerate(
                conn.execute(
                    """
                    SELECT c.id, d.source_uri, d.title, c.heading, c.body,
                           ts_rank_cd(c.tsv, to_tsquery('english', %s)) AS kr
                    FROM chunks c JOIN documents d ON d.id = c.document_id
                    WHERE c.business_id = %s AND c.tsv @@ to_tsquery('english', %s)
                    ORDER BY kr DESC LIMIT 20
                    """,
                    (tsq, business_id, tsq),
                ).fetchall()
            ):
                rows.setdefault(r[0], {"r": r, "rrf": 0.0, "kr": r[5], "vs": None})["rrf"] += 1 / (RRF_K + rank)

        qvec = providers.embed([question], task="query")
        if qvec:
            for rank, r in enumerate(
                conn.execute(
                    """
                    SELECT c.id, d.source_uri, d.title, c.heading, c.body,
                           1 - (c.embedding <=> %s) AS sim
                    FROM chunks c JOIN documents d ON d.id = c.document_id
                    WHERE c.business_id = %s AND c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> %s LIMIT 20
                    """,
                    (np.array(qvec[0]), business_id, np.array(qvec[0])),
                ).fetchall()
            ):
                if r[5] < config.MIN_VECTOR_SIM:
                    continue
                entry = rows.setdefault(r[0], {"r": r, "rrf": 0.0, "kr": None, "vs": None})
                entry["rrf"] += 1 / (RRF_K + rank)
                entry["vs"] = r[5]

    ranked = sorted(rows.values(), key=lambda e: e["rrf"], reverse=True)[:k]
    return [
        Hit(e["r"][0], e["r"][1], e["r"][2], e["r"][3], e["r"][4], e["rrf"], e["kr"], e["vs"])
        for e in ranked
    ]
