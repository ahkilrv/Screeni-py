"""
ScreeniDatabase - Postgres persistence layer for Screeni-py.
Replaces SQLite-based storage with Postgres via psycopg2.
Supports: scan results, stock data cache, watchlist.
Uses DATABASE_URL env var for connection.
"""

import json
import os
import logging
import io
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DEFAULT_DSN = os.environ.get('DATABASE_URL', '')


def get_dsn() -> str:
    return os.environ.get('DATABASE_URL', DEFAULT_DSN)


class ScreeniDatabase:
    """
    Postgres-backed storage for Screeni-py.

    Tables:
        scan_results  - Stores screening run results with metadata
        stock_cache   - Caches fetched stock OHLCV data with TTL
        watchlist     - User watchlist with notes

    Design: each method opens its own connection (safe for multiprocessing).
    A connection pool could be added later if needed.
    """

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or get_dsn()
        if not self.dsn:
            raise ValueError(
                "DATABASE_URL is not set. "
                "Provide a dsn= argument or set the DATABASE_URL environment variable."
            )
        self._init_tables()

    def _get_conn(self):
        """Get a new Postgres connection with DictRow factory."""
        conn = psycopg2.connect(self.dsn, sslmode='require')
        conn.autocommit = False
        return conn

    def _init_tables(self):
        """Create Postgres tables if they don't exist."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS scan_results (
                        id          SERIAL PRIMARY KEY,
                        timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        criteria    TEXT,
                        index_name  TEXT,
                        results_json TEXT NOT NULL,
                        agent_name  TEXT,
                        row_count   INTEGER DEFAULT 0
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_scan_results_timestamp
                        ON scan_results(timestamp DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_scan_results_criteria
                        ON scan_results(criteria, index_name)
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS stock_cache (
                        symbol      TEXT PRIMARY KEY,
                        data_json   TEXT NOT NULL,
                        fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        ttl_seconds INTEGER DEFAULT 86400
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS watchlist (
                        id          SERIAL PRIMARY KEY,
                        symbol      TEXT NOT NULL UNIQUE,
                        added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        notes       TEXT
                    )
                """)
            conn.commit()
        finally:
            conn.close()

    # ---- Scan Results ----

    def save_scan_results(
        self,
        criteria: str,
        index_name: str,
        results_df: pd.DataFrame,
        agent_name: Optional[str] = None,
    ) -> int:
        try:
            results_json = results_df.to_json(orient='records', date_format='iso')
            row_count = len(results_df)
        except Exception as e:
            logger.error(f"Failed to serialize scan results: {e}")
            results_json = "[]"
            row_count = 0

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO scan_results
                       (timestamp, criteria, index_name, results_json, agent_name, row_count)
                       VALUES (NOW(), %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (criteria, index_name, results_json, agent_name, row_count),
                )
                row_id = cur.fetchone()[0]
            conn.commit()
            return row_id
        finally:
            conn.close()

    def get_last_scan_results(
        self,
        criteria: Optional[str] = None,
        index_name: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        conn = self._get_conn()
        try:
            query = "SELECT results_json FROM scan_results WHERE 1=1"
            params = []
            if criteria:
                query += " AND criteria = %s"
                params.append(criteria)
            if index_name:
                query += " AND index_name = %s"
                params.append(index_name)
            query += " ORDER BY timestamp DESC LIMIT 1"

            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                if row is None:
                    return None
                return pd.read_json(io.StringIO(row['results_json']), orient='records')
        except Exception as e:
            logger.error(f"Failed to load scan results: {e}")
            return None
        finally:
            conn.close()

    def get_scan_history(self, limit: int = 20) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """SELECT id, timestamp, criteria, index_name, agent_name, row_count
                       FROM scan_results ORDER BY timestamp DESC LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
                if not rows:
                    return pd.DataFrame()
                return pd.DataFrame([dict(r) for r in rows])
        finally:
            conn.close()

    # ---- Stock Cache ----

    def cache_stock_data(
        self,
        symbol: str,
        df: pd.DataFrame,
        ttl: int = 86400,
    ):
        try:
            data_json = df.to_json(orient='records', date_format='iso')
        except Exception as e:
            logger.error(f"Failed to serialize stock data for {symbol}: {e}")
            return

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO stock_cache (symbol, data_json, fetched_at, ttl_seconds)
                       VALUES (%s, %s, NOW(), %s)
                       ON CONFLICT (symbol) DO UPDATE SET
                       data_json=EXCLUDED.data_json,
                       fetched_at=EXCLUDED.fetched_at,
                       ttl_seconds=EXCLUDED.ttl_seconds""",
                    (symbol, data_json, ttl),
                )
            conn.commit()
        finally:
            conn.close()

    def get_cached_stock_data(self, symbol: str) -> Optional[pd.DataFrame]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """SELECT data_json FROM stock_cache
                       WHERE symbol = %s
                         AND (fetched_at + make_interval(secs => ttl_seconds)) > NOW()""",
                    (symbol,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return pd.read_json(io.StringIO(row['data_json']), orient='records')
        except Exception as e:
            logger.error(f"Failed to load cached data for {symbol}: {e}")
            return None
        finally:
            conn.close()

    # ---- Watchlist ----

    def add_to_watchlist(self, symbol: str, notes: str = "") -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO watchlist (symbol, added_at, notes) VALUES (%s, NOW(), %s)"
                    " ON CONFLICT (symbol) DO UPDATE SET notes=EXCLUDED.notes",
                    (symbol.upper(), notes),
                )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to add {symbol} to watchlist: {e}")
            return False
        finally:
            conn.close()

    def get_watchlist(self) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    "SELECT symbol, added_at, notes FROM watchlist ORDER BY added_at DESC"
                )
                rows = cur.fetchall()
                if not rows:
                    return pd.DataFrame(columns=['symbol', 'added_at', 'notes'])
                return pd.DataFrame([dict(r) for r in rows])
        finally:
            conn.close()

    def remove_from_watchlist(self, symbol: str) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM watchlist WHERE symbol = %s", (symbol.upper(),))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to remove {symbol} from watchlist: {e}")
            return False
        finally:
            conn.close()
