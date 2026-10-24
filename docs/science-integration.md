# Scientific execution foundation

This package is independent of the Node notebook runtime. It installs no routes,
does not start FastAPI, and does not implement Docker, cloud storage, reproduction, or
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
.venv/Scripts/python -m pre_science.demo_plots
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

## Figures and artifact handoff (implemented)

Experiments import `matplotlib.pyplot`, create figures normally, and may call
`plt.show()`. The worker forces the non-interactive Agg backend before execution;
show does not remove figures. Active figures are exported after execution, even
on a code error. Figures explicitly closed by experiment code before capture
are not available. The worker closes all figures before and after each job.
Agg may emit a non-interactive-backend warning for `show()`; this does not
prevent capture and is preserved as diagnostic output under normal execution.
Direct calls are sequential only: Matplotlib and Python output capture use
global state. Production must use a fresh process/container for each job.

Each PNG receives a random run directory and random filename. Experiment IDs
are metadata only and never form filesystem paths. Repeated runs with the same
experiment ID use different directories. Responses contain `FigureArtifact`
objects with artifact/experiment IDs, type `figure`, filename, MIME type
`image/png`, byte count, width/height in pixels, SHA-256, and an opaque
`artifact_reference` equal to the artifact ID. No image bytes or public URLs are
embedded. The old `Artifact` model remains accepted for executor compatibility;
the PNG handoff helpers accept only the new opaque figure IDs.

Defaults: 8 figures, 100 DPI, 4096 pixels per dimension, 16 million pixels per
figure, and 10 MB per PNG. Excess figures are skipped; dimension limits are
checked before rendering and again against the exported PNG header. A bounded
output buffer stops oversized PNG writes. Matplotlib rendering can still use
significant memory before export; external memory/CPU/time limits remain required.
The worker returns export/limit problems in
`execution_metadata.artifact_errors`. Numerical execution status, metrics, and
code errors remain intact; `status="success"` with artifact errors means that
computation succeeded but some figures were unavailable. Always inspect that list.
Other figures are captured when an individual export fails.

The worker defaults to `.runtime/science-artifacts` relative to its working
directory (already ignored by Git). Set `PRE_SCIENCE_ARTIFACT_ROOT` to a dedicated
controlled output mount for deployment. Set `MPLCONFIGDIR` to a writable job-local
configuration directory. Limits can be supplied by the trusted executor via
`run_worker(request, artifact_store=store, figure_limits=FigureLimits(...))`.
CLI workers use defaults; a container wrapper can call the same Python interface
to supply custom limits. Do not source output paths from experiment metadata.

Person 4 can retrieve a PNG from the same root or a shared mounted output root:

```python
import hashlib
from pre_science.plots import ArtifactStore

store = ArtifactStore(controlled_output_mount)
for artifact in result.artifacts:
    png = store.retrieve(artifact.artifact_id)
    if len(png) != artifact.size_bytes or hashlib.sha256(png).hexdigest() != artifact.sha256:
        raise ValueError("Artifact handoff integrity check failed")
    # Person 4: upload png to Vultr using image/png, then persist ownership,
    # experiment/artifact IDs, checksum and permanent object key in the database.
    # Only after both upload and metadata persistence succeed:
    store.cleanup(artifact.artifact_id)
```

Retrieval rejects arbitrary paths, malformed identifiers, symlinks, nonregular
files, oversized files, and non-PNG headers. Cleanup removes the identified PNG
and only an empty parent run directory. No automatic cleanup/expiry occurs:
failed uploads can be retried. Do not delete the output volume/container before
handoff, and do not call cleanup merely because execution finished. Person 4
owns retention/quota policy and orphan recovery after worker crashes.

IDs are locators, not authorization tokens. Person 4 must map each ID to its
experiment/owner before retrieval; no public serving endpoint is implemented.
The root must be controlled, not concurrently changed by untrusted processes.
Path checks do not defend against a process with arbitrary filesystem access
racing directory replacement. On Windows, do not allow untrusted junctions or
reparse points in the mount. Use container/filesystem isolation and validate
worker-produced bytes/metadata at the backend boundary. Retrieval's PNG header
check is not full validation of hostile images.

## Future display, persistence, and manuscript integration

Vultr uploads, database storage and authorized/signed download URLs belong to
Person 4 and are not implemented here. Person 1 can display those persisted URLs
in graph panels. An opaque artifact reference is not a browser URL. For later
manuscript insertion, retain an artifact-to-project asset mapping, materialize
the PNG under an approved project path such as `figures/<artifact-id>.png`, and
let Person 1 insert `\\includegraphics{figures/<artifact-id>.png}`. The compiler
must receive the actual PNG separately; the current text-file API does not
transfer binary artifacts. No frontend or LaTeX integration is added here.

The trusted `pre_science.demo_plots` module runs a sine-wave experiment through
the existing service/worker, retrieves the real PNG by ID, verifies its checksum,
and prints the structured result with retrieval evidence. It retains the PNG
for inspection. Use `store.cleanup(id)` explicitly when finished.

## Security boundaries

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
