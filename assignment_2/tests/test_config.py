from __future__ import annotations

from app.config import Settings


def test_defaults_do_not_require_keys() -> None:
    settings = Settings(_env_file=None)
    assert settings.retrieval_k == 5
    assert settings.chroma_collection == "ultimate_rules"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.web_enabled is True


def test_tavily_url_puts_key_in_query_string() -> None:
    settings = Settings(_env_file=None, tavily_api_key="tvly-abc")
    assert settings.tavily_mcp_url == "https://mcp.tavily.com/mcp/?tavilyApiKey=tvly-abc"


def test_tavily_url_is_none_without_key() -> None:
    assert Settings(_env_file=None).tavily_mcp_url is None


def test_relative_paths_resolve_under_project_root() -> None:
    settings = Settings(_env_file=None)
    assert settings.chroma_path.is_absolute()
    assert settings.chroma_path.name == "chroma_index"
    assert settings.medals_db.name == "medals.sqlite"
