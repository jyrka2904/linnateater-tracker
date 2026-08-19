# Linnateater Tracker v5

Built directly on v4. Ticket discovery/worker logic from v4 is retained.

## Change 1: normal account + password login

New users:
1. Open "Loo konto".
2. Phone number is the username.
3. User chooses a password.
4. Twilio Verify confirms the phone once.
5. Future logins use phone + password only.

Password reset:
- "Unustasid parooli?" sends a Twilio verification code.
- After verification the user chooses a new password.

Legacy v1-v4 users:
- Existing `users` and `trackers` are NOT deleted.
- `password_hash` and `phone_verified_at` are added with safe ALTER TABLE migrations.
- A legacy user opens "Kasutasin varasemat versiooni", enters the existing
  phone number, chooses a password and verifies that phone once.
- Their original user row is updated, so existing trackers stay attached.

Passwords are stored only as Werkzeug password hashes, never plaintext.

## Change 2: redesigned UI

- Editorial theatre-style layout inspired by Tallinna Linnateater's current site.
- Warm neutral background, black typography and red accent.
- Visual production gallery instead of a dropdown.
- Production images lazy-load as cards enter the viewport.
- Selecting a production opens an image-led performance picker.
- Active trackers are large image cards.
- Mobile layout included.
- The app identifies itself as an unofficial ticket tracker.

## Deploy

Replace the existing v4 repository files with the contents of this ZIP.
Do not recreate Railway, PostgreSQL, Twilio, or environment variables.

Existing start commands stay unchanged:

Web:
    /bin/sh -c "exec gunicorn app:app --bind 0.0.0.0:$PORT"

Worker:
    python -u worker.py
