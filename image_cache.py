from concurrent.futures import ThreadPoolExecutor, as_completed

from db import get_conn
from ticket_source import list_productions, production_image


def get_cached_images(productions):
    urls = [p['production_url'] for p in productions]
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
                result[row['production_url']] = row['image_url']
    return result


def refresh_production_images(max_workers=6):
    productions = list_productions()
    if not productions:
        return 0, 0

    by_url = {p['production_url']: p for p in productions}
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
                fresh[row['production_url']] = row['image_url']

    missing = [url for url in urls if url not in fresh]
    if not missing:
        return len(productions), 0

    def fetch_one(url):
        item = by_url[url]
        listed = item.get('image_url') or ''
        if listed:
            return url, listed
        try:
            return url, production_image(item['title'], item['production_url'])
        except Exception:
            return url, ''

    fetched = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(fetch_one, url) for url in missing]
        for future in as_completed(futures):
            url, image = future.result()
            fetched[url] = image

    with get_conn() as conn:
        with conn.cursor() as cur:
            for url, image in fetched.items():
                if not image:
                    continue
                cur.execute(
                    """
                    INSERT INTO production_image_cache (
                        production_url, image_url, updated_at
                    )
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (production_url)
                    DO UPDATE SET
                        image_url=EXCLUDED.image_url,
                        updated_at=NOW()
                    """,
                    (url, image),
                )

    return len(productions), sum(bool(x) for x in fetched.values())
