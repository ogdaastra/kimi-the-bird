"""Autonomous research using Wikipedia's free public API.

Access rules followed:

* Only HTTPS GET requests to hosts in :data:`kimi.safety.TRUSTED_HOSTS`.
* Wikimedia's API etiquette: a descriptive User-Agent, one request at a
  time, at most one request per second, small result sizes. (Wikipedia's
  robots.txt governs web crawlers; API clients follow the API etiquette.)
* No logins, paywalls, CAPTCHAs or access controls are touched, and
  nothing downloaded is ever executed: only JSON text is parsed.
* Research is limited per day (Settings) and Kimi decides when a subject
  is worth investigating.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from .. import __version__
from ..safety import SafetyViolation, check_url, clean_text

MAX_RESPONSE_BYTES = 300_000


class ResearchUnavailable(Exception):
    pass


class RateLimited(ResearchUnavailable):
    pass


@dataclass
class Findings:
    topic: str
    title: str
    extract: str
    url: str
    related: list[str] = field(default_factory=list)


class WikipediaResearcher:
    API = "https://en.wikipedia.org/w/api.php"
    SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"

    def __init__(self, settings, session=None, min_interval_s: float = 1.0, timeout: float = 10.0) -> None:
        self.settings = settings
        self._session = session
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self._lock = threading.Lock()
        self._last = 0.0
        self._cooldown_until = 0.0

    def cooldown_remaining(self) -> float:
        """Seconds until research is allowed again after the encyclopedia asked us to slow down."""
        return max(0.0, self._cooldown_until - time.monotonic())

    @property
    def session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def user_agent(self) -> str:
        contact = clean_text(self.settings.get().research_contact, 80)
        base = f"KimiAutonomousBird/{__version__} (personal desktop companion; low-volume educational use)"
        return f"{base} {contact}".strip() if contact else base

    def _get_json(self, url: str, params: dict | None = None) -> dict:
        check_url(url)
        if self.cooldown_remaining() > 0:
            raise RateLimited("The encyclopedia asked us to slow down; waiting before trying again")
        with self._lock:
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(
                    url, params=params, timeout=self.timeout, stream=True,
                    headers={"User-Agent": self.user_agent(), "Accept": "application/json"},
                )
            except Exception as exc:  # noqa: BLE001 - network failures become "unavailable"
                raise ResearchUnavailable(f"Couldn't reach the encyclopedia ({type(exc).__name__})") from None
            finally:
                self._last = time.monotonic()
            try:
                final_url = getattr(resp, "url", url) or url
                check_url(str(final_url))   # redirects must stay on trusted hosts
                if resp.status_code == 404:
                    raise ResearchUnavailable("No such page")
                if resp.status_code == 429:
                    try:
                        wait = float(resp.headers.get("Retry-After") or 0)
                    except (TypeError, ValueError):
                        wait = 0.0
                    self._cooldown_until = time.monotonic() + max(wait, 30 * 60)
                    raise RateLimited("The encyclopedia asked us to slow down")
                if resp.status_code != 200:
                    raise ResearchUnavailable(f"Encyclopedia returned status {resp.status_code}")
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "json" not in ctype:
                    raise ResearchUnavailable("Unexpected content type")
                chunks, total = [], 0
                for chunk in resp.iter_content(chunk_size=16384):
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise ResearchUnavailable("Response too large")
                    chunks.append(chunk)
                return json.loads(b"".join(chunks).decode("utf-8", errors="replace"))
            except SafetyViolation as exc:
                raise ResearchUnavailable(str(exc)) from None
            except ValueError:
                raise ResearchUnavailable("Malformed response") from None
            finally:
                close = getattr(resp, "close", None)
                if close:
                    close()

    def search(self, topic: str, limit: int = 3) -> list[str]:
        data = self._get_json(self.API, {
            "action": "query", "list": "search", "srsearch": topic, "srlimit": str(limit),
            "srprop": "", "format": "json", "formatversion": "2",
        })
        results = (data.get("query") or {}).get("search") or []
        return [clean_text(r.get("title", ""), 120) for r in results if r.get("title")]

    def summary(self, title: str) -> dict:
        return self._get_json(self.SUMMARY.format(quote(title.replace(" ", "_"), safe="")))

    def _findings(self, topic: str, title: str, s: dict, related: list[str]) -> Findings | None:
        if s.get("type") == "disambiguation":
            return None
        extract = clean_text(s.get("extract", ""), 1500)
        if len(extract) < 40:
            return None
        page = ((s.get("content_urls") or {}).get("desktop") or {}).get("page") or \
            f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        return Findings(topic=topic, title=clean_text(s.get("title", title), 120), extract=extract,
                        url=clean_text(page, 300), related=related)

    def investigate(self, topic: str) -> Findings:
        # 1. Most subjects have a page of the same name: one request (redirects are followed).
        direct = topic[:1].upper() + topic[1:]
        try:
            found = self._findings(topic, direct, self.summary(direct), [])
            if found:
                return found
        except RateLimited:
            raise
        except ResearchUnavailable:
            pass
        # 2. Otherwise search, then read the best result.
        titles = self.search(topic)
        if not titles:
            raise ResearchUnavailable(f"Nothing found about {topic}")
        for title in titles:
            try:
                s = self.summary(title)
            except RateLimited:
                raise
            except ResearchUnavailable:
                continue
            found = self._findings(topic, title, s, [t for t in titles if t != title])
            if found:
                return found
        raise ResearchUnavailable(f"Nothing readable found about {topic}")
