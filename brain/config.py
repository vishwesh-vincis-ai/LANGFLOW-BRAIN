import os
from pathlib import Path

from dotenv import load_dotenv

# Real environment variables win over .env, so cloud secrets override a local file.
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/brain")

# Providers are optional. Without keys the brain still runs: keyword retrieval + extractive answers.
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_CHAT_MODEL = os.getenv("NVIDIA_CHAT_MODEL", "meta/llama-3.3-70b-instruct")
NVIDIA_EMBED_MODEL = os.getenv("NVIDIA_EMBED_MODEL", "nvidia/nv-embedqa-e5-v5")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
EMBED_DIM = 1024  # nv-embedqa-e5-v5 is natively 1024; Gemini is asked for 1024


def _first_available() -> str:
    for name, key in (("nvidia", NVIDIA_API_KEY), ("gemini", GEMINI_API_KEY), ("claude", ANTHROPIC_API_KEY)):
        if key:
            return name
    return "none"


# "nvidia", "gemini", "claude", or "none" (extractive only)
LLM_PROVIDER = os.getenv("LLM_PROVIDER") or _first_available()
# Embeddings: nvidia or gemini (Claude has no embedding API). "none" = keyword search only.
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER") or (
    "nvidia" if NVIDIA_API_KEY else "gemini" if GEMINI_API_KEY else "none"
)

TOP_K = int(os.getenv("TOP_K", "5"))
# Below this cosine similarity, a vector hit is noise. Tune this against the eval set, not by feel.
MIN_VECTOR_SIM = float(os.getenv("MIN_VECTOR_SIM", "0.30"))
