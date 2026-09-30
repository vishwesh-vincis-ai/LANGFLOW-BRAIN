"""Render showcase/index.html from results.json. Usage: python -m showcase.build"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def main() -> None:
    data = json.loads((HERE / "results.json").read_text())
    html = (HERE / "template.html").read_text()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (HERE / "index.html").write_text(html.replace("/*__DATA__*/null", blob))
    print(f"wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()
