# Scientific integration handoff

## Run locally

From the repository root in PowerShell, using Python 3.11+:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-science-dev.txt
$env:MPLCONFIGDIR = Join-Path (Get-Location) '.runtime\matplotlib'
.\.venv\Scripts\python.exe -m pre_science.demo_end_to_end
.\.venv\Scripts\python.exe -m pytest tests/science -q
```

The demo needs no API keys or cloud services. It copies a bundled 15-row CSV,
explicitly drops incomplete and duplicate rows, trains a seeded decision tree on
12 rows, captures PNGs, repeats an actually measured local baseline, then runs
two sequential three-trial Optuna studies. Accuracy is a tiny validation-set
demonstration, not a published reproduction or independent generalization result.

The CLI prints the report path under `.runtime/end-to-end/<run>/report.json`.
That file preserves the complete `{result, scientific}` response, including
partial failures, trial errors, provenance, and artifact metadata. CSV and PNG
bytes remain alongside it. Keep them until storage handoff succeeds; call the
stores' explicit cleanup methods afterward. Generated files are ignored by Git.

## Person 1: frontend

The checkout currently uses React/Vite and Node, with `POST /api/tools/:mode`
accepting `{prompt, files, cells}` and expecting `{result: Markdown}`. Scientific
tool routes currently return 501. `pre_science.integration.tool_response(report)`
provides that string plus `scientific`, the full Pydantic report in JSON form.
It adds no routes and does not turn notebook cells into approved experiments.

Use `ExperimentResult` for status, stdout/stderr, metrics, errors and artifacts;
`ReplicationReport` for comparisons, tolerances, missing information and limitations;
`OptimizationResult` for all trials, failures, objectives and best parameters;
`DatasetSummary`/`DatasetProcessingResult` for summaries, logs and provenance.
Do not treat numerical agreement as scientific fidelity. Artifact references are
opaque local identifiers, not public URLs. Person 4 must authorize and serve or
upload their bytes. Notebook `images` data URLs and `durationMs` differ from
scientific artifact references and execution seconds; no automatic mapping exists.
The current client timeout is 120 seconds: longer jobs need Person 4's job/status
API and a corresponding frontend change.

## Person 2: AI

Existing Gemini services produce LaTeX edits, not scientific proposals. They are
not compatible with scientific contracts. Do not invent a conversion.
Use `validate_ai_proposal(kind, payload)` with `experiment`, `replicate` or
`iterate`; it validates the existing `ExperimentRequest`,
`ReplicationSpecification` or `OptimizationRequest` and rejects AI authorization.
Missing required fields produce Pydantic validation errors. Present sanitized
field errors to clients; do not send raw exception representations containing
input code, credentials or paths. No additional Gemini calls were introduced.

Experiment proposals still require trusted backend approval before execution.
Replication and optimization also enforce digest-bound `ResearcherApproval`.
Only trusted backend code may set `approved_by` and the digest after researcher
review. Editing code, data or parameters requires fresh approval. Starting an
optimization from replication requires separate approval. Actual measurements,
numerical comparisons, methodology completeness and optimized outcomes remain
separate evidence.

## Person 4: backend

The actual FastAPI app has health and JSON-file-backed project CRUD routes.
Authentication, Tiger Data persistence, Vultr artifact transfer, restricted Docker
execution, scientific routes and job orchestration are not implemented here.
No second backend or teammate-owned files were changed.

Inject the production executor into the existing services:

```python
from pre_science.experiment import ExperimentService
from pre_science.replicate import ReplicationService
from pre_science.iterate import IterationService
from pre_science.integration import tool_response, read_verified_artifact

experiments = ExperimentService(restricted_executor)
replication = ReplicationService(experiments)
iteration = IterationService(experiments)
# In an authenticated, authorized handler, with researcher-approved input:
report = replication.run(specification, available_dataset_ids=authorized_dataset_ids)
response = tool_response(report)
```

`restricted_executor.execute(ExperimentRequest) -> ExecutionOutput` is the
interface in `contracts.py`. Run the existing `python -m pre_science.worker`
stdin/stdout JSON protocol inside a fresh restricted container per trial; never
reuse the notebook kernel. Enforce deadlines, CPU/memory/process limits, disabled
network, non-root execution, restricted filesystem mounts, no application
secrets and no Docker socket access externally. No Docker protections have been
tested or supplied by this contribution.

Build dataset-ID mappings from authorized backend records, not client paths.
Use `DatasetService` with a controlled root and artifact store. Verify bytes with
`read_verified_artifact` before mounting approved data or uploading outputs.
Preserve source/processed hashes, transformation logs, approval/request/code
digests, dependency versions, timestamps, all trial errors and artifact metadata
in persistence. Resolve output references only through authorized store access.
Clean local files only after durable transfer succeeds. Never return internal
tracebacks/logs indiscriminately: reports may contain experiment-provided text.

Mount handlers on the existing app after authorization and restricted execution
exist. Reconcile the Node `/api/tools/:mode` proxy with those handlers. The app
currently allows CORS only from localhost:3000, while Vite uses 127.0.0.1:5173;
configure the intended development origins. `backend/routes/projects.py` also has
duplicate `ProjectFiles` declarations; the latter overrides the earlier
`max_length=200` constraint. Its owner should consolidate the declarations and
retain the intended limit. Neither issue was changed in Person 3's files.

## Repeatability and test scope

The earlier failed concurrent Iris demo's failed reports were not retained, so
its historical cause cannot be established. Available standalone reports passed;
that does not prove concurrency safe. No distributed or concurrent study support
is claimed. Execute studies sequentially with isolated process/filesystem state.

The trusted demo transport now uses fresh processes and job directories, filtered
environment variables, single-thread numeric libraries, and executor-local
Matplotlib cache. A code digest allowlist prevents accidental other-code use;
it is not a sandbox. Never expose this transport to user or Gemini code.
In-process worker calls also restore Matplotlib rcParams, including after errors;
they still share global random/module state and must not run concurrently.

`compare_optimization_runs` compares request digests, trial statuses, parameter
sequences and objectives, requiring every requested trial to succeed. Matching
failures do not count as reproducibility. Controlled mocked timeout tests verify
that runtime failures are distinguished from numerical variation; they do not
identify the historical failure's cause. The real CSV integration fixture runs
the full pipeline and repeats the study through fresh worker processes.

`tests/science` includes schema/orchestration mocks, direct trusted worker tests,
real subprocess model execution and the full CSV workflow. Backend smoke tests
are separate: install `backend/requirements.txt`, then run
`python -m pytest tests/test_backend_integration.py -q`; these use the actual
FastAPI routes with isolated temporary configuration and never load `.env`.
Neither suite validates a deployed service, real Gemini calls, Docker isolation,
authentication, Tiger Data or Vultr. See [science-integration.md](science-integration.md)
for the full service contracts.

## Verified in this checkout

Prompt 7 validation: scientific suite **219 passed, 1 skipped, 14 warnings**
(54.65 seconds); the skip is Windows symlink permissions and warnings are Agg
`show()` calls. Actual FastAPI smoke tests: **2 passed**, one dependency
deprecation warning. The standalone default demo completed: 15 to 12 rows,
baseline accuracy 1.0, all local reference metrics agreed, three successful
optimization trials repeated identically, best validation accuracy 1.0
(`max_depth=3`, `min_samples_split=7`), and nine verified artifacts (eight PNGs
and one processed CSV). This tiny dataset is chosen for deterministic plumbing
validation; the score does not establish model quality or useful optimization.
No cloud, production frontend route or Docker verification was performed.
