from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# RFC 7518 s3.2: HMAC-SHA keys must be >= 256 bits. Enforced by jjwt on the
# Java side; enforced here so both services agree.
MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crm:crm@localhost:5433/crm"
    # >= 32 bytes is not arbitrary: RFC 7518 requires >= 256 bits for HMAC-SHA,
    # and the Java analytics service (jjwt) enforces it at startup. python-jose
    # does not, so a short secret works here and hard-fails there -- validated
    # below so the failure surfaces on this side too.
    jwt_secret: str = "dev-only-insecure-secret-change-me-in-production-32b+"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # The dashboard runs on its own origin. Comma-separated so compose can
    # override it with a single env var.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # "stub" runs the whole app with no API key and no network calls.
    # Switch to "anthropic" once ANTHROPIC_API_KEY is set.
    llm_provider: str = "stub"

    anthropic_api_key: str = ""
    lead_scoring_model: str = "claude-sonnet-5"
    follow_up_model: str = "claude-sonnet-5"
    nl_query_model: str = "claude-sonnet-5"


    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("jwt_secret")
    @classmethod
    def _secret_is_strong_enough(cls, value: str) -> str:
        if len(value.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes "
                f"(got {len(value.encode())}). RFC 7518 requires >= 256 bits for "
                "HMAC-SHA, and the Java analytics service refuses to start on a "
                "shorter key -- so a short secret here would break that service "
                "while appearing to work in Python."
            )
        return value


settings = Settings()
