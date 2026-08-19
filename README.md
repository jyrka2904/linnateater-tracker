# Linnateater Tracker v19

Built directly on v18.

## Goal

Keep the fast v10/v18 repertoire behavior, but automatically replace ONLY
production thumbnails that are physically too small.

## How image quality is detected

The Railway worker downloads the image in its own background thread and reads
its actual pixel dimensions with Pillow.

The default lightweight Linnateater listing thumbnail is kept when its shorter
side is at least 650 px.

If the thumbnail is smaller:
1. fetch a larger image candidate from the individual Linnateater production
   page;
2. use it only if it is large enough or has at least 1.5x the pixel area;
3. cache the chosen URL in PostgreSQL.

This means normal sharp thumbnails stay lightweight, while cards such as a
small/blurred source can automatically receive a better image.

## No web-page lag from quality checking

Dimension probing and fallback discovery run in a dedicated daemon thread in
the Railway worker.

They are NOT executed:
- in the repertoire HTTP request;
- when opening a production;
- in the 15–30 second active ticket-monitor cycle.

The first v19 worker run checks every production once so existing cached small
images can be repaired. Later checks happen every 6 hours and normal cache
behavior resumes.

## New dependency

Pillow is included only so the background worker can read image dimensions.

## Existing v18 features retained

- PostgreSQL performance cache;
- fast modal dates;
- added Piletilevi series mappings;
- multiple dates selectable at once;
- Repertuaar / Minu jälgimised;
- password login;
- Twilio SMS alerts;
- approved login-page headline spacing.

## Deploy

Replace v18 files with this ZIP. No Railway, PostgreSQL or Twilio settings need
to change.

After deployment, worker logs may show entries such as:

    🖼 Upgraded small thumbnail: Alguses oli laul → (1200, 1600)

Only productions whose lightweight image is actually too small should be
upgraded.
