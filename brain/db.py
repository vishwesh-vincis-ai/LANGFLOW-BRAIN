from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from . import config


def connect() -> psycopg.Connection:
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    register_vector(conn)
    return conn


def migrate() -> None:
    """Apply every sql/*.sql in name order. Each file is idempotent (IF NOT EXISTS)."""
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        for f in sorted((Path(__file__).parent.parent / "sql").glob("*.sql")):
            conn.execute(f.read_text())
