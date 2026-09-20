import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_name: str = os.getenv("APP_NAME", "Intelispark AI")
    environment: str = os.getenv("ENVIRONMENT", "development")

    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY",
        ""
    )

    # Optional language-model supplement. Leave blank to run Intelispark locally.
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

    # Agent (tool-calling) mode. Off by default: with INTELISPARK_AGENT unset the legacy engine runs unchanged.
    agent_mode: str = os.getenv("INTELISPARK_AGENT", "off").strip().lower()      # "on" | "off"
    ai_provider: str = os.getenv("AI_PROVIDER", "mistral").strip().lower()
    agent_model: str = os.getenv("AGENT_MODEL", "").strip() or os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    agent_reasoning_effort: str = os.getenv("AGENT_REASONING_EFFORT", "").strip()
    agent_deadline_s: float = float(os.getenv("AGENT_DEADLINE_S", "20"))
    agent_history_messages: int = int(os.getenv("AGENT_HISTORY_MESSAGES", "12"))


settings = Settings()
