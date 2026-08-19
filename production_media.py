import hashlib
from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageOps

from db import get_conn
from ticket_source import (
    list_productions,
    production_page_image_candidates,
    page_image,
)


TZ = ZoneInfo("Europe/Tallinn")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

DOWNLOAD_TIMEOUT = 20

# Standard card asset. Large enough for retina-ish display, but still light.
OUTPUT_WIDTH = 900
OUTPUT_HEIGHT = 1150
WEBP_QUALITY = 84

# Ignore tiny graphics/icons even if they are technically valid images.
MIN_SOURCE_SHORT_SIDE = 700


def get_media_manifest():
    """
    Return cached DB image metadata keyed by production slug.
    No image bytes are loaded here.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT slug, updated_at, width, height
                FROM production_image_store
                """
            )
            rows = cur.fetchall()

    return {
        row["slug"]: {
            "updated_at": row["updated_at"],
            "width": row["width"],
            "height": row["height"],
        }
        for row in rows
    }


def get_media_bytes(slug: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT image_bytes, mime_type, updated_at
                FROM production_image_store
                WHERE slug=%s
                """,
                (slug,),
            )
            return cur.fetchone()


def _download_image(url: str):
    if not url:
        return None

    response = requests.get(
        url,
        timeout=DOWNLOAD_TIMEOUT,
        headers={"User-Agent": UA},
    )
    response.raise_for_status()

    with Image.open(BytesIO(response.content)) as original:
        original.load()
        image = ImageOps.exif_transpose(original).convert("RGB")
        return image.copy()


def _detail_score(image: Image.Image):
    """
    Prefer high-resolution, photographic-looking candidates.

    We intentionally do NOT use the old blur heuristic as the primary filter,
    because soft theatrical artwork can still score unpredictably. Source size
    plus choosing from the production page is much more reliable here.
    """
    width, height = image.size
    short = min(width, height)
    area = width * height

    # Strongly reward useful source resolution. Slightly prefer portrait-ish
    # assets because the repertoire cards are portrait.
    aspect = width / height if height else 1
    portrait_bonus = 1.10 if 0.55 <= aspect <= 0.95 else 1.0

    return area * portrait_bonus, short


def _candidate_urls(title: str, production_url: str):
    """
    Prefer actual production-page images. Listing thumbnails are deliberately
    excluded from the primary path because those were the source of the blurry
    cards.
    """
    candidates = []

    for url in production_page_image_candidates(
        title,
        production_url,
        limit=18,
    ):
        if url and url not in candidates:
            candidates.append(url)

    # Last-resort page image.
    try:
        fallback = page_image(production_url)
        if fallback and fallback not in candidates:
            candidates.append(fallback)
    except Exception:
        pass

    return candidates


def choose_best_source(title: str, production_url: str):
    best = None
    best_score = -1

    for url in _candidate_urls(title, production_url):
        try:
            image = _download_image(url)
        except Exception:
            continue

        if image is None:
            continue

        score, short_side = _detail_score(image)

        if short_side < MIN_SOURCE_SHORT_SIDE:
            continue

        if score > best_score:
            best_score = score
            best = (url, image)

    return best


def _encode_card_webp(image: Image.Image):
    """
    Create one stable, optimized card image that every browser receives from
    our own app. This removes dependency on Linnateater/Piletilevi image
    loading during normal page use.
    """
    fitted = ImageOps.fit(
        image,
        (OUTPUT_WIDTH, OUTPUT_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    out = BytesIO()
    fitted.save(
        out,
        format="WEBP",
        quality=WEBP_QUALITY,
        method=6,
    )
    return out.getvalue(), fitted.size


def store_production_image(item):
    chosen = choose_best_source(
        item["title"],
        item["production_url"],
    )

    if not chosen:
        return False, item["title"], "no suitable source"

    source_url, image = chosen
    image_bytes, (width, height) = _encode_card_webp(image)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO production_image_store (
                    slug,
                    production_url,
                    title,
                    source_url,
                    image_bytes,
                    mime_type,
                    width,
                    height,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, 'image/webp', %s, %s, NOW())
                ON CONFLICT (slug)
                DO UPDATE SET
                    production_url=EXCLUDED.production_url,
                    title=EXCLUDED.title,
                    source_url=EXCLUDED.source_url,
                    image_bytes=EXCLUDED.image_bytes,
                    mime_type=EXCLUDED.mime_type,
                    width=EXCLUDED.width,
                    height=EXCLUDED.height,
                    updated_at=NOW()
                """,
                (
                    item["slug"],
                    item["production_url"],
                    item["title"],
                    source_url,
                    image_bytes,
                    width,
                    height,
                ),
            )

    return True, item["title"], f"{width}x{height}"


def refresh_all_production_media():
    """
    Refresh the complete image library.

    This is deliberately a once-daily maintenance task, not something that
    happens while the user is browsing.
    """
    productions = list_productions()

    ok = 0
    failed = 0

    for item in productions:
        try:
            success, title, info = store_production_image(item)

            if success:
                ok += 1
                print(
                    f"🖼 Stored production image: {title} ({info})",
                    flush=True,
                )
            else:
                failed += 1
                print(
                    f"⚠️ No production image stored: {title} ({info})",
                    flush=True,
                )

        except Exception as error:
            failed += 1
            print(
                f"⚠️ Production image failed: {item['title']} — "
                f"{type(error).__name__}: {error}",
                flush=True,
            )

    # Delete assets for productions that are no longer in the current
    # repertoire, so the database stays tidy.
    current_slugs = [item["slug"] for item in productions]

    if current_slugs:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM production_image_store
                    WHERE NOT (slug = ANY(%s))
                    """,
                    (current_slugs,),
                )

    return len(productions), ok, failed


def seconds_until_next_midnight():
    now = datetime.now(TZ)
    tomorrow = (now + timedelta(days=1)).date()
    target = datetime(
        tomorrow.year,
        tomorrow.month,
        tomorrow.day,
        0,
        0,
        0,
        tzinfo=TZ,
    )
    return max(60, int((target - now).total_seconds()))
