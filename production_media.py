from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageOps

from db import get_conn
from ticket_source import list_productions


TZ = ZoneInfo("Europe/Tallinn")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

DOWNLOAD_TIMEOUT = 20
MAX_LONG_SIDE = 1800
WEBP_QUALITY = 88


def get_media_manifest():
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


def _download_listing_image(url: str):
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
        image = ImageOps.exif_transpose(original)

        # Preserve alpha exactly. Never flatten a cut-out onto black, white,
        # beige or any other newly invented background.
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            return image.convert("RGBA").copy()

        return image.convert("RGB").copy()


def _encode_listing_image(image: Image.Image):
    """
    Preserve the exact repertoire artwork and aspect ratio.

    There is deliberately NO ImageOps.fit(), background fill, crop, visual
    comparison, or production-page fallback. The only allowed operation is a
    proportional downscale if the source is exceptionally large.
    """
    width, height = image.size
    long_side = max(width, height)

    if long_side > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / long_side
        image = image.resize(
            (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )

    out = BytesIO()
    image.save(
        out,
        format="WEBP",
        quality=WEBP_QUALITY,
        method=6,
    )
    return out.getvalue(), image.size


def store_production_image(item):
    # CRITICAL RULE: this URL comes from the repertoire card itself.
    # There is no fallback to production-page/gallery/Piletilevi artwork.
    source_url = item.get("image_url") or ""

    if not source_url:
        return False, item["title"], "repertoire card has no image"

    image = _download_listing_image(source_url)
    if image is None:
        return False, item["title"], "repertoire image download failed"

    image_bytes, (width, height) = _encode_listing_image(image)

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

    return True, item["title"], f"{width}x{height} exact repertoire artwork"


def refresh_all_production_media():
    """
    Rewrite the whole stored image library from the CURRENT repertoire cards.

    The startup run therefore also repairs any previously stored alternative
    artwork/backgrounds from older versions.
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
                    f"🖼 Stored exact repertoire image: {title} ({info})",
                    flush=True,
                )
            else:
                failed += 1
                print(
                    f"⚠️ Repertoire image not stored: {title} ({info})",
                    flush=True,
                )

        except Exception as error:
            failed += 1
            print(
                f"⚠️ Production image failed: {item['title']} — "
                f"{type(error).__name__}: {error}",
                flush=True,
            )

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
