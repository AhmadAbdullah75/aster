from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = "postgresql+psycopg://nexus:nexus@127.0.0.1:5434/nexus"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-5-mini"
    openai_search_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    ai_provider: Literal["gemini", "openai"] = "gemini"
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_search_model: str = "gemini-2.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"
    free_only: bool = True
    web_backend: Literal["ddgs", "tavily", "gemini", "openai"] = "ddgs"
    tavily_api_key: str = ""
    session_secret: str = ""
    app_origin: str = "http://127.0.0.1:3000"
    data_dir: str = ".data"
    upload_limit_mib: int = 10
    user_quota_mib: int = 200
    request_timeout_seconds: int = 60
    run_timeout_seconds: int = 180
    max_tool_calls: int = 12
    max_output_tokens: int = 4096
    context_tokens: int = 16000
    session_days: int = 14
    cookie_secure: bool = False

    @property
    def provider_key(self) -> str:
        return self.gemini_api_key if self.ai_provider == "gemini" else self.openai_api_key

    @property
    def key_name(self) -> str:
        return "GEMINI_API_KEY" if self.ai_provider == "gemini" else "OPENAI_API_KEY"

    @property
    def chat_model(self) -> str:
        return self.gemini_chat_model if self.ai_provider == "gemini" else self.openai_chat_model

    @property
    def search_model(self) -> str:
        return (
            self.gemini_search_model if self.ai_provider == "gemini" else self.openai_search_model
        )

    @property
    def embedding_model(self) -> str:
        return (
            self.gemini_embedding_model
            if self.ai_provider == "gemini"
            else self.openai_embedding_model
        )

    def assert_provider_policy(self):
        if self.free_only:
            if self.ai_provider != "gemini":
                raise ValueError(
                    "FREE_ONLY is enabled. Use a Gemini free-tier project with billing disabled."
                )
            if (
                self.chat_model not in {"gemini-3.5-flash-lite", "gemini-3.7-flash"}
                or self.web_backend == "openai"
                or (self.web_backend == "gemini" and self.search_model != "gemini-2.5-flash-lite")
                or self.embedding_model != "gemini-embedding-2"
            ):
                raise ValueError(
                    "FREE_ONLY permits only the documented free-tier model configuration. No paid fallback is enabled."
                )

    @property
    def blobs(self) -> Path:
        path = Path(self.data_dir)
        return (path if path.is_absolute() else ROOT / path) / "blobs"

    @property
    def pg_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


settings = Settings()
