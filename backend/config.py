from pydantic_settings import BaseSettings, SettingsConfigDict


# Redis is a cache and a rate-limit store, not a dependency: both callers
# fail open, so an unreachable one degrades rather than breaks. Nothing
# connects at import either, so this address answering nothing is fine.
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str 
    LLM_KEY_ENCRYPTION_SECRET: str
    
    # Defaulted on purpose. With no default a deployment that did not set
    # this failed pydantic validation at import and the container died
    # before any of the fail-open handling downstream could run -- which
    # is the opposite of how the rest of the code treats redis.
    REDIS_URL: str = DEFAULT_REDIS_URL

    APP_ENV: str = "development"

    # Which routers get mounted. "portfolio" is the public unauthenticated
    # preprod: the UI screen and nothing else. "full" is production, where
    # the admin, indexing and evaluation surfaces are reachable.
    DEPLOYMENT_MODE: str = "full"

    OPENAI_API_KEY: str = ""

    # No default: this repo is public, and the previous value
    # ("admin-secret-key") was therefore a published credential guarding
    # /api/index/documents. Empty means the admin routes refuse rather
    # than accept a key everyone can read.
    ADMIN_API_KEY: str = ""

    # Signs access tokens. No default: a shared fallback secret would let
    # anyone holding this repo mint an admin token for any deployment.
    JWT_SECRET: str = ""
    JWT_EXPIRE_HOURS: int = 12

    # The S3 -> SQS -> Fargate ingestion path. Terraform sets these on the
    # task; empty means the AWS path is off and the fetcher writes straight
    # to Postgres, which is what every local run does.
    AWS_REGION: str = "us-east-1"
    RAW_BUCKET: str = ""
    PROCESSED_BUCKET: str = ""
    INGESTION_QUEUE_URL: str = ""
    ALPHA_VANTAGE_API_KEY: str = ""

    # SEC EDGAR requires a User-Agent naming the caller and a contact
    # address. Empty means the EDGAR collector is off: it refuses to call
    # rather than sending an anonymous request, which SEC rejects and
    # which gets the whole address blocked when it is a shared one.
    SEC_USER_AGENT: str = ""


    # Security. Everything in backend/security is on except the LLM guard,
    # which costs an API round trip per query — about 1-3s against ~0.4ms
    # for every other layer combined. Set true to enable it.
    SECURITY_LLM_GUARD_ENABLED: bool = False
    SECURITY_RATE_LIMIT: int = 20
    SECURITY_RATE_WINDOW_SECONDS: int = 60

    # A SELECT-only role for the generated-SQL path. Falls back to
    # DATABASE_URL when unset, which is the current behaviour.
    READONLY_DATABASE_URL: str = ""

    # Where the admin UI links out to for observability, once deployed.
    # Both are console URLs that differ per account, region and project,
    # so they are configuration rather than constants. Empty means this
    # deployment has nowhere to point -- the ordinary state on a laptop --
    # and the UI says which variable to set rather than showing a dead
    # link. Not secrets: a console URL names a log group, not a key.
    CLOUDWATCH_LOGS_URL: str = ""
    LANGSMITH_PROJECT_URL: str = ""

    LANGSMITH_API_KEY: str = ""
    LANGSMITH_TRACING: bool = False
    LANGCHAIN_PROJECT: str = "ai-financial-intelligence-platform"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()