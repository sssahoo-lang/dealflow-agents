from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crm:crm@localhost:5433/crm"

    # Tokens are signed with RS256, so the CRM holds a private key and nothing
    # else needs one. Verifiers fetch the public half from /.well-known/jwks.json.
    # Empty means "generate an ephemeral keypair at startup" -- see app/core/keys.py
    # for why that is the default rather than a checked-in development key.
    jwt_private_key: str = ""
    jwt_algorithm: str = "RS256"
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

    # Empty = tracing disabled (the default; see app/observability/tracing.py).
    # Set to an OTLP/HTTP collector origin, e.g. http://jaeger:4318 -- what
    # docker-compose sets so `docker compose up` shows a live trace out of the
    # box, while a bare `pytest` run (no env var set) stays exactly as
    # dependency-free as every other suite in this repo.
    otel_exporter_otlp_endpoint: str = ""


    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("jwt_algorithm")
    @classmethod
    def _algorithm_is_asymmetric(cls, value: str) -> str:
        if not value.startswith("RS"):
            raise ValueError(
                f"JWT_ALGORITHM must be an RSA algorithm (got {value!r}). A "
                "symmetric algorithm would hand every verifier the ability to "
                "mint -- including the read-only analytics service, whose whole "
                "design is that it cannot write anything the CRM trusts."
            )
        return value


settings = Settings()
