import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)
TIMEOUT = 15

EVENT_CODE_RE = re.compile(r"/piletid/([A-Z0-9]+)/", re.I)


@dataclass
class EventInfo:
    event_url: str
    series_url: str
    event_code: str
    title: str
    date_text: str


def _get(url: str) -> requests.Response:
    r = requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent": UA,
            "Accept-Language": "et-EE,et;q=0.9,en;q=0.8",
        },
    )
    r.raise_for_status()
    return r


def _event_code(url: str) -> str:
    m = EVENT_CODE_RE.search(urlparse(url).path)
    if not m:
        raise ValueError(
            "Link ei näe välja nagu Piletilevi konkreetse etenduse link."
        )
    return m.group(1).upper()


def resolve_event(event_url: str) -> EventInfo:
    """
    Resolve a concrete Piletilevi event URL to its series URL and display data.
    Example:
      https://www.piletilevi.ee/piletid/S3PIGYZHGH/sinisilmsed
    """
    event_url = event_url.strip()
    code = _event_code(event_url)

    html = _get(event_url).text
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else "Linnateatri etendus"

    series_url = None
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True).lower()
        href = a.get("href") or ""
        if "vaata kogu seeriat" in txt or "/series/" in href:
            candidate = urljoin(event_url, href)
            if "/series/" in candidate:
                series_url = candidate
                break

    if not series_url:
        raise RuntimeError(
            "Piletilevi seeria linki ei leitud. "
            "Kontrolli, et sisestasid konkreetse etenduse lingi."
        )

    # Try to pick the event/date line near the top of the page.
    text_lines = [
        x.strip()
        for x in soup.get_text("\n", strip=True).splitlines()
        if x.strip()
    ]
    date_text = ""
    date_pattern = re.compile(
        r"\b\d{2}\.\d{2}\.\d{4}\b.*\b\d{1,2}:\d{2}\b"
    )
    for line in text_lines[:80]:
        if date_pattern.search(line):
            date_text = line
            break

    return EventInfo(
        event_url=event_url,
        series_url=series_url,
        event_code=code,
        title=title,
        date_text=date_text,
    )


def check_event(series_url: str, event_code: str):
    """
    Return (available, status_text).

    Piletilevi series pages contain a separate link for each performance.
    A sold-out performance is labelled 'Välja müüdud'. When that label
    disappears from the exact target event entry, we treat it as available.
    """
    html = _get(series_url).text
    soup = BeautifulSoup(html, "html.parser")

    target = None
    event_code = event_code.upper()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").upper()
        if f"/PILETID/{event_code}/" in href:
            target = a
            break

    if target is None:
        # Fallback: the event may be represented in JSON/HTML without a normal
        # anchor. Avoid false positive; fail loudly instead.
        if event_code in html.upper():
            raise RuntimeError(
                "Etendus leiti lehe lähtekoodist, kuid staatust ei saanud "
                "turvaliselt tuvastada."
            )
        raise RuntimeError(
            "Jälgitavat etendust ei leitud enam Piletilevi seerialehelt."
        )

    # The status may be on the anchor itself or an immediate parent wrapper.
    pieces = [target.get_text(" ", strip=True)]
    parent = target.parent
    for _ in range(3):
        if parent is None:
            break
        pieces.append(parent.get_text(" ", strip=True))
        parent = parent.parent

    context = " ".join(pieces)
    normalized = " ".join(context.split())
    low = normalized.lower()

    sold_markers = [
        "välja müüdud",
        "sold out",
    ]
    if any(x in low for x in sold_markers):
        return False, "Välja müüdud"

    stopped_markers = [
        "peatatud",
        "müük peatatud",
        "sale suspended",
    ]
    if any(x in low for x in stopped_markers):
        return False, "Müük peatatud"

    # If the specific entry exists and it is not marked sold out/suspended,
    # Piletilevi currently presents it as a purchasable performance.
    return True, "Pilet saadaval"
