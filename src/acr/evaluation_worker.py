"""Untrusted add-submission worker source; it never receives private expected values."""

from __future__ import annotations

SUBMISSION_WORKER_SOURCE = r"""
import importlib.util
import json
import sys

request = json.loads(sys.stdin.buffer.read())
try:
    spec = importlib.util.spec_from_file_location("submitted_target", "/workspace/target.py")
    if spec is None or spec.loader is None:
        raise ImportError("submitted target cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.add(*request["args"])
    result = {"status": "returned", "value": value}
except BaseException as error:
    result = {"status": "submission_error", "error_type": type(error).__name__}
print("ACR_RESULT=" + json.dumps(result, sort_keys=True))
"""
