"""Single-provider send-boundary capture used by the M2 engineering slice.

The transport receives the bytes named by ``sent_body_ref``.  A prepared
Python object is not itself treated as evidence that those bytes were sent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from acr.contracts import EvidenceRef, Fact
from acr.store import ingest_runtime_bytes


@dataclass(frozen=True)
class RequestDraft:
    body: bytes


@dataclass(frozen=True)
class PreparedRequest:
    before_body: bytes
    prepared_body: bytes


@dataclass(frozen=True)
class TransportResult:
    status: str
    response_body: bytes
    provider_request_id: str | None = None


@dataclass(frozen=True)
class CapturedAttempt:
    attempt_id: str
    before_body_ref: EvidenceRef
    prepared_body_ref: EvidenceRef
    sent_body_ref: EvidenceRef
    raw_response_ref: EvidenceRef
    raw_usage_ref: EvidenceRef | None
    usage: Fact[dict]
    transport_status: str
    provider_request_id: str | None


class CapturedProvider:
    """Capture the exact bytes passed into a narrow physical transport boundary."""

    def __init__(
        self,
        transport: Callable[[bytes, str], TransportResult],
        *,
        send_serializer: Callable[[PreparedRequest], bytes] | None = None,
    ) -> None:
        self._transport = transport
        self._send_serializer = send_serializer or (lambda prepared: prepared.prepared_body)

    def prepare(self, request: RequestDraft) -> PreparedRequest:
        return PreparedRequest(before_body=request.body, prepared_body=request.body)

    def send(self, prepared: PreparedRequest, attempt_id: str) -> TransportResult:
        """Protocol-compatible send; capture requires :meth:`capture_attempt`."""

        return self._transport(self._send_serializer(prepared), attempt_id)

    def capture_attempt(
        self,
        prepared: PreparedRequest,
        attempt_id: str,
        *,
        data_root,
        run_id: str,
    ) -> CapturedAttempt:
        """Persist before/prepared/sent evidence at the physical send boundary.

        ``sent`` is calculated once at the boundary and that same byte object is
        passed to the transport.  Thus a transport serializer divergence cannot
        be hidden by reserializing ``prepared`` after the fact.
        """

        before_ref = ingest_runtime_bytes(prepared.before_body, data_root, run_id, f"/attempts/{attempt_id}/before")
        prepared_ref = ingest_runtime_bytes(prepared.prepared_body, data_root, run_id, f"/attempts/{attempt_id}/prepared")
        sent = self._send_serializer(prepared)
        sent_ref = ingest_runtime_bytes(sent, data_root, run_id, f"/attempts/{attempt_id}/sent")
        result = self._transport(sent, attempt_id)
        response_ref = ingest_runtime_bytes(result.response_body, data_root, run_id, f"/attempts/{attempt_id}/response")
        usage_ref, usage = _observed_usage(result.response_body, response_ref)
        return CapturedAttempt(
            attempt_id=attempt_id,
            before_body_ref=before_ref,
            prepared_body_ref=prepared_ref,
            sent_body_ref=sent_ref,
            raw_response_ref=response_ref,
            raw_usage_ref=usage_ref,
            usage=usage,
            transport_status=result.status,
            provider_request_id=result.provider_request_id,
        )


def _observed_usage(response_body: bytes, response_ref: EvidenceRef) -> tuple[EvidenceRef | None, Fact[dict]]:
    """Only usage explicitly present in the raw provider response is observed."""

    try:
        parsed = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict) or "usage" not in parsed or not isinstance(parsed["usage"], dict):
        return None, Fact[dict](status="unknown", reason="provider_did_not_report_usage")
    usage_ref = response_ref.model_copy(update={"locator": "/usage"})
    return usage_ref, Fact[dict](value=parsed["usage"], status="observed", refs=[usage_ref])
