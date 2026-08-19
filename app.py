import os
import re
from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from twilio.rest import Client

from db import get_conn, init_db
from ticket_source import resolve_event


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
            ).verifications.create(
                to=phone,
                channel="sms",
            )
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
            ).verification_checks.create(
                to=phone,
                code=code,
            )
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

    return render_template(
        "dashboard.html",
        user=user,
        trackers=trackers,
        max_trackers=MAX_TRACKERS,
        can_add=len(trackers) < MAX_TRACKERS,
    )


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

    try:
        info = resolve_event(request.form.get("event_url", ""))

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trackers (
                        user_id, title, date_text, event_url,
                        series_url, event_code
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, event_code) DO NOTHING
                    RETURNING id
                    """,
                    (
                        user["id"],
                        info.title,
                        info.date_text,
                        info.event_url,
                        info.series_url,
                        info.event_code,
                    ),
                )
                row = cur.fetchone()

        if row:
            flash(
                f"Jälgimine lisatud: {info.title} {info.date_text}".strip(),
                "success",
            )
        else:
            flash("Seda etendust sa juba jälgid.", "error")

    except Exception as e:
        flash(f"Etendust ei saanud lisada: {e}", "error")

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
