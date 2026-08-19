from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import requests
from PIL import Image, ImageFilter, ImageStat

from db import get_conn
from ticket_source import (
    list_productions,
    production_image,
    production_page_image_candidates,
)


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

MIN_SHORT_SIDE = 650

# Edge-variance score after normalizing the image down to at most 600 px.
# Very soft/blurred images produce much less high-frequency edge detail.
MIN_SHARPNESS = 170.0

IMAGE_TIMEOUT = 15
MAX_SCORE_SIDE = 600


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


def inspect_image(image_url: str):
    """
    Return dimensions + an approximate sharpness score.

    Runs only in the Railway worker background thread.
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

        with Image.open(BytesIO(response.content)) as source:
            source.load()

            width, height = source.size
            image = source.convert("L")

            # Normalize scoring size so a giant file does not automatically
            # receive a larger score simply because it has more pixels.
            max_side = max(image.size)
            if max_side > MAX_SCORE_SIDE:
                scale = MAX_SCORE_SIDE / max_side
                image = image.resize(
                    (
                        max(1, int(image.width * scale)),
                        max(1, int(image.height * scale)),
                    ),
                    Image.Resampling.LANCZOS,
                )

            # FIND_EDGES is cheap and works well enough here: blurry artwork has
            # a much flatter edge map than a crisp photograph.
            edges = image.filter(ImageFilter.FIND_EDGES)
            stats = ImageStat.Stat(edges)

            # Variance of edge intensity. Higher = more fine detail/sharpness.
            sharpness = float(stats.var[0])

            return {
                "width": int(width),
                "height": int(height),
                "short_side": int(min(width, height)),
                "area": int(width * height),
                "sharpness": sharpness,
            }

    except Exception:
        return None


def is_good_card_image(info):
    if not info:
        return False

    return (
        info["short_side"] >= MIN_SHORT_SIDE
        and info["sharpness"] >= MIN_SHARPNESS
    )


def candidate_score(info):
    if not info:
        return -1.0

    # Sharpness is most important once minimum usable dimensions are reached.
    dimension_bonus = min(info["short_side"], 1400) / 10.0
    return info["sharpness"] * 3.0 + dimension_bonus


def best_alternative(item, current_url, current_info):
    """
    Inspect a small number of production-page candidates only when necessary.
    """
    best_url = current_url
    best_info = current_info
    best_score = candidate_score(current_info)

    candidates = production_page_image_candidates(
        item["title"],
        item["production_url"],
        limit=10,
    )

    inspected = 0

    for url in candidates:
        if not url or url == current_url:
            continue

        info = inspect_image(url)
        inspected += 1

        if not info:
            continue

        # Ignore tiny images/headshots/icons regardless of edge score.
        if info["short_side"] < MIN_SHORT_SIDE:
            continue

        score = candidate_score(info)

        if score > best_score:
            best_url = url
            best_info = info
            best_score = score

        # A clearly crisp image lets us stop early and avoids needless remote
        # downloads. The threshold is intentionally above the minimum.
        if (
            info["sharpness"] >= MIN_SHARPNESS * 1.7
            and info["short_side"] >= 900
        ):
            break

    return best_url, best_info, inspected


def choose_image(item):
    """
    Default to the fast v10 listing image.

    Only images that are physically too small OR measurably blurry trigger
    production-page candidate inspection.
    """
    listed = item.get("image_url") or ""

    if listed:
        listed_info = inspect_image(listed)

        if is_good_card_image(listed_info):
            return listed, listed_info, "listing", 0

        better_url, better_info, inspected = best_alternative(
            item,
            listed,
            listed_info,
        )

        if (
            better_url
            and better_url != listed
            and candidate_score(better_info) > candidate_score(listed_info) * 1.15
        ):
            return better_url, better_info, "upgraded", inspected

        return listed, listed_info, "listing-soft", inspected

    image = production_image(
        item["title"],
        item["production_url"],
    )

    return image, inspect_image(image), "fallback-only", 0


def refresh_production_images(max_workers=4, force_all=False):
    productions = list_productions()

    if not productions:
        return 0, 0, 0

    by_url = {
        p["production_url"]: p
        for p in productions
    }
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

    targets = (
        urls
        if force_all
        else [url for url in urls if url not in fresh]
    )

    if not targets:
        return len(productions), 0, 0

    def fetch_one(url):
        item = by_url[url]

        try:
            image, info, source, inspected = choose_image(item)
            return url, image, info, source, inspected
        except Exception:
            return url, "", None, "error", 0

    fetched = {}
    upgraded = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(fetch_one, url)
            for url in targets
        ]

        for future in as_completed(futures):
            url, image, info, source, inspected = future.result()
            fetched[url] = image

            if source == "upgraded":
                upgraded += 1

                print(
                    "🖼 Replaced blurry thumbnail: "
                    f"{by_url[url]['title']} → "
                    f"{info['width']}x{info['height']} "
                    f"(sharpness {info['sharpness']:.1f}; "
                    f"{inspected} alternatives checked)",
                    flush=True,
                )

            elif source == "listing-soft":
                print(
                    "🖼 No clearly better image found: "
                    f"{by_url[url]['title']} "
                    f"(sharpness "
                    f"{(info['sharpness'] if info else 0):.1f})",
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

    resolved = sum(
        bool(image)
        for image in fetched.values()
    )

    return len(productions), resolved, upgraded
