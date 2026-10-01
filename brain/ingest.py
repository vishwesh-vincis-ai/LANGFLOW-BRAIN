"""Ingest files and URLs into the brain. Re-running is safe: unchanged sources are skipped."""
import hashlib
import json
import re
from pathlib import Path

import httpx

from . import config, providers
from .db import connect

MAX_CHARS = 900
OVERLAP = 150
DAYS = {"Mon": "Monday", "Tue": "Tuesday", "Tues": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday",
        "Thur": "Thursday", "Thurs": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}
_ABBR = r"(?:Mon|Tues?|Wed|Thu(?:rs?)?|Fri|Sat|Sun)"
_DAY = rf"(?:{_ABBR}\b\.?|(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b)"
_JOIN = r"\s*(?:[-–—&,/]|\b(?:to|thru|through|and)\b)\s*"
# A capitalised abbreviation counts as a day only inside a run of days ("Mon–Sat", "Sat/Sun", "Mon thru Fri")
# or when a time or "Closed" follows ("Fri. Closed", "Sun 10:00"). Punctuation alone is not enough:
# "Sun-kissed", "Sun & Sand", "Sat-nav" and "sun protection" stay as they are.
DAY_RUN = re.compile(rf"\b{_DAY}(?:{_JOIN}{_DAY})+")
DAY_ABBR = re.compile(rf"\b({_ABBR})\b\.?")
DAY_BEFORE_TIME = re.compile(rf"\b({_ABBR})\b\.?(?=:?\s*(?:\d|[Cc]losed\b))")
FULL_DAY = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b")


def read_source(uri: str) -> tuple[str, str]:
    """Return (title, text) for a local file or http(s) URL."""
    if uri.startswith(("http://", "https://")):
        html = httpx.get(uri, timeout=20, follow_redirects=True).text
        title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return (title.group(1).strip() if title else uri), re.sub(r"[ \t]+", " ", text)
    path = Path(uri)
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return path.stem, "\n\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    return path.stem, path.read_text(encoding="utf-8")


def _spell(m: re.Match) -> str:
    return DAYS[m.group(1)]


def normalize(text: str) -> str:
    """Spell out abbreviated weekdays. "Fri. Closed" shares no word with "Are you open on Fridays?" and its
    embedding lands under MIN_VECTOR_SIM, so without this an hours question retrieves nothing."""
    text = DAY_RUN.sub(lambda run: DAY_ABBR.sub(_spell, run.group(0)), text)
    return DAY_BEFORE_TIME.sub(_spell, text)


def chunk(text: str) -> list[tuple[str, str]]:
    """Split on markdown headings, then window long sections. Returns (heading, body) pairs."""
    sections: list[tuple[str, str]] = []
    heading, buf = "", []
    for line in text.splitlines():
        if m := re.match(r"^#{1,6}\s+(.*)", line):
            if "".join(buf).strip():
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((heading, "\n".join(buf).strip()))

    out = []
    for h, body in sections:
        # A section listing three or more weekdays is a schedule; say so, so "what are your hours" finds it.
        if len(set(FULL_DAY.findall(body))) >= 3 and not re.search(r"hour|timing", h, re.I):
            h = f"{h} (opening hours)".strip()
        start = 0
        while start < len(body):
            out.append((h, body[start : start + MAX_CHARS]))
            if start + MAX_CHARS >= len(body):
                break
            start += MAX_CHARS - OVERLAP
    return out


def _stored_pieces(conn, doc_id: int) -> list[tuple[str, str]]:
    return [tuple(r) for r in conn.execute(
        "SELECT heading, body FROM chunks WHERE document_id = %s ORDER BY ord", (doc_id,)).fetchall()]


def ingest(business_id: str, business_name: str, uris: list[str]) -> dict:
    stats = {"added": 0, "updated": 0, "unchanged": 0, "chunks": 0}
    with connect() as conn:
        conn.execute(
            "INSERT INTO businesses (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
            (business_id, business_name),
        )
        for uri in uris:
            if not uri.startswith(("http://", "https://")):
                uri = str(Path(uri).resolve())  # one file = one document, however the path was spelled
            title, text = read_source(uri)
            pieces = chunk(normalize(text))
            # Hash what we store, not the raw text: a chunker change rebuilds only the documents it changes.
            digest = hashlib.sha256(json.dumps(pieces).encode()).hexdigest()
            row = conn.execute(
                "SELECT d.id, d.content_hash, bool_or(c.embedding IS NULL) FROM documents d "
                "LEFT JOIN chunks c ON c.document_id = d.id "
                "WHERE d.business_id = %s AND d.source_uri = %s GROUP BY d.id",
                (business_id, uri),
            ).fetchone()
            if row and row[1] != digest and _stored_pieces(conn, row[0]) == pieces:
                # Hashed by an older release, but the chunks are the same: keep their embeddings.
                conn.execute("UPDATE documents SET content_hash = %s WHERE id = %s", (digest, row[0]))
                row = (row[0], digest, row[2])
            # Unchanged text is skipped, unless it was ingested without embeddings and a provider is now set.
            if row and row[1] == digest and not (row[2] and config.EMBED_PROVIDER != "none"):
                stats["unchanged"] += 1
                continue

            vectors = providers.embed([f"{h}\n{b}" for h, b in pieces]) or [None] * len(pieces)
            with conn.transaction():
                if row:
                    doc_id = row[0]
                    conn.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))
                    conn.execute(
                        "UPDATE documents SET content_hash = %s, title = %s, synced_at = now() WHERE id = %s",
                        (digest, title, doc_id),
                    )
                    stats["updated"] += 1
                else:
                    doc_id = conn.execute(
                        "INSERT INTO documents (business_id, source_uri, title, content_hash) "
                        "VALUES (%s, %s, %s, %s) RETURNING id",
                        (business_id, uri, title, digest),
                    ).fetchone()[0]
                    stats["added"] += 1
                for i, ((h, b), vec) in enumerate(zip(pieces, vectors)):
                    conn.execute(
                        "INSERT INTO chunks (document_id, business_id, ord, heading, body, embedding) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (doc_id, business_id, i, h, b, vec),
                    )
            stats["chunks"] += len(pieces)
    return stats
