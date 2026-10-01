# Langflow layer

The owner-facing, visual side of the brain. A custom **Business Brain** component wraps the brain's
`/chat` and `/ask` endpoints, so the flow can be rewired in Langflow's editor while the guarantees
(citations, "I don't know", human handoff, tenant isolation) stay enforced by the API.

![Business Brain flow in Langflow](flow-canvas.png)

## Files
| Path | What it is |
|---|---|
| `components/business_brain/` | The custom component (Langflow 1.12, `lfx` API) |
| `flows/business_brain_chat.json` | Exported flow: Chat Input → Business Brain → Chat Output. Import via *New Flow → Import* |
| `build_flow.py` | Builds the flow with Langflow's graph API and adds canvas layout; regenerates the JSON |

## Run
```bash
# 1. brain API (from the repo root)
.venv/bin/uvicorn brain.api:app --port 8000

# 2. Langflow, with the custom component on its path
pip install langflow
export LANGFLOW_COMPONENTS_PATH=$PWD/langflow/components
langflow run            # open http://localhost:7860, import flows/business_brain_chat.json

# or headless, no UI:
lfx run --format text langflow/flows/business_brain_chat.json "How much is a zirconia crown?"
```

## Verified
- `lfx run` on the exported JSON: cited answer for a price question, handoff for an unanswerable one.
- Langflow REST (`POST /api/v1/run/{flow_id}`), three turns on one `session_id`: question → "talk to a real
  person" → name and phone → handoff opened. Session memory carries across turns through the component.
- The flow imports into the Langflow 1.12.4 UI and renders as shown above.

The component's **Mode** switch picks `chat` (stateful, collects contact details on handoff) or `ask`
(one-off answer). **Business ID** points the same flow at any tenant the brain has ingested.
