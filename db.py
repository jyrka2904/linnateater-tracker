import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ["DATABASE_URL"]


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    phone_number TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    phone_verified_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            # Safe migration from v1-v4.
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT"
            )
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified_at TIMESTAMPTZ"
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trackers (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    date_text TEXT,
                    event_url TEXT NOT NULL,
                    series_url TEXT NOT NULL,
                    event_code TEXT NOT NULL,
                    image_url TEXT,
                    production_url TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_checked_at TIMESTAMPTZ,
                    last_available BOOLEAN,
                    last_status TEXT,
                    last_error TEXT,
                    UNIQUE(user_id, event_code)
                )
                """
            )
            cur.execute(
                "ALTER TABLE trackers ADD COLUMN IF NOT EXISTS image_url TEXT"
            )
            cur.execute(
                "ALTER TABLE trackers ADD COLUMN IF NOT EXISTS production_url TEXT"
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS production_image_cache (
                    production_url TEXT PRIMARY KEY,
                    image_url TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_cache (
                    production_url TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

