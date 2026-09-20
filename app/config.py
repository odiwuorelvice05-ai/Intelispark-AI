import os

from dotenv import load_dotenv

load_dotenv()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class Settings:
    app_name: str = os.getenv("APP_NAME", "Intelispark AI")
    environment: str = os.getenv("ENVIRONMENT", "development")

    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # Language model (any OpenAI-compatible chat-completions endpoint with tool calling).
    # Defaults target Mistral; MISTRAL_API_KEY is accepted so an existing deployment keeps working.
    llm_api_key: str = os.getenv("LLM_API_KEY") or os.getenv("MISTRAL_API_KEY") or ""
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.mistral.ai/v1")
    llm_model: str = os.getenv("LLM_MODEL", "mistral-small-latest")

    # Whole-turn time budget (seconds) and how many prior messages the model sees.
    assistant_deadline_s: float = _float_env("ASSISTANT_DEADLINE_S", 7.0)
    assistant_history_messages: int = _int_env("ASSISTANT_HISTORY_MESSAGES", 10)


settings = Settings()
