from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    database_url: str = "sqlite:///./rankcraft.db"
    app_name: str = "Ranksit"
    secret_key: str = "dev-insecure-change-me-in-production"
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = "http://localhost:8000"


settings = Settings()
