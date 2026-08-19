# Linnateater Tracker v23

Hotfix for v22 worker startup crash.

v22 accidentally still started the removed `image_cache_loop` thread, causing `NameError: image_cache_loop is not defined` immediately after container startup.

v23 removes that stale thread reference. The worker now starts only:
- `performance_cache_loop`
- `production_media_loop`
- the normal 15–30 second ticket-check cycle

All v22 PostgreSQL-stored WebP image functionality remains unchanged.


## New production-image architecture

v22 stops serving production-card images directly from Linnateater or
Piletilevi during normal browsing.

The actual optimized image files are stored in PostgreSQL as BYTEA.

For this app the scale is small (roughly a few dozen production images), so
PostgreSQL is a practical solution and avoids adding Railway Volume/S3 setup.

## Daily image workflow

The Railway worker starts a separate `production-media` background thread.

On startup:
1. read the current Linnateater productions;
2. inspect several high-resolution images from each production page;
3. choose a large suitable source;
4. crop/resize to one standard 900×1150 card;
5. encode as WebP quality 84;
6. store the actual WebP bytes in PostgreSQL.

After startup, the complete image library refreshes once per day at exactly
00:00 Europe/Tallinn time.

Productions removed from the current repertoire are removed from the stored
image library.

## Repertoire performance

The repertoire page itself:
- does not scrape Linnateater for card images;
- does not fetch Piletilevi images;
- does not run blur/resolution analysis;
- reads only metadata from PostgreSQL;
- displays `/media/production/<slug>.webp`.

The media response has a one-year immutable browser cache. The URL includes a
version timestamp, so a newly stored daily image automatically invalidates the
old browser cache.

## Why this should fix blurry cards

The old blurry cards came from Linnateater listing thumbnails.

v22 deliberately chooses images from the individual production page, creates
our own standardized WebP asset, and serves that same stored file every time.

Therefore cards such as:
- Alguses oli laul
- Esietendus
- Kolemees
- Krum

are no longer dependent on their listing-thumbnail file.

## Existing behavior retained

- v18 performance cache;
- multiple dates selectable at once;
- Repertuaar / Minu jälgimised;
- password login;
- Twilio SMS alerts;
- v21 clean Minu jälgimised page;
- approved login headline spacing.

## Deploy

Replace v21 files with this ZIP.

No new Railway Volume, S3 bucket, PostgreSQL service, or Twilio configuration
is needed.

After the new worker starts, watch for:

    🖼 Refreshing stored production images...
    🖼 Production image library ready: ...

The first run creates the whole PostgreSQL image library. After it completes,
hard-refresh the repertoire page once.
