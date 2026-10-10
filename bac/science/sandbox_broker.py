"""Internal trusted broker: untrusted Python runs ONLY in a disposable container.

The broker has Docker daemon access (operator/root-equivalent privilege). It must
never be public. API/worker and execution containers never receive that socket.
"""

import hmac
import json
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_INPUT = 65536
MAX_WIRE = 80000
SLOTS = threading.BoundedSemaphore(2)
IMAGE = os.getenv("PYTHON_SANDBOX_IMAGE", "masar-python-runtime:local")
TOKEN_FILE = Path(os.getenv("PYTHON_SANDBOX_TOKEN_FILE", "/run/masar-sandbox/token"))


def initialize_token(path=TOKEN_FILE):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "w") as file:
            file.write(secrets.token_hex(32))
    if os.getuid() == 0:
        os.chown(path.parent, 10001, 10001)
        os.chown(path, 10001, 10001)
    os.chmod(path.parent, 0o700)
    os.chmod(path, 0o400)
    token = path.read_text().strip()
    if len(token) != 64:
        raise ValueError("Invalid sandbox token file")
    return token


def validate_request(value):
    if not isinstance(value, dict) or set(value) != {"code", "inputs", "limits"}:
        raise ValueError("Invalid Python request fields")
    if not isinstance(value["code"], str) or not 1 <= len(value["code"]) <= 12000:
        raise ValueError("Code limit")
    if not isinstance(value["inputs"], dict) or len(value["inputs"]) > 32:
        raise ValueError("Inputs limit")
    limits = value["limits"]
    ranges = {
        "timeout": (2, 15),
        "cpu_seconds": (1, 15),
        "memory_mb": (128, 512),
        "output_chars": (512, 16000),
    }
    if not isinstance(limits, dict) or set(limits) != set(ranges):
        raise ValueError("Invalid limits")
    for key, (low, high) in ranges.items():
        if type(limits[key]) is not int or not low <= limits[key] <= high:
            raise ValueError("Invalid resource limits")
    if limits["cpu_seconds"] > limits["timeout"]:
        raise ValueError("CPU limit exceeds deadline")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_INPUT:
        raise ValueError("Input limit")
    return encoded


def container_command(name, limits):
    # All security flags, image and entrypoint are operator-owned, never supplied by code.
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--pull=never",
        "-i",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user=65534:65534",
        "--pids-limit=16",
        "--cpus=1",
        "--memory=" + str(limits["memory_mb"]) + "m",
        "--memory-swap=" + str(limits["memory_mb"]) + "m",
        "--ulimit=core=0:0",
        "--ulimit=nofile=32:32",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
        "--workdir=/tmp",
        "--env=OPENBLAS_NUM_THREADS=1",
        "--env=OMP_NUM_THREADS=1",
        "--env=MKL_NUM_THREADS=1",
        IMAGE,
    ]


def execute(value):
    try:
        encoded = validate_request(value)
    except (ValueError, TypeError, RecursionError):
        return {"error": "SCIENTIFIC_INPUT_LIMIT"}
    if not SLOTS.acquire(blocking=False):
        return {"error": "SCIENTIFIC_SANDBOX_BUSY"}
    name = "masar-python-" + uuid.uuid4().hex
    process = None
    try:
        limits = value["limits"]
        deadline = time.monotonic() + limits["timeout"]
        # A bounded trusted temporary input file avoids stdin pipe deadlocks.
        with tempfile.TemporaryFile() as stdin, selectors.DefaultSelector() as selector:
            stdin.write(encoded)
            stdin.seek(0)
            process = subprocess.Popen(
                container_command(name, limits),
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            output = bytearray()
            total = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"error": "SCIENTIFIC_TIMEOUT"}
                for key, _ in selector.select(min(0.1, remaining)):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > MAX_WIRE:
                        return {"error": "SCIENTIFIC_OUTPUT_LIMIT"}
                    if key.fileobj is process.stdout:
                        output.extend(chunk)
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if process.returncode:
                return {"error": "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT"}
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError("Invalid runtime output")
            # Child output is data, not an authenticated claim; the app validates it again.
            if (
                len(json.dumps(result, ensure_ascii=False, allow_nan=False))
                > limits["output_chars"]
            ):
                return {"error": "SCIENTIFIC_OUTPUT_LIMIT"}
            return result
    except subprocess.TimeoutExpired:
        return {"error": "SCIENTIFIC_TIMEOUT"}
    except OSError:
        return {"error": "SCIENTIFIC_SANDBOX_UNAVAILABLE"}
    except (ValueError, TypeError, RecursionError):
        return {"error": "SCIENTIFIC_PROCESS_FAILURE"}
    finally:
        # Killing the CLI alone does not stop its container. Always remove the entire
        # container/cgroup, including grandchildren, even on timeout/invalid JSON.
        try:
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            process.stdout.close()
            process.stderr.close()
        SLOTS.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    token = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(25)

    def log_message(self, *_):
        pass  # Never log code, inputs, outputs or auth headers.

    def reply(self, status, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != "/health":
            return self.reply(404, {})
        try:
            ready = (
                subprocess.run(
                    ["docker", "image", "inspect", IMAGE],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    check=False,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            ready = False
        self.reply(200 if ready else 503, {"ready": ready})

    def do_POST(self):
        if self.path != "/execute":
            return self.reply(404, {})
        if not self.token or not hmac.compare_digest(
            self.headers.get("Authorization", "").encode(),
            ("Bearer " + self.token).encode(),
        ):
            return self.reply(401, {})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Transfer-Encoding") or not 1 <= length <= MAX_INPUT:
                return self.reply(413, {})
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.reply(400, {})
            value = json.loads(raw)
        except (ValueError, OSError, RecursionError):
            return self.reply(400, {})
        self.reply(200, execute(value))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8
    threads = threading.BoundedSemaphore(16)

    def process_request(self, request, client_address):
        if not self.threads.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.threads.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.threads.release()


if __name__ == "__main__":
    Handler.token = initialize_token()
    Server(("0.0.0.0", 8080), Handler).serve_forever()
