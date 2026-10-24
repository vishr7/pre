# Scientific execution foundation

This package is independent of the Node notebook runtime. It installs no routes,
does not start FastAPI, and does not implement Docker, storage, reproduction, or
optimization. Python 3.10+ is required; use a version supported by the scientific
dependencies.

## Install, test, and trusted demonstration

From the repository root, in a virtual environment:

```powershell
py -3 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-science-dev.txt
$env:MPLCONFIGDIR = Join-Path (Get-Location) '.venv\matplotlib-config'
.venv/Scripts/python -m pytest tests/science -q
.venv/Scripts/python -m pre_science.worker --demo
```

The demo executes a fixed developer-authored NumPy example, prints real stdout,
metrics, runtime in seconds, seed, code SHA-256, and dependency versions. Its
local executor is confined to the demo branch. Never reuse it for submitted or
Gemini-generated code. Direct worker tests likewise use trusted test literals;
they do not test security isolation or deadline enforcement.

## Person 4: service and executor integration

```python
from pre_science import ExperimentService, ExperimentRequest

# docker_executor is supplied by Person 4 and implements ExperimentExecutor.
service = ExperimentService(docker_executor)
result = service.run(ExperimentRequest(
    experiment_id="experiment-123",
    code=approved_code,
    parameters={"alpha": 0.1},
    random_seed=42,
    timeout_seconds=30,
))
response = result.model_dump(mode="json")
```

`ExperimentExecutor.execute(request)` returns `ExecutionOutput`. The executor
serializes `request.model_dump_json()` to an isolated container's stdin, launches
`python -m pre_science.worker` with the package installed/importable, and parses
its stdout using `ExecutionOutput.model_validate_json(...)`. Code exceptions
produce structured output and process exit code 1; parse this output even when
the process exits nonzero. Infrastructure failures without valid worker output
raise `ExecutionFailure`. Unexpected adapter programming errors propagate.

The executor must supervise the deadline and kill the entire container on expiry,
returning `status="timeout"`, a nonzero exit code, and an `ExecutionError`. The
request timeout accepts integer seconds from 1 through 300. The worker does not
enforce deadlines, and the service does not interrupt a blocking executor.
Person 4 should run this synchronous interface outside FastAPI's async event loop.
Long jobs require a separately designed job/status API; the current frontend
aborts HTTP requests after 120 seconds.

Invalid specifications raise Pydantic `ValidationError` before execution. Map
these to backend validation errors. The existing client reads HTTP errors from
an `error` field. Service results distinguish `success`, `error`, and `timeout`;
partial metrics/stdout may remain on failure and are not successful results.
`exit_code` is the logical worker/adapter code, not necessarily a host signal.

The orchestration layer records a code hash, UTC submission time, total
orchestration duration, dataset identifier, and supplied metadata. The worker
reports its Python and installed dependency versions (null means unavailable).
These are worker versions, not backend versions. Dependency availability does
not guarantee an experiment's reproducibility. Python and NumPy legacy global
RNGs are seeded; experiments must pass `random_seed` to scikit-learn estimators,
NumPy `default_rng`, and other independently seeded algorithms themselves.

## Person 2: structured experiment proposals

Supply code, JSON parameters, seed, optional dataset identifier and metadata
through `ExperimentRequest`. Values must be JSON-compatible with no NaN or
infinity. Code is proposal data, not authorization to execute. Person 4 must
apply the project's approval policy and route it exclusively to restricted
execution. Dataset identifiers are references; this foundation does not download
or resolve datasets. Person 4 supplies approved mounted data separately.

Experiment code receives `parameters`, `random_seed`, `dataset_id`, and
`report_metric` as globals. It may import NumPy, Pandas, SciPy, scikit-learn,
and Matplotlib when installed from the science requirements.

## Explicit numerical metrics

```python
import numpy as np
data = np.array([10, 20, 30, 40, 50])
mean = float(np.mean(data))
std = float(np.std(data))
print("Mean:", mean)
print("Standard deviation:", std)
report_metric("mean", mean)
report_metric("std", std)
```

Expected values are 30.0 and approximately 14.142135623730951. Only deliberate
`report_metric(name, value)` calls produce metrics. Names must be nonblank text
up to 128 characters; values must be finite real numbers, excluding booleans.
Duplicate metric names raise an error. Arrays and implicit variable inspection
are unsupported. An experiment that reports nothing returns `{}`.

## Person 1: rendering and existing endpoint compatibility

Structured results expose experiment ID, status, stdout/stderr, duration in
seconds, exit code, metrics, artifacts, error, parameters, seed, and metadata.
Display metrics as name/value pairs and show failure status alongside partial
output. Render code output as escaped text.

The current `/api/tools/experiment` sends `{prompt, files, cells}` and expects
`{result: "Markdown"}`. Person 4 can pass that context to Person 2 for a structured
proposal, approve/validate it, invoke the service, and format the result as
Markdown without frontend changes:

```python
import json
payload = {"result": "Scientific execution result:\n\n```json\n"
           + json.dumps(result.model_dump(mode="json"), indent=2)
           + "\n```"}
```

For production rendering, escape untrusted strings/backticks or use a dedicated
safe formatter. Structured frontend presentation can be added by Person 1 later.

## Figures, artifacts, and security boundaries

`artifacts` is an empty list today. `Artifact` reserves name, media type, and
worker-relative path metadata for the next prompt. This foundation does not
capture figures or upload files. Matplotlib uses Agg. Person 4 must validate
future artifact paths and handle object storage; never expose worker paths as
public URLs directly.

The worker is NOT a security sandbox. It uses ordinary Python `exec`, redirects
Python stdout/stderr, and runs with its process's permissions. Native/subprocess
output can bypass Python capture or corrupt the JSON channel; the container
adapter must treat malformed output as execution failure. Code can access the
filesystem/environment, alter process state, allocate resources, or terminate
the process. Request validation and RNG seeding do not prevent these actions.

Before any untrusted execution, Person 4 must provide a fresh restricted Docker
container per job: non-root user, CPU/memory and output limits, enforced deadline,
disabled networking, restricted filesystem/mounts, no application secrets, and
no Docker socket exposure. No public arbitrary-code endpoint exists here.
Set `MPLCONFIGDIR` to a writable directory in the container's job workspace.
Worker output capture currently buffers in memory; outer resource limits are
required. Authentication, authorization, approval, cancellation, persistence,
and deployment remain backend responsibilities. Do not connect this worker to
the existing Node runtime as a production execution strategy.
