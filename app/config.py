from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional local .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    tavily_api_key: SecretStr | None = None
    mcp_files_root: Path = Path("workspace")
    agent_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)
    mcp_discovery_timeout_seconds: float = Field(default=30.0, ge=2.0, le=120.0)
    port: int = Field(default=8080, ge=1, le=65535)

    @property
    def files_root(self) -> Path:
        root = self.mcp_files_root
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        return root.resolve()

    @property
    def node_modules(self) -> Path:
        return PROJECT_ROOT / "node_modules"


def child_process_environment(**extra: str | None) -> dict[str, str]:
    """Build a minimal explicit environment for MCP stdio subprocesses."""

    keys = ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR")
    environment = {key: os.environ[key] for key in keys if key in os.environ}
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    environment["PYTHON_EXECUTABLE"] = sys.executable
    environment.update({key: value for key, value in extra.items() if value})
    return environment
