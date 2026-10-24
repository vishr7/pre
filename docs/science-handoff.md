# Scientific integration handoff

## Statistical validation (Prompt 10)

`pre_science.statistics` provides `StatisticalRequest`, `StatisticalReport`,
`DescriptiveStatistics`, `ConfidenceInterval`, `EffectSize`,
`analyze_statistics(request)` and `statistics_from_robustness(...)`. There is no
execution, AI, storage or public endpoint in this engine; NumPy/SciPy perform all
calculations. Tests are explicitly selected, never chosen by a normality check.

```python
from pre_science.statistics import StatisticalRequest, analyze_statistics

request = StatisticalRequest(
    analysis_id='comparison-1', method_a='Method A', method_b='Method B',
    observations_a=[1.0, 3.0, 5.0], observations_b=[0.0, 2.0, 4.0],
    test='welch', alternative='two-sided', alpha=0.05,
    source_ids=['stored-study-a', 'stored-study-b'],
    provenance={'description': 'Illustrative input syntax, not executed findings'},
)
payload = analyze_statistics(request).model_dump(mode='json')
```

Available tests: `welch` (SciPy `ttest_ind(equal_var=False)`), `paired_t`
(`ttest_rel`, requires `paired=True` and equal lengths) and `mann_whitney`
(`mannwhitneyu(method='auto')`, independent groups). All support `two-sided`,
`greater` and `less`. MVP inputs require 2–10,000 finite observations per group;
no missing values or numeric strings are coerced/dropped. No automatic test
fallback or data cleaning occurs. Paired order is preserved; equal length alone
does not justify pairing. `greater` means method A exceeds B.

Reports retain the full validated input, source IDs, provenance and optional
units, test/hypothesis/direction, group descriptions, paired-difference
descriptions, statistic, degrees of freedom, p-value, alpha, strict `p < alpha`,
mean difference A−B, confidence interval, effect size, warnings, limitations,
dependency versions and UTC timestamp. Descriptions include n, mean, sample SD
(ddof=1), median, min/max and SE=s/sqrt(n). The human-readable `summary` is
deterministic; report timestamps intentionally change. Original input is untouched.

Welch SE=sqrt(s_A²/n_A+s_B²/n_B) and Welch–Satterthwaite degrees of freedom;
paired SE=SD(A−B)/sqrt(n), df=n−1. Intervals use difference ± t(1−alpha/2,df)×SE.
They are explicitly **two-sided at 1−alpha even for one-sided tests**, so interval
exclusion of zero is not interchangeable with one-sided test rejection.
No Mann–Whitney mean/median interval is implemented. Its mean difference is
descriptive, not the quantity tested by U. Zero SE, numerical overflow and
undefined test values produce unavailable fields/reasons, never JSON NaN/Inf.
No infinite effect sizes are returned for zero denominators.

Independent-sample effect size is Hedges' g=J(df)×(mean_A−mean_B)/pooled sample
SD, with df=n_A+n_B−2 and exact correction
J(df)=Gamma(df/2)/(sqrt(df/2)×Gamma((df−1)/2)). This pooled-SD effect-size
convention does not change Welch's unequal-variance test. Paired Cohen dz is
mean(A−B)/SD(A−B). Mann–Whitney rank-biserial correlation is
2U_A/(n_A n_B)−1, positive when A tends to exceed B; ties count half.
No domain-independent qualitative size labels are assigned.

For existing robustness records:

```python
from pre_science.statistics import statistics_from_robustness, analyze_statistics

# Trusted caller verifies corresponding data/splits/conditions for each seed.
request = statistics_from_robustness(
    report_a, report_b, analysis_id='paired-evaluation', metric='accuracy',
    test='paired_t', paired=True,
    conditions_a=verified_condition_ids_a, conditions_b=verified_condition_ids_b,
)
payload = analyze_statistics(request).model_dump(mode='json')
```

The adapter extracts actual metrics from successful per-seed execution records,
not cached aggregate means. It requires all requested observations to be present
and successful; incomplete studies need explicit, documented preprocessing outside
this adapter. It rejects duplicate/missing seeds, missing metrics and disagreeing
execution seeds. Paired requests require identical seed sets and separately
supplied, equal, nonblank condition identifiers per seed; B is aligned to A's
seed order. Pairing is a caller attestation, not an empirical verification by
the engine. Seeds alone never suffice. Source experiment/study IDs, specification/
code hashes, datasets, original source provenance and per-seed execution IDs are
retained. Independent comparisons do not align or truncate observations.

Person 4 resolves authorized stored reports, validates the request and calls this
pure function in the existing backend. Return sanitized validation errors rather
than raw input-bearing exceptions. Person 1 displays the structured JSON plus
`summary`; existing Markdown/LaTeX adapters are unchanged. Optional replication/
optimization identifiers go in `source_ids`/`provenance`; the robustness adapter
also preserves those source origins. No original scientific reports are modified.

Assumptions are stated, not claimed verified. Welch requires independent sampling
units and approximately normal mean sampling distributions. Paired inference
requires independent, meaningfully corresponding pairs and approximately normal
differences for exact small-sample inference. U compares distributions/stochastic
ordering, not universally medians when shapes differ. Shared datasets or overlapping
splits may violate independence. Selection on evaluation data biases comparisons.
Significance establishes neither practical importance, causality, valid science,
nor reproduction; nonsignificance is not equivalence. P-values are not posterior
probabilities that the null is true. No multiplicity correction, power analysis,
statistical visualization or automatic manuscript/table insertion is added.

Run `.\.venv\Scripts\python.exe -m pre_science.demo_statistics` for actual trusted
Iris depth-1 versus depth-3 trees on five explicitly matched seeded stratified
splits. It saves both robustness reports and a paired statistical report under
`.runtime/statistics/<run>/`. The shared Iris observations make inference
illustrative, despite justified pair correspondence. Local execution is developer
code only; untrusted code still requires Person 4's restricted executor.
Tests: `python -m pytest tests/science/test_statistics.py -q` or the complete
`python -m pytest tests/science -q` suite.

Prompt 10 final scientific suite: **309 passed, 2 skipped, 14 warnings** in
59.48 seconds. Skips remain unavailable Tectonic and Windows symlink permissions;
warnings are existing noninteractive Agg calls. Statistical tests compare actual
NumPy/SciPy calculations (all alternatives, intervals, effect sizes, ties,
degeneracy, threshold boundaries and pairing). The installed SciPy can return an
undefined p-value for all-tied Mann–Whitney inputs; the report preserves finite U
and rank-biserial values while marking inference unavailable, rather than
substituting a p-value. No deployed backend or Docker protections were tested.

The real demo completed: depth-1 accuracies were 0.6666666667 on all five seeds;
depth-3 accuracies were 0.9777777778, 0.9777777778, 0.9555555556, 0.9777777778,
0.9111111111. Paired A−B mean difference −0.2933333333; t=−22.6378, df=4,
p≈0.000022552; 95% two-sided mean-difference interval
[−0.3293095952, −0.2573570715]; Cohen dz=−10.1239378528. These are actual
executed measurements with illustrative inference under questionable independent-
pair assumptions, not proof of independent improvement or scientific validity.

## Multi-seed evaluation (Prompt 9)

`pre_science.robustness` defines `RobustnessRequest`, `RobustnessReport`,
`SeedRun`, `MetricSummary`, `RobustnessThresholds` and `RobustnessService`.
It reuses `ExperimentService` and the injected executor, sequentially. No routes,
UI, AI calls, database or separate execution engine are added.

```python
from pre_science.robustness import RobustnessRequest, RobustnessService, robustness_digest
from pre_science.schemas import ResearcherApproval

request = RobustnessRequest(
    study_id='seed-evaluation', experiment_id='approved-experiment', code=approved_code,
    parameters=approved_parameters, seeds=[1, 7, 21, 42, 123], metrics=['accuracy'],
    timeout_seconds=30, max_duration_seconds=180, confidence_interval=True,
    thresholds={'accuracy': {'max_std': 0.05, 'min_successful_runs': 5}},
)
# Only after authenticated researcher review of this complete request:
request.approval = ResearcherApproval(approved=True, approved_by=researcher_id,
    specification_sha256=robustness_digest(request))
report = RobustnessService(experiments, artifact_store=figure_store).run(
    request, available_dataset_ids=authorized_dataset_ids,
    available_asset_ids=authorized_asset_ids)
payload = report.model_dump(mode='json')
```

Person 4 supplies `experiments = ExperimentService(restricted_executor)` and
authorized dataset/asset IDs. `dataset` uses the existing `ReplicationDataset`,
including source/processed hashes and transformations. Approval is domain-separated
and binds all settings, source provenance, metrics, seeds, code, parameters and
dataset. Changing any field requires new approval. Seeds are 2–20 unique integers
in [0, 2^32−1]; metrics must be explicitly named. Per-run deadlines are 1–300
seconds; the study budget is 1–3600 seconds. A remaining budget below one second
prevents launching another run; each trial timeout is capped to remaining whole
seconds. The executor must actually terminate work on expiry. Scheduler budgeting
does not interrupt backend summary/plot generation or enforce hard wall time.

Reports preserve requested seeds, successful/failed execution counts, unattempted
seeds, unique per-run execution IDs, complete valid execution records/errors,
missing metrics, dependency versions, dataset/code/source provenance and timing.
`completed_runs` counts successful executions, even if a selected metric is
missing. A fully attempted study with failures/missing metrics has status
`completed_with_failures`; budget exhaustion is separate. Malformed executor
outputs are rejected and recorded as sanitized `InvalidExecution` errors.
Only metrics from successful executions contribute to summaries. Missing metrics
are excluded independently for each metric. No fabricated zeros are inserted.

Each summary includes contributing seeds/values/count, arithmetic mean, median,
min/max/range, sample standard deviation (ddof=1), and standard error s/sqrt(n).
With n<2, sample standard deviation, standard error and intervals are unavailable.
With n=0 all numerical aggregates are unavailable. Optional 95% Student t bounds
are mean ± t(0.975,n−1)×standard_error. These assume independent observations and
an approximately normal sampling distribution of the mean; overlapping dataset
splits can violate independence. Intervals are not proof of robustness and are
not clipped to metric bounds. Overflowing statistics are unavailable. Threshold
results are per condition (`True`, `False`, or `None` when undefined); minimum
successful count means valid observations for that metric. No global robust/
unreliable verdict is inferred, with or without thresholds.

The worker records `seed_application`: Python `random.seed` and NumPy legacy
`np.random.seed` are applied before code. Code may override these. NumPy
`default_rng`, library-specific random states and hardware are not automatically
controlled. The demo explicitly passes `random_seed` into both split and model.
Other injected runtimes may omit this evidence: a requested seed alone does not
prove application. Fresh globals are insufficient to isolate module/filesystem
state: Person 4 must use fresh restricted workers, never persistent kernels.
The local trusted executor is not a sandbox and is not suitable for user/AI code.

`generate_figure=True` requires an injected `ArtifactStore`; it plots each metric
by seed with an observed mean line using existing bounded PNG capture. Run-level
artifacts remain in each execution, summary figures in report `artifacts`.
Retrieve/verify and upload through the existing authorized handoff; cleanup only
after persistence. Plot failures preserve numerical reports and add a warning.
All scheduling and plotting must remain sequential; no concurrency guarantee.

`robustness_from_replication(report, study_id=..., seeds=..., metrics=...)` and
`robustness_from_optimization(...)` create new unapproved proposals from actual
executed configurations, preserving source IDs/digests and leaving originals
unchanged. For original experiments supply their approved code/parameters and
explicit source identifiers. Optimized configurations need separate approval;
reusing selection data does not establish independent test performance.

Person 1 can display `runs` and `summaries` directly from the JSON response;
the existing Markdown tool adapter and LaTeX formatter are unchanged and do not
implicitly accept robustness reports. Person 4 owns any endpoint/adapter wiring.

Run `.\.venv\Scripts\python.exe -m pre_science.demo_robustness`. It executes five
fixed Iris decision-tree runs twice in fresh processes, verifies matching accuracy
sequences and real PNG bytes, and saves both full reports under
`.runtime/robustness/<run>/report.json`. This measures split sensitivity as well
as model randomness; shared Iris data are not an independent test evaluation.
No cloud services or keys are required. Tests:
`python -m pytest tests/science/test_robustness.py -q` (focused) or
`python -m pytest tests/science -q` (complete scientific suite).

Prompt 9 final scientific suite: **267 passed, 2 skipped, 14 warnings** in
57.57 seconds. Skips remain unavailable Tectonic and Windows symlink permissions;
warnings are existing noninteractive Agg `show()` calls. The robustness tests
separate mocked statistics/scheduling/authorization checks from real fresh-worker
Python/NumPy seed repeatability and PNG retrieval. These results do not validate
Docker isolation or a deployed endpoint.

The standalone five-seed Iris demo completed and repeated the exact accuracy
sequence: seeds 1, 7, 21, 42, 123 produced 0.9777777778, 0.9777777778,
0.9555555556, 0.9777777778, 0.9111111111. Mean 0.96; sample standard deviation
0.0289742329; standard error 0.0129576709; min/max 0.9111111111/0.9777777778;
illustrative 95% t interval [0.9240237381, 0.9959762619]. Both studies generated
real 600×300 PNGs and verified their bytes. The overlapping Iris splits mean the
interval's independence assumption is questionable; it is descriptive output,
not evidence of a scientifically robust model or independent held-out evaluation.

## Automatic LaTeX tables (Prompt 8)

`pre_science.latex_tables` is a pure formatter; it executes no code, calls no AI,
and writes no manuscript. It accepts existing validated `ExperimentResult` and
`ReplicationReport` records. Supported types: `experiment` (metric/value),
`comparison` (selected metric columns across experiments), and `replication`
(reference/reproduced/difference/recorded agreement status). Optuna trial-table
generation is not included; do not present optimized trials as reproductions.

Person 4 resolves source IDs from authenticated, authorized stored records, then
calls the generator inside the existing backend handler:

```python
from pre_science.latex_tables import LatexTableRequest, generate_latex_table

request = LatexTableRequest(
    table_type='comparison', source_ids=['baseline', 'variant'],
    selected_metrics=['accuracy'], caption='Recorded validation accuracy',
    label='tab:accuracy', decimal_precision=4,
)
response = generate_latex_table(request, authorized_records)
payload = response.model_dump(mode='json')
```

No route or storage system is added. Mapping keys are backend record identifiers;
they may differ from the original execution ID. A missing source or incompatible
record raises `ValueError`; malformed requests/non-finite records raise Pydantic
validation errors. Return sanitized errors rather than echoing entire records.

Person 1 inserts `payload['latex_source']` at the Monaco cursor after user action,
then uses the existing Tectonic preview workflow. The response also contains
`table_type`, `source_ids`, `included_metrics`, `missing_metrics`,
`missing_by_source`, `warnings`, `generation_timestamp` (UTC), and `compiled=False`.
The generator does not claim compilation. Generated table source is deterministic
for identical input; the generation timestamp intentionally changes.

Options include `metric_names`, `experiment_names` (comparison rows),
`missing_value`, `placement` (restricted standard values or `None`), precision
0–12 and `number_format='fixed'|'scientific'`. Empty metric selection uses the
recorded order (ordered union for comparisons). Metrics absent from a source use
the missing marker; no values are invented. Execution time appears only if
explicitly recorded as a metric. Failed/timeout records retain partial metrics
and visible status. Replication uses the existing comparison values/statuses
without recomputing conclusions; its caption identifies reference source and
warns that numerical agreement does not establish scientific fidelity.

All captions, display names and missing markers are escaped as text. Labels must
start with a letter and contain only ASCII letters, digits, `:._-`; arbitrary
formatting commands are rejected. No additional LaTeX packages are required.
Formatting rounds display only and leaves source records untouched. Very wide
tables and long names may require manuscript layout work by Person 1; no layout
or statistical significance guarantee is made.

Run `.\.venv\Scripts\python.exe -m pre_science.demo_latex_tables` for three real
trusted worker executions (baseline, variant, replication), generated `.tex`
snippets and full evidence under `.runtime/latex-tables/<run>/report.json`.
The comparison is explicitly against a measured local baseline, not a paper.
Run `python -m pytest tests/science/test_latex_tables.py -q` for focused tests.
The optional compilation test uses PATH/`PRE_TECTONIC` or `.runtime/bin/tectonic`
(Windows `.exe` also supported), with cached assets only and untrusted mode.
It skips if Tectonic is unavailable; installed Tectonic needs a populated cache.

Prompt 8 verification: `pytest tests -q` completed with **243 passed, 2 skipped,
15 warnings** in 51.52 seconds. Skips were Windows symlink permissions and absent
Tectonic; warnings were the existing Agg/dependency warnings. Repository-wide
`pytest -q` was also attempted, but collection stopped in the separate
`backend/ai/tests` because `google-genai` is not installed in the test environment
(it is already declared in `backend/ai/requirements.txt`). No AI files or
dependencies were changed for table generation. The standalone demo measured
baseline mean 30.0, variant mean 32.0 and population standard deviation
14.142135623730951 for both, then reproduced the measured baseline. All three
tables were saved and their displayed values verified against the actual records.
Tectonic compilation was not performed.

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
