"""Pure helpers used by the first-run configuration wizard."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class ProviderPreset:
    label: str
    base_url: str
    model: str
    guide_url: str
    description: str


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "阿里云百炼": ProviderPreset(
        label="阿里云百炼",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        guide_url="https://help.aliyun.com/zh/model-studio/get-api-key",
        description="适合国内网络环境；这里预填按量付费的北京地域地址。",
    ),
    "DeepSeek": ProviderPreset(
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        guide_url="https://api-docs.deepseek.com/zh-cn/",
        description="使用 DeepSeek 官方 OpenAI-compatible API。",
    ),
}
CUSTOM_PROVIDER = "其他 OpenAI-compatible 服务"


def infer_provider(base_url: str) -> str:
    normalized = base_url.strip().lower()
    if "dashscope.aliyuncs.com" in normalized:
        return "阿里云百炼"
    if "api.deepseek.com" in normalized:
        return "DeepSeek"
    return CUSTOM_PROVIDER


def validate_llm(
    base_url: str,
    model: str,
    *,
    has_api_key: bool,
) -> list[str]:
    errors: list[str] = []
    url = base_url.strip().rstrip("/")
    parsed = urlparse(url)
    if not url:
        errors.append("请填写 API Base URL。")
    elif parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append("API Base URL 需要是完整的 http(s) 地址。")
    elif parsed.path.rstrip("/").endswith("/chat/completions"):
        errors.append("Base URL 不要包含 `/chat/completions`，应用会自动补上。")
    if not model.strip():
        errors.append("请填写模型 ID。")
    if not has_api_key:
        errors.append("请填写 AI API Key。")
    return errors


def validate_profile(
    repository: str,
    ref: str,
    *,
    has_token: bool,
) -> list[str]:
    errors: list[str] = []
    repo = repository.strip()
    parts = repo.split("/")
    if (
        len(parts) != 2
        or not all(parts)
        or any(part in {".", ".."} for part in parts)
        or any(char.isspace() for char in repo)
    ):
        errors.append("仓库名请按 `owner/repo` 格式填写。")
    if not ref.strip():
        errors.append("请填写仓库分支，例如 `main`。")
    if not has_token:
        errors.append("请填写可读取该仓库的 GitHub Token。")
    return errors


def validate_timezone(timezone_name: str) -> list[str]:
    value = timezone_name.strip()
    if not value:
        return ["请填写时区，例如 `Asia/Shanghai`。"]
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return ["时区无效，请使用 `Asia/Shanghai` 这类 IANA 时区名称。"]
    return []


def build_user_config(cfg: Any, values: Mapping[str, Any]) -> dict[str, Any]:
    """Build the persisted YAML structure while preserving blank secrets."""
    api_key = str(values.get("api_key", "")).strip() or cfg.llm.api_key
    github_token = (
        str(values.get("github_token", "")).strip()
        or cfg.profile.token
        or cfg.github.token
    )
    data = cfg.as_user_dict(
        llm_api_key=api_key,
        github_token=github_token,
    )
    data["llm"].update(
        {
            "base_url": str(values["base_url"]).strip().rstrip("/"),
            "model": str(values["model"]).strip(),
        }
    )
    data["profile"].update(
        {
            "repo": str(values["repo"]).strip(),
            "ref": str(values["ref"]).strip() or "main",
            "path_prefix": str(values.get("path_prefix", "")).strip().strip("/"),
        }
    )
    data["app"].update(
        {
            "timezone": str(values["timezone"]).strip(),
            "scheduler_enabled": bool(values["scheduler_enabled"]),
            "http_timeout": int(values["http_timeout"]),
            "analyze_batch_size": int(values["analyze_batch_size"]),
            "ai_concurrency": int(
                values.get("ai_concurrency", getattr(cfg, "ai_concurrency", 4))
            ),
            "score_window_days": int(values["score_window_days"]),
            "max_assessment_facts": int(values["max_assessment_facts"]),
        }
    )
    return data
