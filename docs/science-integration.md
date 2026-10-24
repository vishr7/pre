# Scientific execution foundation

This package is independent of the Node notebook runtime. It installs no routes,
does not start FastAPI, and does not implement Docker or cloud storage.
Python 3.10+ is required; use a version supported by the scientific
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
.venv/Scripts/python -m pre_science.demo_data
.venv/Scripts/python -m pre_science.demo_replicate
.venv/Scripts/python -m pre_science.demo_iterate
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

## CSV inspection and approved processing (implemented)

`pre_science.data.DatasetService` accepts dataset IDs rather than client-supplied
host paths. Person 4 supplies an authorization mapping for the current caller,
mapping each approved ID to a relative `.csv` reference under a controlled input
root. No upload endpoint, cloud client, or database access is implemented here.

```python
from pre_science.data import DatasetService, DatasetArtifactStore, DatasetLimits

store = DatasetArtifactStore(controlled_output_root)
service = DatasetService(
    controlled_input_root,
    authorized_datasets={"study-123": "uploads/study.csv"},
    artifact_store=store,
    limits=DatasetLimits(),
)
summary = service.inspect({"dataset_id": "study-123"})
result = service.process({
    "dataset_id": "study-123",
    "transformations": [
        {"operation": "drop_missing", "columns": ["label"]},
        {"operation": "drop_duplicates"},
        {"operation": "fill_median", "columns": ["age", "score"]},
        {"operation": "standardize", "columns": ["age", "score"], "ddof": 0},
    ],
})
```

Pydantic rejects unknown operations/options, duplicate/blank column selections,
missing explicit columns (except `drop_duplicates`), and overlong pipelines.
All columns are checked against the current frame at each step. Service calls
must represent researcher-approved operations; the service does not infer
approval from an AI proposal and never chooses a cleaning strategy.

Inspection returns shape, column names/dtypes, missing and unique counts,
numeric/non-numeric/categorical column lists, duplicate rows beyond their first
occurrence, and count/mean/population std/min/25th percentile/median/75th
percentile/max for numerical columns. Non-numeric columns (including booleans)
are classified as categorical; category values and entire datasets are not
included in ordinary reports. Unavailable/overflowed statistics are null, with
warnings, rather than non-JSON NaN/Infinity values.

Input is strict UTF-8 (optional BOM), comma-delimited, with unique nonblank
headers and a consistent field count. Quoted commas/newlines are supported.
Blank physical records are rejected rather than silently dropping rows. The
explicit NA spellings are empty fields, `NA`, `NaN`, `nan`, `NULL`, and `null`;
other strings/whitespace remain data. Pandas infers dtypes; mixed numeric/text
columns remain non-numeric and numerical operations reject them. Empty/headerless
files are rejected; header-only zero-row CSVs are valid and carry warnings.
Infinity spellings and non-finite numeric values are rejected, never silently
imputed. Python's CSV reader also applies its field-size limit (typically 128 KiB).

Defaults: 10 MB input, 20 MB output, 100,000 rows, 200 columns, 2 million cells,
100 MB estimated DataFrame memory, and at most 50 operations. `DatasetLimits`
configures these with bounded maxima. The CSV output stream enforces its byte
limit while writing. These application limits do not replace isolated-process
CPU/memory/time limits: decoding and parsing allocate memory before a DataFrame
estimate is available. No secrets or arbitrary source bytes appear in validation
errors. Invalid source files raise `DatasetError`; invalid request structures
raise Pydantic `ValidationError` before loading.

Supported operations and exact semantics:

| Operation | Behavior |
| --- | --- |
| `drop_missing` | Remove rows missing any selected column. |
| `fill_mean`, `fill_median` | Compute from observed numeric values and fill only missing cells. |
| `drop_duplicates` | Keep the first row for all columns, or the explicitly selected subset. |
| `standardize` | `(x - mean) / std`; `ddof=0` by default, optionally `1`. |
| `minmax` | `(x - min) / (max - min)` into `[0, 1]`. |
| `select_columns` | Retain exactly the selected columns in the supplied order. |
| `drop_columns` | Remove selected columns; removing all columns is rejected. |

Constant columns cannot be standardized/scaled; insufficient observations or
all-missing numeric columns cannot be imputed/normalized. These are explicit
failures, not invented zeros. Normalization excludes missing observations from
statistics and retains missing cells, with a warning. No silent imputation or
type coercion from text is performed. Selected numeric columns are processed as
float64 and dtype changes are logged. No-operation processing preserves original
bytes; transformed output uses UTF-8, LF line endings, no index, and empty fields
for missing values. CSV output does not preserve lexical formatting or dtype
annotations; the report records dtypes, and the consumer may need explicit
dtype configuration on reload. Formula-looking text is retained as research
data: do not open untrusted CSVs in a spreadsheet without appropriate protection.

## Transformation reports, provenance, and dataset handoff

Every attempted operation generates an ordered `TransformationLogEntry` with
operation, actual target columns/options, before/after rows and column names,
before/after dtypes, actual rows removed, changed-cell counts for numerical
operations, actual computed values (fill counts/values, mean/std/ddof or
min/max/range), status, and warnings/errors. Changed-cell counts exclude
missing-to-missing cells and values equal before/after. Failed operations are
atomic: no partial changes from that step are committed, the failed entry is
included, later steps are not attempted, and no processed artifact is exported.
The provenance's final shape then describes the last successful in-memory step;
`final_summary`, artifact, and processed hash remain null. Export failures are
also returned as structured `status="error"` results.

Successful results include original/final summaries and an artifact. Provenance
records the dataset ID, original basename, hashes of the actual source/output
bytes, original/final shapes, UTC processing time, Pandas/NumPy versions, and a
SHA-256 of canonical JSON transformation logs. No AI-derived statistics or
fabricated source descriptions are used. Person 2 can turn those measured logs
into a Methods paragraph; preserve order, actual values, and failure/warning
status. These logs describe fitted preprocessing on this dataset, not a reusable
train/test transformer: fit preprocessing on training data only to avoid leakage.
Person 1 can display summaries and chronological logs without receiving raw rows.

`DatasetArtifactStore` is separate from the PNG-only store and uses compatible
opaque `<random-run>-<random-file>` IDs, per-run directories and metadata
(`artifact_type="dataset"`, `mime_type="text/csv"`, filename, byte count,
dataset ID, source/output/history hashes, processing ID, artifact reference).
Default output root is `.runtime/dataset-artifacts`; applications should pass
their own dedicated controlled output mount. No new environment setting is
required. Output IDs never contain dataset IDs or user-provided filenames.

```python
import hashlib

if result.status == "success":
    artifact = result.artifact
    csv_bytes = store.retrieve(artifact.artifact_id)
    assert hashlib.sha256(csv_bytes).hexdigest() == artifact.sha256
    # Person 4: persist CSV bytes to Vultr and the result/logs/ownership metadata
    # to the database. Only after both have succeeded:
    store.cleanup(artifact.artifact_id)
```

Cleanup is explicit and idempotent; files survive processing and failed upload
attempts. It removes just the identified file and its empty parent directory,
never recursively deletes other artifacts. Person 4 owns retention and orphan
recovery. Input datasets are never modified or removed. Retrieval IDs are
locators, not permission grants: authorize ownership before retrieving. Relative
reference validation, containment, regular-file checks and symlink/junction/
hardlink rejection prevent ordinary path traversal. Controlled roots must not
be concurrently writable by untrusted processes; path checks are not a sandbox
or a defense against filesystem replacement races. Use isolated inputs without
secrets. Only authorized CSV bytes are eligible for processing.

## Consuming processed datasets in experiments

`artifact.to_reference()` returns a `ProcessedDatasetReference` with dataset ID,
opaque artifact reference, output SHA-256, source SHA-256 and history SHA-256.
Person 4 must authorize the reference, retrieve the bytes, verify the checksum,
and materialize only that approved file into a restricted worker's read-only
input mount (for example `/input/dataset.csv`). Never mount arbitrary host
directories or give experiments backend storage credentials. The current worker
does not fetch artifacts or create mounts.

Use the existing `ExperimentRequest.dataset_id` and
`metadata={"processed_dataset": artifact.to_reference().model_dump(mode="json")}`.
The existing experiment service preserves these identifiers/hashes under
`execution_metadata.dataset_id` and `execution_metadata.request_metadata`.
The backend adapter must validate this metadata against the persisted report;
caller-supplied metadata is not proof of provenance. Approved experiment code
can load the mounted path via Pandas, optionally receiving a worker-local path
through `parameters`. No experiment API or execution/figure code was changed.

`python -m pre_science.demo_data` creates a deterministic study CSV inside a new
ignored `.runtime/dataset-demo/<run>` directory and performs label filtering,
duplicate removal, median imputation, standardization, and CSV retrieval. It
prints the complete real inspection/report and retrieved CSV, retaining artifacts
for inspection. No actual `.env` or external dataset is read.

## PRE Replicate: approved reconstruction and numerical validation

`pre_science.replicate.ReplicationService` wraps the existing `ExperimentService`.
It does not execute code, fetch datasets, invoke Gemini, install dependencies,
or create another backend. Execution, PNG artifacts, and CSV preprocessing keep
their existing interfaces. New schemas reside in `pre_science.schemas`.

`ReplicationSpecification` distinguishes source metadata from reconstruction:
paper title, optional authors/identifier/year, source kind, method and experiment
title, optional declared dependencies, published parameters/seed, actual
reconstruction parameters/seed, evaluation metrics, published scalar metrics,
implementation code, dataset provenance, and limitations. Missing information
stays null or explicitly listed; nothing is extracted or invented from code.
Use `source_kind="local_baseline"` for demonstrations, `"publication"` for a
publication provided by the researcher, and `"unverified"` when unknown. Source
kind is a declaration, not independent bibliographic verification.

Each `PublishedMetric` requires an explicit nonnegative finite
`absolute_tolerance` and `relative_tolerance`; no scientific tolerances are
silently selected. A null reference value represents unavailable source results;
strings, NaN and infinity in proposed numerical results fail Pydantic validation.
The standalone `compare_metric` utility safely reports unavailable comparisons
for nonnumeric, nonfinite, or missing input without leaking non-JSON values.
Unknown fields, duplicate metric names, invalid seeds/timeouts, and nonfinite
parameter values are rejected before execution.

### Approval and inputs

Person 2 submits an **unapproved** specification. Person 4 validates project
access, presents the complete proposal to the researcher, and records approval
against `specification_digest(proposal)`. The digest includes code, references,
tolerances, parameters, dataset metadata, and limitations, excluding only the
approval record itself. Edits to any proposal data invalidate the recorded hash.

```python
from pre_science.experiment import ExperimentService
from pre_science.replicate import ReplicationService, specification_digest
from pre_science.schemas import ReplicationSpecification, ResearcherApproval

proposal = ReplicationSpecification.model_validate(extracted_proposal)
# Person 4: only after authenticated researcher review; never trust an AI/client
# payload that claims it is already approved. Store this approval server-side.
proposal.approval = ResearcherApproval(
    approved=True, approved_by=authenticated_researcher_id,
    specification_sha256=specification_digest(proposal),
)
report = ReplicationService(ExperimentService(isolated_executor)).run(
    proposal,
    available_dataset_ids=backend_verified_dataset_ids,
    available_asset_ids=backend_verified_asset_ids,
)
response = report.model_dump(mode="json")
```

Missing, incomplete, or stale approval returns `approval_required` with the full
proposal retained and no executor call. This library does not authenticate an
`approved_by` string: Person 4 must establish approval from trusted account
state, rather than exposing a raw approval switch in an execution endpoint.

An approved proposal needs code, explicit reconstruction parameters (`{}` means
none), an explicit reconstruction seed, and an explicit `dataset_required`
decision before execution. No default seed or scientific parameter choice is
introduced to fill missing source information. The published seed can remain
unknown while the researcher explicitly chooses a reconstruction seed; the
methodology is then partial. A missing implementation input returns
`missing_inputs`, never silent substitution. Other missing methodology may
allow execution while reducing the completeness assessment.

Required datasets and assets/weights must appear in the backend's verified
availability context. Listing a reference in the proposal does not establish
access. Person 4 resolves **the exact approved dataset/artifact version**,
checks ownership and hashes, and mounts only authorized files into the isolated
worker before supplying that context. `dataset_required=False` means the
implementation is self-contained; it cannot accompany an external dataset
reference. Missing original source datasets/code/weights are also recorded as
limitations; approved proxy implementations may run but remain approximate.
Required dependency strings are declarations, not an automated installation or
version-equivalence check. Worker import failures remain execution failures.

### Numerical rule and scientifically conservative interpretation

For every reference metric the reusable comparison utility applies:

```text
abs(reproduced - published) <= absolute_tolerance + relative_tolerance * abs(published)
relative_difference = absolute_difference / abs(published)
percentage_difference = 100 * relative_difference
```

No rounding or hidden epsilon precedes comparison. Decimal arithmetic on the
exact binary64 input representations avoids overflow falsely turning a failure
into `infinity <= infinity`. Published values therefore have their supplied
floating-point meaning, including at tolerance boundaries. Relative/percentage
differences are null for a zero reference. Differences outside finite JSON float
range, or below its resolution, are null with warnings; agreement is still
computed without overflowing. This is a scalar tolerance check, not statistical
significance testing or confidence-interval overlap.

Per-metric results contain reference/actual values, differences, tolerances,
agreement, status, and unavailable reasons. Missing actual metrics remain
missing; extra actual metrics are separately listed without invented references.
`numerical_assessment` distinguishes `all_comparable_agree`,
`some_metrics_differ`, `no_comparable_metrics`, `execution_failed`, and
`not_executed`. `all_comparable_agree` can cover only a subset: consult each
comparison and `all_published_metrics_agree`, which is null if required reference
comparisons are unavailable (unless a known disagreement already makes it false).
Failures/timeouts preserve actual partial metrics/logs in the execution evidence
but never treat them as successful numerical reproduction.

Methodology completeness is separate:

- `insufficient_information`: required execution inputs are unavailable.
- `approximate_reconstruction`: assumptions, substitutions, unavailable original
  resources, declared condition mismatches, or parameter/seed changes are present.
- `partially_specified`: source conditions or methodology/results are unknown,
  incomplete, or the source is unverified.
- `fully_specified`: the supplied declarations include the method, parameters,
  seed, dependencies, evaluation/results, dataset description/hash when needed,
  and explicitly known/matching source conditions, without listed gaps or changes.

Even `fully_specified` is a classification of supplied declarations, not proof
that the code implements the paper. Numerical agreement never yields a
"scientifically validated" verdict. The service does not verify units, metric
definitions, train/test splits, hardware, dependency equivalence, algorithmic
fidelity, or the truth of a publication's reported results. Record those details
and uncertainties in the proposal and its limitations before approval.

### Reports, datasets, figures, and team integration

`ReplicationReport` includes the original specification, approval digest, paper
metadata, statuses, published/actual/extra metrics, comparisons, methodology
assessment, missing inputs/details, assumptions, dataset provenance, executed
code hash, actual parameters/seed, worker dependency versions, PNG metadata,
duration and UTC report time. Its nested `execution` is the unabridged existing
`ExperimentResult`, including stdout/stderr, errors, partial metrics, and all
execution metadata. If code has not run, execution evidence/duration/code hash
are null, not fabricated. A deterministic plain-text `summary` is derived from
these fields, with explicit warnings against interpreting agreement as proof.

`ReplicationDataset` reuses `ProcessedDatasetReference` and
`TransformationLogEntry` from Prompt 4, with optional original artifact/hash and
dataset description. Original/processed source hashes and logical dataset IDs
must agree. Dataset provenance and approved proposal digest are passed through
the existing experiment metadata. The service never resolves local paths from
these identifiers. Figures use the existing `FigureArtifact` metadata and
`ArtifactStore`; no PNG payloads or fake public URLs are added.

Person 1 can render structured per-metric comparisons, missing-information
messages, completeness and numerical indicators independently, and authorized
persisted figure URLs supplied by Person 4. Person 2 validates Gemini output
against `ReplicationSpecification`, preserves unknowns/assumptions, and may
explain the actual structured report; it must never replace worker metrics.
Person 4 owns approval integrity, project/resource access, isolated execution,
data mounts, error-to-HTTP mapping, storage of reports/artifacts, authorization
of returned data, and explicit cleanup after persistence. Provider/error/log
sanitization remains a backend boundary: do not return arbitrary infrastructure
exception text to public clients. No teammates' routes or UI are changed.

`python -m pre_science.demo_replicate` executes trusted fixed NumPy code via the
real worker against an explicitly identified **local demonstration baseline**:
mean `30.0` and population std `14.142135623730951` for `[10,20,30,40,50]`.
It also executes a separately approved proposal with the mean reference changed
to `31.0`, demonstrating a real numerical discrepancy. Both reports preserve
actual outputs, dependency versions, code hashes, seeds and PNGs; PNG retrieval
is checked. These results are not an independently reproduced publication.

## PRE Iterate: bounded Optuna optimization

`pre_science.iterate.IterationService` uses a seeded standard Optuna TPESampler
and an in-memory study. Each sequential trial calls the existing
`ExperimentService`; no new workers, routes, storage clients, or dependencies
are introduced. The sampler's default startup behavior is retained, so small
studies may consist entirely of its initial random exploration.

```python
from pre_science.iterate import IterationService, optimization_digest
from pre_science.schemas import OptimizationRequest, ResearcherApproval

request = OptimizationRequest.model_validate({
    "study_id": "tree-search", "experiment_id": "source-tree-experiment",
    "code": approved_source_code,
    "base_parameters": {"validation_fraction": 0.3},
    "search_space": {
        "max_depth": {"type": "int", "low": 1, "high": 10},
        "learning_rate": {"type": "float", "low": 0.001, "high": 0.1, "log": True},
        "criterion": {"type": "categorical", "choices": ["gini", "entropy"]},
    },
    "objective_metric": "accuracy", "direction": "maximize",
    "n_trials": 8, "max_duration_seconds": 120,
    "trial_timeout_seconds": 20, "random_seed": 42,
})
# The example search syntax is illustrative: the approved code must implement
# every chosen parameter (e.g. decision trees do not use learning_rate).
# Person 4: only after authenticated approval of this complete request:
request.approval = ResearcherApproval(
    approved=True, approved_by=authenticated_researcher_id,
    specification_sha256=optimization_digest(request),
)
report = IterationService(experiment_service).run(
    request, available_dataset_ids=backend_verified_dataset_ids,
    available_asset_ids=backend_verified_asset_ids,
    should_stop=backend_job_stop_requested,
)
```

Fixed and sampled parameter names must be disjoint. Pass only fixed values in
`base_parameters`; remove keys intentionally selected for optimization. Numeric
bounds must be finite and ordered. Integer bounds are limited to +/-1 billion,
with aligned positive steps; log integers require positive bounds and step 1.
Float bounds are limited to +/-1e12; log floats require positive bounds.
Categorical choices are 1–32 distinct JSON scalars, strings at most 512
characters, and numerical magnitudes at most 1e12. Equivalent choices such as
`true` and `1` are rejected. Names must be identifiers of at most 64 characters;
there are at most 20 varied parameters. Unsupported types, NaN/infinity,
empty spaces, duplicate-equivalent choices, and conflicting fixed keys fail
Pydantic validation before execution.

Parameters remain exclusively inside `ExperimentRequest.parameters`, accessed
by approved code as `parameters["max_depth"]`. No source substitution is used.
They are never merged into environment variables, approval, timeout, mounts,
networking, or other execution-control fields. The same explicit seed is used
for the sampler and for every experiment, enabling fixed splits and comparable
trial conditions when code uses the provided `random_seed`. Sequential sampling
is canonicalized by parameter name so JSON key ordering does not change it.

### Authorization, limits, and fresh state

Approval reuses `ResearcherApproval` but is bound to the **optimization** digest,
including code, dataset, search space, objective, direction, seed, trial count,
budgets, fixed parameters, and any reproduction origin. Reproduction approval
is not optimization approval. A missing/stale record returns
`approval_required` with no trial execution. As with PRE Replicate, backend
authentication and persisted approval integrity are required; a client-provided
`approved_by` string is not authentication.

The MVP permits 1–50 trials, a 1–900 second study budget, and 1–300 second
per-trial timeout. Before scheduling each trial, the service checks its monotonic
clock and optional backend stop callback. It rechecks the clock after sampling
and before execution. It stops if fewer than one full second
remains, since the existing experiment contract uses integer-second deadlines.
The requested trial timeout is capped to the remaining whole seconds. A timeout
or stop retains all collected trials and any best observed result. A stop check
acts between trials, not inside a running one. This scheduler cannot forcibly
interrupt `ExperimentService.run`; Person 4 must enforce actual worker deadlines
and resource quotas. A noncompliant executor can overrun the wall-clock budget,
which the result reports honestly as `time_limit`.

Each trial has a unique execution ID and fresh `ExperimentRequest`. Metadata
includes source experiment, study/run IDs, trial number, approval digest,
dataset provenance and `fresh_state_required=true`. **The production executor
must actually create fresh process/container state for every request.** A new
request object alone does not reset imported modules, working directories,
filesystem state, RNGs in external libraries, or native process state. Never
route optimization through persistent notebook namespaces. The existing worker
still owns code execution, seeding, explicit metrics, errors and PNG capture.

Dataset/asset references use PRE Replicate's existing schemas and availability
context. Person 4 must authorize, verify hashes, and mount the exact approved
versions; identifiers alone cannot establish availability. The service does
not resolve filesystem paths or obtain storage credentials.

### Objectives, failures, reports, and chart data

Only `execution.metrics[objective_metric]`, explicitly emitted by
`report_metric`, can become an objective. Missing metrics, invalid/nonfinite
structured results, code exceptions, worker timeouts and invalid parameter
combinations fail the trial without manufacturing a score. Subsequent trials
continue. Unexpected adapter exceptions use a fixed error message, not raw
exception text that may contain secrets. Valid worker error/metadata evidence
is retained for authorized backend debugging.

`OptimizationResult` distinguishes `completed`, `failed`, `time_limit`, `stopped`,
`approval_required` and `missing_inputs`. `completed` means all requested trials
were attempted with at least one successful objective; inspect successful and
failed counts separately. All failures yield `failed` and null best fields.
A successful worker execution with a missing objective is still a failed
optimization trial, with `execution_status="success"` and `MissingObjective`.
Malformed output cannot be retained as an `ExperimentResult`; its trial is
marked `invalid_result` and no invalid numerical values enter JSON.

Each trial contains suggested and full merged parameters, unique execution ID,
objective or null, trial/execution statuses, errors, measured durations,
execution metadata, artifacts, and the full existing `ExperimentResult` when
valid. The report includes request/digest, proposed code hash, seed,
Optuna/sampler version, source dataset/reproduction provenance, actual study
duration, timestamps, best trial, and best full/sampled parameters. A code hash
on a nonexecuted study identifies proposed code, not evidence that it ran.
Existing per-trial metadata contains the actual executed code hash and worker
dependency versions.

`history` contains trial number, actual objective or null, best-so-far objective
or null, and status. Failed trials never receive fabricated penalty values.
Person 1 can plot this directly and pair it with each trial's configuration;
objective `0.0` is a valid result, not missing. Strict improvements update the
best record; ties retain the earliest successful trial. Best means best
**observed within the search**, not a global optimum.

### Starting from PRE Replicate and team responsibilities

`optimization_from_replication(report, study_id=..., search_space=...,
objective_metric=..., direction=..., n_trials=..., max_duration_seconds=...)`
creates an unapproved request from a successful reproduction's actual parameters,
seed, code and dataset provenance. It verifies the source code hash, removes
explicitly varied keys from fixed parameters, and records a `ReplicationOrigin`
with original experiment/digest, code hash, baseline metrics and report timestamp.
It never mutates the reproduction report or reuses its approval. Optimized
results are separate experimental outcomes and cannot be labeled faithful
reproductions merely because a selected metric improved.

Person 2 may propose validated search spaces and interpret measured outcomes,
but cannot authorize execution or substitute objective values. Person 4 owns
access checks, approval, exact dataset mounts, isolated workers, job scheduling,
stop state and report/artifact persistence through existing backend services.
There is no persistent Optuna database or resume support. Person 1 receives
structured history, parameters, failure states, and authorized artifact links;
no frontend changes are implemented here.

`python -m pre_science.demo_iterate` performs two real six-trial Iris decision-tree
studies with the same seed/configuration, checking that parameter sequences and
accuracy values match. Each trial runs through the existing worker CLI in a
fresh subprocess with a filtered environment. This helper executes **trusted
developer-authored code only**, is not a sandbox and must not be connected to
user/Gemini input. It trains real models on a fixed stratified training/validation
split and emits `accuracy` explicitly. Because that validation split guides
selection, the selected score is **not independent test/generalization evidence**.
No dataset download or published-paper reproduction is involved.

Repeated seeded sequences require the same Optuna/library versions and
deterministic experiment code. Early time/stop limits and execution failures can
change the sampled sequence, and seeds cannot guarantee deterministic hardware
or every third-party algorithm. Trials can generate many artifacts; Person 4
must persist or explicitly clean them up under a storage quota. CPU/memory limits,
disabled networking, restricted filesystems and absence of backend secrets must
be enforced outside this service before any untrusted execution.

## Execution security boundaries

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
