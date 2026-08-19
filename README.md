# Linnateater Tracker v20

Built directly on v19.

## Why v19 did not fix all blurry cards

The affected image files are not necessarily small. A 1000+ px image can still
be visually blurred/soft, so dimension checks alone cannot identify the
problem.

## v20: actual sharpness detection

The Railway worker now measures two things:

1. physical image dimensions;
2. edge-detail variance (approximate visual sharpness).

A lightweight repertoire thumbnail is used immediately when it is both large
enough and sharp enough.

If it is large but measurably blurry:
- fetch several alternative images from that production's Linnateater page;
- score them by sharpness and dimensions;
- select a meaningfully better candidate;
- persist only that URL in PostgreSQL.

The normal repertoire HTTP request still performs NONE of this work.

## Performance characteristics

All quality analysis stays inside the dedicated image-cache background thread.

It does not block:
- repertoire page rendering;
- opening a production modal;
- the 15–30 second ticket-monitor cycle;
- the performance-cache background thread.

Only blurry/small thumbnails trigger inspection of multiple alternatives.

## First deploy

The first v20 worker run force-rechecks all current production images so old
v19 cache choices can be replaced.

Worker logs will show messages such as:

    🖼 Replaced blurry thumbnail: Krum → 1200x1600
       (sharpness 420.3; 3 alternatives checked)

## Existing features retained

Everything from v18/v19 remains, including:
- fast PostgreSQL performance cache;
- multiple dates in one modal;
- current Piletilevi series mappings;
- Repertuaar / Minu jälgimised;
- password login;
- Twilio SMS alerts;
- approved login headline spacing.

## Deploy

Replace v19 files with this ZIP. Railway, PostgreSQL and Twilio settings remain
unchanged.
