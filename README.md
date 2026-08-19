# Linnateater Tracker v3

This release fixes the three issues found in v2.

## Fixed

1. Missing performances
   - v2 scraped the generic Piletilevi organiser page.
   - v3 starts from the selected production's own Linnateater page and follows
     that production's Piletilevi event/series links.

2. Repeated date/time
   - v2 could read one date from a shared parent container.
   - v3 opens each unique concrete Piletilevi event URL and reads that event's
     own date/time, deduplicated by Piletilevi event code.

3. Missing production image
   - v3 uses OpenGraph, Twitter image, img/src, lazy-load attributes, srcset,
     CSS/JSON image URLs.
   - existing v1/v2 trackers with no image are automatically backfilled from
     their Piletilevi event page and/or matching Linnateater production page.

## Deploy

Replace the existing repository files with this ZIP's contents.

Do not delete PostgreSQL, create a new Railway project, or create new Twilio
services. Existing environment variables remain unchanged.

Web:
    /bin/sh -c "exec gunicorn app:app --bind 0.0.0.0:$PORT"

Worker:
    python -u worker.py
