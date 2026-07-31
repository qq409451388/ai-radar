"""Cross-platform user configuration.

Normal desktop use reads ``config.yaml`` from the operating system's user
configuration directory. Environment variables remain the highest-priority
override for CI and containers. A project-root ``.env`` is read only as a
legacy, in-memory migration source and is never loaded into ``os.environ``.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_TEMPLATE_PATH = PROJECT_ROOT / "config" / "app.example.yaml"
LEGACY_ENV_PATH = PROJECT_ROOT / ".env"


def user_config_dir() -> Path:
    """Return the conventional per-user configuration directory."""
    override = os.getenv("AI_RADAR_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.getenv("APPDATA")
        if base:
            return Path(base) / "AI Radar"
        return Path.home() / "AppData" / "Roaming" / "AI Radar"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AI Radar"
    xdg = os.getenv("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg).expanduser() if xdg else Path.home() / ".config") / "ai-radar"


def user_config_path() -> Path:
    override = os.getenv("AI_RADAR_CONFIG_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return user_config_dir() / "config.yaml"


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class GithubConfig:
    token: str
    http_timeout: int


@dataclass(frozen=True)
class ProfileConfig:
    repo: str
    ref: str
    path_prefix: str
    token: str


class AppConfig:
    def __init__(
        self,
        db_path: str,
        timezone: str,
        scheduler_enabled: bool,
        http_timeout: int,
        llm: LlmConfig,
        github: GithubConfig,
        profile: ProfileConfig,
        analyze_batch_size: int = 30,
        score_window_days: int = 90,
        max_assessment_facts: int = 24,
        project_root: Path = PROJECT_ROOT,
        config_path: Path | None = None,
        config_exists: bool = False,
        legacy_env_detected: bool = False,
    ) -> None:
        self.db_path = db_path
        self.timezone = timezone
        self.scheduler_enabled = scheduler_enabled
        self.http_timeout = http_timeout
        self.llm = llm
        self.github = github
        self.profile = profile
        self.analyze_batch_size = analyze_batch_size
        self.score_window_days = score_window_days
        self.max_assessment_facts = max_assessment_facts
        self.project_root = project_root
        self.config_path = config_path or user_config_path()
        self.config_exists = config_exists
        self.legacy_env_detected = legacy_env_detected

    @classmethod
    def load(cls) -> "AppConfig":
        path = user_config_path()
        file_data = _read_yaml(path)
        legacy = _legacy_env()

        def value(
            yaml_path: str,
            env_name: str,
            default: Any,
            *,
            legacy_name: str | None = None,
        ) -> Any:
            if env_name in os.environ:
                return os.environ[env_name]
            from_file = _nested_get(file_data, yaml_path)
            if from_file is not None:
                return from_file
            key = legacy_name or env_name
            if legacy.get(key) not in (None, ""):
                return legacy[key]
            return default

        http_timeout = _as_int(
            value("app.http_timeout", "AI_RADAR_HTTP_TIMEOUT", 20)
        )
        github_token = str(
            value("github.token", "GITHUB_TOKEN", "")
        ).strip()
        profile_token = str(
            value("profile.token", "PROFILE_GITHUB_TOKEN", "")
        ).strip() or github_token
        llm = LlmConfig(
            base_url=str(
                value("llm.base_url", "LLM_BASE_URL", "")
            ).strip().rstrip("/"),
            api_key=str(value("llm.api_key", "LLM_API_KEY", "")).strip(),
            model=str(value("llm.model", "LLM_MODEL", "qwen-plus")).strip(),
            timeout_seconds=_as_int(
                value(
                    "llm.timeout_seconds",
                    "LLM_TIMEOUT_SECONDS",
                    120,
                )
            ),
        )
        github = GithubConfig(token=github_token, http_timeout=http_timeout)
        profile = ProfileConfig(
            repo=str(
                value("profile.repo", "PROFILE_GITHUB_REPO", "")
            ).strip(),
            ref=str(
                value("profile.ref", "PROFILE_GITHUB_REF", "main")
            ).strip(),
            path_prefix=str(
                value(
                    "profile.path_prefix",
                    "PROFILE_GITHUB_PATH_PREFIX",
                    "",
                )
            ).strip(),
            token=profile_token,
        )
        return cls(
            db_path=str(
                value("app.db_path", "AI_RADAR_DB_PATH", "data/ai_radar.db")
            ).strip(),
            timezone=str(
                value("app.timezone", "AI_RADAR_TIMEZONE", "Asia/Shanghai")
            ).strip(),
            scheduler_enabled=_as_bool(
                value(
                    "app.scheduler_enabled",
                    "AI_RADAR_SCHEDULER_ENABLED",
                    True,
                )
            ),
            http_timeout=http_timeout,
            llm=llm,
            github=github,
            profile=profile,
            analyze_batch_size=_as_int(
                value(
                    "app.analyze_batch_size",
                    "AI_RADAR_ANALYZE_BATCH_SIZE",
                    30,
                )
            ),
            score_window_days=_as_int(
                value(
                    "app.score_window_days",
                    "AI_RADAR_SCORE_WINDOW_DAYS",
                    90,
                )
            ),
            max_assessment_facts=_as_int(
                value(
                    "app.max_assessment_facts",
                    "AI_RADAR_MAX_ASSESSMENT_FACTS",
                    24,
                )
            ),
            config_path=path,
            config_exists=path.exists(),
            legacy_env_detected=bool(legacy) and not path.exists(),
        )

    @property
    def is_ready(self) -> bool:
        return bool(
            self.llm.base_url
            and self.llm.api_key
            and self.profile.repo
            and self.profile.token
        )

    @property
    def db_url(self) -> str:
        p = Path(self.db_path).expanduser()
        if not p.is_absolute():
            p = self.project_root / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{p}"

    def as_user_dict(
        self,
        *,
        llm_api_key: str | None = None,
        github_token: str | None = None,
    ) -> dict[str, Any]:
        shared_github_token = (
            self.github.token if github_token is None else github_token
        )
        return {
            "version": 1,
            "llm": {
                "base_url": self.llm.base_url,
                "api_key": self.llm.api_key
                if llm_api_key is None
                else llm_api_key,
                "model": self.llm.model,
                "timeout_seconds": self.llm.timeout_seconds,
            },
            "github": {"token": shared_github_token},
            "profile": {
                "repo": self.profile.repo,
                "ref": self.profile.ref,
                "path_prefix": self.profile.path_prefix,
                # Empty means reuse github.token.
                "token": "",
            },
            "app": {
                "db_path": self.db_path,
                "timezone": self.timezone,
                "scheduler_enabled": self.scheduler_enabled,
                "http_timeout": self.http_timeout,
                "analyze_batch_size": self.analyze_batch_size,
                "score_window_days": self.score_window_days,
                "max_assessment_facts": self.max_assessment_facts,
            },
        }


def save_user_config(data: dict[str, Any], path: Path | None = None) -> Path:
    target = path or user_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(target)
    return target


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _legacy_env() -> dict[str, Any]:
    if not LEGACY_ENV_PATH.exists():
        return {}
    try:
        return {
            key: value
            for key, value in dotenv_values(LEGACY_ENV_PATH).items()
            if value not in (None, "")
        }
    except OSError:
        return {}


def _nested_get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: Any) -> int:
    return int(value)


_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig.load()
    return _config


def reset_config() -> None:
    global _config
    _config = None


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return "<empty>"
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)
