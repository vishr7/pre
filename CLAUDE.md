# PRE — Progressive Research Editor (HackPSU Fall 2026)

AI-powered research environment: LaTeX editing, AI review, experiment reproduction, voice thesis defense.
Full product overview: `docs/overview.md`. Full stack: `docs/tech-stack.md`. Read them when you need detail.

## Who I am
I'm **Person 2 — AI Research Intelligence**. I own:
- **PRE Review** — AI reviewer for methodology, clarity, experimental weaknesses, unsupported claims
- **PRE Compose AI** — natural-language → LaTeX edit agent (approved edits only)
- **PRE Integrity** — folded into the reviewer as comment categories, not a separate system
- A shared Gemini helper that Person 3 uses for their own extraction/code-gen prompts

Teammates (don't touch their code unless I ask):
- Person 1 — Next.js frontend, Monaco editor, Tectonic compile, PDF.js preview
- Person 3 — PDF replication, Docker experiment runner, Optuna, Matplotlib
- Person 4 — FastAPI backend, Tiger Data (Postgres), Auth0, Vultr storage, ElevenLabs, deployment

## My stack
Python, FastAPI (router mounted into Person 4's app), Google Gemini via the `google-genai` SDK, Pydantic for all AI outputs.
- `GEMINI_API_KEY` and `GEMINI_MODEL` come from env vars. Never hardcode keys or model names.
- If the shared backend repo isn't set up yet, build my code as a standalone FastAPI `APIRouter` in its own package (e.g. `backend/ai/`) with a tiny local `main.py` for testing.

## API contracts (agreed with Persons 1 & 4; don't change shapes without telling me)
`POST /ai/review`
- in: `{ latex: str, venue: "neurips" | "acl" | "journal" | "generic" }`
- out: `{ summary: str, scores: {methodology, novelty, clarity, reproducibility: int 1-5}, comments: Comment[], action_items: ActionItem[] }`
- `Comment = { id, section, quote, category, severity, comment, suggestion }`
  - `category`: methodology | clarity | experimental | novelty | unsupported_claim | inconsistent_metric
  - `severity`: minor | major | critical
- `ActionItem = { id, title, description, related_comment_ids }`

`POST /ai/edit`
- in: `{ latex: str, instruction: str, selection?: str }`
- out: `{ edits: [{ old_text, new_text, reason }] }`

## Rules
- **Anchor by exact quote, never line numbers.** Every `quote` and `old_text` must appear verbatim in the input LaTeX. Validate this in code; re-prompt (max 2 retries) on failure and drop anything that still doesn't match.
- Edits are targeted replacements, never a full-file rewrite.
- All Gemini calls go through one helper: `structured_call(prompt, schema: type[BaseModel]) -> BaseModel` with JSON-schema output + validation + retry.
- Venue criteria live as prompt templates in their own file, easy to add to.
- Keep prompts in separate files/constants, not buried in route code.
- Hackathon: favor working and simple over clever. No new dependencies beyond the stack without asking.

## Build order
1. Gemini helper + Pydantic schemas
2. `/ai/review` working end-to-end on `samples/demo_paper.tex`
3. `/ai/edit` with quote validation
4. Venue prompt templates
5. Cached fallback review JSON for the demo
6. Stretch: AI-generated rebuttal drafts from review comments

## Status
- [x] 1  - [x] 2  - [ ] 3  - [ ] 4  - [ ] 5
