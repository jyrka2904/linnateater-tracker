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
        image = ImageOps.exif_transpose(original)

        # IMPORTANT: do not blindly convert RGBA/LA images to RGB. Doing so
        # can flatten transparent pixels to black and make a cut-out actor look
        # as if they were pasted onto a random dark background.
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            return image.convert("RGBA").copy()

        return image.convert("RGB").copy()


def _has_transparency(image: Image.Image) -> bool:
    if image.mode != "RGBA":
        return False

    alpha = image.getchannel("A")
    extrema = alpha.getextrema()
    return extrema[0] < 255


def _visual_fingerprint(image: Image.Image):
    """
    Conservative perceptual fingerprint used only to answer one question:
    "is this essentially the same artwork/photo as the repertoire thumbnail?"

    We deliberately prefer false negatives over false positives. If a larger
    candidate is not clearly the same visual, we keep the repertoire image.
    """
    # Flatten alpha onto a neutral light canvas *only for comparison*.
    if image.mode == "RGBA":
        canvas = Image.new("RGBA", image.size, (239, 237, 232, 255))
        canvas.alpha_composite(image)
        compare = canvas.convert("RGB")
    else:
        compare = image.convert("RGB")

    # Normalize framing. This tolerates normal resizing and mild cropping but
    # strongly penalizes a different background/artwork.
    compare = ImageOps.fit(
        compare,
        (32, 32),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    ).convert("L")

    pixels = list(compare.getdata())
    avg = sum(pixels) / len(pixels)
    bits = tuple(1 if value >= avg else 0 for value in pixels)
    return bits


def _fingerprint_distance(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 1.0
    diff = sum(x != y for x, y in zip(a, b))
    return diff / len(a)


def _detail_score(image: Image.Image):
    width, height = image.size
    return width * height, min(width, height)


def choose_best_source(item):
    """
    The repertoire thumbnail is the visual source of truth.

    A production-page candidate may replace it ONLY when it is confidently
    the same visual and genuinely larger. Otherwise the listing image itself
    is stored. This prevents future background/artwork substitutions.
    """
    reference_url = item.get("image_url") or ""
    if not reference_url:
        return None

    try:
        reference = _download_image(reference_url)
    except Exception:
        return None

    if reference is None:
        return None

    reference_fp = _visual_fingerprint(reference)
    reference_area, _ = _detail_score(reference)
    reference_transparency = _has_transparency(reference)

    best_url = reference_url
    best_image = reference
    best_area = reference_area

    for candidate_url in production_page_image_candidates(
        item["title"],
        item["production_url"],
        limit=18,
    ):
        if not candidate_url or candidate_url == reference_url:
            continue

        try:
            candidate = _download_image(candidate_url)
        except Exception:
            continue

        if candidate is None:
            continue

        # Do not substitute a cut-out/transparent artwork for a normal photo,
        # or vice versa. That is exactly the class of visual change we want to
        # rule out.
        if _has_transparency(candidate) != reference_transparency:
            continue

        distance = _fingerprint_distance(
            reference_fp,
            _visual_fingerprint(candidate),
        )

        # 10% bit difference is intentionally strict. If we are not sure it is
        # the same visual, we keep the repertoire thumbnail.
        if distance > 0.10:
            continue

        candidate_area, candidate_short = _detail_score(candidate)
        if candidate_short < MIN_SOURCE_SHORT_SIDE:
            continue

        if candidate_area > best_area * 1.20:
            best_url = candidate_url
            best_image = candidate
            best_area = candidate_area

    return best_url, best_image


def _encode_card_webp(image: Image.Image):
    """
    Standardized card image. Alpha is preserved instead of being flattened to
    black. ImageOps.fit only crops/resizes; it never invents a new background.
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
    chosen = choose_best_source(item)

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
