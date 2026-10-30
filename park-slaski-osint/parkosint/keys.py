"""Kreator kluczy API: python -m parkosint keys

* YouTube: w pełni automatycznie przez Google Cloud CLI (gcloud). Jedyny ręczny krok to
  zalogowanie się na konto Google w przeglądarce, które gcloud sam otworzy. Potem program
  zakłada projekt, włącza YouTube Data API, tworzy klucz ograniczony do tego API i zapisuje go w .env.
* Flickr, Mapillary, Windy: te serwisy nie mają API do zakładania kluczy. Program otwiera właściwą
  stronę, Ty klikasz "utwórz" i wklejasz klucz, a program go sprawdza i zapisuje.
  Pełna automatyzacja wymagałaby podania programowi Twojego hasła i przeklikania za Ciebie
  logowania oraz akceptacji regulaminu, czyli omijania logowania. Tego celowo nie robimy.
"""
from __future__ import annotations

import getpass
import os
import re
import secrets
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT
from .http import Http, HttpError

ENV_PATH = ROOT / ".env"
KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{35}")


class KeysError(Exception):
    pass


@dataclass
class Service:
    name: str
    env: str
    url: str
    steps: str


MANUAL = {
    "mapillary": Service("Mapillary", "MAPILLARY_ACCESS_TOKEN", "https://www.mapillary.com/dashboard/developers",
                         "Kliknij 'Register application', wpisz dowolną nazwę, callback URL https://localhost, "
                         "zaznacz 'Read', zapisz i skopiuj 'Client Token' (zaczyna się od MLY|)."),
    "flickr": Service("Flickr", "FLICKR_API_KEY", "https://www.flickr.com/services/apps/create/apply/",
                      "Wybierz 'Apply for a Non-Commercial Key', wpisz nazwę i opis, skopiuj 'Key' (nie 'Secret'). "
                      "Jeśli Flickr zażąda konta Pro, pomiń go (Enter)."),
    "windy": Service("Windy Webcams (opcjonalnie)", "WINDY_WEBCAMS_API_KEY", "https://api.windy.com/keys",
                     "Zaloguj się, utwórz klucz dla 'Webcams API' i skopiuj go."),
    "youtube": Service("YouTube (ręcznie)", "YOUTUBE_API_KEY",
                       "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
                       "Kliknij 'Włącz', potem w 'Dane logowania' utwórz 'Klucz interfejsu API' i skopiuj go."),
}


# ---------- .env ----------

def update_env(values: dict[str, str], path: Path = ENV_PATH) -> None:
    """Wpisuje klucze do .env, zachowując resztę pliku. Brakujące zmienne dopisuje na końcu."""
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif (ROOT / ".env.example").exists():
        lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    todo = dict(values)
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z0-9_]+)=", line)
        if m and m.group(1) in todo:
            lines[i] = f"{m.group(1)}={todo.pop(m.group(1))}"
    lines += [f"{k}={v}" for k, v in todo.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---------- sprawdzanie kluczy ----------

def validate(service: str, key: str, http: Http) -> tuple[bool, str]:
    try:
        if service == "youtube":
            data = http.get_json("https://www.googleapis.com/youtube/v3/videos",
                                 params={"part": "id", "id": "jNQXAC9IVRw", "key": key})
            return bool(data.get("items") is not None), "działa"
        if service == "flickr":
            data = http.get_json("https://api.flickr.com/services/rest/", params={
                "method": "flickr.test.echo", "api_key": key, "format": "json", "nojsoncallback": 1})
            return data.get("stat") == "ok", data.get("message", "działa")
        if service == "mapillary":
            http.get_json("https://graph.mapillary.com/images",
                          params={"bbox": "18.985,50.288,18.986,50.289", "limit": 1, "fields": "id"},
                          headers={"Authorization": f"OAuth {key}"})
            return True, "działa"
        if service == "windy":
            http.get_json("https://api.windy.com/webcams/api/v3/webcams", params={"limit": 1},
                          headers={"x-windy-api-key": key})
            return True, "działa"
    except HttpError as e:
        if e.blocked:
            return True, f"nie da się sprawdzić z tej sieci ({e}), zapisuję bez sprawdzenia"
        return False, str(e)
    return False, "nieznana usługa"


# ---------- YouTube przez gcloud ----------

def _gcloud(args: list[str], run=subprocess.run, check: bool = True) -> str:
    exe = shutil.which("gcloud")
    if not exe:
        raise KeysError("Brak Google Cloud CLI (gcloud). Instalacja: https://cloud.google.com/sdk/docs/install")
    p = run([exe, *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        msg = (p.stderr or p.stdout).strip()
        if "Terms of Service" in msg or "terms of service" in msg:
            msg += ("\nWejdź raz na https://console.cloud.google.com, zaakceptuj regulamin i uruchom kreator ponownie.")
        raise KeysError(f"gcloud {' '.join(args[:3])}: {msg[-600:]}")
    return (p.stdout or "") + (p.stderr or "")


def youtube_via_gcloud(run=subprocess.run, project: str | None = None, say=print) -> str:
    if not shutil.which("gcloud"):
        raise KeysError("Brak Google Cloud CLI (gcloud). Instalacja: https://cloud.google.com/sdk/docs/install")
    active = _gcloud(["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], run, check=False).strip()
    if not active or "@" not in active:
        say("Otwieram logowanie Google w przeglądarce (to jedyny krok, który musisz zrobić sam)...")
        exe = shutil.which("gcloud")
        if run([exe, "auth", "login"]).returncode != 0:
            raise KeysError("Logowanie gcloud nie powiodło się")
    project = project or os.getenv("GCP_PROJECT") or f"park-slaski-osint-{secrets.token_hex(3)}"
    exists = _gcloud(["projects", "describe", project, "--format=value(projectId)"], run, check=False).strip()
    if project not in exists:
        say(f"Zakładam projekt {project}...")
        _gcloud(["projects", "create", project, "--name=park-slaski-osint"], run)
    say("Włączam YouTube Data API v3...")
    _gcloud(["services", "enable", "youtube.googleapis.com", "apikeys.googleapis.com", "--project", project], run)
    say("Tworzę klucz ograniczony do YouTube Data API...")
    out = _gcloud(["services", "api-keys", "create", "--project", project, "--display-name=park-slaski-osint",
                   "--api-target=service=youtube.googleapis.com", "--format=json"], run)
    m = KEY_RE.search(out)
    if m:
        return m.group(0)
    names = _gcloud(["services", "api-keys", "list", "--project", project,
                     "--filter=displayName=park-slaski-osint", "--format=value(name)"], run).split()
    for name in names:
        m = KEY_RE.search(_gcloud(["services", "api-keys", "get-key-string", name, "--format=value(keyString)"], run))
        if m:
            return m.group(0)
    raise KeysError("Klucz utworzony, ale nie udało się odczytać jego wartości. Sprawdź w konsoli: "
                    f"https://console.cloud.google.com/apis/credentials?project={project}")


# ---------- kreator ----------

def manual_key(svc: Service, open_browser: bool, ask=getpass.getpass, say=print) -> str:
    say(f"\n== {svc.name} ==\n{svc.steps}\nStrona: {svc.url}")
    if open_browser:
        try:
            webbrowser.open(svc.url)
        except Exception:
            pass
    return ask(f"Wklej klucz {svc.env} (nie będzie widoczny, Enter = pomiń): ").strip()


def run_wizard(services: list[str], http: Http, open_browser: bool = True, use_gcloud: bool = True,
               ask_secret=getpass.getpass, ask=input, say=print, run=subprocess.run, env_path: Path = ENV_PATH) -> dict:
    saved: dict[str, str] = {}
    contact = ask("Twój e-mail do nagłówka User-Agent (wymóg Wikimedia, Enter = pomiń): ").strip()
    if contact:
        saved["CONTACT_EMAIL"] = contact
    for service in services:
        key = ""
        if service == "youtube" and use_gcloud and shutil.which("gcloud"):
            say("\n== YouTube (automatycznie przez gcloud) ==")
            try:
                key = youtube_via_gcloud(run=run, say=say)
            except KeysError as e:
                say(f"Automat nie zadziałał: {e}\nPrzechodzę na tryb ręczny.")
        if not key:
            key = manual_key(MANUAL[service], open_browser, ask_secret, say)
        if not key:
            say(f"{service}: pominięte")
            continue
        ok, msg = validate(service, key, http)
        say(f"{service}: {'OK' if ok else 'BŁĄD'}, {msg}")
        if ok:
            saved[MANUAL[service].env] = key
    if saved:
        update_env(saved, env_path)
        say(f"\nZapisano w {env_path}: {', '.join(saved)}")
    return saved
