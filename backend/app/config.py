from pathlib import Path
from typing import List, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Which model answers the questions.
    #   "ollama": a model served by Ollama (local, or an Ollama ":cloud" model)
    #   "openai": any OpenAI-compatible API, e.g. OpenRouter, OpenAI, Groq, LM Studio
    llm_provider: Literal["ollama", "openai"] = "ollama"
    llm_model: str = "qwen2.5:3b"
    # Thinking models (e.g. mimo-v2.6) reason silently before answering, which delays
    # the first visible word. False = no thinking (fast), True = think, unset = model default.
    llm_think: Optional[bool] = None

    # Used when LLM_PROVIDER=ollama
    ollama_url: str = "http://localhost:11434"

    # Used when LLM_PROVIDER=openai
    api_base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""  # secret: keep it only in backend/.env, never commit it

    backend_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    # Where uploaded PDFs are saved; the PDF Q&A MCP server reads them from here.
    upload_dir: str = str(Path(__file__).resolve().parents[2] / "data" / "uploads")
    # Comma-separated MCP server URLs, e.g. "http://localhost:8101/mcp,http://localhost:8102/mcp"
    mcp_servers: str = ""

    @property
    def mcp_server_urls(self) -> List[str]:
        return [url.strip() for url in self.mcp_servers.split(",") if url.strip()]


def get_settings() -> Settings:
    """Read the settings again (including backend/.env).

    Called on every question, so changing LLM_PROVIDER, LLM_MODEL, LLM_THINK, API_KEY or
    MCP_SERVERS in backend/.env takes effect on the next question, no restart needed.
    """
    return Settings()


# Values only needed once at startup (port, CORS origin).
settings = Settings()
