# Unified Python computation

The answering model now has **one computation tool: `run_python`**. Arithmetic,
substitution, domains, derivatives, primitives, limits, unit/dimension checks,
statistics, simulations and generated graphs all use model-written ordinary
Python. Imports, functions, loops and comprehensions are allowed. Standard
library, SymPy, NumPy, SciPy and Pint are installed in the runtime image.

Library/router/private-file/note/final-answer tools are unchanged. Old numerical
handlers remain internal for historical compatibility and existing tests, but
are **not advertised and agent execution rejects non-advertised calls**. This
change does not reintroduce extraction agents or PDF import.

## Code/result protocol

Arguments: `code` (up to 12,000 characters), optional JSON `inputs` (up to 32
keys). Values are accessed through `inputs`, not injected as global variables.
Use `emit("name", JSON_value)` to return needed results; convert symbolic values
with `str()` and NumPy arrays with `.tolist()`. `print()` is bounded. Each call is
stateless; explicitly pass values needed from earlier results.

```python
import sympy as sp
x = sp.symbols("x", real=True)
f = x**3 - 2*x
primitive = sp.integrate(f, x)
check("primitive differentiates to original", bool(sp.simplify(sp.diff(primitive, x)-f) == 0), "real x")
emit("primitive", str(primitive))
```

`check(label, bool_or_None, details)` records a specific program-reported check.
A failed/inconclusive check propagates to existing mandatory warning handling.
Successful execution is always `computed`, **not independent certification**.
The model must test assumptions, original domains, constraints and appropriate
tolerances. Sampling a few points is not proof of a universal statement.

For an existing graph block, emit `chart` with a JSON object containing `title`,
`x_label`, `y_label`, `kind` (`line`, `scatter`, `bar`) and `series` of `{label,x,y}`.
There are 1–4 series, 2–401 points per series, finite coordinates; null y is a gap.
Line x values must increase; split poles/discontinuities into separate series.
Optional `diagram` follows the existing bounded geometry contract. Neither HTML
nor SVG nor generated file paths are accepted. `render_answer` receives only the
real returned `result_id`; the server supplies graph/result data.

Execution results retain user/chat/run ownership, code/input provenance, output
hash and cancellation/budget checks. No database migration is needed. Python
execution grants **no lesson/source credit** and cannot bypass grounding.

## Isolation (mandatory)

`python-sandbox` is an **internal trusted broker**, not the Python execution
process. It launches a fresh container for each call using a fixed runtime image,
no host mounts, no network, a read-only root filesystem, non-root UID, no
capabilities, no-new-privileges and Docker's default seccomp profile. A bounded
32 MiB temporary filesystem is available. The runtime image contains only its
bootstrap and libraries, not application data or credentials. The broker removes
the whole container on completion, errors, output overflow or deadline, including
child processes. Resource limits remain; there is no syntax/AST allowlist.

Only the broker gets the Docker socket. **Docker daemon access is root-equivalent
operator privilege**: do not expose the broker publicly, add public ports, mount
its socket in API/worker, mount platform data in the runtime, or disable container
security. Prefer a dedicated host/daemon for hostile multi-tenant workloads;
containers share a host kernel and are not VM-level isolation. Daemon availability
is required for reliable cleanup. No host `exec`/`eval`/subprocess fallback exists.

## Deployment

On the existing single-host Linux Docker deployment:

```sh
docker compose up -d --build
```

This builds the separate runtime/broker images, creates a private authentication
volume, initializes its token, waits for broker health and connects API/worker.
The library volume is preserved. Production HTTPS overlay inherits this wiring.
The internal sandbox network has no public port. API/worker mount only a read-only
auth volume; the runtime mounts neither it nor the library.

`SCIENCE_TIMEOUT=15`, `SCIENCE_CPU_SECONDS=10`, `SCIENCE_MEMORY_MB=512` are the new
defaults; limits stay configurable within the validated ranges. Existing `.env`
files retain older values until updated. The broker accepts at most two concurrent
executions, 64 KiB requests, bounded output and fixed resource ranges. Large code
or outputs can exceed the existing model/tool budget: shorten them, never truncate
or credit partial results. AI keys are not sent to this service.

Bare-host development needs `PYTHON_SANDBOX_URL` and
`PYTHON_SANDBOX_TOKEN_FILE` pointing to a configured internal broker. Empty URL,
missing token or unavailable Docker fails closed with an explicit tool error.
Use Compose rather than starting unrestricted code in the application process.

## Verification

Unit tests use fixed **trusted** Python programs or a mock HTTP broker; direct
bootstrap tests are not a security test or production fallback. Real isolation
integration tests are opt-in:

```sh
docker build -f deploy/python-sandbox/runtime.Dockerfile -t masar-python-runtime:local .
MASAR_PYTHON_DOCKER_TESTS=1 python -m pytest tests/test_python_sandbox.py -q
```

CI additionally builds the broker, checks real runtime limits/no network/no host
files/no secrets, cleanup, and a Compose-to-app authenticated smoke test. No real
AI/provider request is made. Run a real student conversation separately after
merging and rebuilding to evaluate generated code/teaching quality; these tests
are not a claim that the model always chooses the correct program.
