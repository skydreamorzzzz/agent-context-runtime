"""JSON Pointer resolution and M1 field provenance records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from acr.contracts import EvidenceRef


@dataclass(frozen=True)
class FieldProvenance:
    output_object: str
    field: str
    input_refs: tuple[EvidenceRef, ...]
    transform_name: str
    transform_version: str

def resolve_json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "": return value
    if not pointer.startswith("/"): raise ValueError("invalid JSON Pointer")
    current = value
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current
