"""Runtime settings, read once from environment variables and the project's .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"   # git-ignored; see .env.example
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "ledgersync.db"   # git-ignored: data/


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _names(value: Optional[str], default: tuple[str, ...]) -> tuple[str, ...]:
    """A comma-separated list: unset gives the default, blank gives none."""
    return default if value is None else tuple(part.strip() for part in value.split(",") if part.strip())


def read_env_file(path: Optional[Path]) -> dict[str, str]:
    """KEY=VALUE lines from a .env file. Comments, blank and malformed lines are skipped, and an
    `export ` prefix and surrounding quotes are removed; a missing file gives nothing."""
    if path is None or not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8085
    reload: bool = False
    warmup: bool = True
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    max_upload_mb: int = 20
    max_pdf_pages: int = 30
    job_ttl_seconds: float = 3600.0
    max_parallel_jobs: int = 5            # documents read at once, from any input; 1 reads them one at a time
    log_level: str = "INFO"
    # The hosted vision model, through an OpenAI-compatible API: OpenRouter when its key is set,
    # otherwise Groq (see `provider`). The keys live in .env.
    openrouter_api_key: str = field(default="", repr=False)   # never printed or logged
    openrouter_model: str = "qwen/qwen3.8-27b"                # the model Groq serves, under the same name
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_max_output_tokens: int = 32768
    openrouter_providers: tuple[str, ...] = ("deepinfra/bf16",)
    openrouter_quantizations: tuple[str, ...] = ("bf16", "fp16", "fp32", "fp8")
    groq_api_key: str = field(default="", repr=False)   # never printed or logged
    groq_model: str = "qwen/qwen3.8-27b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout: float = 60.0
    groq_max_output_tokens: int = 8192
    groq_reasoning_effort: str = "high"
    groq_max_images: int = 3
    health_ttl: float = 300.0
    business_name: str = ""
    db_path: Path = DEFAULT_DB            # the local database of clients and their saved rows
    # MongoDB storage: if set, MongoStore is used instead of SQLite
    mongodb_uri: str = ""                 # e.g. "mongodb://localhost:27017"
    mongodb_db_name: str = "ledgersync"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def provider(self) -> str:
        """Who reads the documents: OpenRouter when OPENROUTER_API_KEY is set, otherwise Groq."""
        return "OpenRouter" if self.openrouter_api_key else "Groq"

    @property
    def api_key(self) -> str:
        return self.openrouter_api_key or self.groq_api_key

    @property
    def model(self) -> str:
        return self.openrouter_model if self.openrouter_api_key else self.groq_model

    @property
    def base_url(self) -> str:
        return self.openrouter_base_url if self.openrouter_api_key else self.groq_base_url

    @property
    def max_output_tokens(self) -> int:
        return self.openrouter_max_output_tokens if self.openrouter_api_key else self.groq_max_output_tokens

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None,
                 env_file: Optional[Path] = ENV_FILE) -> "Settings":
        """Settings from `env`, or else from the process environment laid over the .env file."""
        env = {**read_env_file(env_file), **os.environ} if env is None else env
        d = cls()
        origins = env.get("LEDGERSYNC_CORS_ORIGINS")
        return cls(
            host=env.get("LEDGERSYNC_HOST", d.host),
            port=int(env.get("LEDGERSYNC_PORT", d.port)),
            reload=_flag(env.get("LEDGERSYNC_RELOAD", "0")),
            warmup=_flag(env.get("LEDGERSYNC_WARMUP", "1")),
            cors_origins=(tuple(o.strip() for o in origins.split(",") if o.strip())
                          if origins else d.cors_origins),
            max_upload_mb=int(env.get("LEDGERSYNC_MAX_UPLOAD_MB", d.max_upload_mb)),
            max_pdf_pages=int(env.get("LEDGERSYNC_MAX_PDF_PAGES", d.max_pdf_pages)),
            max_parallel_jobs=max(1, int(env.get("LEDGERSYNC_MAX_PARALLEL_JOBS", d.max_parallel_jobs))),
            log_level=env.get("LEDGERSYNC_LOG_LEVEL", d.log_level).upper(),
            openrouter_api_key=env.get("OPENROUTER_API_KEY", "").strip(),
            openrouter_model=env.get("OPENROUTER_MODEL", d.openrouter_model).strip(),
            openrouter_base_url=env.get("OPENROUTER_BASE_URL", d.openrouter_base_url).strip().rstrip("/"),
            openrouter_max_output_tokens=int(env.get("OPENROUTER_MAX_OUTPUT_TOKENS", d.openrouter_max_output_tokens)),
            openrouter_providers=_names(env.get("OPENROUTER_PROVIDERS"), d.openrouter_providers),
            openrouter_quantizations=_names(env.get("OPENROUTER_QUANTIZATIONS"), d.openrouter_quantizations),
            groq_api_key=env.get("GROQ_API_KEY", "").strip(),
            groq_model=env.get("GROQ_MODEL", d.groq_model).strip(),
            groq_base_url=env.get("GROQ_BASE_URL", d.groq_base_url).strip().rstrip("/"),
            groq_timeout=float(env.get("GROQ_TIMEOUT", d.groq_timeout)),
            groq_max_output_tokens=int(env.get("GROQ_MAX_OUTPUT_TOKENS", d.groq_max_output_tokens)),
            groq_reasoning_effort=env.get("GROQ_REASONING_EFFORT", d.groq_reasoning_effort).strip(),
            groq_max_images=int(env.get("GROQ_MAX_IMAGES", d.groq_max_images)),
            business_name=env.get("LEDGERSYNC_BUSINESS_NAME", "").strip(),
            db_path=(Path(env["LEDGERSYNC_DB_PATH"].strip()).expanduser()
                     if env.get("LEDGERSYNC_DB_PATH", "").strip() else d.db_path),
            mongodb_uri=env.get("MONGODB_URI", "").strip(),
            mongodb_db_name=env.get("MONGODB_DB_NAME", "ledgersync").strip(),
        )