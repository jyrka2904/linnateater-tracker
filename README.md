# Linnateater Tracker v9

## Fix: fake "Lavastused A-Z" production

The production parser now reads only real production title links inside H2
elements on Linnateater's productions page.

Navigation/actions such as:
- Lavastused A-Z
- Uuemad eespool
- Liitu uudiskirjaga
- Lavastuste arhiiv

can no longer enter the tracker repertoire.

## Fix: more complete production images

Image resolution now uses layered fallbacks:

1. image already embedded in the Linnateater production-list card;
2. individual Linnateater production page;
3. matching Piletilevi series page.

Additional HTML image forms are supported:
- `<source srcset>`
- lazy-loading attributes
- data-background/data-image attributes
- CSS/background URLs

Results are saved in the existing PostgreSQL image cache.

Important: v9 retries cache rows whose previous image value was empty, so the
grey cards created by v8 can repair themselves after deployment.

## Deploy

Replace v8 repository files with this ZIP.
No Railway/Twilio/PostgreSQL configuration changes are required.
