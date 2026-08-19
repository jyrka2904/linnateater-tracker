# Linnateater Tracker v8

## Faster production images

The repertoire renders immediately with placeholders.

After first paint, the browser makes ONE request to `/api/production-images`.
The server:
- reads cached production image URLs from PostgreSQL;
- fetches only missing/stale Linnateater production pages;
- fetches missing pages concurrently (up to 8 at once);
- persists the resulting image URLs for 7 days.

The browser then assigns the URLs to lazy/async `<img>` elements.

Result: images return to the repertoire without 20-30 sequential requests on
every page visit.

## Much faster performance picker

v7 opened every concrete Piletilevi event page separately.

v8 uses ONE Piletilevi series-page request. The series page already contains:
- concrete event URL;
- event code;
- date;
- time;
- sold-out / available state.

This should make the modal noticeably faster.

## Separate navigation

Top navigation now has:
- Repertuaar
- Minu jälgimised

`/dashboard` contains only production discovery/selection.
`/my-trackers` contains the active monitored performances.

Railway, PostgreSQL and Twilio settings do not need to change.
