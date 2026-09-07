"""Single-provider send-boundary capture used by the M2 engineering slice.

The transport receives the bytes named by ``sent_body_ref``.  A prepared
Python object is not itself treated as evidence that those bytes were sent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from acr.contracts import EvidenceRef, Fact, PhysicalAttempt
from acr.store import ingest_runtime_bytes, persist_physical_attempt


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
    raw_response_ref: EvidenceRef | None
    failure_ref: EvidenceRef | None
    raw_usage_ref: EvidenceRef | None
    usage: Fact[dict]
    transport_status: str
    provider_request_id: str | None


def serialize_deepseek_chat_request(*, model: str, messages: list[dict[str, str]]) -> bytes:
    """Build the exact JSON body handed to the standard-library HTTP client."""

    return json.dumps(
        {"model": model, "messages": messages, "temperature": 0},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class DeepSeekHTTPTransport:
    """Thin DeepSeek chat-completions transport for the one real-smoke provider.

    The observed request boundary is the exact ``body`` passed to
    ``urllib.request.Request(data=body)``.  This adapter deliberately makes no
    claim about HTTP-client framing or bytes after the client takes ownership.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 30.0,
        opener: Callable[[Request, float], object] | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout_seconds = timeout_seconds
        self._opener = opener or _open_request

    def __call__(self, body: bytes, attempt_id: str) -> TransportResult:
        """Send the captured body once and preserve response bytes verbatim."""

        del attempt_id
        request = Request(
            self._endpoint,
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            response = self._opener(request, self._timeout_seconds)
        except HTTPError as error:
            return TransportResult(
                status=f"http_{error.code}",
                response_body=error.read(),
                provider_request_id=error.headers.get("x-request-id"),
            )
        with response:
            raw = response.read()
            status = getattr(response, "status", 200)
            headers = getattr(response, "headers", {})
        return TransportResult(
            status=f"http_{status}",
            response_body=raw,
            provider_request_id=_provider_request_id(raw, headers),
        )


def _open_request(request: Request, timeout_seconds: float) -> object:
    return urlopen(request, timeout=timeout_seconds)


def _provider_request_id(raw: bytes, headers: object) -> str | None:
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("id"), str):
        return parsed["id"]
    get = getattr(headers, "get", None)
    value = get("x-request-id") if callable(get) else None
    return value if isinstance(value, str) else None


def extract_deepseek_message_content(response_body: bytes) -> str | None:
    """Return only the documented chat-message content when it is present."""

    try:
        parsed = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("choices"), list):
        return None
    if not parsed["choices"] or not isinstance(parsed["choices"][0], dict):
        return None
    message = parsed["choices"][0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else None


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
        self._data_root = None
        self._run_id: str | None = None
        self._producer_ref: EvidenceRef | None = None

    def prepare(self, request: RequestDraft) -> PreparedRequest:
        return PreparedRequest(before_body=request.body, prepared_body=request.body)

    def bind_capture(self, *, data_root, run_id: str, producer_ref: EvidenceRef) -> None:
        """Bind the one run that owns this provider's persisted observations."""

        if self._run_id is not None and (
            self._run_id != run_id or self._data_root != data_root or self._producer_ref != producer_ref
        ):
            raise ValueError("provider capture is already bound to another run")
        self._data_root = data_root
        self._run_id = run_id
        self._producer_ref = producer_ref

    def send(self, prepared: PreparedRequest, attempt_id: str) -> CapturedAttempt:
        """Persist before/prepared/sent evidence at the physical send boundary.

        ``sent`` is calculated once at the boundary and that same byte object is
        passed to the transport.  Thus a transport serializer divergence cannot
        be hidden by reserializing ``prepared`` after the fact.
        """

        if self._data_root is None or self._run_id is None or self._producer_ref is None:
            raise RuntimeError("provider send requires a bound capture run")
        before_ref = ingest_runtime_bytes(
            prepared.before_body, self._data_root, self._run_id, f"/attempts/{attempt_id}/before"
        )
        prepared_ref = ingest_runtime_bytes(
            prepared.prepared_body,
            self._data_root,
            self._run_id,
            f"/attempts/{attempt_id}/prepared",
        )
        sent = self._send_serializer(prepared)
        sent_ref = ingest_runtime_bytes(sent, self._data_root, self._run_id, f"/attempts/{attempt_id}/sent")
        self._persist_attempt(
            PhysicalAttempt(
                kind="physical_attempt",
                id=f"physical-attempt:{attempt_id}:entered",
                producer_ref=self._producer_ref,
                run_id=self._run_id,
                attempt_id=attempt_id,
                phase="entered",
                sent_body_ref=sent_ref,
            )
        )
        try:
            result = self._transport(sent, attempt_id)
        except Exception as error:  # noqa: BLE001 - transport exceptions are evidence, not control flow
            failure_ref = ingest_runtime_bytes(
                json.dumps({"exception_type": type(error).__name__}, sort_keys=True).encode(),
                self._data_root,
                self._run_id,
                f"/attempts/{attempt_id}/transport-failure",
            )
            self._persist_attempt(
                PhysicalAttempt(
                    kind="physical_attempt",
                    id=f"physical-attempt:{attempt_id}:terminal",
                    producer_ref=self._producer_ref,
                    run_id=self._run_id,
                    attempt_id=attempt_id,
                    phase="terminal",
                    sent_body_ref=sent_ref,
                    terminal_state="transport_exception",
                    failure_ref=failure_ref,
                )
            )
            return CapturedAttempt(
                attempt_id=attempt_id,
                before_body_ref=before_ref,
                prepared_body_ref=prepared_ref,
                sent_body_ref=sent_ref,
                raw_response_ref=None,
                failure_ref=failure_ref,
                raw_usage_ref=None,
                usage=Fact[dict](status="unknown", reason="transport_exception_before_response"),
                transport_status="transport_exception",
                provider_request_id=None,
            )
        response_ref = ingest_runtime_bytes(
            result.response_body, self._data_root, self._run_id, f"/attempts/{attempt_id}/response"
        )
        usage_ref, usage = _observed_usage(result.response_body, response_ref)
        self._persist_attempt(
            PhysicalAttempt(
                kind="physical_attempt",
                id=f"physical-attempt:{attempt_id}:terminal",
                producer_ref=self._producer_ref,
                run_id=self._run_id,
                attempt_id=attempt_id,
                phase="terminal",
                sent_body_ref=sent_ref,
                terminal_state="response_observed",
                raw_response_ref=response_ref,
            )
        )
        return CapturedAttempt(
            attempt_id=attempt_id,
            before_body_ref=before_ref,
            prepared_body_ref=prepared_ref,
            sent_body_ref=sent_ref,
            raw_response_ref=response_ref,
            failure_ref=None,
            raw_usage_ref=usage_ref,
            usage=usage,
            transport_status=result.status,
            provider_request_id=result.provider_request_id,
        )

    def _persist_attempt(self, attempt: PhysicalAttempt) -> None:
        assert self._data_root is not None
        persist_physical_attempt(self._data_root, attempt.run_id, attempt)


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
