"""Freeze the console with one business's data embedded, for publishing as a static page.

Usage: python -m dashboard.export [business_id]   → dashboard/snapshot.html
The snapshot page shows the same views; actions and live chat are disabled because there is no API behind it.
"""
import json
import sys
from pathlib import Path

from brain.dashboard import snapshot

HERE = Path(__file__).parent


def main(business_id: str = "smile-point") -> Path:
    data = json.dumps(snapshot(business_id), ensure_ascii=False, default=str).replace("</", "<\\/")
    out = HERE / "snapshot.html"
    out.write_text((HERE / "index.html").read_text().replace("/*__SNAPSHOT__*/null", data))
    print(f"wrote {out}")
    return out


if __name__ == "__main__":
    main(*sys.argv[1:])
