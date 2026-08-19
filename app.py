import json
import os
import re
from datetime import timedelta
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
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_conn, init_db
from image_cache import get_cached_images
from performance_cache import get_cached_performances, save_cached_performances
from ticket_source import (
    list_performances,
    list_productions,
    page_image,
    production_image,
    tracker_image,
)


app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.permanent_session_lifetime = timedelta(days=30)

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


def validate_password(password: str):
    if len(password or "") < 8:
        raise ValueError("Parool peab olema vähemalt 8 tähemärki.")
    if len(password) > 128:
        raise ValueError("Parool on liiga pikk.")


def get_user_by_phone(phone):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, phone_number, password_hash, phone_verified_at
                FROM users
                WHERE phone_number=%s
                """,
                (phone,),
            )
            return cur.fetchone()


def send_verify_code(phone):
    twilio.verify.v2.services(
        TWILIO_VERIFY_SERVICE_SID
    ).verifications.create(to=phone, channel="sms")


def check_verify_code(phone, code):
    result = twilio.verify.v2.services(
        TWILIO_VERIFY_SERVICE_SID
    ).verification_checks.create(to=phone, code=code)
    return result.status == "approved"


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
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            phone = normalize_phone(request.form.get("phone", ""))
            password = request.form.get("password") or ""
            user = get_user_by_phone(phone)

            if not user:
                flash("Selle telefoninumbriga kontot ei leitud.", "error")
                return render_template("login.html", phone=phone)

            if not user.get("password_hash"):
                flash(
                    "Sellel varasemal kontol pole veel parooli. "
                    "Määra parool ühe SMS-kinnitusega.",
                    "notice",
                )
                return redirect(url_for("activate", phone=phone))

            if not check_password_hash(user["password_hash"], password):
                flash("Telefoninumber või parool on vale.", "error")
                return render_template("login.html", phone=phone)

            session.clear()
            session["user_id"] = user["id"]
            session.permanent = bool(request.form.get("remember"))
            return redirect(url_for("dashboard"))

        except Exception as e:
            flash(str(e), "error")

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            phone = normalize_phone(request.form.get("phone", ""))
            password = request.form.get("password") or ""
            password2 = request.form.get("password2") or ""

            validate_password(password)
            if password != password2:
                raise ValueError("Paroolid ei kattu.")

            existing = get_user_by_phone(phone)
            if existing and existing.get("password_hash"):
                flash(
                    "Selle telefoninumbriga konto on juba olemas. Logi sisse.",
                    "notice",
                )
                return redirect(url_for("login"))

            send_verify_code(phone)

            session["pending_auth"] = {
                "action": "signup",
                "phone": phone,
                # A password hash is safe to keep in the signed session; the
                # plaintext password never survives the request.
                "password_hash": generate_password_hash(password),
            }
            return redirect(url_for("verify"))

        except Exception as e:
            flash(f"Kontot ei saanud luua: {e}", "error")

    return render_template("signup.html")


@app.route("/activate", methods=["GET", "POST"])
def activate():
    """
    One-time migration path for users created in v1-v4.
    Their user row and trackers are retained; they only add a password.
    """
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    default_phone = request.args.get("phone", "")

    if request.method == "POST":
        try:
            phone = normalize_phone(request.form.get("phone", ""))
            password = request.form.get("password") or ""
            password2 = request.form.get("password2") or ""

            validate_password(password)
            if password != password2:
                raise ValueError("Paroolid ei kattu.")

            user = get_user_by_phone(phone)
            if not user:
                flash(
                    "Selle numbriga varasemat kontot ei leitud. Loo uus konto.",
                    "notice",
                )
                return redirect(url_for("signup"))

            if user.get("password_hash"):
                flash("Sellel kontol on parool juba olemas.", "notice")
                return redirect(url_for("login"))

            send_verify_code(phone)
            session["pending_auth"] = {
                "action": "activate",
                "phone": phone,
                "password_hash": generate_password_hash(password),
            }
            return redirect(url_for("verify"))

        except Exception as e:
            flash(f"Parooli määramine ebaõnnestus: {e}", "error")

    return render_template("activate.html", phone=default_phone)


@app.route("/verify", methods=["GET", "POST"])
def verify():
    pending = session.get("pending_auth")
    if not pending:
        return redirect(url_for("login"))

    phone = pending["phone"]
    action = pending["action"]

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()

        try:
            if not check_verify_code(phone, code):
                flash("Kood ei olnud õige.", "error")
                return render_template(
                    "verify.html",
                    phone=phone,
                    action=action,
                )

            if action in ("signup", "activate"):
                password_hash = pending.get("password_hash")
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO users (
                                phone_number,
                                password_hash,
                                phone_verified_at
                            )
                            VALUES (%s, %s, NOW())
                            ON CONFLICT (phone_number)
                            DO UPDATE SET
                                password_hash=EXCLUDED.password_hash,
                                phone_verified_at=NOW()
                            RETURNING id
                            """,
                            (phone, password_hash),
                        )
                        uid = cur.fetchone()["id"]

                session.clear()
                session["user_id"] = uid
                session.permanent = True
                flash("Konto on valmis.", "success")
                return redirect(url_for("dashboard"))

            if action == "reset":
                session.pop("pending_auth", None)
                session["reset_authorized_phone"] = phone
                return redirect(url_for("reset_password"))

            raise RuntimeError("Tundmatu kinnitustoiming.")

        except Exception as e:
            flash(f"Koodi kontroll ebaõnnestus: {e}", "error")

    return render_template("verify.html", phone=phone, action=action)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        try:
            phone = normalize_phone(request.form.get("phone", ""))
            user = get_user_by_phone(phone)

            # Generic message for non-existing users is safer, but for this
            # small private utility clear feedback is more useful.
            if not user:
                flash("Selle telefoninumbriga kontot ei leitud.", "error")
                return render_template("forgot_password.html", phone=phone)

            send_verify_code(phone)
            session["pending_auth"] = {
                "action": "reset",
                "phone": phone,
            }
            return redirect(url_for("verify"))

        except Exception as e:
            flash(f"Taastamiskoodi ei saanud saata: {e}", "error")

    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    phone = session.get("reset_authorized_phone")
    if not phone:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        try:
            password = request.form.get("password") or ""
            password2 = request.form.get("password2") or ""

            validate_password(password)
            if password != password2:
                raise ValueError("Paroolid ei kattu.")

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE users
                        SET password_hash=%s, phone_verified_at=NOW()
                        WHERE phone_number=%s
                        RETURNING id
                        """,
                        (generate_password_hash(password), phone),
                    )
                    row = cur.fetchone()

            if not row:
                raise RuntimeError("Kasutajat ei leitud.")

            session.clear()
            flash("Parool on muudetud. Logi nüüd sisse.", "success")
            return redirect(url_for("login"))

        except Exception as e:
            flash(f"Parooli ei saanud muuta: {e}", "error")

    return render_template("reset_password.html", phone=phone)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def load_user_trackers(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM trackers
                WHERE user_id=%s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return cur.fetchall()


def backfill_tracker_images(trackers):
    for tracker in trackers:
        if not tracker.get("image_url"):
            try:
                image_url, production_url = tracker_image(
                    tracker.get("title") or "",
                    tracker.get("event_url") or "",
                    tracker.get("production_url") or "",
                )
                if image_url:
                    tracker["image_url"] = image_url
                    if production_url:
                        tracker["production_url"] = production_url

                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE trackers
                                SET image_url=%s,
                                    production_url=COALESCE(NULLIF(%s, ''), production_url)
                                WHERE id=%s
                                """,
                                (
                                    image_url,
                                    production_url or "",
                                    tracker["id"],
                                ),
                            )
            except Exception:
                pass


@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    trackers = load_user_trackers(user["id"])

    try:
        productions = list_productions()
        productions_error = None
        cached_images = get_cached_images(productions)

        for production in productions:
            production["display_image_url"] = (
                production.get("image_url")
                or cached_images.get(production["production_url"], "")
            )
    except Exception as e:
        productions = []
        productions_error = str(e)

    remaining_slots = max(0, MAX_TRACKERS - len(trackers))

    return render_template(
        "dashboard.html",
        user=user,
        tracker_count=len(trackers),
        productions=productions,
        productions_error=productions_error,
        max_trackers=MAX_TRACKERS,
        remaining_slots=remaining_slots,
        can_add=remaining_slots > 0,
    )


@app.get("/my-trackers")
@login_required
def my_trackers():
    user = current_user()
    trackers = load_user_trackers(user["id"])
    backfill_tracker_images(trackers)

    return render_template(
        "my_trackers.html",
        user=user,
        trackers=trackers,
        tracker_count=len(trackers),
        max_trackers=MAX_TRACKERS,
    )


@app.get("/api/production-image")
@login_required
def api_production_image():
    production_url = (request.args.get("production_url") or "").strip()
    title = (request.args.get("title") or "").strip()

    if not production_url.startswith("https://linnateater.ee/"):
        return jsonify({"ok": False, "error": "Vigane lavastuse link."}), 400

    try:
        image = (
            production_image(title, production_url)
            if title
            else page_image(production_url)
        )
        return jsonify({
            "ok": True,
            "image_url": image,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.get("/api/performances")
@login_required
def api_performances():
    title = (request.args.get("title") or "").strip()
    production_url = (request.args.get("production_url") or "").strip()

    if not title or not production_url:
        return jsonify({"ok": False, "error": "Lavastus puudub."}), 400

    try:
        # Fast path: PostgreSQL cache populated in the background worker.
        cached = get_cached_performances(production_url)
        if cached is not None:
            return jsonify({
                "ok": True,
                "performances": cached,
                "cached": True,
            })

        # First-ever fallback only. Still just one Piletilevi series request.
        items = list_performances(title, production_url)
        save_cached_performances(title, production_url, items)

        return jsonify({
            "ok": True,
            "performances": items,
            "cached": False,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.post("/trackers")
@login_required
def add_tracker():
    user = current_user()
    title = (request.form.get("title") or "").strip()
    production_url = (request.form.get("production_url") or "").strip()
    image_url = (request.form.get("image_url") or "").strip()

    try:
        selected_codes = json.loads(
            request.form.get("selected_event_codes") or "[]"
        )
    except Exception:
        selected_codes = []

    if not isinstance(selected_codes, list):
        selected_codes = []

    normalized_codes = []
    seen = set()
    for value in selected_codes:
        code = str(value or "").strip().upper()
        if not code or code in seen:
            continue
        if not re.fullmatch(r"[A-Z0-9]+", code):
            continue
        seen.add(code)
        normalized_codes.append(code)

    if not title or not production_url or not normalized_codes:
        flash("Vali vähemalt üks kuupäev.", "error")
        return redirect(url_for("dashboard"))

    try:
        performances = list_performances(title, production_url)
        by_code = {
            str(item["event_code"]).upper(): item
            for item in performances
        }
        chosen = [by_code[code] for code in normalized_codes if code in by_code]

        if not chosen:
            flash(
                "Valitud etendusi ei õnnestunud Piletilevist kinnitada.",
                "error",
            )
            return redirect(url_for("dashboard"))

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_code FROM trackers WHERE user_id=%s",
                    (user["id"],),
                )
                existing_codes = {
                    str(row["event_code"]).upper() for row in cur.fetchall()
                }
                new_items = [
                    item for item in chosen
                    if str(item["event_code"]).upper() not in existing_codes
                ]
                remaining = max(0, MAX_TRACKERS - len(existing_codes))

                if len(new_items) > remaining:
                    flash(
                        f"Sul on ruumi veel {remaining} jälgimisele. Vali vähem kuupäevi.",
                        "error",
                    )
                    return redirect(url_for("dashboard"))

                added = 0
                for item in new_items:
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
                            user["id"], title, item["date_text"],
                            item["event_url"], item["series_url"],
                            item["event_code"], image_url, production_url,
                        ),
                    )
                    if cur.fetchone():
                        added += 1

        duplicates = len(chosen) - added
        if added == 1:
            flash("1 etendus lisati jälgimisse.", "success")
        elif added > 1:
            flash(f"{added} etendust lisati jälgimisse.", "success")
        elif duplicates:
            flash("Kõik valitud etendused olid juba jälgimisel.", "notice")

        if duplicates and added:
            flash(
                f"{duplicates} juba jälgimisel olnud etendust jäeti vahele.",
                "notice",
            )

    except Exception as e:
        flash(f"Jälgimisi ei saanud lisada: {e}", "error")

    return redirect(url_for("my_trackers"))


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
    return redirect(url_for("my_trackers"))


@app.get("/health")
def health():
    return {"ok": True}


init_db()
