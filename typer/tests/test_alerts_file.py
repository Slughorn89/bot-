import json

from typer.pipeline import daily


def test_alert_survives_corrupted_file(tmp_path, monkeypatch):
    f = tmp_path / "alerts.json"
    f.write_text('[\n {"ts": "x", "msg": "a"}\n] }\n]', encoding="utf-8")  # jak po rownoczesnym zapisie
    monkeypatch.setattr(daily, "ALERTS", f)
    monkeypatch.setattr(daily, "LIVE_DIR", tmp_path)
    assert daily.read_alerts(f) == []
    daily.alert("test")
    items = json.loads(f.read_text(encoding="utf-8"))
    assert [a["msg"] for a in items] == ["test"]
    assert not list(tmp_path.glob("*.tmp"))
