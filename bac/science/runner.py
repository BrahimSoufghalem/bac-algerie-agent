"""Hard process deadlines/limits around the restricted scientific grammar."""

from pathlib import Path
import json
import os
import subprocess
import sys
import threading
import time

SLOTS = threading.BoundedSemaphore(2)
ROOT = Path(__file__).resolve().parents[2]


class ScienceRunner:
    def __init__(self, settings):
        self.settings = settings

    def execute(self, name, args):
        if os.name != "posix":
            return {
                "error": "SCIENTIFIC_SANDBOX_UNAVAILABLE",
                "message": "Linux/POSIX resource limits required; no in-process fallback",
            }
        if not SLOTS.acquire(timeout=self.settings.science_timeout):
            return {"error": "SCIENTIFIC_SANDBOX_BUSY"}
        start = time.monotonic()
        # Fixed trusted bootstrap only. No untrusted text interpolated into code/argv/env.
        script = (
            "import resource,sys;"
            f"resource.setrlimit(resource.RLIMIT_CPU,({self.settings.science_cpu_seconds},{self.settings.science_cpu_seconds}));"
            f"resource.setrlimit(resource.RLIMIT_AS,({self.settings.science_memory_mb}*1024*1024,)*2);"
            "resource.setrlimit(resource.RLIMIT_FSIZE,(0,0));"
            "resource.setrlimit(resource.RLIMIT_CORE,(0,0));"
            "resource.setrlimit(resource.RLIMIT_NOFILE,(32,32));"
            f"sys.path.insert(0,{str(ROOT)!r});"
            "from bac.science.kernel import main;main()"
        )
        try:
            request = json.dumps(
                {
                    "name": name,
                    "arguments": args,
                    "max_output": min(self.settings.max_tool_chars - 400, 18000),
                },
                allow_nan=False,
            )
            if len(request) > 17000:
                return {"error": "SCIENTIFIC_INPUT_LIMIT"}
            # cwd is trusted application code; user AST has no file/network/OS capabilities.
            p = subprocess.Popen(
                [sys.executable, "-I", "-c", script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=ROOT,
                env={"LANG": "C.UTF-8"},
                text=True,
                start_new_session=True,
            )
            try:
                out, _ = p.communicate(request, timeout=self.settings.science_timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
                return {
                    "error": "SCIENTIFIC_TIMEOUT",
                    "message": "No result verified; computation terminated",
                }
            if p.returncode != 0:
                return {
                    "error": "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT",
                    "message": "No result verified; child process failed or exceeded resource limits",
                }
            result = json.loads(out)
            result["duration_ms"] = round((time.monotonic() - start) * 1000, 2)
            result["limits"] = {
                "wall_seconds": self.settings.science_timeout,
                "cpu_seconds": self.settings.science_cpu_seconds,
                "memory_mb": self.settings.science_memory_mb,
                "language": "restricted_numeric_AST",
            }
            return result
        except (OSError, ValueError):
            return {
                "error": "SCIENTIFIC_PROCESS_FAILURE",
                "message": "Scientific process unavailable; no unsafe fallback",
            }
        finally:
            SLOTS.release()
