"""Neon Postgres database layer for business tables (not RAG)."""

import os
from contextlib import contextmanager
from typing import List

import psycopg

NEON_DATABASE_URL = os.environ.get("NEON_DATABASE_URL")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


def init_db():
    """Create business tables. RAG tables are managed by LangChain PGVector."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()


@contextmanager
def get_conn():
    if not NEON_DATABASE_URL:
        raise RuntimeError("NEON_DATABASE_URL not set")
    # Use psycopg3 connection (strip +psycopg if present for raw psycopg)
    url = NEON_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(url)
    try:
        yield conn
    finally:
        conn.close()


def get_processed_video_ids() -> List[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM videos")
            return [row[0] for row in cur.fetchall()]


def insert_video(video_id: str, channel_id: str, title: str, published_at: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO videos (id, channel_id, title, published_at) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (video_id, channel_id, title, published_at),
            )
        conn.commit()
