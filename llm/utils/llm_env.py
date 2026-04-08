import os
from pathlib import Path

from dotenv import load_dotenv


LLM_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

FALLBACK_GATEWAY_BASE_URL = "https://ai-gateway.uni-paderborn.de/v1/"
FALLBACK_GATEWAY_CHAT_MODEL = "gwdg.qwen3-30b-a3b-instruct-2507"
FALLBACK_OPENAI_CHAT_MODEL = "gpt-4o-mini"
FALLBACK_OPENAI_EMB_MODEL = "text-embedding-3-small"


def load_llm_env() -> None:
    """
    Backfill environment variables from llm/.env without overriding exported values.

    This keeps local CLI usage aligned with the repo's documented llm/.env workflow.
    """
    load_dotenv()
    load_dotenv(dotenv_path=LLM_ENV_FILE)


def env_or_fallback(var_name: str, fallback: str) -> str:
    return os.getenv(var_name, "").strip() or fallback


def get_gateway_base_url() -> str:
    return env_or_fallback("GATEWAY_BASE_URL", FALLBACK_GATEWAY_BASE_URL)


def get_gateway_chat_model() -> str:
    return env_or_fallback("GATEWAY_CHAT_MODEL", FALLBACK_GATEWAY_CHAT_MODEL)


def get_openai_chat_model() -> str:
    return env_or_fallback("OPENAI_CHAT_MODEL", FALLBACK_OPENAI_CHAT_MODEL)


def get_openai_emb_model() -> str:
    return env_or_fallback("OPENAI_EMB_MODEL", FALLBACK_OPENAI_EMB_MODEL)
