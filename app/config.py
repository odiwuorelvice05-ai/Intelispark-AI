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


settings = Settings()
