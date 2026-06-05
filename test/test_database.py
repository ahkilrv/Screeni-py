"""
Tests for ScreeniDatabase - Postgres persistence layer.
Requires DATABASE_URL environment variable to be set.
"""
import pytest
import os
import sys
import pickle
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from classes.Database import ScreeniDatabase, get_dsn

pytestmark = pytest.mark.skipif(
    not os.environ.get('DATABASE_URL'),
    reason="DATABASE_URL environment variable is required for Postgres tests"
)


@pytest.fixture
def db():
    dsn = get_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL not set")
    yield ScreeniDatabase(dsn=dsn)
    # Clean up test data
    conn = psycopg2.connect(dsn, sslmode='require')
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM scan_results")
            cur.execute("DELETE FROM stock_cache")
            cur.execute("DELETE FROM watchlist")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'Stock': ['RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'SBIN'],
        'LTP': [2450.0, 1850.0, 3700.0, 1650.0, 580.0],
        'RSI': [62.5, 58.3, 71.2, 45.8, 55.0],
        'Trend': ['Bullish', 'Bullish', 'Sideways', 'Bearish', 'Bullish'],
    })


class TestDatabaseInit:

    def test_creates_all_tables(self, db):
        conn = psycopg2.connect(get_dsn(), sslmode='require')
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' ORDER BY table_name
                """)
                tables = {row[0] for row in cur.fetchall()}
            assert 'scan_results' in tables
            assert 'stock_cache' in tables
            assert 'watchlist' in tables
        finally:
            conn.close()

    def test_idempotent_init(self, db):
        db2 = ScreeniDatabase(dsn=get_dsn())
        assert db2 is not None


class TestScanResults:

    def test_save_scan_results(self, db, sample_df):
        row_id = db.save_scan_results('breakout', 'Nifty 500', sample_df)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_get_last_scan_results(self, db, sample_df):
        db.save_scan_results('breakout', 'Nifty 500', sample_df)
        result = db.get_last_scan_results()
        assert result is not None
        assert len(result) == len(sample_df)
        assert set(result.columns) == set(sample_df.columns)

    def test_get_last_scan_results_filtered_by_criteria(self, db, sample_df):
        db.save_scan_results('breakout', 'Nifty 500', sample_df)
        df2 = sample_df.head(2).copy()
        db.save_scan_results('rsi_scan', 'Nifty 50', df2)
        result = db.get_last_scan_results(criteria='rsi_scan')
        assert result is not None
        assert len(result) == 2

    def test_get_last_scan_results_filtered_by_index(self, db, sample_df):
        db.save_scan_results('breakout', 'Nifty 50', sample_df.head(1))
        db.save_scan_results('breakout', 'Nifty 500', sample_df)
        result = db.get_last_scan_results(index_name='Nifty 500')
        assert result is not None
        assert len(result) == len(sample_df)

    def test_get_last_scan_results_returns_most_recent(self, db, sample_df):
        db.save_scan_results('breakout', 'Nifty 500', sample_df)
        df_new = sample_df.head(2).copy()
        db.save_scan_results('breakout', 'Nifty 500', df_new)
        result = db.get_last_scan_results(criteria='breakout', index_name='Nifty 500')
        assert result is not None
        assert len(result) == 2

    def test_get_last_scan_results_none_when_empty(self, db):
        result = db.get_last_scan_results()
        assert result is None

    def test_save_with_agent_name(self, db, sample_df):
        row_id = db.save_scan_results('breakout', 'Nifty 500', sample_df, agent_name='SwingTrader')
        assert row_id > 0
        conn = psycopg2.connect(get_dsn(), sslmode='require')
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT agent_name FROM scan_results WHERE id=%s", (row_id,))
                row = cur.fetchone()
            assert row[0] == 'SwingTrader'
        finally:
            conn.close()

    def test_scan_history(self, db, sample_df):
        for i in range(3):
            db.save_scan_results(f'criteria_{i}', 'Nifty 500', sample_df)
        history = db.get_scan_history(limit=10)
        assert len(history) == 3
        assert 'criteria' in history.columns
        assert 'timestamp' in history.columns
        assert 'row_count' in history.columns


class TestStockCache:

    @pytest.fixture
    def stock_df(self):
        import numpy as np
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        return pd.DataFrame({
            'Open': np.random.uniform(100, 200, 30),
            'High': np.random.uniform(100, 200, 30),
            'Low': np.random.uniform(100, 200, 30),
            'Close': np.random.uniform(100, 200, 30),
            'Volume': np.random.randint(100000, 1000000, 30),
        }, index=dates)

    def test_cache_and_retrieve(self, db, stock_df):
        db.cache_stock_data('RELIANCE', stock_df, ttl=3600)
        result = db.get_cached_stock_data('RELIANCE')
        assert result is not None
        assert len(result) == len(stock_df)

    def test_cache_miss_returns_none(self, db):
        result = db.get_cached_stock_data('NONEXISTENT')
        assert result is None

    def test_expired_cache_returns_none(self, db, stock_df):
        db.cache_stock_data('INFY', stock_df, ttl=-1)
        result = db.get_cached_stock_data('INFY')
        assert result is None

    def test_cache_update(self, db, stock_df):
        db.cache_stock_data('TCS', stock_df, ttl=3600)
        new_df = stock_df.tail(5).copy()
        db.cache_stock_data('TCS', new_df, ttl=3600)
        result = db.get_cached_stock_data('TCS')
        assert result is not None
        assert len(result) == 5


class TestWatchlist:

    def test_add_to_watchlist(self, db):
        assert db.add_to_watchlist('RELIANCE', notes='Good setup')

    def test_get_watchlist(self, db):
        db.add_to_watchlist('RELIANCE', notes='Breakout')
        db.add_to_watchlist('INFY', notes='RSI dip')
        watchlist = db.get_watchlist()
        assert len(watchlist) == 2
        assert 'RELIANCE' in watchlist['symbol'].values
        assert 'INFY' in watchlist['symbol'].values

    def test_remove_from_watchlist(self, db):
        db.add_to_watchlist('SBIN')
        db.remove_from_watchlist('SBIN')
        watchlist = db.get_watchlist()
        assert len(watchlist) == 0

    def test_empty_watchlist(self, db):
        watchlist = db.get_watchlist()
        assert isinstance(watchlist, pd.DataFrame)
        assert len(watchlist) == 0
