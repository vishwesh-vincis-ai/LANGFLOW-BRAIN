"""Embedding and LLM providers. Swappable, and every one of them is optional."""
import time

import httpx

from . import config

# Token counts from the most recent calls, for cost measurement (benchmark/run.py reads and resets these).
USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "embed_tokens": 0}


def _nvidia(path: str, payload: dict) -> dict:
    # The hosted endpoints return 429/5xx under load; back off instead of failing the whole eval run.
    for attempt in range(5):
        resp = httpx.post(
            f"{config.NVIDIA_BASE_URL}/{path}",
            headers={"Authorization": f"Bearer {config.NVIDIA_API_KEY}"},
            json=payload,
            timeout=90,
        )
        if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 4:
            break
        time.sleep(2 ** attempt)
    resp.raise_for_status()
    return resp.json()


def embed(texts: list[str], task: str = "passage") -> list[list[float]] | None:
    """task is "passage" for stored chunks, "query" for questions (asymmetric retrieval models)."""
    if config.EMBED_PROVIDER == "nvidia":
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            data = _nvidia(
                "embeddings",
                {"model": config.NVIDIA_EMBED_MODEL, "input": texts[i : i + 50],
                 "input_type": task, "encoding_format": "float", "truncate": "END",
                 "dimensions": config.EMBED_DIM},
            )
            out.extend(d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"]))
            USAGE["embed_tokens"] += (data.get("usage") or {}).get("prompt_tokens", 0)
        return out
    if config.EMBED_PROVIDER == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        out = []
        for i in range(0, len(texts), 100):
            resp = client.models.embed_content(
                model=config.GEMINI_EMBED_MODEL,
                contents=texts[i : i + 100],
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=config.EMBED_DIM),
            )
            out.extend(e.values for e in resp.embeddings)
        return out
    return None


def complete(system: str, user: str, max_tokens: int = 600) -> str | None:
    if config.LLM_PROVIDER == "nvidia":
        data = _nvidia(
            "chat/completions",
            {"model": config.NVIDIA_CHAT_MODEL, "temperature": 0, "max_tokens": max_tokens,
             # Nemotron reasons by default; grounded answers need the answer, not the scratchpad.
             "chat_template_kwargs": {"enable_thinking": False},
             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
        u = data.get("usage") or {}
        USAGE["prompt_tokens"] += u.get("prompt_tokens", 0)
        USAGE["completion_tokens"] += u.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"]
    if config.LLM_PROVIDER == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0,
                                               max_output_tokens=max_tokens),
        )
        return resp.text
    if config.LLM_PROVIDER == "claude":
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text
    return None
