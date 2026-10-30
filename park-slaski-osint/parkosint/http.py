"""Klient HTTP z limitem zapytań per host, ponawianiem po 429/5xx i obsługą robots.txt.

robots.txt sprawdzamy dla zwykłych stron WWW (robots=True). Oficjalne API wołamy
zgodnie z ich regulaminami i limitami, bo robots.txt opisuje zasady dla crawlerów
(np. Wikimedia blokuje /w/ crawlerom, a jednocześnie zaprasza do korzystania z API).
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from . import __version__

log = logging.getLogger(__name__)

UA_TOKEN = "ParkSlaskiOSINT"
_SECRET_RE = re.compile(r"((?:api_)?key|access_token|token)=([^&\s]+)", re.I)


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1=***", str(text))


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, payload=None, blocked: bool = False):
        super().__init__(redact(message))
        self.status = status
        self.payload = payload
        # blocked = host w ogóle nieosiągalny (proxy, firewall), kolejne zapytania nie mają sensu
        self.blocked = blocked


class RobotsDisallowed(HttpError):
    pass


class Http:
    def __init__(
        self,
        contact: str = "",
        default_interval: float = 1.0,
        per_host: dict[str, float] | None = None,
        timeout: float = 30,
        max_retries: int = 3,
        sleep=time.sleep,
    ):
        # nagłówki HTTP muszą być w latin-1, więc User-Agent bez polskich znaków
        contact = contact or "no contact given"
        self.user_agent = f"{UA_TOKEN}/{__version__} (private search of public media; contact: {contact})"
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.user_agent
        self.default_interval = default_interval
        self.per_host = dict(per_host or {})
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | bool] = {}
        self._robots_reason: dict[str, str] = {}
        self.count = 0

    def _wait(self, host: str) -> None:
        interval = self.per_host.get(host, self.default_interval)
        last = self._last.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < interval:
                self._sleep(interval - delta)
        self._last[host] = time.monotonic()

    def request(self, url: str, params=None, headers=None, robots: bool = False) -> requests.Response:
        if robots and not self.allowed_by_robots(url):
            base = "{0.scheme}://{0.netloc}".format(urlparse(url))
            raise RobotsDisallowed(self._robots_reason.get(base, "robots.txt zabrania pobrania tej strony"))
        host = urlparse(url).netloc
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._wait(host)
            self.count += 1
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except (requests.exceptions.ProxyError, requests.exceptions.SSLError) as e:
                m = re.search(r"Tunnel connection failed: [^'\")]+|CERTIFICATE_VERIFY_FAILED", str(e))
                reason = m.group(0) if m else type(e).__name__
                raise HttpError(f"Połączenie z {host} zablokowane przez proxy/sieć ({reason})", blocked=True) from e
            except requests.RequestException as e:
                last_exc = e
                self._sleep(2 ** attempt * 2)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else 2 ** attempt * 2
                log.warning("%s: HTTP %s, ponawiam za %.0fs", host, r.status_code, wait)
                last_exc = HttpError(f"HTTP {r.status_code} z {host}", status=r.status_code)
                if attempt < self.max_retries:
                    self._sleep(min(wait, 120))
                continue
            return r
        raise HttpError(f"Nie udało się pobrać {url}: {last_exc}")

    def get_json(self, url: str, params=None, headers=None) -> dict:
        r = self.request(url, params=params, headers=headers)
        try:
            data = r.json()
        except ValueError:
            raise HttpError(f"HTTP {r.status_code} z {urlparse(url).netloc}, odpowiedź nie jest JSON-em: {r.text[:200]}",
                            status=r.status_code)
        if r.status_code >= 400:
            raise HttpError(f"HTTP {r.status_code} z {urlparse(url).netloc}: {str(data)[:300]}",
                            status=r.status_code, payload=data)
        return data

    def get_text(self, url: str, robots: bool = True) -> str:
        r = self.request(url, robots=robots)
        if r.status_code >= 400:
            raise HttpError(f"HTTP {r.status_code} dla {url}", status=r.status_code)
        r.encoding = r.encoding or r.apparent_encoding
        return r.text

    def download(self, url: str, path: Path) -> bool:
        try:
            r = self.request(url)
        except HttpError as e:
            log.debug("miniatura %s: %s", url, e)
            return False
        if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return True

    def allowed_by_robots(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp, reason = self._load_robots(base)
            self._robots[base] = rp
            if reason:
                self._robots_reason[base] = reason
        if isinstance(rp, bool):
            return rp
        return rp.can_fetch(UA_TOKEN, url)

    def _load_robots(self, base: str) -> tuple[RobotFileParser | bool, str]:
        """Zwraca (parser albo True/False, powód odmowy do pokazania w raporcie)."""
        try:
            r = self.request(base + "/robots.txt")
        except HttpError as e:
            log.warning("robots.txt %s niedostępny (%s), nie pobieram stron z tego hosta", base, e)
            return False, f"nie udało się pobrać robots.txt, więc strony nie pobrano: {e}"
        # RFC 9309: 5xx = zakaz; brak pliku (404/410) = wolno. 401/403 traktujemy ostrożnie jako zakaz.
        if r.status_code in (401, 403) or r.status_code >= 500:
            return False, f"robots.txt odpowiada HTTP {r.status_code}, strony nie pobrano"
        if r.status_code >= 400:
            return True, ""
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        delay = rp.crawl_delay(UA_TOKEN)
        if delay:
            host = urlparse(base).netloc
            self.per_host[host] = max(self.per_host.get(host, self.default_interval), float(delay))
        return rp, "robots.txt zabrania pobrania tej strony"
