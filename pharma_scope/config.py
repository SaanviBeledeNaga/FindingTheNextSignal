"""Load project-local settings without echoing secrets or overriding the shell."""
import os
import importlib.util
from pathlib import Path


def load_env(path=None):
    path = Path(path or ".env")
    if not path.is_file():
        return
    allowed = {"PHARMA_PROVIDER", "PHARMA_MODEL", "PHARMA_SEARCH_PROVIDER", "GEMINI_API_KEY", "OPENAI_API_KEY",
               "BRAVE_API_KEY", "TAVILY_API_KEY", "LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in allowed:
            os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


def doctor():
    provider = os.getenv("PHARMA_PROVIDER", "gemini")
    search = os.getenv("PHARMA_SEARCH_PROVIDER", "brave")
    model_key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    search_key = "BRAVE_API_KEY" if search == "brave" else "TAVILY_API_KEY"
    account_free = search == "duckduckgo"
    search_installed = bool(importlib.util.find_spec("ddgs")) if account_free else True
    search_ready = search_installed if account_free else bool(os.getenv(search_key))
    valid = provider in {"openai", "gemini"} and search in {"brave", "tavily", "duckduckgo"}
    return {"model_provider": provider, "model": os.getenv("PHARMA_MODEL") or "not configured",
            "search_provider": search, "model_key_configured": bool(os.getenv(model_key)),
            "search_key_required": not account_free, "search_key_configured": bool(os.getenv(search_key)) if not account_free else None,
            "search_package_installed": search_installed, "tracing_enabled": os.getenv("LANGSMITH_TRACING", "").lower() == "true",
            "ready_for_live_research": bool(valid and os.getenv(model_key) and search_ready and os.getenv("PHARMA_MODEL")),
            "note": "Presence check only; credentials and model access require a live run."}
