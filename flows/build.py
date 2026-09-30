"""Build flows/brain.json: Chat Input -> Business Brain -> Chat Output.

Usage: python -m flows.build   (needs a running Langflow; LANGFLOW_URL defaults to http://localhost:7860)
Node templates come from that Langflow, so the export matches its version instead of being hand-written.
"""
import json
import os
from pathlib import Path

import httpx

HERE = Path(__file__).parent
LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://localhost:7860")


def _handle(d: dict) -> str:
    # Langflow encodes edge handles as JSON with œ in place of double quotes.
    return json.dumps(d, separators=(", ", ": ")).replace('"', "œ")


def _node(node_id: str, template: dict, x: int, y: int) -> dict:
    return {"id": node_id, "type": "genericNode", "position": {"x": x, "y": y},
            "data": {"id": node_id, "type": node_id.split("-")[0], "node": template,
                     "selected_output": template["outputs"][0]["name"]}}


def _edge(src: str, src_type: str, out: dict, tgt: str, field: str, target_field: dict) -> dict:
    sh = {"dataType": src_type, "id": src, "name": out["name"], "output_types": out["types"]}
    # The UI rebuilds this handle from the target field and drops the edge if it differs, so copy its type.
    th = {"fieldName": field, "id": tgt, "inputTypes": target_field["input_types"], "type": target_field["type"]}
    return {"source": src, "target": tgt, "sourceHandle": _handle(sh), "targetHandle": _handle(th),
            "data": {"sourceHandle": sh, "targetHandle": th},
            "id": f"reactflow__edge-{src}{_handle(sh)}-{tgt}{_handle(th)}", "animated": False, "className": ""}


def main() -> None:
    token = httpx.get(f"{LANGFLOW_URL}/api/v1/auto_login").json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    io = httpx.get(f"{LANGFLOW_URL}/api/v1/all", headers=auth, timeout=120).json()["input_output"]
    brain = httpx.post(f"{LANGFLOW_URL}/api/v1/custom_component", headers=auth, timeout=60,
                       json={"code": (HERE / "brain_component.py").read_text()}).json()["data"]
    chat_in, chat_out = io["ChatInput"], io["ChatOutput"]

    ids = {"in": "ChatInput-brain1", "brain": "BusinessBrain-brain2", "out": "ChatOutput-brain3"}
    nodes = [_node(ids["in"], chat_in, 0, 80), _node(ids["brain"], brain, 420, 0),
             _node(ids["out"], chat_out, 840, 80)]
    edges = [
        _edge(ids["in"], "ChatInput", chat_in["outputs"][0], ids["brain"], "message",
              brain["template"]["message"]),
        _edge(ids["brain"], "BusinessBrain", brain["outputs"][0], ids["out"], "input_value",
              chat_out["template"]["input_value"]),
    ]
    flow = {"name": "Business Brain", "endpoint_name": "business-brain", "is_component": False,
            "description": "Customer chat answered from the business's own documents, or handed to the team.",
            "data": {"nodes": nodes, "edges": edges, "viewport": {"x": 80, "y": 160, "zoom": 0.9}}}
    (HERE / "brain.json").write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {HERE / 'brain.json'}")


if __name__ == "__main__":
    main()
