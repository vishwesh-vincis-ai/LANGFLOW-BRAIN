"""Langflow component that calls the Business Brain /chat endpoint.

Kept as a file so it can be reviewed and diffed; flows/build.py embeds it in flows/brain.json.
"""
import re

import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import IntInput, MessageInput, MessageTextInput, Output
from lfx.schema.message import Message


class BusinessBrainComponent(Component):
    display_name = "Business Brain"
    description = "Answers from the business's own documents with citations, or hands off to the team."
    icon = "brain"
    name = "BusinessBrain"

    inputs = [
        MessageInput(name="message", display_name="Customer message", required=True),
        MessageTextInput(name="business_id", display_name="Business ID", value="smile-point",
                         info="Which business's documents to answer from."),
        MessageTextInput(name="api_url", display_name="Brain API URL", value="http://localhost:8000",
                         advanced=True),
        IntInput(name="timeout", display_name="Timeout (s)", value=60, advanced=True),
    ]
    outputs = [Output(display_name="Reply", name="reply", method="ask_brain")]

    def ask_brain(self) -> Message:
        # One Langflow chat session = one brain session, so handoff state (name, phone) carries over.
        session_id = self.message.session_id or self.graph.session_id or "langflow"
        resp = httpx.post(
            f"{self.api_url.rstrip('/')}/chat",
            json={"business_id": self.business_id, "session_id": session_id, "message": self.message.text},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        reply = re.sub(r"\s*\[\d+\]", "", data["reply"])  # numbered markers; sources are listed below
        if data.get("citations"):
            sources = sorted({f"{c['source'].rsplit('/', 1)[-1]} › {c['section']}" for c in data["citations"]})
            reply += "\n\nSources: " + "; ".join(sources)
        self.status = data
        return Message(text=reply)
