import os
from pathlib import Path

from dotenv import load_dotenv

# .env lives next to the backend folder root; fall back to process env if absent
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()  # also pick up a cwd-level .env when running from the repo root

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Which provider drives the assistant and the copilot.
# "openai" -> GPT via the Responses API (default), "anthropic" -> Claude via the Anthropic SDK.
USE_MODEL = os.getenv("USE_MODEL", "openai").strip().lower()
if USE_MODEL not in ("anthropic", "openai"):
    raise RuntimeError(f"USE_MODEL must be 'anthropic' or 'openai', got {USE_MODEL!r}")

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

# The model actually in use, for display and logging
MODEL = OPENAI_MODEL if USE_MODEL == "openai" else ANTHROPIC_MODEL

PORT = int(os.getenv("PORT", "8000"))

SEED_DIR = Path(__file__).resolve().parent / "seed"
