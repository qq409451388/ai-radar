"""External YAML configuration and precedence."""
from __future__ import annotations

from pathlib import Path

import yaml

import ai_radar.config as config_module
from ai_radar.config import (
    AppConfig,
    save_user_config,
    user_config_dir,
    user_config_path,
)


def test_user_config_yaml_loads_secrets(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("AI_RADAR_CONFIG_PATH", str(path))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("PROFILE_GITHUB_TOKEN", raising=False)
    save_user_config(
        {
            "version": 1,
            "llm": {
                "base_url": "https://llm.example/v1",
                "api_key": "secret-ai",
                "model": "model-x",
                "timeout_seconds": 90,
            },
            "github": {"token": "secret-gh"},
            "profile": {
                "repo": "owner/private-memory",
                "ref": "main",
                "path_prefix": "memory",
                "token": "",
            },
            "app": {
                "db_path": "data/test.db",
                "timezone": "Asia/Shanghai",
                "scheduler_enabled": False,
                "http_timeout": 12,
                "analyze_batch_size": 18,
                "score_window_days": 60,
                "max_assessment_facts": 16,
            },
        },
        path,
    )

    cfg = AppConfig.load()
    assert cfg.config_exists is True
    assert cfg.config_path == path
    assert cfg.llm.api_key == "secret-ai"
    assert cfg.github.token == "secret-gh"
    assert cfg.profile.token == "secret-gh"
    assert cfg.profile.repo == "owner/private-memory"
    assert cfg.analyze_batch_size == 18
    assert cfg.is_ready is True


def test_environment_overrides_user_yaml(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "base_url": "https://file.example/v1",
                    "api_key": "from-file",
                    "model": "file-model",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_RADAR_CONFIG_PATH", str(path))
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    cfg = AppConfig.load()
    assert cfg.llm.api_key == "from-env"
    assert cfg.llm.model == "env-model"


def test_config_path_override(tmp_path, monkeypatch):
    expected = tmp_path / "custom.yaml"
    monkeypatch.setenv("AI_RADAR_CONFIG_PATH", str(expected))
    assert user_config_path() == expected


def test_windows_uses_appdata(monkeypatch):
    monkeypatch.delenv("AI_RADAR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AI_RADAR_CONFIG_PATH", raising=False)
    monkeypatch.setenv("APPDATA", "C:/Users/test/AppData/Roaming")
    monkeypatch.setattr(config_module.sys, "platform", "win32")
    assert str(user_config_dir()).replace("\\", "/").endswith(
        "AppData/Roaming/AI Radar"
    )
