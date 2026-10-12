from __future__ import annotations


class QueryHandler:
    """Read-side handler. Implementations must never modify application state."""

    def execute(self, *args, **kwargs):
        raise NotImplementedError
