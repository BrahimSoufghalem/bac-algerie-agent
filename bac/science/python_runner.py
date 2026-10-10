"""Authenticated internal sandbox client. Never executes model code on the host."""

import hashlib
import json
from pathlib import Path
import httpx
from bac.science.python_contract import PythonCode, validate_output

WIRE_LIMIT = 80000


class PythonRunner:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def execute(self, args):
        s = self.settings
        inputs = PythonCode.model_validate(args).model_dump()
        encoded = json.dumps(inputs, ensure_ascii=False, allow_nan=False)
        output_chars = min(16000, s.max_tool_chars - len(encoded) - 1200)
        if output_chars < 512 or len(encoded.encode()) > 60000:
            return {
                "error": "SCIENTIFIC_INPUT_LIMIT",
                "message": "Shorten code/inputs to leave room for actual results",
            }
        if not s.python_sandbox_url:
            return {
                "error": "SCIENTIFIC_SANDBOX_UNAVAILABLE",
                "message": "Isolated Python service is not configured; no host execution fallback",
            }
        try:
            token = Path(s.python_sandbox_token_file).read_text().strip()
            if not 32 <= len(token) <= 256:
                raise ValueError("Invalid sandbox token")
            request = inputs | {
                "limits": {
                    "timeout": s.science_timeout,
                    "cpu_seconds": s.science_cpu_seconds,
                    "memory_mb": s.science_memory_mb,
                    "output_chars": output_chars,
                }
            }
            # Explicit proxy bypass: private code and auth must never go through an ambient proxy.
            with httpx.Client(
                timeout=s.science_timeout + 10,
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    "POST",
                    s.python_sandbox_url.rstrip("/") + "/execute",
                    headers={"Authorization": "Bearer " + token},
                    json=request,
                ) as response:
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        if len(chunks) + len(chunk) > WIRE_LIMIT:
                            return {"error": "SCIENTIFIC_OUTPUT_LIMIT"}
                        chunks.extend(chunk)
                    if response.status_code != 200:
                        return {
                            "error": "SCIENTIFIC_SANDBOX_UNAVAILABLE",
                            "message": "Python service unavailable or authentication failed",
                        }
            payload = json.loads(chunks)
            if isinstance(payload, dict) and "error" in payload:
                allowed = {
                    "SCIENTIFIC_TIMEOUT",
                    "SCIENTIFIC_OUTPUT_LIMIT",
                    "SCIENTIFIC_SANDBOX_BUSY",
                    "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT",
                    "SCIENTIFIC_INPUT_OR_COMPUTATION_ERROR",
                    "SCIENTIFIC_SANDBOX_UNAVAILABLE",
                    "SCIENTIFIC_PROCESS_FAILURE",
                    "SCIENTIFIC_INPUT_LIMIT",
                }
                return {
                    "error": payload["error"]
                    if payload["error"] in allowed
                    else "SCIENTIFIC_PROCESS_FAILURE",
                    "message": str(payload.get("message", "Python execution failed"))[
                        :500
                    ],
                }
            output = validate_output(payload)
            output["code_sha256"] = hashlib.sha256(inputs["code"].encode()).hexdigest()
            output["limits"] = request["limits"] | {
                "language": "python",
                "isolation": "fresh_container_no_network_no_host_mounts",
            }
            if len(json.dumps(output, ensure_ascii=False)) > s.max_tool_chars:
                return {"error": "SCIENTIFIC_OUTPUT_LIMIT"}
            return output
        except (OSError, httpx.HTTPError):
            return {
                "error": "SCIENTIFIC_SANDBOX_UNAVAILABLE",
                "message": "Cannot contact isolated Python service; no host execution fallback",
            }
        except (ValueError, TypeError, RecursionError):
            return {
                "error": "SCIENTIFIC_PROCESS_FAILURE",
                "message": "Invalid or non-finite Python output; no result credited",
            }
