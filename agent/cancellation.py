from __future__ import annotations

from threading import Event


class OperationCancelledError(RuntimeError):
    """Raised when the user cancels a running agent action."""


def raise_if_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelledError("Cancelled by user.")
