import html as html_lib
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


LINNATEATER_PRODUCTIONS = "https://linnateater.ee/lavastused/"
PILETILEVI_ORGANIZER = (
    "https://www.piletilevi.ee/korraldajad/21-69-257/tallinna-linnateater"
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)
TIMEOUT = 18

EVENT_CODE_RE = re.compile(r"/piletid/([A-Z0-9]+)/", re.I)
DATE_TIME_RE = re.compile(
    r"\b(\d{2}\.\d{2}\.\d{4})\b.{0,40}?\b(\d{1,2}:\d{2})\b"
)

_cache = {}


@dataclass
class Performance:
    title: str
    date_text: str
    event_url: str
    event_code: str
    series_url: str
    status: str
    image_url: str
    production_url: str


def _cached(key, ttl, builder):
    now = time.time()
    item = _cache.get(key)
    if item and now - item[0] < ttl:
        return item[1]
    value = builder()
    _cache[key] = (now, value)
    return value


def _get(url: str) -> requests.Response:
    r = requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent": UA,
            "Accept-Language": "et-EE,et;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        },
    )
    r.raise_for_status()
    return r


def _clean(value: str) -> str:
    return " ".join(html_lib.unescape(value or "").split())


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[„“”\"'’`´]", "", value)
    value = re.sub(r"[^a-z0-9õäöüšž]+", " ", value)
    return " ".join(value.split())


def _event_code(url: str) -> str:
    m = EVENT_CODE_RE.search(urlparse(url).path)
    if not m:
        raise ValueError("Piletilevi etenduse koodi ei leitud.")
    return m.group(1).upper()


def _og_image(soup, base_url=""):
    tag = soup.find("meta", attrs={"property": "og:image"})
    if tag and tag.get("content"):
        return urljoin(base_url, tag["content"])

    tag = soup.find("meta", attrs={"name": "twitter:image"})
    if tag and tag.get("content"):
        return urljoin(base_url, tag["content"])

    img = soup.find("img", src=True)
    return urljoin(base_url, img["src"]) if img else ""


def list_productions():
    def build():
        html = _get(LINNATEATER_PRODUCTIONS).text
        soup = BeautifulSoup(html, "html.parser")
        found = {}

        for a in soup.find_all("a", href=True):
            href = urljoin(LINNATEATER_PRODUCTIONS, a["href"])
            if "/lavastused/" not in href:
                continue
            if href.rstrip("/") == LINNATEATER_PRODUCTIONS.rstrip("/"):
                continue

            title = ""
            heading = a.find(["h1", "h2", "h3"])
            if heading:
                title = _clean(heading.get_text(" ", strip=True))
            if not title:
                title = _clean(a.get_text(" ", strip=True))

            # Skip generic navigation labels.
            if not title or title.lower() in {
                "lavastused",
                "lavastuste arhiiv",
                "piletid",
            }:
                continue

            slug = urlparse(href).path.rstrip("/").split("/")[-1]
            key = _norm(title)
            if key and key not in found:
                found[key] = {
                    "title": title,
                    "production_url": href,
                    "slug": slug,
                }

        return sorted(found.values(), key=lambda x: x["title"].casefold())

    return _cached("productions", 300, build)


def production_details(production_url: str):
    def build():
        html = _get(production_url).text
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        title = _clean(h1.get_text(" ", strip=True)) if h1 else ""

        if not title:
            # Linnateater pages often render the title outside h1 in parsed HTML.
            page_title = soup.find("title")
            if page_title:
                title = _clean(page_title.get_text(" ", strip=True)).split(" - ")[0]

        return {
            "title": title,
            "image_url": _og_image(soup, production_url),
        }

    return _cached("production:" + production_url, 1800, build)


def _context_for_anchor(anchor):
    """
    Find the smallest nearby wrapper that contains a date+time.
    Piletilevi markup can change, so do not depend on one CSS class.
    """
    node = anchor
    best = _clean(anchor.get_text(" ", strip=True))

    for _ in range(7):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if text:
            best = text
        if DATE_TIME_RE.search(text):
            # Avoid swallowing the entire organizer page.
            if len(text) < 1600:
                return text
    return best


def _extract_date_text(context: str):
    m = DATE_TIME_RE.search(context)
    if not m:
        return ""
    return f"{m.group(1)} • {m.group(2)}"


def _status_from_context(context: str):
    low = _norm(context)
    if "valja muudud" in low or "sold out" in low:
        return "Välja müüdud"
    if "peatatud" in low or "suspended" in low:
        return "Müük peatatud"
    return "Pilet saadaval"


def _find_series_url(event_url: str):
    html = _get(event_url).text
    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        txt = _norm(a.get_text(" ", strip=True))
        href = urljoin(event_url, a.get("href") or "")
        if "/series/" in href and (
            "vaata kogu seeriat" in txt
            or "other events from the series" in txt
            or "series" in href
        ):
            return href

    # If no series URL is exposed, the event page itself remains usable as a
    # fallback checker target.
    return event_url


def list_performances(title: str, production_url: str):
    """
    Load the Tallinna Linnateater organiser page from Piletilevi and return
    only performances whose event title matches the selected production.
    """
    title_norm = _norm(title)

    def build():
        html = _get(PILETILEVI_ORGANIZER).text
        soup = BeautifulSoup(html, "html.parser")
        details = production_details(production_url)
        image_url = details.get("image_url") or ""

        candidates = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = urljoin(PILETILEVI_ORGANIZER, a.get("href") or "")
            if not EVENT_CODE_RE.search(urlparse(href).path):
                continue

            event_code = _event_code(href)
            if event_code in seen:
                continue

            anchor_text = _clean(a.get_text(" ", strip=True))
            context = _context_for_anchor(a)
            combined_norm = _norm(anchor_text + " " + context)

            # Exact-ish production name matching. This intentionally allows
            # suffixes such as replacement-performance notes.
            if title_norm not in combined_norm:
                continue

            date_text = _extract_date_text(context)
            if not date_text:
                continue

            seen.add(event_code)
            candidates.append(
                {
                    "title": title,
                    "date_text": date_text,
                    "event_url": href,
                    "event_code": event_code,
                    "status": _status_from_context(context),
                    "image_url": image_url,
                    "production_url": production_url,
                }
            )

        # Some Piletilevi list cards expose a click target around title/date in
        # a way BeautifulSoup may not associate perfectly. If none were found,
        # return an explicit error rather than silently showing an empty list.
        if not candidates:
            raise RuntimeError(
                "Piletilevist ei leitud sellele lavastusele tulevasi etendusi."
            )

        # Resolve the series only once and reuse it for all performances.
        series_url = _find_series_url(candidates[0]["event_url"])
        for item in candidates:
            item["series_url"] = series_url

        # dd.mm.yyyy can be sorted as yyyy-mm-dd after rearranging.
        def key(item):
            m = re.match(
                r"(\d{2})\.(\d{2})\.(\d{4})\s*•\s*(\d{2}):(\d{2})",
                item["date_text"],
            )
            if not m:
                return item["date_text"]
            d, mo, y, hh, mm = m.groups()
            return f"{y}-{mo}-{d} {hh}:{mm}"

        candidates.sort(key=key)
        return candidates

    return _cached(
        "performances:" + title_norm + ":" + production_url,
        120,
        build,
    )


def check_event(series_url: str, event_code: str):
    html = _get(series_url).text
    soup = BeautifulSoup(html, "html.parser")
    event_code = event_code.upper()

    target = None
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").upper()
        if event_code in href and "/PILETID/" in href:
            target = a
            break

    if target is None:
        # Fallback for cases where series_url is the event itself.
        if event_code in html.upper():
            body = _clean(soup.get_text(" ", strip=True))
            status = _status_from_context(body[:4500])
            return status == "Pilet saadaval", status

        raise RuntimeError(
            "Jälgitavat etendust ei leitud enam Piletilevi lehelt."
        )

    context = _context_for_anchor(target)
    status = _status_from_context(context)
    return status == "Pilet saadaval", status
