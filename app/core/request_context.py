"""Request-scoped context (request_id) propagated via contextvars."""

from __future__ import annotations

import contextvars
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str:
    rid = request_id_var.get()
    return rid or uuid.uuid4().hex
