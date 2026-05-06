"""IBKR TWS/Gateway connection wrapper with auto-reconnect."""

from __future__ import annotations

import logging
import time
from typing import Optional

from ib_insync import IB

logger = logging.getLogger(__name__)


class ConnectionError(Exception):
    """Raised when a connection to IBKR cannot be established."""


class IBKRConnection:
    """Manage the lifecycle of an ib_insync IB connection.

    Wraps connect/disconnect with retry logic and exposes the underlying
    IB instance via the ``ib`` attribute. Supports use as a context manager:

        with IBKRConnection(host, port, client_id) as ib:
            ...
    """

    MAX_RETRIES = 3
    BACKOFF_BASE_SECONDS = 2

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib: IB = IB()

    def connect(self) -> IB:
        """Connect to TWS/Gateway, retrying with exponential backoff on failure."""
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    "Connecting to IBKR at %s:%s (clientId=%s, attempt %s/%s)",
                    self.host, self.port, self.client_id, attempt, self.MAX_RETRIES,
                )
                self.ib.connect(self.host, self.port, clientId=self.client_id)
                logger.info("Connected to IBKR.")
                return self.ib
            except (OSError, TimeoutError, ConnectionRefusedError) as exc:
                last_exc = exc
                wait = self.BACKOFF_BASE_SECONDS ** attempt
                logger.warning(
                    "Connection attempt %s failed (%s). Retrying in %ss...",
                    attempt, exc, wait,
                )
                time.sleep(wait)

        raise ConnectionError(
            f"Could not connect to IBKR after {self.MAX_RETRIES} attempts"
        ) from last_exc

    def disconnect(self) -> None:
        """Cleanly disconnect from IBKR if connected."""
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IBKR.")

    def is_connected(self) -> bool:
        """Return True if the underlying IB instance is currently connected."""
        return self.ib.isConnected()

    def __enter__(self) -> IB:
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
