"""Embedding and LLM providers. Swappable, and every one of them is optional."""
from . import config


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]] | None:
    if not config.GEMINI_API_KEY:
        return None
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    out: list[list[float]] = []
    for i in range(0, len(texts), 100):
        resp = client.models.embed_content(
            model=config.EMBED_MODEL,
            contents=texts[i : i + 100],
            config=types.EmbedContentConfig(task_type=task, output_dimensionality=config.EMBED_DIM),
        )
        out.extend(e.values for e in resp.embeddings)
    return out


def complete(system: str, user: str) -> str | None:
    if config.LLM_PROVIDER == "gemini" and config.GEMINI_API_KEY:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0),
        )
        return resp.text
    if config.LLM_PROVIDER == "claude" and config.ANTHROPIC_API_KEY:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=600,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text
    return None
