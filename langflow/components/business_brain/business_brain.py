"""Langflow component: send a customer message to the Business Brain and return its reply.

Drop this folder into Langflow's components path (LANGFLOW_COMPONENTS_PATH) and it appears in the
sidebar as "Business Brain". The owner can rewire everything around it visually; the brain keeps
the guarantees (citations, "I don't know", handoff, tenant isolation) on the server side.
"""
import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output, StrInput
from lfx.schema.message import Message


class BusinessBrainComponent(Component):
    display_name = "Business Brain"
    description = "Answers from the business's own documents with citations, or hands off to the team."
    icon = "brain"
    name = "BusinessBrain"

    inputs = [
        MessageTextInput(name="message", display_name="Customer message", required=True),
        StrInput(name="brain_url", display_name="Brain API URL", value="http://localhost:8000"),
        StrInput(name="business_id", display_name="Business ID", value="smile-point"),
        DropdownInput(
            name="mode",
            display_name="Mode",
            options=["chat", "ask"],
            value="chat",
            info="chat: remembers the conversation and collects contact details on handoff. ask: one-off answer.",
        ),
        StrInput(
            name="session_id",
            display_name="Session ID",
            value="",
            advanced=True,
            info="Customer thread (phone number, call id). Empty uses the Langflow session.",
        ),
    ]
    outputs = [Output(display_name="Reply", name="reply", method="reply")]

    def reply(self) -> Message:
        text = self.message.text if isinstance(self.message, Message) else str(self.message)
        session = self.session_id or self.graph.session_id or "langflow"
        if self.mode == "ask":
            body = {"business_id": self.business_id, "question": text}
        else:
            body = {"business_id": self.business_id, "session_id": session, "message": text}
        resp = httpx.post(f"{self.brain_url.rstrip('/')}/{self.mode}", json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        answer = data.get("reply") or data.get("answer", "")
        sources = [f"{c['source'].rsplit('/', 1)[-1]} › {c['section']}" for c in data.get("citations", [])]
        if sources:
            answer += "\n\nSources: " + "; ".join(sources)
        self.status = data.get("state", "answered" if data.get("answered") else "declined")
        return Message(text=answer)
