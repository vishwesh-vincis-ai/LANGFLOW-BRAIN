"""Build the Business Brain flow with Langflow's own graph API and export it as JSON.

Usage (from the Langflow venv):  python langflow/build_flow.py
Writes langflow/flows/business_brain_chat.json, importable in the Langflow UI (Import → Flow).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "components"))

from business_brain import BusinessBrainComponent  # noqa: E402
from lfx.components.input_output import ChatInput, ChatOutput  # noqa: E402
from lfx.graph import Graph  # noqa: E402


def build() -> Graph:
    chat_in = ChatInput(_id="ChatInput-Brain1")
    brain = BusinessBrainComponent(_id="BusinessBrain-Brain1")
    brain.set(message=chat_in.message_response, brain_url="http://localhost:8000", business_id="smile-point")
    chat_out = ChatOutput(_id="ChatOutput-Brain1")
    chat_out.set(input_value=brain.reply)
    return Graph(chat_in, chat_out)


# Canvas positions, left to right. graph.dump() gives an executable flow; the visual editor also needs
# React Flow fields (node type/position/size, string edge handles) to draw it.
POSITIONS = {"ChatInput-Brain1": (0, 120), "BusinessBrain-Brain1": (420, 40), "ChatOutput-Brain1": (860, 120)}


def _handle(d: dict) -> str:
    return json.dumps(d, separators=(",", ":")).replace('"', "\u0153")


def for_canvas(flow: dict) -> dict:
    for n in flow["data"]["nodes"]:
        x, y = POSITIONS[n["id"]]
        node = n["data"]["node"]
        n.update(type="genericNode", position={"x": x, "y": y}, positionAbsolute={"x": x, "y": y},
                 measured={"width": 320, "height": 260}, selected=False, dragging=False)
        n["data"].update(display_name=node["display_name"], description=node["description"])
    for e in flow["data"]["edges"]:
        sh, th = _handle(e["data"]["sourceHandle"]), _handle(e["data"]["targetHandle"])
        e.update(sourceHandle=sh, targetHandle=th, animated=False, className="", selected=False,
                 id=f"reactflow__edge-{e['source']}{sh}-{e['target']}{th}")
    flow["data"]["viewport"] = {"x": 80, "y": 160, "zoom": 0.9}
    return flow


if __name__ == "__main__":
    graph = build()
    flow = for_canvas(graph.dump(name="Business Brain Chat",
                                 description="Customer chat answered by the Business Brain: cited answers or a human handoff."))
    out = HERE / "flows" / "business_brain_chat.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(flow, indent=2))
    print(f"wrote {out} ({len(flow['data']['nodes'])} nodes, {len(flow['data']['edges'])} edges)")
