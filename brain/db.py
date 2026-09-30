from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from . import config


def connect() -> psycopg.Connection:
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    register_vector(conn)
    return conn


def migrate() -> None:
    sql = (Path(__file__).parent.parent / "sql" / "001_init.sql").read_text()
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute(sql)
