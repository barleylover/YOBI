from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import oracledb

from app.core.config import Settings


class OraclePool:
    """Small Thin-mode pool sized for the existing 1 OCPU demo VM."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pool: oracledb.ConnectionPool | None = None

    def initialize(self) -> None:
        if self._pool is not None:
            return
        dsn = self.settings.adb_dsn.get_secret_value()
        password = self.settings.db_password.get_secret_value()
        if not dsn or not password:
            raise RuntimeError("ORACLE_CONFIGURATION_MISSING")
        self._pool = oracledb.create_pool(
            user=self.settings.db_username,
            password=password,
            dsn=dsn,
            min=1,
            max=3,
            increment=1,
            getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
            wait_timeout=5000,
            timeout=60,
            ping_interval=60,
        )

    @contextmanager
    def connection(self) -> Iterator[oracledb.Connection]:
        self.initialize()
        if self._pool is None:
            raise RuntimeError("ORACLE_POOL_NOT_INITIALIZED")
        connection = self._pool.acquire()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._pool.release(connection)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close(force=True)
            self._pool = None

