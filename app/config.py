import os


class Settings:
    app_name: str = os.getenv("APP_NAME", "Forge AI")
    environment: str = os.getenv("ENVIRONMENT", "development")


settings = Settings()
