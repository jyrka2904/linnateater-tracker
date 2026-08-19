from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import requests
from PIL import Image

from db import get_conn
from ticket_source import (
    list_productions,
    production_image,
    production_image_fallback,
)


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

# Cards are commonly rendered at ~300-350 CSS px wide.
# A ~650 px short side gives a useful 2x-ish source without switching every
# production to giant full-resolution artwork.
MIN_SHORT_SIDE = 650
IMAGE_TIMEOUT = 15


def get_cached_images(productions):
    urls = [p["production_url"] for p in productions]
    if not urls:
        return {}

    result = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT production_url, image_url
                FROM production_image_cache
                WHERE production_url = ANY(%s)
                  AND image_url <> ''
                """,
                (urls,),
            )
            for row in cur.fetchall():
                result[row["production_url"]] = row["image_url"]
    return result


def image_dimensions(image_url: str):
    """
    Download the image in the BACKGROUND WORKER and read its actual dimensions.

    This never runs inside the repertoire web request.
    """
    if not image_url:
        return None

    try:
        response = requests.get(
            image_url,
            timeout=IMAGE_TIMEOUT,
            headers={"User-Agent": UA},
        )
        response.raise_for_status()

        with Image.open(BytesIO(response.content)) as img:
            width, height = img.size
            return int(width), int(height)

    except Exception:
        return None


def is_large_enough(dimensions):
    if not dimensions:
        return False

    width, height = dimensions
    return min(width, height) >= MIN_SHORT_SIDE


def pixel_area(dimensions):
    if not dimensions:
        return 0
    return dimensions[0] * dimensions[1]


def choose_image(item):
    """
    Keep the v10 lightweight thumbnail when it is large enough.

    Only a physically small thumbnail triggers one extra lookup for this
    production. If the fallback is actually better, cache that instead.
    """
    listed = item.get("image_url") or ""

    if listed:
        listed_dims = image_dimensions(listed)

        if is_large_enough(listed_dims):
            return listed, listed_dims, "listing"

        # Thumbnail is genuinely small (or unreadable): inspect a larger source.
        fallback = production_image_fallback(
            item["title"],
            item["production_url"],
        )

        if fallback and fallback != listed:
            fallback_dims = image_dimensions(fallback)

            # Use the fallback only when it has meaningfully more pixels.
            if (
                is_large_enough(fallback_dims)
                or pixel_area(fallback_dims) > pixel_area(listed_dims) * 1.5
            ):
                return fallback, fallback_dims, "fallback"

        # If no better source exists, keep the lightweight image rather than
        # leaving the card blank.
        return listed, listed_dims, "listing-small"

    # No listing image at all: use the existing layered fallback.
    image = production_image(
        item["title"],
        item["production_url"],
    )
    return image, image_dimensions(image), "fallback-only"


def refresh_production_images(max_workers=6, force_all=False):
    productions = list_productions()
    if not productions:
        return 0, 0, 0

    by_url = {p["production_url"]: p for p in productions}
    urls = list(by_url)

    fresh = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT production_url, image_url
                FROM production_image_cache
                WHERE production_url = ANY(%s)
                  AND image_url <> ''
                  AND updated_at > NOW() - INTERVAL '30 days'
                """,
                (urls,),
            )
            for row in cur.fetchall():
                fresh[row["production_url"]] = row["image_url"]

    targets = urls if force_all else [url for url in urls if url not in fresh]

    if not targets:
        return len(productions), 0, 0

    def fetch_one(url):
        item = by_url[url]
        try:
            image, dims, source = choose_image(item)
            return url, image, dims, source
        except Exception:
            return url, "", None, "error"

    fetched = {}
    upgraded = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fetch_one, url) for url in targets]

        for future in as_completed(futures):
            url, image, dims, source = future.result()
            fetched[url] = image

            if source == "fallback":
                upgraded += 1
                print(
                    f"🖼 Upgraded small thumbnail: "
                    f"{by_url[url]['title']} → {dims}",
                    flush=True,
                )

    with get_conn() as conn:
        with conn.cursor() as cur:
            for url, image in fetched.items():
                if not image:
                    continue

                cur.execute(
                    """
                    INSERT INTO production_image_cache (
                        production_url,
                        image_url,
                        updated_at
                    )
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (production_url)
                    DO UPDATE SET
                        image_url=EXCLUDED.image_url,
                        updated_at=NOW()
                    """,
                    (url, image),
                )

    resolved = sum(bool(image) for image in fetched.values())
    return len(productions), resolved, upgraded
