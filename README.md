# Linnateater Tracker v6

Built on v5.

## Performance fix

The repertoire gallery no longer requests an image for every production.
Production cards are lightweight HTML/CSS only.

A production image is requested only AFTER the user selects that production,
and it is then shown in the performance picker. Active tracker cards continue
to use their already stored image.

This removes dozens of unnecessary external Linnateater requests and makes the
dashboard substantially lighter.

## Availability fix

Piletilevi event detail pages are NOT used as the source of truth for sold-out
state. A sold-out event page may still render normally.

v6 reads availability from the exact event row on the Piletilevi SERIES page,
matched by the unique Piletilevi event code.

The worker uses the same rule. If it cannot confidently locate the event/status
on the series page, it records an error instead of sending a false-positive SMS.

## Deploy

Replace v5 files with this ZIP. Railway/PostgreSQL/Twilio settings stay the same.
