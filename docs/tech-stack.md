PRE — Final Optimized Technology Stack
Progressive Research Editor | HackPSU 2026
For your four-person team, I would use one frontend, one backend, one AI provider, one database, and one isolated compute service. This keeps development efficient without sacrificing PRE's main features.
1. The final stack
Component
Final technology
Purpose
Frontend
Next.js + React + TypeScript
Complete web application
UI & Styling
Tailwind CSS + shadcn/ui
Professional pearl/pink research interface
Code & LaTeX Editor
Monaco Editor
VS Code-style editor
Notebook Interface
Custom React cell components
Python, Markdown, LaTeX, outputs
PDF Compilation
Tectonic
Compile LaTeX to PDF
PDF Preview
PDF.js
Display compiled papers
Backend
Python + FastAPI
One API serving all modules
AI
Google Gemini API
Writing, reviewing, methodology extraction, experiment generation
AI Validation
Pydantic
Structured AI outputs and approved edits
Scientific Execution
Python + isolated Docker workers
Execute approved code safely
Scientific Libraries
NumPy, Pandas, SciPy, scikit-learn
Statistics, cleaning, ML experiments
Experiment Optimization
Optuna
Parameter sweeps and experiment comparison
Visualization
Matplotlib
Publication-ready figures
PDF Extraction
PyMuPDF
Extract methodology and findings from papers
Database
Tiger Data (PostgreSQL)
Projects, chats, experiments, execution metadata
File Storage
Vultr Object Storage
Papers, datasets, figures, generated PDFs
Authentication
Auth0
Secure user login
Live Messaging
FastAPI WebSockets
Built-in research team chat
Voice Defense
ElevenLabs
AI thesis-defense simulation
Cloud Hosting
Vultr
FastAPI and isolated compute workers
Frontend Deployment
Vercel
Deploy frontend
Development
Cursor + GitHub + Grok Bot
AI-assisted coding, collaboration, automation
Testing
Pytest + Playwright
Backend and browser testing

Why these choices?
Gemini only: Don't mix multiple LLM providers unless absolutely necessary.
FastAPI only: No separate Node.js backend; Next.js handles the UI and FastAPI handles the application logic.
Tiger Data only: No additional Supabase or Firebase database.
Matplotlib only: Avoid maintaining several chart-generation systems for the hackathon.
One compute worker: Both notebook execution and research replication use the same execution infrastructure.
One source of experiment data: PRE Experiment, Iterate, Review, and Replicate all reference the same experiment records.
2. Final architecture
Next.js Frontend — Vercel
Notebook · LaTeX · Chat · Experiments · Review · Defense
REST / WebSockets
FastAPI Backend — Vultr
Projects · AI orchestration · Auth · Experiments · Messaging
Gemini
AI intelligence
Tiger Data
Research records
Docker Worker
Code + experiments
Vultr Storage
PDFs + datasets
ElevenLabs
Voice defense
Auth0
Authentication
3. Final responsibilities and API keys
Developer
Owns
Stack
API keys / credentials
Person 1 — Frontend
Compose, notebook UI, PDF preview, chat UI, experiment dashboards
Next.js, Monaco, PDF.js, Tailwind
Auth0 public client config, backend URL
Person 2 — AI Intelligence
AI LaTeX, Review, methodology extraction, code proposals, validation summaries
Gemini, Python, Pydantic
GEMINI_API_KEY
Person 3 — Research Execution
Replicate, Experiment, Iterate, data cleaning, figures, result comparisons
Python, Docker, Optuna, Pandas, SciPy, Matplotlib, PyMuPDF
Internal worker token, storage access; Gemini through Person 2's service
Person 4 — Backend & Voice
Projects, database, WebSockets, file storage, authentication, defense, deployment
FastAPI, Tiger Data, Vultr, Auth0, ElevenLabs
DATABASE_URL, ELEVENLABS_API_KEY, Auth0 credentials, Vultr/storage credentials

Person 4 manages shared secrets centrally. The other developers access the shared services through agreed-upon interfaces rather than creating duplicate infrastructure.
4. What to build at HackPSU
Priority
Features
P0 — Must work
Notebook-style editor, LaTeX compilation, PDF preview, Gemini research review, Python execution, experiment visualization
P1 — Main innovation
PDF methodology extraction, experiment reconstruction, simple Optuna parameter sweeps, numerical comparison with published results
P2 — If time permits
Integrated chat, ElevenLabs thesis defense, AI-generated rebuttals
Post-hackathon
SSH/SLURM supercomputing, simultaneous collaborative editing, advanced scientific provenance, larger-scale reproduction

Your main demo should show:
Upload
Analyze
Execute
Compare
Publish
5. Final environment configuration
# AI
GEMINI_API_KEY=
ELEVENLABS_API_KEY=

# Database
DATABASE_URL=

# Authentication
AUTH0_DOMAIN=
AUTH0_AUDIENCE=
AUTH0_CLIENT_ID=

# Storage
S3_ENDPOINT=
S3_BUCKET=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=

# Compute
RUNNER_SERVICE_TOKEN=

# Frontend public configuration
NEXT_PUBLIC_API_URL=
NEXT_PUBLIC_AUTH0_DOMAIN=
NEXT_PUBLIC_AUTH0_CLIENT_ID=

Vultr deployment credentials and any Auth0 confidential client secret should be configured separately in the relevant secure deployment environment. Keep server-side keys out of frontend bundles and Git.
Run AI-generated Python only in non-privileged, resource-limited, network-restricted execution environments with timeouts and researcher approval. A normal Docker container alone is not a complete security boundary for arbitrary untrusted code.
Final recommendation: Keep Next.js + FastAPI + Gemini + Tiger Data + Vultr as PRE's foundation. Add ElevenLabs for defense simulation once the central research workflow functions.
Your main differentiator is not the number of technologies used. It's the ability to reproduce research, systematically test improvements, verify results, and incorporate those results directly into a scientific manuscript through one connected environment.