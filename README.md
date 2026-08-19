# Linnateater Tracker v10

## Images without page lag

Production image discovery is no longer done by the user's browser.

The Railway worker now refreshes the production image cache at startup and then
periodically. Successful image URLs are persisted in PostgreSQL. The repertoire
page only reads cached URLs and uses browser-native lazy image loading.

After the first v10 worker deployment, allow a short moment for previously
missing images to be cached. Future page loads do not wait for external image
discovery.

## Multi-select performance dates

Inside the production modal, performance dates are toggles. You can select
several dates from the same production and then press one button, for example:

    Jälgi 3 etendust

Each selected date is stored as its own tracker. The app respects the remaining
tracker limit and revalidates the chosen event codes against the Piletilevi
series data before inserting them.

## Deploy

Replace v9 files with this ZIP. Railway, PostgreSQL and Twilio settings remain
unchanged.
