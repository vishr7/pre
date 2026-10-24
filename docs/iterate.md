# Iterate studies

Iterate runs trusted Python scripts locally or through a connected PRE HPC session. Install `backend/requirements.txt`, start `uvicorn backend.main:app` from the repository root, and set the app's Backend API URL to that server. The server must stay private to the researcher. The local runner is a subprocess, not a sandbox for untrusted code.

Create a `.py` project file that accepts each search parameter as a command line flag and accepts `--out`. It must write a finite numeric objective to `<out>/metrics.json`; other JSON metadata may accompany it. Optionally print one JSON object per epoch with `epoch` and the objective metric; Iterate streams these for live curves and Optuna median pruning. Read `PRE_TRIAL_SEED` from the environment and seed all training libraries with it.

The Iterate screen accepts a JSON search space with `objective`, `params`, `strategy` (`grid`, `random`, or `bayesian`), `n_trials`, `parallel`, `timeout_seconds`, and `seed`. After preview, the researcher explicitly approves the exact proposal digest before execution. Each trial gets a separate folder with stdout, stderr, metrics, seed, script hash, and package metadata. Remote jobs also try to capture `pip freeze` and the Python version from the job environment. The SQLite results and Optuna studies live in `backend/data/iterate/`. The interface reconnects to the last study after reload.

The REST API provides `POST /iterate/preview`, `POST /iterate/studies`, `GET /iterate/studies/{id}`, `GET /iterate/studies/{id}/analysis`, `GET /iterate/studies/{id}/trials/{number}/logs`, `POST /iterate/studies/{id}/stop`, and `POST /iterate/studies/{id}/suggest`. Live state is available at `WS /iterate/studies/{id}/live`. Branching records the parent study and trial and enqueues the parent configuration as the new baseline when its parameters fit. AI suggestions require the backend's Gemini configuration, use a compact study summary, and require separate approval before a new study starts. The **Repeat best ×3** action creates a separate approved study with the best parameters pinned and displays the mean and sample standard deviation after all three seeded runs finish.

The runner schedules local concurrency slots or uses the `/hpc` service for remote jobs. On workstations, it checks for free GPUs and assigns one to each active worker. On SLURM, it submits one `sbatch` job per trial; the cluster queues jobs. The same Optuna ask/tell loop records both backends. Select the remote option in Iterate, connect over SSH (including 2FA when needed), and review the session ID, project, environment, and search space before approving the study. The UI shows a leaderboard, best score history, latest live epoch values, parameter importance, parallel coordinates, a radial view of the current study (first 24 trials), and seeded confirmation statistics.

HPC connections and live jobs use the existing in-memory session manager. If the backend restarts, Iterate marks the interrupted study failed; remote jobs may continue and must be inspected through the HPC service. Use a single backend server worker so the study scheduler and HPC sessions share memory.

## IDE entry points

Tools → Iterate keeps both workflows available:
- **AI parameter batch** generates editable `run_trial(params)` code, runs bounded
  local batches through the IDE runtime, saves reports in project files, and
  passes recorded results to Ask AI. It also exports a SLURM array script.
- **Backend / SSH study** uses the Python backend described above for CLI-based
  scripts, adaptive searches, persistent studies, and connected HPC execution.

The two runners use different script contracts. A `run_trial(params)` draft is
not directly a CLI study script: adapt it to accept the search flags and `--out`
and write `metrics.json` before using it in Backend / SSH study. The AI batch
export does not itself submit SSH jobs.
