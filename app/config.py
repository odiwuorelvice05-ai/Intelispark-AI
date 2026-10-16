import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_name: str = os.getenv("APP_NAME", "Intelispark AI")
    environment: str = os.getenv("ENVIRONMENT", "development")

    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # Gemini is the sole hosted language-model provider for the intelligence engine.
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    # Keep the existing tool-calling agent and response contracts unchanged.
    agent_mode: str = os.getenv("INTELISPARK_AGENT", "on").strip().lower()
    ai_provider: str = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    agent_model: str = os.getenv("AGENT_MODEL", "").strip() or gemini_model
    agent_reasoning_effort: str = os.getenv("AGENT_REASONING_EFFORT", "").strip()
    agent_deadline_s: float = float(os.getenv("AGENT_DEADLINE_S", "20"))
    agent_history_messages: int = int(os.getenv("AGENT_HISTORY_MESSAGES", "12"))


settings = Settings()
