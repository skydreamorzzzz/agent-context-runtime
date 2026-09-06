"""The four small external-boundary protocols frozen for the MVP."""

from __future__ import annotations

from typing import Any, Protocol, TypeAlias

from acr.contracts import EvaluationResult, Run

NormalizedBatch: TypeAlias = Any
RequestDraft: TypeAlias = Any
PreparedRequest: TypeAlias = Any
ProviderResult: TypeAlias = Any
AgentTask: TypeAlias = Any
RunConfig: TypeAlias = Any


class TrajectoryAdapter(Protocol):
    def normalize(self, raw_ref: str) -> NormalizedBatch: ...


class Provider(Protocol):
    def prepare(self, request: RequestDraft) -> PreparedRequest: ...

    def send(self, prepared: PreparedRequest, attempt_id: str) -> ProviderResult: ...


class Runtime(Protocol):
    def run(self, task: AgentTask, spec: RunConfig, intervention: str) -> Run: ...


class Evaluator(Protocol):
    def evaluate(self, sealed_run: Run, private_spec_ref: str) -> EvaluationResult: ...
