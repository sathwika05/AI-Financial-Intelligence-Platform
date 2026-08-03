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


    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_PROJECT: str = "financial-intelligence-pipeline"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()