"""Private evaluator subprocess for the fixed public add task."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text())
    tests = spec["tests"]
    try:
        module_spec = importlib.util.spec_from_file_location(
            "submitted_target", Path(args.workspace) / "target.py"
        )
        if module_spec is None or module_spec.loader is None:
            raise ImportError("submitted target cannot be loaded")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        add = module.add
        if not callable(add):
            raise TypeError("submitted add is missing")
        passed = sum(add(*case["args"]) == case["expected"] for case in tests)
    except Exception:  # noqa: BLE001 - submitted code is intentionally untrusted
        passed = 0
    result = {
        "status": "completed",
        "tests_executed": len(tests),
        "passed": passed,
        "failed": len(tests) - passed,
        "patch_valid": passed == len(tests),
        "resolved": passed == len(tests),
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
