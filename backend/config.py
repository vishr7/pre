"""Server-only configuration. Loading .env never exports secrets to child processes."""

from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr


ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    'GEMINI_API_KEY', 'GEMINI_MODEL', 'ELEVENLABS_API_KEY',
    'ELEVENLABS_AGENT_ID', 'ELEVENLABS_CRITICAL_REVIEWER_AGENT_ID', 'DATABASE_URL',
    'AUTH0_DOMAIN', 'AUTH0_AUDIENCE', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET',
    'S3_ENDPOINT', 'S3_BUCKET', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY',
    'RUNNER_SERVICE_TOKEN',
)


class ConfigurationError(RuntimeError):
    """Safe configuration error containing variable names, never their values."""


@dataclass(frozen=True)
class Settings:
    # SecretStr masks repr/str; suppress the mapping entirely in Settings repr.
    _values: dict[str, SecretStr] = field(repr=False)

    def require(self, name: str) -> SecretStr:
        if name not in NAMES:
            raise ConfigurationError('Unknown server configuration variable')
        value = self._values[name]
        if not value.get_secret_value().strip():
            raise ConfigurationError(f'Missing server configuration: {name}')
        return value


def load_settings(env_file: Path = ROOT / '.env') -> Settings:
    # Avoid load_dotenv(): application credentials must not enter worker envs.
    # No interpolation: literal credentials containing $ are preserved.
    values = dotenv_values(env_file, interpolate=False) if env_file.is_file() else {}
    return Settings({name: SecretStr(os.environ.get(name, values.get(name) or ''))
                     for name in NAMES})


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Backend dependency; deployed environment values override local .env values."""
    return load_settings()
