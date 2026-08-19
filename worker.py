import os
import random
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from twilio.rest import Client

from db import get_conn, init_db
from ticket_source import check_event
from performance_cache import refresh_all_performances
from production_media import refresh_all_production_media, seconds_until_next_midnight


TZ = ZoneInfo("Europe/Tallinn")
MIN_WAIT = int(os.environ.get("MIN_WAIT_SECONDS", "15"))
MAX_WAIT = int(os.environ.get("MAX_WAIT_SECONDS", "30"))

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_MESSAGING_SERVICE_SID = os.environ[
    "TWILIO_MESSAGING_SERVICE_SID"
]

twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)



def get_trackers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.*, u.phone_number
                FROM trackers t
                JOIN users u ON u.id=t.user_id
                ORDER BY t.id
                """
            )
            return cur.fetchall()


def update_result(tid, available, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trackers
                SET
                    last_checked_at=NOW(),
                    last_available=%s,
                    last_status=%s,
                    last_error=NULL
                WHERE id=%s
                """,
                (available, status, tid),
            )


def mark_error(tid, error):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE trackers
                SET last_checked_at=NOW(), last_error=%s
                WHERE id=%s
                """,
                (str(error)[:900], tid),
            )


def build_sms(t):
    return (
        "🎭 Linnateatri pilet on saadaval!\n"
        f"{t['title']}\n"
        f"{t['date_text']}\n\n"
        "Osta kohe:\n"
        f"{t['event_url']}\n\n"
        "Jälgimine eemaldati automaatselt."
    )


def send_and_remove(t):
    msg = twilio.messages.create(
        to=t["phone_number"],
        messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
        body=build_sms(t),
    )
    print(
        f"📲 SMS submitted to Twilio | tracker #{t['id']} | SID {msg.sid}",
        flush=True,
    )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM trackers WHERE id=%s", (t["id"],))

    print(f"🗑 Tracker #{t['id']} removed after alert.", flush=True)


def production_media_loop():
    """
    Build the image library on worker startup, then refresh it every day at
    00:00 Europe/Tallinn time.
    """
    while True:
        print(
            "🖼 Refreshing stored production images...",
            flush=True,
        )

        try:
            total, ok, failed = refresh_all_production_media()

            print(
                f"🖼 Production image library ready: "
                f"{ok}/{total} stored, {failed} failed.",
                flush=True,
            )
        except Exception as error:
            print(
                f"⚠️ Production image library refresh failed: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )

        wait = seconds_until_next_midnight()

        print(
            f"🖼 Next production image refresh at 00:00 "
            f"({wait // 3600}h {(wait % 3600) // 60}m).",
            flush=True,
        )

        time.sleep(wait)


def run_cycle():
    trackers = get_trackers()
    print("", flush=True)
    print("=" * 72, flush=True)
    print(
        "Linnateater check cycle started: "
        + datetime.now(TZ).strftime("%d.%m.%Y %H:%M:%S"),
        flush=True,
    )
    print(f"Active trackers: {len(trackers)}", flush=True)

    for t in trackers:
        try:
            available, status = check_event(
                t["series_url"],
                t["event_code"],
            )
            update_result(t["id"], available, status)

            print(
                f"→ #{t['id']} | {t['title']} | {t['date_text']} | {status}",
                flush=True,
            )

            if available:
                send_and_remove(t)

        except Exception as e:
            mark_error(t["id"], e)
            print(
                f"❌ Tracker #{t['id']} error: "
                f"{type(e).__name__}: {e}",
                flush=True,
            )

    print("Check cycle finished.", flush=True)
    print("=" * 72, flush=True)


def performance_cache_loop():
    """
    Keep the modal data warm without ever blocking normal ticket checks.
    """
    while True:
        print("🎟 Refreshing performance cache in background...", flush=True)
        try:
            refreshed, item_count = refresh_all_performances(max_workers=6)
            print(
                f"🎟 Performance cache ready: "
                f"{refreshed} productions / {item_count} performances.",
                flush=True,
            )
        except Exception as error:
            print(
                f"⚠️ Performance cache refresh failed: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )

        time.sleep(5 * 60)


def main():
    init_db()
    print("Linnateater worker started", flush=True)

    threading.Thread(
        target=performance_cache_loop,
        name="performance-cache",
        daemon=True,
    ).start()

    threading.Thread(
        target=production_media_loop,
        name="production-media",
        daemon=True,
    ).start()

    threading.Thread(
        target=image_cache_loop,
        name="image-cache",
        daemon=True,
    ).start()
    print(
        f"Pause between completed cycles: {MIN_WAIT}–{MAX_WAIT} seconds",
        flush=True,
    )

    while True:
        try:
            run_cycle()
        except Exception as e:
            print(
                f"❌ Unexpected cycle error: {type(e).__name__}: {e}",
                flush=True,
            )

        wait = random.randint(MIN_WAIT, MAX_WAIT)
        print(f"Next full cycle in {wait}s", flush=True)
        time.sleep(wait)


if __name__ == "__main__":
    main()
