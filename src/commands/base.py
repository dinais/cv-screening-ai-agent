from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    """Acknowledgement only. Commands must not return domain aggregates."""

    success: bool
    message: str = ""
    ticket_id: str | None = None

    @staticmethod
    def ok(message: str = "", ticket_id: str | None = None) -> CommandResult:
        return CommandResult(success=True, message=message, ticket_id=ticket_id)

    @staticmethod
    def fail(message: str) -> CommandResult:
        return CommandResult(success=False, message=message)


class CommandHandler:
    """Write-side handler. Implementations may only append events (Feature 2+)."""

    def execute(self, *args, **kwargs) -> CommandResult:
        raise NotImplementedError
