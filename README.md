# Linnateater Tracker

A Railway-ready Linnateater/Piletilevi ticket availability monitor with Twilio SMS alerts.

## What it does

1. User logs in with a phone number.
2. Twilio Verify sends the login code.
3. User pastes a concrete Piletilevi performance URL.
4. The app resolves the related Piletilevi series automatically.
5. The worker checks the exact performance every 15–30 seconds.
6. When the performance is no longer marked **Välja müüdud**, Twilio sends an SMS with the purchase link.
7. The tracker is removed automatically after the SMS is submitted.

## Railway setup

Use one Railway project with PostgreSQL and two services from the same GitHub repo.

### Web service
Start command:

    gunicorn app:app --bind 0.0.0.0:$PORT

### Worker service
Start command:

    python -u worker.py

### Environment variables

Set the same variables on both services as relevant:

- `DATABASE_URL`
- `SECRET_KEY`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_VERIFY_SERVICE_SID`
- `TWILIO_MESSAGING_SERVICE_SID`
- `MIN_WAIT_SECONDS=15`
- `MAX_WAIT_SECONDS=30`
- `MAX_TRACKERS=10`

## Why no Playwright?

Unlike Praamid.ee, Piletilevi series pages expose each performance and its
"Välja müüdud" status in server-delivered HTML. So this version uses normal
HTTP requests instead of Chromium/Playwright. That makes each check much
lighter and avoids Chromium process accumulation/hanging.

## Test URL

A concrete performance URL has this shape:

    https://www.piletilevi.ee/piletid/S3PIGYZHGH/sinisilmsed

Do not paste only a general series page; paste the exact date/performance page.

## Important reliability behavior

The checker is deliberately conservative:
- if it cannot find the exact event on the series page, it records an error;
- it does **not** treat parsing failures as ticket availability;
- an SMS is sent only when the exact target event is found and it is not
  marked sold out/suspended;
- after a successful Twilio submission, the tracker is deleted.
