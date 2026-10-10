"""Ordinary CPython bootstrap. ONLY run in the disposable sandbox image.

This file is NOT a security boundary. Docker isolation is mandatory for untrusted code.
No application modules, files, credentials or sockets are included in its image.
"""

import contextlib
import io
import json
import resource
import sys

MAX_INPUT_BYTES = 65536


class BoundedText(io.StringIO):
    def write(self, value):
        if self.tell() + len(value) > 4096:
            raise ValueError("Printed output limit; emit only the needed results")
        return super().write(value)


def compute(request):
    """Called directly in unit tests ONLY with fixed trusted test programs."""
    outputs, checks = {}, []
    captured = BoundedText()
    budget = request["limits"]["output_chars"]

    def emit(name, value):
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise ValueError("emit requires a short string name")
        outputs[name] = value
        if (
            len(outputs) > 32
            or len(json.dumps(outputs, ensure_ascii=False, allow_nan=False)) > budget
        ):
            raise ValueError("Output limit; return smaller arrays/fewer results")

    def check(label, condition, details=""):
        if condition is not True and condition is not False and condition is not None:
            raise ValueError(
                "check condition must be bool or None; explicitly convert library booleans"
            )
        if (
            not isinstance(label, str)
            or not 1 <= len(label) <= 160
            or not isinstance(details, str)
            or len(details) > 500
            or len(checks) >= 32
        ):
            raise ValueError("Check label/details limit")
        checks.append(
            {
                "label": label,
                "status": "inconclusive"
                if condition is None
                else "passed"
                if condition
                else "failed",
                "details": details,
            }
        )

    scope = {
        "__name__": "__computation__",
        "inputs": request.get("inputs", {}),
        "emit": emit,
        "check": check,
    }
    # No AST filter, import allowlist, altered builtins, or restricted expression language.
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        exec(compile(request["code"], "<computation>", "exec"), scope, scope)
    result = {"outputs": outputs, "checks": checks, "stdout": captured.getvalue()}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False)) > budget:
        raise ValueError("Output limit; reduce results/print/check details")
    return result


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Input limit")
        request = json.loads(raw)
        limits = request["limits"]
        resource.setrlimit(
            resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"])
        )
        memory = limits["memory_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        result = compute(request)
    except BaseException as exc:
        result = {
            "error": "SCIENTIFIC_INPUT_OR_COMPUTATION_ERROR",
            "message": type(exc).__name__ + ": " + str(exc)[:400],
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
