import os
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from twilio.rest import Client

from db import get_conn, init_db
from ticket_source import check_event


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
                SELECT
                    t.*,
                    u.phone_number
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
                SET
                    last_checked_at=NOW(),
                    last_error=%s
                WHERE id=%s
                """,
                (str(error)[:900], tid),
            )


def build_sms(t):
    date_line = f"\n{t['date_text']}" if t.get("date_text") else ""
    return (
        "🎭 Linnateatri pilet on saadaval!\n"
        f"{t['title']}"
        f"{date_line}\n\n"
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

    print(
        f"🗑 Tracker #{t['id']} removed after alert.",
        flush=True,
    )


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
                f"→ #{t['id']} | {t['title']} | "
                f"{t.get('date_text') or t['event_code']} | {status}",
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


def main():
    init_db()
    print("Linnateater worker started", flush=True)
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
