import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres@localhost:5432/brain")

# Providers are optional. Without keys the brain still runs: keyword retrieval + extractive answers.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = 768

# "gemini", "claude", or "none" (extractive only)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini" if GEMINI_API_KEY else ("claude" if ANTHROPIC_API_KEY else "none"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

TOP_K = int(os.getenv("TOP_K", "5"))
# Below this cosine similarity, a vector hit is noise. Tune this against the eval set, not by feel.
MIN_VECTOR_SIM = float(os.getenv("MIN_VECTOR_SIM", "0.55"))
