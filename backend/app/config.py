from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    # Comma-separated MCP server URLs, e.g. "http://localhost:8101/mcp,http://localhost:8102/mcp"
    mcp_servers: str = ""

    @property
    def mcp_server_urls(self) -> List[str]:
        return [url.strip() for url in self.mcp_servers.split(",") if url.strip()]


settings = Settings()
