# Linnateater Tracker v11

## Fix: blurry production images

Some production cards were still using lower-resolution thumbnail images from
the Linnateater listing page. That is why cards such as "Alguses oli laul" and
"Esietendus" could look blurry.

v11 changes the image priority:

1. high-resolution image from the individual Linnateater production page;
2. high-resolution fallback from the matching Piletilevi series page;
3. only if neither exists, the smaller listing thumbnail.

## Important deployment behavior

On the first v11 worker start, the image cache is refreshed with `force_all`,
so previously cached low-resolution image URLs are replaced with better ones.

That means:
- deploy v11;
- let the worker run for a moment;
- then hard refresh the browser.

After that, the sharper images should appear on the production cards.

## Other behavior unchanged

- multi-select dates in the modal;
- separate Repertuaar / Minu jälgimised views;
- phone + password login;
- Twilio SMS alerts.

## Deploy

Replace v10 files with this ZIP. Railway, PostgreSQL and Twilio settings stay
the same.
