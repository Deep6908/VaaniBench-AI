"""Small SQL boundary: shared state logic, SQLite locally, PostgreSQL when configured.

Only application-owned SQL passes through this adapter. Values remain bound
parameters; the question-mark conversion is never applied to user input.
"""
from contextlib import contextmanager


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)

    def __iter__(self):
        # StateStore also unpacks aggregate rows as positional values.
        return iter(self.values())


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        value = self.cursor.fetchone()
        return Row(value) if value is not None else None

    def fetchall(self):
        return [Row(value) for value in self.cursor.fetchall()]


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        return Cursor(self.connection.execute(sql.replace("?", "%s"), parameters))

    def executemany(self, sql, parameters):
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), parameters)


def connect_postgres(url):
    import psycopg
    from psycopg.rows import dict_row
    # Errors must be sanitized by the caller, never log the connection string.
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5,
        options="-c search_path=vaanibench -c statement_timeout=10000 -c lock_timeout=5000",
        keepalives=1,keepalives_idle=30,keepalives_interval=10,keepalives_count=3,tcp_user_timeout=15000,
        prepare_threshold=None)


@contextmanager
def postgres_transaction(url, write=False):
    with connect_postgres(url) as connection:
        if write:
            # Match SQLite BEGIN IMMEDIATE semantics across processes/threads.
            connection.execute("SELECT pg_advisory_xact_lock(857231901)")
        yield PostgresConnection(connection)


@contextmanager
def postgres_lease(url):
    """Dedicated direct/session connection; transaction-pool URLs are unsuitable."""
    with connect_postgres(url) as connection:
        acquired = connection.execute("SELECT pg_try_advisory_lock(857231902) AS acquired").fetchone()["acquired"]
        connection.commit()
        if not acquired:
            raise RuntimeError("Another hosted instance owns this database")
        try:
            yield connection
        finally:
            connection.execute("SELECT pg_advisory_unlock(857231902)")
            connection.commit()
