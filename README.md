# Linnateater Tracker v18

This release intentionally resets the architecture to the v10 version that
performed well, then adds only the later features/fixes that are still needed.

## 1. v10 image architecture restored

The repertoire uses the lightweight v10 production-card/image-cache behavior.
The large-image changes introduced after v10 are not used.

The login headline/spacing from v16 is preserved.

## 2. Missing Piletilevi series mappings added

Added:
- Vaikus
- Uskuja
- Viimane liivlane
- Esietendus
- Suur veeuputus
- Ülestähendusi põranda alt
- Polkovniku lesk
- Muusikale
- Kolemees

Existing mappings remain intact.

## 3. Performance dates are cached in PostgreSQL

New table:

    performance_cache

The Railway worker refreshes performance lists in a separate background thread
every 5 minutes. Each production uses the fast one-request Piletilevi series
parser.

The `/api/performances` modal endpoint:
1. reads PostgreSQL first (normally instant);
2. only contacts Piletilevi when the production has no cached data yet;
3. saves that fallback result for later clicks.

The background cache thread is completely separate from the 15–30 second ticket
monitor cycle, so refreshing repertoire data cannot delay active tracker checks.

## 4. Later features retained

- multiple dates selectable at once;
- Repertuaar / Minu jälgimised navigation;
- phone + password login;
- Twilio SMS alerts;
- existing trackers/database remain intact.

## Deploy

Replace v17 files with this ZIP.

Do NOT change:
- Railway services;
- PostgreSQL;
- Twilio variables;
- web start command;
- worker start command.

After deployment, the worker log should show:

    🎟 Refreshing performance cache in background...
    🎟 Performance cache ready: ...

Once that first cache pass completes, opening production modals should normally
be served directly from PostgreSQL rather than waiting on Piletilevi.
