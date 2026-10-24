"""Focused merge regression tests; never load the project's real .env."""

import importlib
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest


@pytest.mark.parametrize('package_mode', [True, False])
def test_configuration_and_project_routes_in_both_launch_modes(tmp_path, monkeypatch, package_mode):
    if not package_mode:
        monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'backend'))
    prefix = 'backend.' if package_mode else ''
    config = importlib.import_module(prefix + 'config')
    # Supply an isolated configuration before main imports/calls get_settings.
    settings = config.load_settings(tmp_path / 'absent.env')
    loader = Mock(return_value=settings)
    monkeypatch.setattr(config, 'get_settings', loader)
    main = importlib.import_module(prefix + 'main')
    projects = importlib.import_module(prefix + 'routes.projects')
    monkeypatch.setattr(projects, 'DATA_FOLDER', tmp_path)

    with TestClient(main.app) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        response = client.post('/projects/', json={'name': 'Merge verification'})
        assert response.status_code == 200
        project = response.json()
        files = [{'path': 'notes.md', 'content': 'preserved'}]
        saved = client.put(f'/projects/{project["id"]}/files', json={'files': files})
        assert saved.status_code == 200
        assert saved.json()['files'] == files
        assert client.get(f'/projects/{project["id"]}').json()['files'] == files
        assert client.put(f'/projects/{project["id"]}/files', json={
            'files': [{'path': '../outside', 'content': 'rejected'}],
        }).status_code == 400
    loader.assert_called_once_with()
