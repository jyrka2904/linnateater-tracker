import os
import re
from functools import wraps

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from twilio.rest import Client

from db import get_conn, init_db
from ticket_source import list_performances, list_productions


app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_VERIFY_SERVICE_SID = os.environ["TWILIO_VERIFY_SERVICE_SID"]

twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
MAX_TRACKERS = int(os.environ.get("MAX_TRACKERS", "10"))


def normalize_phone(value: str) -> str:
    value = re.sub(r"[^\d+]", "", (value or "").strip())
    if value.startswith("00"):
        value = "+" + value[2:]
    if not value.startswith("+"):
        raise ValueError("Kasuta telefoninumbrit kujul +372...")
    if len(re.sub(r"\D", "", value)) < 7:
        raise ValueError("Telefoninumber tundub liiga lühike.")
    return value


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, phone_number FROM users WHERE id=%s",
                (uid,),
            )
            return cur.fetchone()


@app.get("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            phone = normalize_phone(request.form.get("phone", ""))
            twilio.verify.v2.services(
                TWILIO_VERIFY_SERVICE_SID
            ).verifications.create(to=phone, channel="sms")
            session["pending_phone"] = phone
            return redirect(url_for("verify"))
        except Exception as e:
            flash(f"SMS-koodi saatmine ebaõnnestus: {e}", "error")
    return render_template("login.html")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    phone = session.get("pending_phone")
    if not phone:
        return redirect(url_for("login"))

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        try:
            check = twilio.verify.v2.services(
                TWILIO_VERIFY_SERVICE_SID
            ).verification_checks.create(to=phone, code=code)

            if check.status != "approved":
                flash("Kood ei olnud õige.", "error")
                return render_template("verify.html", phone=phone)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (phone_number)
                        VALUES (%s)
                        ON CONFLICT (phone_number)
                        DO UPDATE SET phone_number=EXCLUDED.phone_number
                        RETURNING id
                        """,
                        (phone,),
                    )
                    uid = cur.fetchone()["id"]

            session.clear()
            session["user_id"] = uid
            return redirect(url_for("dashboard"))

        except Exception as e:
            flash(f"Koodi kontroll ebaõnnestus: {e}", "error")

    return render_template("verify.html", phone=phone)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM trackers
                WHERE user_id=%s
                ORDER BY created_at DESC
                """,
                (user["id"],),
            )
            trackers = cur.fetchall()

    try:
        productions = list_productions()
        productions_error = None
    except Exception as e:
        productions = []
        productions_error = str(e)

    return render_template(
        "dashboard.html",
        user=user,
        trackers=trackers,
        productions=productions,
        productions_error=productions_error,
        max_trackers=MAX_TRACKERS,
        can_add=len(trackers) < MAX_TRACKERS,
    )


@app.get("/api/performances")
@login_required
def api_performances():
    title = (request.args.get("title") or "").strip()
    production_url = (request.args.get("production_url") or "").strip()

    if not title or not production_url:
        return jsonify({"ok": False, "error": "Lavastus puudub."}), 400

    try:
        items = list_performances(title, production_url)
        return jsonify({"ok": True, "performances": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.post("/trackers")
@login_required
def add_tracker():
    user = current_user()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM trackers WHERE user_id=%s",
                (user["id"],),
            )
            if cur.fetchone()["n"] >= MAX_TRACKERS:
                flash("Aktiivsete jälgimiste limiit on täis.", "error")
                return redirect(url_for("dashboard"))

    event_url = (request.form.get("event_url") or "").strip()
    event_code = (request.form.get("event_code") or "").strip().upper()
    series_url = (request.form.get("series_url") or "").strip()
    title = (request.form.get("title") or "").strip()
    date_text = (request.form.get("date_text") or "").strip()
    image_url = (request.form.get("image_url") or "").strip()
    production_url = (request.form.get("production_url") or "").strip()

    if not all([event_url, event_code, series_url, title, date_text]):
        flash("Etenduse info oli puudulik. Vali etendus uuesti.", "error")
        return redirect(url_for("dashboard"))

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trackers (
                        user_id, title, date_text, event_url,
                        series_url, event_code, image_url, production_url
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, event_code) DO NOTHING
                    RETURNING id
                    """,
                    (
                        user["id"],
                        title,
                        date_text,
                        event_url,
                        series_url,
                        event_code,
                        image_url,
                        production_url,
                    ),
                )
                row = cur.fetchone()

        if row:
            flash(f"Jälgimine lisatud: {title} · {date_text}", "success")
        else:
            flash("Seda etendust sa juba jälgid.", "error")

    except Exception as e:
        flash(f"Jälgimist ei saanud lisada: {e}", "error")

    return redirect(url_for("dashboard"))


@app.post("/trackers/<int:tracker_id>/delete")
@login_required
def delete_tracker(tracker_id):
    user = current_user()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trackers WHERE id=%s AND user_id=%s",
                (tracker_id, user["id"]),
            )
    flash("Jälgimine eemaldatud.", "success")
    return redirect(url_for("dashboard"))


@app.get("/health")
def health():
    return {"ok": True}


init_db()
