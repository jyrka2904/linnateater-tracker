# Linnateater Tracker v2

## v2 changes

- No Piletilevi URL needs to be pasted manually.
- The dashboard first loads Tallinna Linnateater productions.
- Selecting a production loads its future Piletilevi performances.
- User selects the exact date/time to monitor.
- Each active tracker displays the production image from Linnateater.
- The UI has been redesigned in a theatre/editorial style inspired by
  Tallinna Linnateater's visual language.
- Existing v1 database is migrated automatically by `ALTER TABLE ... IF NOT EXISTS`.
- Existing Railway/Twilio environment variables remain the same.

## Replace v1

Upload the contents of this ZIP to the existing GitHub repository and replace
the matching files. Do not delete the Railway PostgreSQL database and do not
create a new Twilio setup.

Web Start Command:
    /bin/sh -c "exec gunicorn app:app --bind 0.0.0.0:$PORT"

Worker Start Command:
    python -u worker.py

## Data sources

Production names and production images:
    https://linnateater.ee/lavastused/

Performance dates, event links and availability:
    https://www.piletilevi.ee/korraldajad/21-69-257/tallinna-linnateater

Ticket availability checks continue against Piletilevi.
