from __future__ import annotations

from ai_radar.config import AppConfig, GithubConfig, LlmConfig, ProfileConfig
from ai_radar.setup_wizard import (
    CUSTOM_PROVIDER,
    build_user_config,
    infer_provider,
    validate_llm,
    validate_profile,
    validate_timezone,
)


def _config() -> AppConfig:
    return AppConfig(
        db_path="data/test.db",
        timezone="Asia/Shanghai",
        scheduler_enabled=True,
        http_timeout=20,
        llm=LlmConfig(
            base_url="https://old.example/v1",
            api_key="existing-ai-key",
            model="old-model",
            timeout_seconds=120,
        ),
        github=GithubConfig(token="existing-github-token", http_timeout=20),
        profile=ProfileConfig(
            repo="owner/old-memory",
            ref="main",
            path_prefix="",
            token="existing-github-token",
        ),
    )


def test_provider_is_inferred_from_base_url():
    assert (
        infer_provider("https://dashscope.aliyuncs.com/compatible-mode/v1")
        == "阿里云百炼"
    )
    assert infer_provider("https://api.deepseek.com") == "DeepSeek"
    assert infer_provider("https://llm.example/v1") == CUSTOM_PROVIDER


def test_llm_validation_explains_base_url_shape():
    assert validate_llm(
        "https://llm.example/v1",
        "model-x",
        has_api_key=True,
    ) == []
    errors = validate_llm(
        "https://llm.example/v1/chat/completions",
        "",
        has_api_key=False,
    )
    assert any("不要包含" in error for error in errors)
    assert any("模型 ID" in error for error in errors)
    assert any("API Key" in error for error in errors)


def test_profile_validation_requires_owner_repo_ref_and_token():
    assert validate_profile("owner/memory", "main", has_token=True) == []
    errors = validate_profile("not-a-repository", "", has_token=False)
    assert len(errors) == 3


def test_timezone_validation_uses_iana_names():
    assert validate_timezone("Asia/Shanghai") == []
    assert validate_timezone("Shanghai") != []


def test_build_user_config_preserves_existing_secrets_when_inputs_are_blank():
    data = build_user_config(
        _config(),
        {
            "base_url": "https://new.example/v1/",
            "model": "new-model",
            "api_key": "",
            "repo": "owner/new-memory",
            "ref": "develop",
            "path_prefix": "/notes/",
            "github_token": "",
            "timezone": "Asia/Shanghai",
            "scheduler_enabled": False,
            "http_timeout": 35,
            "analyze_batch_size": 12,
            "score_window_days": 45,
            "max_assessment_facts": 16,
        },
    )

    assert data["llm"]["base_url"] == "https://new.example/v1"
    assert data["llm"]["api_key"] == "existing-ai-key"
    assert data["github"]["token"] == "existing-github-token"
    assert data["profile"] == {
        "repo": "owner/new-memory",
        "ref": "develop",
        "path_prefix": "notes",
        "token": "",
    }
    assert data["app"]["scheduler_enabled"] is False
    assert data["app"]["http_timeout"] == 35
