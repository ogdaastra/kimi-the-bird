"""Autonomous research in the Library, using free, trusted public sources.

The Library has several *shelves*, each backed by a free public API that
needs no key. Kimi picks the shelf that fits its curiosity:

=====================  =================================  ============================
shelf                  in Bramblewick                     source
=====================  =================================  ============================
encyclopedia           Professor Quill's encyclopedia     Wikipedia (en)
simple_encyclopedia    the gentle children's encyclopedia Simple English Wikipedia
dictionary             the great dictionary               Wiktionary
nature_guide           the nature field guide             iNaturalist
star_atlas             the star atlas                     NASA Image and Video Library
art_folio              the art folio                      Art Institute of Chicago
book_catalogue         the book catalogue                 Open Library
=====================  =================================  ============================

Access rules followed:

* Only HTTPS GET requests to hosts in :data:`kimi.safety.TRUSTED_HOSTS`;
  redirects that leave those hosts are refused.
* Each API's etiquette: a descriptive User-Agent, one request at a time, at
  most one request per second, small responses. If a site answers "slow
  down" (HTTP 429), that site is left alone for at least 30 minutes.
* No logins, paywalls, CAPTCHAs or access controls are touched, and nothing
  downloaded is executed: only JSON text is parsed, and HTML inside it is
  reduced to plain text.
* Research is limited per day (Settings) and Kimi decides when a subject is
  worth investigating. Web search beyond these shelves is a separate,
  opt-in feature (see ``kimi.runtime.KimiRuntime.web_research_status``).
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

from .. import __version__
from ..safety import SafetyViolation, check_url, clean_text

MAX_RESPONSE_BYTES = 300_000
COOLDOWN_S = 30 * 60

SHELVES: dict[str, str] = {
    "encyclopedia": "Professor Quill's encyclopedia",
    "simple_encyclopedia": "the gentle children's encyclopedia",
    "dictionary": "the great dictionary",
    "nature_guide": "the nature field guide",
    "star_atlas": "the star atlas",
    "art_folio": "the art folio",
    "book_catalogue": "the book catalogue",
}
SHELF_HOSTS: dict[str, str] = {
    "encyclopedia": "en.wikipedia.org",
    "simple_encyclopedia": "simple.wikipedia.org",
    "dictionary": "en.wiktionary.org",
    "nature_guide": "api.inaturalist.org",
    "star_atlas": "images-api.nasa.gov",
    "art_folio": "api.artic.edu",
    "book_catalogue": "openlibrary.org",
}
DEFAULT_SHELF = "encyclopedia"
FALLBACK = ("encyclopedia", "simple_encyclopedia")


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
    source: str = DEFAULT_SHELF
    citations: list[dict] = field(default_factory=list)

    @property
    def shelf_name(self) -> str:
        return SHELVES.get(self.source, "the wider world")


_TAGS = re.compile(r"<[^>]+>")


def plain(text: object, limit: int = 1500) -> str:
    """HTML from an API -> plain, length-limited text."""
    s = html.unescape(_TAGS.sub(" ", str(text or "")))
    return clean_text(re.sub(r"\s+", " ", s), limit)


class LibraryResearcher:
    WIKI_API = "https://{host}/w/api.php"
    WIKI_SUMMARY = "https://{host}/api/rest_v1/page/summary/{title}"

    def __init__(self, settings, session=None, min_interval_s: float = 1.0, timeout: float = 10.0) -> None:
        self.settings = settings
        self._session = session
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self._lock = threading.Lock()
        self._last = 0.0
        self._cooldowns: dict[str, float] = {}

    # -- etiquette ---------------------------------------------------------------
    def cooldown_remaining(self, shelf: str | None = None) -> float:
        """Seconds until a shelf can be used again. Without a shelf: until *any* default shelf is usable."""
        now = time.monotonic()
        if shelf is not None:
            return max(0.0, self._cooldowns.get(SHELF_HOSTS.get(shelf, ""), 0.0) - now)
        return min(max(0.0, self._cooldowns.get(SHELF_HOSTS[s], 0.0) - now) for s in FALLBACK)

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
        host = urlparse(url).hostname or ""
        if self._cooldowns.get(host, 0.0) > time.monotonic():
            raise RateLimited(f"{host} asked us to slow down; waiting before trying again")
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
                raise ResearchUnavailable(f"Couldn't reach the shelf ({type(exc).__name__})") from None
            finally:
                self._last = time.monotonic()
            try:
                check_url(str(getattr(resp, "url", url) or url))   # redirects must stay on trusted hosts
                if resp.status_code == 404:
                    raise ResearchUnavailable("No such page")
                if resp.status_code == 429:
                    try:
                        wait_s = float(resp.headers.get("Retry-After") or 0)
                    except (TypeError, ValueError):
                        wait_s = 0.0
                    self._cooldowns[host] = time.monotonic() + max(wait_s, COOLDOWN_S)
                    raise RateLimited(f"{host} asked us to slow down")
                if resp.status_code != 200:
                    raise ResearchUnavailable(f"The shelf returned status {resp.status_code}")
                if "json" not in (resp.headers.get("Content-Type") or "").lower():
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

    # -- shelves ---------------------------------------------------------------------
    def _wiki(self, topic: str, host: str, source: str) -> Findings:
        def summary(title: str) -> dict:
            return self._get_json(self.WIKI_SUMMARY.format(host=host, title=quote(title.replace(" ", "_"), safe="")))

        def findings(title: str, s: dict, related: list[str]) -> Findings | None:
            if s.get("type") == "disambiguation":
                return None
            extract = plain(s.get("extract", ""))
            if len(extract) < 40:
                return None
            page = ((s.get("content_urls") or {}).get("desktop") or {}).get("page") or \
                f"https://{host}/wiki/{quote(title.replace(' ', '_'))}"
            return Findings(topic, clean_text(s.get("title", title), 120), extract, clean_text(page, 300), related, source)

        direct = topic[:1].upper() + topic[1:]
        try:
            found = findings(direct, summary(direct), [])
            if found:
                return found
        except RateLimited:
            raise
        except ResearchUnavailable:
            pass
        data = self._get_json(self.WIKI_API.format(host=host), {
            "action": "query", "list": "search", "srsearch": topic, "srlimit": "3",
            "srprop": "", "format": "json", "formatversion": "2",
        })
        titles = [clean_text(r.get("title", ""), 120) for r in (data.get("query") or {}).get("search") or [] if r.get("title")]
        for title in titles:
            try:
                found = findings(title, summary(title), [t for t in titles if t != title])
            except RateLimited:
                raise
            except ResearchUnavailable:
                continue
            if found:
                return found
        raise ResearchUnavailable(f"Nothing readable about {topic}")

    def _dictionary(self, topic: str) -> Findings:
        word = topic.strip().split()[0] if len(topic.split()) > 2 else topic.strip()
        data = self._get_json(f"https://en.wiktionary.org/api/rest_v1/page/definition/{quote(word.replace(' ', '_'), safe='')}")
        lines = []
        for entry in data.get("en") or []:
            for d in (entry.get("definitions") or [])[:2]:
                text = plain(d.get("definition"), 240)
                if text:
                    lines.append(f"({entry.get('partOfSpeech', 'word').lower()}) {text}")
            if len(lines) >= 4:
                break
        if not lines:
            raise ResearchUnavailable(f"The dictionary has no entry for {word}")
        return Findings(topic, f"{word} (dictionary)", " ".join(lines)[:1500],
                        f"https://en.wiktionary.org/wiki/{quote(word.replace(' ', '_'))}", source="dictionary")

    def _nature(self, topic: str) -> Findings:
        data = self._get_json("https://api.inaturalist.org/v1/taxa", {"q": topic, "per_page": "3"})
        results = data.get("results") or []
        if not results:
            raise ResearchUnavailable(f"The field guide has nothing on {topic}")
        taxon = results[0]
        detail = self._get_json(f"https://api.inaturalist.org/v1/taxa/{int(taxon['id'])}")
        t = (detail.get("results") or [taxon])[0]
        common = t.get("preferred_common_name") or t.get("name")
        summary = plain(t.get("wikipedia_summary"), 1200)
        facts = (f"{common} ({t.get('name')}, a {t.get('rank', 'group')} of {t.get('iconic_taxon_name') or 'living things'}). "
                 f"People have recorded it {int(t.get('observations_count') or 0):,} times.")
        extract = f"{facts} {summary}".strip()
        return Findings(topic, clean_text(str(common), 120), extract[:1500],
                        f"https://www.inaturalist.org/taxa/{int(t['id'])}", source="nature_guide",
                        related=[clean_text(r.get("preferred_common_name") or r.get("name"), 80) for r in results[1:]])

    def _stars(self, topic: str) -> Findings:
        data = self._get_json("https://images-api.nasa.gov/search", {"q": topic, "media_type": "image", "page_size": "5"})
        items = ((data.get("collection") or {}).get("items")) or []
        for item in items:
            meta = (item.get("data") or [{}])[0]
            desc = plain(meta.get("description"), 1400)
            if len(desc) >= 60:
                nasa_id = clean_text(meta.get("nasa_id", ""), 120)
                when = str(meta.get("date_created", ""))[:4]
                return Findings(topic, clean_text(meta.get("title", topic), 120), f"({when}) {desc}" if when else desc,
                                f"https://images.nasa.gov/details/{quote(nasa_id)}", source="star_atlas")
        raise ResearchUnavailable(f"The star atlas has nothing on {topic}")

    def _art(self, topic: str) -> Findings:
        data = self._get_json("https://api.artic.edu/api/v1/artworks/search", {
            "q": topic, "limit": "3",
            "fields": "id,title,artist_display,date_display,medium_display,short_description,description,place_of_origin",
        })
        for art in data.get("data") or []:
            desc = plain(art.get("short_description") or art.get("description"), 1100)
            if len(desc) < 40:
                continue
            artist = plain(art.get("artist_display"), 120).split(" Born ")[0]
            header = f"\"{plain(art.get('title'), 120)}\" by {artist} ({plain(art.get('date_display'), 40)}, {plain(art.get('medium_display'), 80)})."
            return Findings(topic, plain(art.get("title"), 120), f"{header} {desc}"[:1500],
                            f"https://www.artic.edu/artworks/{int(art['id'])}", source="art_folio")
        raise ResearchUnavailable(f"The art folio has nothing on {topic}")

    def _books(self, topic: str) -> Findings:
        data = self._get_json("https://openlibrary.org/search.json", {
            "q": topic, "limit": "4", "fields": "key,title,author_name,first_publish_year,subject",
        })
        docs = data.get("docs") or []
        if not docs:
            raise ResearchUnavailable(f"The book catalogue has nothing on {topic}")
        parts = []
        for d in docs[:4]:
            author = ", ".join((d.get("author_name") or ["unknown"])[:2])
            subjects = ", ".join((d.get("subject") or [])[:5])
            parts.append(f"\"{plain(d.get('title'), 100)}\" by {plain(author, 80)} ({d.get('first_publish_year', '?')})"
                         + (f", about {plain(subjects, 160)}" if subjects else ""))
        key = clean_text(docs[0].get("key", ""), 80)
        return Findings(topic, f"Books about {topic}", ("Books in the catalogue: " + "; ".join(parts) + ".")[:1500],
                        f"https://openlibrary.org{key}" if key.startswith("/") else "https://openlibrary.org",
                        source="book_catalogue")

    def _from_shelf(self, topic: str, shelf: str) -> Findings:
        if shelf == "encyclopedia":
            return self._wiki(topic, "en.wikipedia.org", shelf)
        if shelf == "simple_encyclopedia":
            return self._wiki(topic, "simple.wikipedia.org", shelf)
        if shelf == "dictionary":
            return self._dictionary(topic)
        if shelf == "nature_guide":
            return self._nature(topic)
        if shelf == "star_atlas":
            return self._stars(topic)
        if shelf == "art_folio":
            return self._art(topic)
        if shelf == "book_catalogue":
            return self._books(topic)
        raise ResearchUnavailable(f"Unknown shelf {shelf}")

    def investigate(self, topic: str, shelf: str = DEFAULT_SHELF) -> Findings:
        """Try the chosen shelf, then fall back to the encyclopedias."""
        order = [shelf if shelf in SHELVES else DEFAULT_SHELF] + [s for s in FALLBACK if s != shelf]
        last: ResearchUnavailable | None = None
        all_limited = True
        for s in order:
            try:
                return self._from_shelf(topic, s)
            except RateLimited as exc:
                last = exc
            except (ResearchUnavailable, KeyError, TypeError, ValueError) as exc:
                all_limited = False
                last = exc if isinstance(exc, ResearchUnavailable) else ResearchUnavailable("Malformed response")
        if all_limited and isinstance(last, RateLimited):
            raise last
        raise last or ResearchUnavailable(f"Nothing found about {topic}")


# Backwards-compatible name.
WikipediaResearcher = LibraryResearcher
