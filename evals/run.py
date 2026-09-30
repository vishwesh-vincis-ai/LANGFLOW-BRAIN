"""Run the eval set. Usage: python -m evals.run  (ingests sample data first)"""
import json
import statistics
from pathlib import Path

from brain import config, db
from brain.answer import answer
from brain.ingest import ingest
from brain.retrieve import search

ROOT = Path(__file__).parent.parent
CLINIC = "smile-point"


def setup() -> None:
    db.migrate()
    ingest(CLINIC, "Smile Point Dental", sorted(str(p) for p in (ROOT / "data/sample_clinic").glob("*.md")))
    ingest("glow-studio", "Glow Studio Salon", [str(ROOT / "data/sample_salon/prices.md")])


def main() -> None:
    setup()
    cases = [json.loads(l) for l in (ROOT / "evals/clinic.jsonl").read_text().splitlines() if l.strip()]
    results, latencies = [], []
    for c in cases:
        hits = search(CLINIC, c["q"])
        leaked = any("sample_salon" in h.source_uri for h in hits)
        r = answer(CLINIC, c["q"])
        latencies.append(r["latency_ms"])
        if c["type"] == "answer":
            retrieved = any(h.source_uri.endswith(c["source"]) for h in hits)
            correct = r["answered"] and all(m.lower() in r["answer"].lower() for m in c["must"])
            ok = retrieved and correct and not leaked
            why = "" if ok else ("leak" if leaked else "not retrieved" if not retrieved else "wrong/abstained")
        else:
            ok = not r["answered"] and not leaked
            why = "" if ok else ("leak" if leaked else "answered when it should abstain")
        results.append((c, ok, why, r))

    by_type: dict[str, list[bool]] = {}
    for c, ok, *_ in results:
        by_type.setdefault(c["id"][0], []).append(ok)
    names = {"a": "answerable", "u": "unanswerable", "t": "cross-tenant", "i": "injection"}

    print(f"mode: llm={config.LLM_PROVIDER}  vectors={'on' if config.GEMINI_API_KEY else 'off'}\n")
    for c, ok, why, r in results:
        if not ok:
            print(f"FAIL {c['id']}: {c['q']}\n     -> {why}: {r['answer'][:110]!r}")
    print()
    for k, oks in by_type.items():
        print(f"{names[k]:<14} {sum(oks):>2}/{len(oks)}")
    total = sum(ok for _, ok, *_ in results)
    print(f"{'TOTAL':<14} {total:>2}/{len(results)}  ({100 * total / len(results):.0f}%)")
    print(f"latency p50={statistics.median(latencies):.0f}ms  max={max(latencies)}ms")


if __name__ == "__main__":
    main()
