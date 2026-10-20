import json

import settings


def test_project_settings_override_user_settings(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".deimos").mkdir(parents=True)
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"permission_mode": "auto-edit", "verify": {"max_attempts": 5}}))
    (project / ".deimos" / "settings.json").write_text(json.dumps({"verify": {"commands": ["pytest -q"]}}))
    monkeypatch.setattr(settings, "LOCAL_DIR", home)
    settings.reload_settings()

    s = settings.load_settings(str(project))

    assert s["permission_mode"] == "auto-edit"
    assert s["verify"] == {"enabled": True, "commands": ["pytest -q"], "max_attempts": 5}
    assert s["hooks"]["pre_tool"] == []  # defaults survive partial overrides
    settings.reload_settings()


def test_invalid_settings_file_is_ignored(tmp_path, monkeypatch, capsys):
    (tmp_path / ".deimos").mkdir()
    (tmp_path / ".deimos" / "settings.json").write_text("{not json")
    monkeypatch.setattr(settings, "LOCAL_DIR", tmp_path / "nohome")
    settings.reload_settings()

    s = settings.load_settings(str(tmp_path))

    assert s["permission_mode"] == "ask"
    assert "invalid settings file" in capsys.readouterr().err
    settings.reload_settings()
