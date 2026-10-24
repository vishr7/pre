"""Uses fake secrets only; never reads the actual project .env."""
import os
from unittest.mock import patch

import pytest

from backend.config import ConfigurationError, load_settings


def test_server_settings_are_masked_and_not_exported(tmp_path):
    path = tmp_path / '.env'
    path.write_text('GEMINI_API_KEY=fixture-secret\nGEMINI_MODEL=test-model\n')
    with patch.dict(os.environ, {}, clear=True):
        settings = load_settings(path)
        value = settings.require('GEMINI_API_KEY')
        assert value.get_secret_value() == 'fixture-secret'
        assert 'fixture-secret' not in repr(settings)
        assert 'fixture-secret' not in str(value)
        assert 'GEMINI_API_KEY' not in os.environ


def test_environment_precedence_and_literal_dollars(tmp_path):
    path = tmp_path / '.env'
    path.write_text('GEMINI_API_KEY=local\nS3_SECRET_ACCESS_KEY=${LITERAL}\n')
    with patch.dict(os.environ, {'GEMINI_API_KEY': 'deployment'}, clear=True):
        settings = load_settings(path)
        assert settings.require('GEMINI_API_KEY').get_secret_value() == 'deployment'
        assert settings.require('S3_SECRET_ACCESS_KEY').get_secret_value() == '${LITERAL}'


def test_missing_config_errors_never_contain_values(tmp_path):
    with patch.dict(os.environ, {}, clear=True):
        settings = load_settings(tmp_path / 'missing')
        with pytest.raises(ConfigurationError, match='GEMINI_API_KEY'):
            settings.require('GEMINI_API_KEY')
        with pytest.raises(ConfigurationError, match='Unknown server'):
            settings.require('untrusted-input')
