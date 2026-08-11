"""Minimal type stubs for asyncpg — the subset LINA's services use.

asyncpg ships no type information. Without a stub, every `db.fetch*` call
resolves to Unknown and the whole call graph downstream degrades to
"partially unknown" noise. This stub pins the shapes we actually use.
"""

from typing import Any, AsyncContextManager, Mapping


class Record(Mapping[str, Any]):
    """A database row: dict-like (``dict(row)`` / ``row["key"]`` / ``row.get``)."""

    def get(self, key: str, default: Any = None) -> Any: ...
    def keys(self) -> Any: ...
    def items(self) -> Any: ...
    def __getitem__(self, key: str) -> Any: ...


class Transaction(AsyncContextManager["Transaction"]):
    async def fetch(self, query: str, *args: Any, timeout: float | None = None) -> Any: ...
    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None) -> Record | None: ...
    async def fetchval(self, query: str, *args: Any, column: int = 0, timeout: float | None = None) -> Any: ...
    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str: ...


class Pool:
    async def fetch(
        self,
        query: str,
        *args: Any,
        timeout: float | None = None,
        record_class: type[Record] | None = None,
    ) -> list[Record]: ...
    async def fetchrow(
        self,
        query: str,
        *args: Any,
        timeout: float | None = None,
        record_class: type[Record] | None = None,
    ) -> Record | None: ...
    async def fetchval(
        self,
        query: str,
        *args: Any,
        column: int = 0,
        timeout: float | None = None,
    ) -> Any: ...
    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str: ...
    def transaction(
        self,
        *,
        isolation: str | None = None,
        readonly: bool | None = None,
    ) -> Transaction: ...
    async def close(self) -> None: ...
    async def acquire(self) -> Any: ...
    def release(self, connection: Any) -> Any: ...


def create_pool(
    dsn: str | None = None,
    *,
    min_size: int = 10,
    max_size: int = 10,
    max_queries: int = 50000,
    max_inactive_connection_lifetime: float = 300.0,
    **kwargs: Any,
) -> Any: ...
