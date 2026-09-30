"""Ingest files and URLs into the brain. Re-running is safe: unchanged sources are skipped."""
import hashlib
import re
from pathlib import Path

import httpx

from . import providers
from .db import connect

MAX_CHARS = 900
OVERLAP = 150


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
        start = 0
        while start < len(body):
            out.append((h, body[start : start + MAX_CHARS]))
            if start + MAX_CHARS >= len(body):
                break
            start += MAX_CHARS - OVERLAP
    return out


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
            digest = hashlib.sha256(text.encode()).hexdigest()
            row = conn.execute(
                "SELECT id, content_hash FROM documents WHERE business_id = %s AND source_uri = %s",
                (business_id, uri),
            ).fetchone()
            if row and row[1] == digest:
                stats["unchanged"] += 1
                continue

            pieces = chunk(text)
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
