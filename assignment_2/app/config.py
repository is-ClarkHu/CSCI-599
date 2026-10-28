from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAVILY_MCP_URL = "https://mcp.tavily.com/mcp/"


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional local .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-6-sol"
    openai_embedding_model: str = "text-embedding-3-small"
    google_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    kimi_api_key: SecretStr | None = None
    kimi_model: str = "kimi-k3"
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    tavily_api_key: SecretStr | None = None

    chroma_persist_dir: Path = Path("chroma_index")
    chroma_collection: str = "ultimate_rules"
    medals_db_path: Path = Path("data/medals.sqlite")
    retrieval_k: int = Field(default=5, ge=1, le=20)
    web_enabled: bool = True

    llm_timeout_seconds: float = Field(default=45.0, ge=5.0, le=120.0)
    mcp_timeout_seconds: float = Field(default=20.0, ge=2.0, le=60.0)
    request_timeout_seconds: float = Field(default=240.0, ge=10.0, le=290.0)
    port: int = Field(default=8080, ge=1, le=65535)

    @property
    def chroma_path(self) -> Path:
        return _resolve(self.chroma_persist_dir)

    @property
    def medals_db(self) -> Path:
        return _resolve(self.medals_db_path)

    @property
    def tavily_mcp_url(self) -> str | None:
        """Remote MCP endpoint with the key as a query parameter, as the assignment specifies (PDF §3.4).

        The URL therefore contains a secret: main.py silences httpx request logging so it never reaches logs,
        and TavilyTools never puts the URL into error messages.
        """

        if self.tavily_api_key is None:
            return None
        return f"{TAVILY_MCP_URL}?tavilyApiKey={self.tavily_api_key.get_secret_value()}"


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
