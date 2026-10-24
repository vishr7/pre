# Server environment configuration

Copy `.env.example` to the repository-root `.env` and fill values locally. Never
commit `.env`, PEM/private key files, credential JSON files or secret directories.
The example contains empty values only. Configure production secrets through
the backend deployment environment rather than shipping a local .env file.

FastAPI loads `backend.config.get_settings()` at startup. It resolves .env from
the repository root regardless of the launch directory. Existing environment
variables take precedence, including explicitly empty values. Credentials remain
in masked `SecretStr` objects, not exported to `os.environ`. The current backend
has only health routes; no provider clients exist yet and no external API calls
are made by configuration loading. Missing values are checked when a service
calls `require`, so optional services do not block backend startup.

Future server-side integrations use this interface:

```python
from backend.config import get_settings

settings = get_settings()
# Inside Person 2's Gemini helper only, pass directly to the SDK constructor:
api_key = settings.require('GEMINI_API_KEY').get_secret_value()
model = settings.require('GEMINI_MODEL').get_secret_value()
```

Person 4's future clients should use the same mechanism for DATABASE_URL, S3
credentials, Auth0 credentials, ElevenLabs, and the runner token. Read these only
in the API process; scientists call Person 2's AI service rather than Gemini
directly. Never return settings, serialize unwrapped credentials, log SDK request
headers/configuration, or return raw provider exception text. Convert provider
failures to fixed public messages. Configuration errors contain variable names
only. SecretStr masking is defense in depth, not permission to log settings.

No keys belong in `src/`, Vite `define`, browser localStorage, HTML, or public
assets. Never prefix secrets with `VITE_` or `NEXT_PUBLIC_`: these designate public
configuration. Vite's default prefix remains unchanged; no server configuration
module is imported by frontend code. Only non-secret backend URLs and public
Auth0 identifiers may become frontend configuration later.

Notebook Python/JavaScript, local terminal, and Tectonic subprocesses receive an OS-variable
allowlist instead of inheriting service credentials from the API/server process.
The terminal additionally retains the configured shell and SSH-agent connection
for the existing interactive-shell/SSH workflow; compute workers do not receive
those terminal-specific settings.
Do not add credentials to that allowlist. Scientific Docker workers likewise
must receive only explicitly allowed runtime variables, never backend secrets.
The local notebook runtime still executes trusted code with host permissions:
environment filtering cannot prevent reading a local `.env` file from disk.
Use isolated workers without secret mounts for untrusted code. Never expose the
local runtime publicly or upload `.env` as a project file. Provider integration,
authorization, and production isolation remain owned by Persons 2 and 4.

`python-dotenv` is already declared in `backend/requirements.txt`. Install backend
dependencies in the backend environment. Restart the backend after changing
configuration because settings are cached. No key values should appear in
diagnostics; check variable presence using names/booleans only.
