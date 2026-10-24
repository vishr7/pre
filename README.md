# PRE Compose

A simple research notebook with executable Python, JavaScript, LaTeX, and Markdown cells.

## Run

```sh
npm install
npm run dev
```

Open the printed localhost URL. **Leave Backend API URL empty** in Settings to use the built-in local runtime. `npm run preview` also includes the runtime after `npm run build`; hosting only `dist/` requires an external API.

Python uses `.venv/bin/python` when available, otherwise `python3`. To set up scientific packages on a fresh checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm run setup:latex
```

The current workspace already has the virtual environment and Tectonic installed. The LaTeX setup script downloads the pinned official Tectonic 0.17.0 release to `.runtime/bin/`; its first compilation downloads TeX support files. Other platforms can install [Tectonic](https://tectonic-typesetting.github.io/en-US/install.html) directly. Override executables with `PRE_PYTHON` and `PRE_TECTONIC` environment variables.

## Projects

The home page lists your projects. Use **New project** to name and open a blank workspace with its own notebook and paper. Search, rename, archive, and restore projects from the list. Opening a project shows the PDF preview and automatically compiles `paper/main.tex`; compilation errors appear with a retry button. Click **All projects** (or the PRE logo) to return home. Project URLs support browser back/forward and reopening after refresh.

Each project saves its files and cells separately on this device. Existing single-workspace content is imported once as **Untitled project**. Leaving a workspace stops and releases its execution session; reopening starts fresh kernels while preserving source and saved text outputs. New projects open a notebook/paper workspace; the bottom Terminal bar opens a local interactive shell.

## AI compile repair

When a **LaTeX cell** fails, PRE automatically asks the configured Gemini model for a minimal fix. The original source remains unchanged. PRE validates exact-quote edits, compiles the proposed source with Tectonic, and shows a single inline diff inside that same cell, with green additions and red removals. The editor automatically jumps to the first changed line.

- **Accept fix** applies the complete proposed patch and displays its verified PDF. It is enabled only after successful compilation.
- **Reject** discards the suggestion and restores the original editable cell.
- If validation or compilation fails, the source is unchanged and the suggestion is labeled unverified. Compiler details remain available; Try again requests a new suggestion.
- Changing the cell invalidates pending suggestions. If project files changed after verification, acceptance is refused until the cell is checked again.

Set `GEMINI_API_KEY` and `GEMINI_MODEL` in the root `.env`, then restart the dev server. Credentials stay on the server. The failed cell and a bounded compiler-log excerpt are sent to Gemini; unrelated files and their contents are not sent. This feature checks compilation, not scientific correctness. Review the diff before accepting. It currently handles cell-level LaTeX errors, not Python errors or whole-paper file editing.

The local endpoint `POST /api/repair/latex` accepts `{ source, error }` and returns `{ summary, edits: [{old_text, new_text, reason}], source }`. Candidate compilation uses the existing `/api/compile` endpoint without changing the displayed PDF until acceptance. External backends must implement the same repair contract. Invalid AI output is retried at most twice; no repeated repair loop runs after a rejected or non-compiling suggestion.

## Terminal and SSH

The terminal opens automatically beneath the middle notebook/editor column, with matching pearl-and-pink styling. It stays docked within that column while the files sidebar and PDF preview keep their full height. Click **Terminal** to collapse or expand it. It starts your local `$SHELL` in the repository directory with a real pseudo-terminal. Run normal commands or connect to a remote host:

```sh
ssh username@hostname
```

SSH uses your computer's installed SSH client, keys, agent, and host configuration. Password and host-key prompts stay interactive in the terminal. Ctrl+C interrupts commands. Drag the top edge to resize, use Clear to clear the display, and Restart to open a fresh shell. Collapsing the panel preserves the session; leaving the project or closing the connection ends it.

The terminal runs locally on macOS, Linux, and Windows 10 1809+ through `npm run dev` or `npm run preview`; it does not use the optional remote backend URL. On Windows it opens PowerShell (or `pwsh` if installed; set `PRE_TERMINAL_SHELL` to override) in a ConPTY pseudo console and uses Windows' built-in OpenSSH client. It has your local user permissions and starts in the actual checkout, not the browser's virtual file tree. Browser-saved project files are not automatically mirrored into the terminal directory. Shell output and keystrokes are not stored by PRE. WebSocket connections require a same-origin, short-lived single-use ticket.

## Cells

- **Python:** Run code, print output, inspect the final expression, and display Matplotlib plots. Variables persist between Python cells. Project files are copied into the kernel's working directory; Python can import from the root and `src/`.
- **JavaScript:** Run standard JavaScript and `console.log` in a separate persistent Node VM context. The last expression is displayed; returned promises are awaited. Use `var` for bindings you want to redefine when rerunning cells. Browser DOM, Node imports, and top-level `await` are not provided.
- **LaTeX:** Compile the selected cell into a real PDF. Fragments get an article wrapper with `amsmath`, `amssymb`, and `graphicx`; complete documents are used unchanged. The preview's Compile button compiles `paper/main.tex` instead.
- **Markdown:** Click Render to display the text. Double-click the rendered cell or use its edit icon to edit it.

Editors automatically fit their content, up to a scrollable 480-pixel height. Drag the bottom handle to resize manually; click **Fit content** or double-click the handle to restore automatic sizing. Manual heights are saved per cell. The focused handle also supports arrow keys and Enter.

Change a cell's language with its dropdown. **Run all** runs cells from top to bottom and stops at the first error. **Stop** interrupts the active execution and clears both code kernels. **Restart** clears variables while keeping old outputs visible. Code execution times out after 30 seconds; LaTeX after 90 seconds. Python and JavaScript do not share variables. Kernel state lasts until the page session or dev server is restarted; saved outputs are not live variables.

New projects start with an empty Python cell and a minimal LaTeX file. Untouched demo content from older versions is removed automatically; edited cells and files are preserved. For a quick plotting check, add:

```python
import numpy as np
import matplotlib.pyplot as plt
x = np.linspace(0, 6, 100)
plt.plot(x, np.sin(x))
plt.show()
```

## Workspace

Notebook is the default view. Paper opens LaTeX source. Preview displays the paper directly, without browser PDF controls; Fit sizes it to the panel. Ask AI opens chat; Tools contains Review, Experiment, Replicate, Iterate, and Defend.

Text files and cells autosave in browser localStorage. Plot images remain in memory to avoid filling browser storage. Export downloads a project JSON backup; the notebook menu downloads `.ipynb`. Mixed JavaScript/Python notebooks retain language metadata but need an appropriate Jupyter kernel to execute outside PRE. Binary uploads and project archive import are not implemented.

## Local execution model

This runtime is for trusted code on your own computer. Python executes with your user permissions; it is not a security sandbox. The server binds to loopback and rejects cross-origin execution requests. Do not expose this runtime as a public or multi-user service. A deployed service must supply isolated execution workers, authentication, and resource quotas.

Each open project workspace gets independent persistent Python and JavaScript processes. There are at most 16 sessions per server; restart the server to release unused page sessions. Runtime files and downloaded executables are ignored by Git. Source changes to imported Python modules require Restart because Python caches imports. File synchronization writes the supplied files but does not delete runtime-generated files. PDFs are retained in server memory (most recent 30); recompile after restarting the server.

## Backend API

An optional Settings URL routes requests to an external backend. Local execution needs no URL or API keys. External backends should allow the frontend origin through CORS. AI chat and research tools still require your team's AI backend.

All routes accept JSON POST:

| Route | Request | Response |
| --- | --- | --- |
| `/api/execute` | `{ sessionId, language: "python" or "javascript", code, files }` | `{ stdout, stderr, error?, images: [PNG data URLs], durationMs, executionCount }` |
| `/api/compile` | `{ sessionId, files, source? , entrypoint? }` | `{ pdfUrl, logs }` |
| `/api/runtime/reset` | `{ sessionId }` | `{ ok: true }` |
| `/api/runtime/release` | `{ sessionId }` | `{ ok: true }` (stop and remove session) |
| `/api/chat` | `{ messages: [{role, text}], mode, context: {cells, files} }` | `{ message }` |
| `/api/tools/:mode` | `{ prompt, files, cells }` | `{ result }` |

Files are `{ path, content }`. `source` compiles an individual LaTeX cell; otherwise `entrypoint` defaults to `paper/main.tex`. Local PDF URLs are served by `/api/pdf/:id`. Local execution POSTs require `X-PRE-Runtime: 1`; the client adds it only for same-origin requests. HTTP errors return `{ error }`; user-code exceptions are returned within successful execution responses so stdout is preserved.

## Verify

```sh
npm test
PRE_TEST_PLOTS=1 PRE_TEST_LATEX=1 npm test
npm run build
```

The extended suite requires scientific Python packages and Tectonic. It verifies real plot/PDF generation in addition to state persistence, language isolation, errors, file imports, path traversal rejection, timeouts, and cancellation.

### Generate LaTeX in a cell

Type an instruction on its own line, for example `pre write a centered title saying HW 7 - 432`, then press Enter (Shift+Enter inserts a normal newline). You can also click AI edit or Compile to process the first PRE command. PRE replaces only that instruction line, checks compilation, and shows an inline change for Accept/Reject. Surrounding source stays intact. Requires the server-side Gemini configuration described above; the cell context and instruction are sent to Gemini. External runtimes must implement `POST /api/compose/latex` with `{source, line}` (1-based line) returning the same proposal shape as the repair endpoint.

Compile in the notebook combines its nonempty LaTeX cells into one preview. A complete document supplies the preamble; additional fragments are inserted before its document ending. Keep at most one complete document per notebook. Notebook compiles its LaTeX cells; Paper combines project LaTeX files with those same notebook LaTeX cells. An empty notebook produces a blank preview. Paper combines all `.tex` files and appends notebook LaTeX cells in notebook order, using the complete document as its root and adding other fragments before the document ending; explicit input/include references are expanded once. Unreferenced files follow filename order. Switching tabs rebuilds the corresponding preview. Cell compilation and AI suggestion verification use the combined notebook source too.

Ask AI supports screenshot-to-LaTeX by pasting an image directly into the chat message box. Paste PNG, JPEG, or WebP (up to 2 MB), describe the desired result, choose a new or existing LaTeX cell, and press Enter or Send. The server sends the image, instruction, and target source to the configured Gemini model. Proposed edits are compilation-checked and require Accept in the notebook. Image attachments are kept in memory, not saved with the project. External backends must implement `POST /api/compose/image` with `{source,instruction,image:{mimeType,data}}` and the repair proposal response shape. Visual matching is approximate; review the PDF for layout accuracy.

### Review your paper

Open **Tools → Review**, choose General, NeurIPS, ACL, or Journal, and select **Start review**. Review reads the same combined LaTeX files and notebook cells as Paper. Results include scores, anchored comments, and action items. **Show in paper** opens and highlights the quoted passage in the combined source. Reviews use server-side Gemini configuration and do not edit your source. The local endpoint is `POST /api/review` with `{latex, venue}`; external runtimes must support that endpoint too. The branch's standalone Python reviewer remains available under `backend/ai` with its own requirements and development app.

### Replicate

Open **Tools → Replicate**, upload a searchable PDF (up to 15 MB / 150 pages) or paste an HTTPS arXiv abstract/PDF link, and optionally specify the experiment to reconstruct. PRE reads the PDF text and asks Gemini for a methodology explanation, reconstruction steps, requirements, missing inputs, expected results, and standalone Python source. Image-only/scanned PDFs need a searchable version; figures are not extracted as evidence.

The plan appears beside an editable Python file. Generated source is saved under `replication/` with `latest-plan.json`, and checked for syntax without execution. **Run locally** explicitly runs the code through a fresh local notebook kernel, using project files, and shows stdout, errors, and plots. It saves a results JSON containing the exact executed source. **To notebook** inserts the current source as a Python cell. Execution success does not establish reproduction of the published experiment; datasets, weights, and dependencies may still be required. No dependency installation or dataset download is automatic.

Uses server-only Gemini settings. Routes: `POST /api/replicate/paper` (validated arXiv URL), `/api/replicate/plan` (paper text and focus), `/api/tools/replicate` (`syntax` check), and existing `/api/execute`. External runtimes need these contracts. The science comparison/report/fixed-demo actions remain available through `/api/tools/replicate`; arbitrary generated code is not passed to its trusted-demo worker. Local notebook execution is not the isolated production science executor.

Ask AI shares project context across tools: notebook source/output/errors, the latest replication plan and saved execution, Review feedback, compilation logs, and project text files. **Analyze with Ask AI** in Replicate opens a comparison request. It includes up to two result images (each up to 1 MB encoded) as visual context, and marks results whose source has since changed. Long text is explicitly truncated to fit the request. New replication plans retain extracted paper text for analysis; older plans may only have their summary and expected-results description. Generated code remains a proposal until inserted/run by the user.

Ask AI distinguishes new content from edits to existing cells/files. Edit suggestions use exact source quotes and retain the original target. For a single LaTeX cell, **Review in cell** opens the existing inline diff and compilation check; accept there to apply. Other edits are grouped for **Apply edits**, with stale-source checks and a combined-paper compilation check when LaTeX changes. Moving text uses removal and insertion edits together rather than adding a duplicate cell. Page-break requests insert a LaTeX page-break command before the existing section.

The notebook insert toolbar groups programming languages under **Code ▾**, with LaTeX and Markdown alongside it. Choose from 27 code/markup languages, including Python, JavaScript, TypeScript, Java, C/C++, C#, Go, Rust, R, Julia, SQL, and Shell. Each cell's language selector can switch its syntax highlighting without replacing its content. Python and JavaScript execute in the notebook; other code languages are labeled **Editor only** and can be run using an appropriate installed runtime in the terminal. Run all skips editor-only cells.

### Review and formatting evaluation

Keep Gemini and establish a measured baseline with `npm run eval:check`, `eval:prepare`, `eval:review`, and `eval:format`. See [evaluation/README.md](evaluation/README.md) for normalized dataset input, paper-grouped splits, live API flags, result interpretation, and the PDF inspection checklist. External datasets are not bundled; the included examples are synthetic smoke fixtures, not quality benchmarks. Reports and PDFs are saved under ignored `.runtime/evaluations/`.
