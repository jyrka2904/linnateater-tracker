import html as html_lib
import re
import time
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


LINNATEATER_PRODUCTIONS = "https://linnateater.ee/lavastused/"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)
TIMEOUT = 18

EVENT_CODE_RE = re.compile(r"/piletid/([A-Z0-9]+)/", re.I)
DATE_TIME_RE = re.compile(
    r"\b(\d{2}\.\d{2}\.\d{4})\b.{0,80}?\b(\d{1,2}:\d{2})\b"
)

_cache = {}

# Verified Piletilevi series URLs for current Tallinna Linnateater productions.
# These series IDs remain stable for the lifetime of the production and are a
# much more reliable bridge than trying to find ticket links on Linnateater's
# dynamically rendered "Etendused" block.
SERIES_BY_TITLE = {
    "alguses oli laul": "https://www.piletilevi.ee/series/L5IUG4FOJT/alguses-oli-laul-tallinna-linnateater",
    "annapurna": "https://www.piletilevi.ee/series/Q5NAYLMAR4/annapurna-tallinna-linnateater",
    "avamine": "https://www.piletilevi.ee/series/SNH4ITZH2X/avamine-tallinna-linnateater",
    "elu on unenagu": "https://www.piletilevi.ee/series/SWJ363TX5L/elu-on-unenagu-tallinna-linnateater",
    "exit": "https://www.piletilevi.ee/series/O5OIWM2BWH/exit-tallinna-linnateater",
    "iphigeneia agamemnon elektra": "https://www.piletilevi.ee/series/SO5I226DRM/iphigeneia-agamemnon-elektra-tallinna-linnateater",
    "kaitumisreeglid tanapaeva uhiskonnas": "https://www.piletilevi.ee/series/6TK3F2QTEO/kaitumisreeglid-tanapaeva-uhiskonnas-tallinna-linnateater",
    "karussell": "https://www.piletilevi.ee/series/OQLYXVFGWC/karussell-tallinna-linnateater",
    "kiilaspaine lauljanna": "https://www.piletilevi.ee/series/XEASVWDB6Z/kiilaspaine-lauljanna-tallinna-linnateater",
    "krum": "https://www.piletilevi.ee/series/A37XK2BVIM/krum-tallinna-linnateater",
    "nachtland": "https://www.piletilevi.ee/series/TVM2FMJGZ4/nachtland-tallinna-linnateater",
    "nousolek": "https://www.piletilevi.ee/series/TSGQ45KDPN/nousolek-tallinna-linnateater",
    "novecento": "https://www.piletilevi.ee/series/BLY672UD3Y/novecento-tallinna-linnateater",
    "oo": "https://www.piletilevi.ee/series/T5AUILXR6L/oo-tallinna-linnateater",
    "opetatud naised": "https://www.piletilevi.ee/series/I7NF4RLG7I/opetatud-naised-tallinna-linnateater",
    "orvud": "https://www.piletilevi.ee/series/VMNVIODQWL/orvud-tallinna-linnateater",
    "poiss kes nagi pimeduses": "https://www.piletilevi.ee/series/I4GGEG4NMY/poiss-kes-nagi-pimeduses-tallinna-linnateater",
    "puhkus": "https://www.piletilevi.ee/series/YWOR22Y4FR/puhkus-tallinna-linnateater",
    "seitsmemagajapaev": "https://www.piletilevi.ee/series/OMSSF6ONWA/seitsmemagajapaev-tallinna-linnateater",
    "sinisilmsed": "https://www.piletilevi.ee/series/M6A5FX7IFF/sinisilmsed-tallinna-linnateater",
    "sudameharjutus": "https://www.piletilevi.ee/series/AOKECBOEM7/sudameharjutus-tallinna-linnateater",
    "toeline laas": "https://www.piletilevi.ee/series/IOQMPZIKQQ/toeline-laas-tallinna-linnateater",
}



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


def _strip_piletilevi_suffix(title: str) -> str:
    title = _clean(title)
    title = re.sub(
        r"\s*\(\s*Tallinna\s+Linnateater\s*\)\s*$",
        "",
        title,
        flags=re.I,
    )
    return title.strip()


def _event_code(url: str) -> str:
    m = EVENT_CODE_RE.search(urlparse(url).path)
    if not m:
        raise ValueError("Piletilevi etenduse koodi ei leitud.")
    return m.group(1).upper()


def _image_candidates(soup, raw_html: str, base_url: str):
    candidates = []

    for attrs in (
        {"property": "og:image"},
        {"property": "og:image:url"},
        {"name": "twitter:image"},
        {"name": "twitter:image:src"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            candidates.append(tag["content"])

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            value = img.get(attr)
            if value:
                candidates.append(value)

        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            for part in srcset.split(","):
                url = part.strip().split(" ")[0]
                if url:
                    candidates.append(url)

    for match in re.findall(
        r'(?:url\(|["\'])(https?://[^"\'()\\\s]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\'()\\\s]*)?)',
        raw_html,
        flags=re.I,
    ):
        candidates.append(match)

    for match in re.findall(
        r'["\']([^"\']+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\']*)?)["\']',
        raw_html,
        flags=re.I,
    ):
        if "/uploads/" in match or "/wp-content/" in match:
            candidates.append(match)

    cleaned = []
    seen = set()

    for value in candidates:
        value = html_lib.unescape(value or "").strip()
        if not value or value.startswith("data:"):
            continue
        url = urljoin(base_url, value)
        low = url.lower()

        if any(
            token in low
            for token in (
                "logo",
                "icon",
                "favicon",
                "sprite",
                "avatar",
                "placeholder",
            )
        ):
            continue

        if url not in seen:
            seen.add(url)
            cleaned.append(url)

    return cleaned


def page_image(url: str) -> str:
    def build():
        html = _get(url).text
        soup = BeautifulSoup(html, "html.parser")
        candidates = _image_candidates(soup, html, url)
        return candidates[0] if candidates else ""

    return _cached("image:" + url, 1800, build)


def _image_from_node(node, base_url: str):
    """
    Extract an image already present in the production-list card markup.
    This avoids opening every individual production page.
    """
    if node is None:
        return ""

    # Prefer image elements inside the card/link.
    img = node.find("img")
    if img:
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            value = img.get(attr)
            if value and not value.startswith("data:"):
                return urljoin(base_url, value)

        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            # Usually the last candidate is the largest.
            candidates = []
            for part in srcset.split(","):
                value = part.strip().split(" ")[0]
                if value:
                    candidates.append(value)
            if candidates:
                return urljoin(base_url, candidates[-1])

    # Background-image fallback.
    style = node.get("style") or ""
    m = re.search(r'url\((["\']?)(.*?)\1\)', style, flags=re.I)
    if m and m.group(2):
        return urljoin(base_url, m.group(2))

    # Look one level up; some sites place the image beside the anchor text.
    parent = getattr(node, "parent", None)
    if parent is not None:
        img = parent.find("img")
        if img:
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                value = img.get(attr)
                if value and not value.startswith("data:"):
                    return urljoin(base_url, value)

            srcset = img.get("srcset") or img.get("data-srcset")
            if srcset:
                candidates = [
                    part.strip().split(" ")[0]
                    for part in srcset.split(",")
                    if part.strip()
                ]
                if candidates:
                    return urljoin(base_url, candidates[-1])

    return ""


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
                    "image_url": _image_from_node(a, LINNATEATER_PRODUCTIONS),
                }

        return sorted(found.values(), key=lambda x: x["title"].casefold())

    return _cached("productions", 300, build)


def production_for_title(title: str):
    wanted = _norm(_strip_piletilevi_suffix(title))
    productions = list_productions()

    for item in productions:
        if _norm(item["title"]) == wanted:
            return item

    for item in productions:
        n = _norm(item["title"])
        if n and wanted and (n in wanted or wanted in n):
            return item

    return None


def _extract_event_page_info(event_url: str):
    html = _get(event_url).text
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = _clean(h1.get_text(" ", strip=True)) if h1 else ""
    body_text = _clean(soup.get_text(" ", strip=True))

    date_text = ""
    m = DATE_TIME_RE.search(body_text)
    if m:
        date_text = f"{m.group(1)} • {m.group(2)}"

    if not date_text:
        for tag in soup.find_all("meta"):
            content = tag.get("content") or ""
            m = DATE_TIME_RE.search(content)
            if m:
                date_text = f"{m.group(1)} • {m.group(2)}"
                break

    low = _norm(body_text[:6500])
    if "valja muudud" in low or "sold out" in low:
        status = "Välja müüdud"
    elif "muuk peatatud" in low or "suspended" in low:
        status = "Müük peatatud"
    else:
        status = "Pilet saadaval"

    series_url = ""
    for a in soup.find_all("a", href=True):
        href = urljoin(event_url, a.get("href") or "")
        text = _norm(a.get_text(" ", strip=True))
        if "/series/" in href and (
            "vaata kogu seeriat" in text
            or "series" in href.lower()
            or "kogu seeriat" in text
        ):
            series_url = href
            break

    image_url = page_image(event_url)

    return {
        "event_url": event_url,
        "event_code": _event_code(event_url),
        "title": title,
        "date_text": date_text,
        "status": status,
        "series_url": series_url or event_url,
        "image_url": image_url,
    }


def _piletilevi_links_from_linnateater(production_url: str):
    html = _get(production_url).text
    soup = BeautifulSoup(html, "html.parser")

    event_urls = []
    series_urls = []
    seen_events = set()
    seen_series = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(production_url, a.get("href") or "")
        host = urlparse(href).netloc.lower()
        if "piletilevi" not in host:
            continue

        if EVENT_CODE_RE.search(urlparse(href).path):
            code = _event_code(href)
            if code not in seen_events:
                seen_events.add(code)
                event_urls.append(href)

        elif "/series/" in urlparse(href).path.lower():
            if href not in seen_series:
                seen_series.add(href)
                series_urls.append(href)

    for raw in re.findall(
        r'https?://(?:www\.)?piletilevi\.ee/[^"\'<>\\\s]+',
        html,
        flags=re.I,
    ):
        href = html_lib.unescape(raw).replace("\\/", "/")
        path = urlparse(href).path

        if EVENT_CODE_RE.search(path):
            try:
                code = _event_code(href)
            except Exception:
                continue
            if code not in seen_events:
                seen_events.add(code)
                event_urls.append(href)

        elif "/series/" in path.lower() and href not in seen_series:
            seen_series.add(href)
            series_urls.append(href)

    return event_urls, series_urls


def _event_links_from_series(series_url: str):
    html = _get(series_url).text
    soup = BeautifulSoup(html, "html.parser")

    urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(series_url, a.get("href") or "")
        if not EVENT_CODE_RE.search(urlparse(href).path):
            continue
        code = _event_code(href)
        if code not in seen:
            seen.add(code)
            urls.append(href)

    for raw in re.findall(
        r'https?://(?:www\.)?piletilevi\.ee/[^"\'<>\\\s]+',
        html,
        flags=re.I,
    ):
        href = html_lib.unescape(raw).replace("\\/", "/")
        if not EVENT_CODE_RE.search(urlparse(href).path):
            continue
        try:
            code = _event_code(href)
        except Exception:
            continue
        if code not in seen:
            seen.add(code)
            urls.append(href)

    return urls


def _series_url_for_title(title: str):
    return SERIES_BY_TITLE.get(_norm(title))


def _series_statuses(series_url: str):
    """
    Return {event_code: status} from the Piletilevi SERIES page.

    Sold-out state is authoritative on the series/listing card. A concrete
    event detail page can still be readable when tickets are sold out, so
    treating the detail page itself as "available" caused false positives.
    """
    html = _get(series_url).text
    soup = BeautifulSoup(html, "html.parser")
    statuses = {}

    anchors = []
    for a in soup.find_all("a", href=True):
        href = urljoin(series_url, a.get("href") or "")
        if EVENT_CODE_RE.search(urlparse(href).path):
            anchors.append((a, href))

    for anchor, href in anchors:
        try:
            code = _event_code(href)
        except Exception:
            continue

        # Find the SMALLEST ancestor that looks like one event card/row.
        # Stop as soon as it has a date+time. This prevents accidentally
        # inheriting "Sold out" from a neighbouring performance.
        node = anchor
        context = _clean(anchor.get_text(" ", strip=True))

        for _ in range(7):
            node = getattr(node, "parent", None)
            if node is None:
                break

            text = _clean(node.get_text(" ", strip=True))
            if not text:
                continue

            # A useful event row normally contains a date/time and remains
            # reasonably short. Prefer the first such ancestor.
            if DATE_TIME_RE.search(text) and len(text) <= 1200:
                context = text
                break

        low = _norm(context)

        if "valja muudud" in low or "sold out" in low:
            status = "Välja müüdud"
        elif (
            "muuk peatatud" in low
            or "müük peatatud" in context.lower()
            or "suspended" in low
        ):
            status = "Müük peatatud"
        else:
            status = "Pilet saadaval"

        statuses[code] = status

    return statuses


def list_performances(title: str, production_url: str):
    """
    v4: use the verified Piletilevi series page as the canonical source.

    The series page contains the complete set of current/future performances.
    We collect each unique concrete event URL from it and then read each event
    page individually for an exact date/time/status. This avoids both the
    missing-link problem and the duplicate-date bug from earlier versions.
    """
    title_norm = _norm(title)

    def build():
        series_url = _series_url_for_title(title)

        if not series_url:
            # Keep a fallback for newly-added productions that are not yet in
            # the mapping. If Linnateater later begins exposing direct links,
            # they can still work without another deploy.
            event_urls, series_urls = _piletilevi_links_from_linnateater(
                production_url
            )
            if series_urls:
                series_url = series_urls[0]
            elif event_urls:
                info = _extract_event_page_info(event_urls[0])
                series_url = info.get("series_url") or event_urls[0]
            else:
                raise RuntimeError(
                    "Selle lavastuse Piletilevi seeriat ei ole veel "
                    "jälgijasse lisatud."
                )

        event_urls = _event_links_from_series(series_url)
        series_statuses = _series_statuses(series_url)

        # Some Piletilevi pages can serialize event URLs without normal anchors.
        # _event_links_from_series already checks both forms.
        if not event_urls:
            raise RuntimeError(
                "Piletilevi seerialeht leiti, kuid konkreetsete etenduste "
                "linke ei õnnestunud lugeda."
            )

        production_image = page_image(production_url)
        results = []
        seen_codes = set()

        for event_url in event_urls:
            try:
                item = _extract_event_page_info(event_url)
            except Exception:
                continue

            code = item["event_code"]
            if code in seen_codes or not item.get("date_text"):
                continue

            event_title_norm = _norm(
                _strip_piletilevi_suffix(item.get("title") or "")
            )

            # Allow replacement-performance notes, but reject unrelated events.
            if title_norm and event_title_norm:
                if (
                    title_norm not in event_title_norm
                    and event_title_norm not in title_norm
                ):
                    continue

            seen_codes.add(code)
            item["title"] = title
            item["series_url"] = series_url
            item["production_url"] = production_url

            # IMPORTANT: availability comes from the exact event row on the
            # series page, not from the event detail page.
            if code in series_statuses:
                item["status"] = series_statuses[code]
            if not item.get("image_url"):
                item["image_url"] = production_image
            results.append(item)

        if not results:
            raise RuntimeError(
                "Piletilevi seeria on olemas, kuid ühegi etenduse "
                "kuupäeva ei õnnestunud lugeda."
            )

        def sort_key(item):
            m = re.match(
                r"(\d{2})\.(\d{2})\.(\d{4})\s*•\s*(\d{1,2}):(\d{2})",
                item["date_text"],
            )
            if not m:
                return item["date_text"]
            d, mo, y, hh, mm = m.groups()
            return f"{y}-{mo}-{d} {int(hh):02d}:{mm}"

        results.sort(key=sort_key)
        return results

    return _cached(
        "performances-v4:" + title_norm + ":" + production_url,
        120,
        build,
    )

def tracker_image(title: str, event_url: str = "", production_url: str = ""):
    if production_url:
        try:
            image = page_image(production_url)
            if image:
                return image, production_url
        except Exception:
            pass

    if event_url:
        try:
            image = page_image(event_url)
            if image:
                return image, production_url
        except Exception:
            pass

    production = production_for_title(title)
    if production:
        try:
            image = page_image(production["production_url"])
            return image, production["production_url"]
        except Exception:
            return "", production["production_url"]

    return "", production_url


def check_event(series_url: str, event_code: str):
    """
    Worker availability check.

    Piletilevi's series page is the source of truth for SOLD OUT / available.
    This uses the exact Piletilevi event code, so the status of neighbouring
    dates cannot leak into the target performance.
    """
    event_code = event_code.upper()

    try:
        statuses = _series_statuses(series_url)
        if event_code in statuses:
            status = statuses[event_code]
            return status == "Pilet saadaval", status
    except Exception:
        # Continue to the conservative fallback below.
        pass

    # Conservative fallback: if the exact event cannot be located on the
    # series page, do NOT claim availability. This prevents false SMS alerts.
    raise RuntimeError(
        "Etenduse saadavust ei saanud Piletilevi seerialehelt kindlalt tuvastada."
    )

