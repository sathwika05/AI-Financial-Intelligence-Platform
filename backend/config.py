from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str 
    LLM_KEY_ENCRYPTION_SECRET: str
    
    REDIS_URL: str
    APP_ENV: str = "development"

    OPENAI_API_KEY: str = ""
    ADMIN_API_KEY: str = "admin-secret-key"
    ALPHA_VANTAGE_API_KEY: str = ""


    # Security. Everything in backend/security is on except the LLM guard,
    # which costs an API round trip per query — about 1-3s against ~0.4ms
    # for every other layer combined. Set true to enable it.
    SECURITY_LLM_GUARD_ENABLED: bool = False
    SECURITY_RATE_LIMIT: int = 20
    SECURITY_RATE_WINDOW_SECONDS: int = 60

    # A SELECT-only role for the generated-SQL path. Falls back to
    # DATABASE_URL when unset, which is the current behaviour.
    READONLY_DATABASE_URL: str = ""

    LANGSMITH_API_KEY: str = ""
    LANGSMITH_TRACING: bool = False
    LANGCHAIN_PROJECT: str = "ai-financial-intelligence-platform"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()