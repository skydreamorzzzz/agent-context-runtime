"""JSON Pointer resolution used by the official Provenance contract."""
from __future__ import annotations

from typing import Any


def resolve_json_pointer(value: Any, pointer: str) -> Any:
    if pointer=="": return value
    if not pointer.startswith("/"): raise ValueError("invalid JSON Pointer")
    for token in pointer[1:].split("/"):
        token=token.replace("~1","/").replace("~0","~")
        value=value[int(token)] if isinstance(value,list) else value[token]
    return value
