import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from db import get_conn
from ticket_source import list_performances, list_productions


REFRESH_SECONDS = 5 * 60


def get_cached_performances(production_url: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT payload, updated_at
                FROM performance_cache
                WHERE production_url=%s
                """,
                (production_url,),
            )
            row = cur.fetchone()

    if not row:
        return None

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload


def save_cached_performances(title: str, production_url: str, items):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO performance_cache (
                    production_url, title, payload, updated_at
                )
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (production_url)
                DO UPDATE SET
                    title=EXCLUDED.title,
                    payload=EXCLUDED.payload,
                    updated_at=NOW()
                """,
                (
                    production_url,
                    title,
                    json.dumps(items, ensure_ascii=False),
                ),
            )


def refresh_one(title: str, production_url: str):
    items = list_performances(title, production_url)
    save_cached_performances(title, production_url, items)
    return len(items)


def refresh_all_performances(max_workers=6):
    productions = list_productions()
    if not productions:
        return 0, 0

    refreshed = 0
    total_items = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                refresh_one,
                item["title"],
                item["production_url"],
            ): item
            for item in productions
        }

        for future in as_completed(futures):
            try:
                count = future.result()
                refreshed += 1
                total_items += count
            except Exception:
                # A production without a current Piletilevi series must not
                # prevent the rest of the cache from becoming available.
                pass

    return refreshed, total_items
