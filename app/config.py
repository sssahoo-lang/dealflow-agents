from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crm:crm@localhost:5433/crm"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # "stub" runs the whole app with no API key and no network calls.
    # Switch to "anthropic" once ANTHROPIC_API_KEY is set.
    llm_provider: str = "stub"

    anthropic_api_key: str = ""
    lead_scoring_model: str = "claude-sonnet-5"
    follow_up_model: str = "claude-sonnet-5"
    nl_query_model: str = "claude-sonnet-5"


settings = Settings()
