# Linnateater Tracker v7

Built on v6.

## Repertoire images without lag

v7 no longer opens each individual production page to discover card images.

Instead, `list_productions()` extracts a thumbnail from the SAME Linnateater
repertoire HTML request that is already used to get the production names.

The browser then loads those direct image URLs with:

    loading="lazy"
    decoding="async"

So:
- no extra Flask API request per production card;
- no extra Linnateater HTML request per production card;
- images still appear in the repertoire;
- only images near the viewport are downloaded by the browser.

If a production card does not expose a thumbnail in the repertoire HTML, the
app shows a lightweight fallback card. When the user selects that production,
one production-image request is allowed to fetch the full image.

## Modal performance picker

Clicking a production now opens a fixed modal/pop-up.

Inside the modal:
- large production image;
- exact Piletilevi performance dates/times;
- current availability;
- "Jälgi seda etendust" action.

The user no longer has to scroll past the full production gallery to find the
date picker.

## Deploy

Replace v6 repository files with v7. Railway, PostgreSQL and Twilio settings do
not change.
