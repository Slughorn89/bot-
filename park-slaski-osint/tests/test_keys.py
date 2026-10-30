import subprocess

from conftest import FakeHttp

from parkosint import keys
from parkosint.http import HttpError

KEY = "AIza" + "A" * 35


def test_update_env_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# komentarz\nYOUTUBE_API_KEY=\nCONTACT_EMAIL=old@x\n# PARK_BBOX=1\n", encoding="utf-8")
    keys.update_env({"YOUTUBE_API_KEY": KEY, "CONTACT_EMAIL": "a@b", "NEW_ONE": "1"}, env)
    text = env.read_text(encoding="utf-8")
    assert f"YOUTUBE_API_KEY={KEY}" in text and "CONTACT_EMAIL=a@b" in text and "NEW_ONE=1" in text
    assert "# komentarz" in text and "# PARK_BBOX=1" in text and "old@x" not in text


def test_youtube_via_gcloud_sequence(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output=False, text=False):
        calls.append(cmd[1:])
        args = cmd[1:]
        out = ""
        if args[:2] == ["auth", "list"]:
            out = "ja@example.com"
        elif args[:2] == ["projects", "describe"]:
            return subprocess.CompletedProcess(cmd, 1, "", "not found")
        elif args[:3] == ["services", "api-keys", "create"]:
            out = '{"response": {"keyString": "%s"}}' % KEY
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(keys.shutil, "which", lambda name: "/usr/bin/gcloud")
    key = keys.youtube_via_gcloud(run=fake_run, project="park-test", say=lambda *a: None)
    assert key == KEY
    flat = [" ".join(c) for c in calls]
    assert any(c.startswith("projects create park-test") for c in flat)
    assert any("services enable youtube.googleapis.com" in c for c in flat)
    assert any("--api-target=service=youtube.googleapis.com" in c for c in flat)
    assert not any(c.startswith("auth login") for c in flat)  # już zalogowany


def test_gcloud_terms_of_service_hint(monkeypatch):
    def fake_run(cmd, capture_output=False, text=False):
        if cmd[1:3] == ["projects", "create"]:
            return subprocess.CompletedProcess(cmd, 1, "", "Callers must accept Terms of Service")
        if cmd[1:3] == ["projects", "describe"]:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        return subprocess.CompletedProcess(cmd, 0, "ja@example.com", "")

    monkeypatch.setattr(keys.shutil, "which", lambda name: "/usr/bin/gcloud")
    try:
        keys.youtube_via_gcloud(run=fake_run, project="p", say=lambda *a: None)
    except keys.KeysError as e:
        assert "zaakceptuj regulamin" in str(e)
    else:
        raise AssertionError("powinien być błąd")


def test_validate_and_wizard_manual(tmp_path, monkeypatch):
    def handler(url, p, h):
        if "flickr" in url:
            return {"stat": "ok"} if p["api_key"] == "goodflickr" else {"stat": "fail", "message": "Invalid API Key"}
        if "mapillary" in url:
            raise HttpError("zablokowane", blocked=True)
        return {"items": []}

    http = FakeHttp(handler)
    assert keys.validate("flickr", "goodflickr", http) == (True, "działa")
    assert keys.validate("flickr", "zly", http)[0] is False
    ok, msg = keys.validate("mapillary", "MLY|1|2", http)
    assert ok and "bez sprawdzenia" in msg

    monkeypatch.setattr(keys.shutil, "which", lambda name: None)  # brak gcloud = YouTube ręcznie
    secrets_in = iter(["yt-key", "MLY|1|2", "zly", ""])
    env = tmp_path / ".env"
    saved = keys.run_wizard(["youtube", "mapillary", "flickr", "windy"], http, open_browser=False,
                            ask_secret=lambda prompt: next(secrets_in), ask=lambda prompt: "ja@example.com",
                            say=lambda *a: None, env_path=env)
    assert saved == {"CONTACT_EMAIL": "ja@example.com", "YOUTUBE_API_KEY": "yt-key", "MAPILLARY_ACCESS_TOKEN": "MLY|1|2"}
    assert "FLICKR_API_KEY=zly" not in env.read_text(encoding="utf-8")
