from __future__ import annotations

import yaml
from streamlit.testing.v1 import AppTest


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_first_run_wizard_keeps_values_and_saves_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.scheduler import shutdown_scheduler

    reset_config()
    database.reset_engine()
    try:
        app = AppTest.from_file("app.py", default_timeout=10).run()
        assert not app.exception
        assert [item.label for item in app.selectbox] == ["模型服务"]

        app.text_input(key="_setup_field_api_key").set_value("test-ai-key")
        _button(app, "下一步：连接记忆仓库 →").click().run()
        assert not app.exception

        app.text_input(key="_setup_field_repo").set_value("owner/memory")
        app.text_input(key="_setup_field_github_token").set_value("test-gh-token")
        _button(app, "下一步：运行偏好 →").click().run()
        assert not app.exception

        _button(app, "下一步：检查配置 →").click().run()
        assert not app.exception

        _button(app, "保存配置并进入 AI Radar").click().run()
        assert not app.exception

        data = yaml.safe_load(
            (config_dir / "config.yaml").read_text(encoding="utf-8")
        )
        assert data["llm"]["api_key"] == "test-ai-key"
        assert data["profile"]["repo"] == "owner/memory"
        assert data["github"]["token"] == "test-gh-token"
    finally:
        shutdown_scheduler()
        reset_config()
        database.reset_engine()
