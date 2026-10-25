"""Defend examiner routing tests; use fake credentials and an ElevenLabs response."""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

import backend.routes.defend as defend
from backend.config import ConfigurationError


class FakeSettings:
    values = {
        "ELEVENLABS_AGENT_ID": "supportive-agent",
        "ELEVENLABS_CRITICAL_REVIEWER_AGENT_ID": "critical-agent",
        "ELEVENLABS_API_KEY": "server-only-test-key",
    }

    def require(self, name):
        if name not in self.values:
            raise ConfigurationError(f"Missing server configuration: {name}")
        return SecretStr(self.values[name])


class MissingCriticalSettings(FakeSettings):
    values = {
        "ELEVENLABS_AGENT_ID": "supportive-agent",
        "ELEVENLABS_API_KEY": "server-only-test-key",
    }


class FakeElevenLabsResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"signed_url": "wss://example.test/session"}


class FakeElevenLabsClient:
    expected_agent = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, *, params, headers, timeout):
        if params != {"agent_id": self.expected_agent}:
            raise AssertionError(f"Unexpected agent selection: {params}")
        if headers != {"xi-api-key": "server-only-test-key"}:
            raise AssertionError("The server API key was not sent to ElevenLabs")
        return FakeElevenLabsResponse()


class DefendVoiceTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(defend.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def test_each_examiner_gets_its_own_agent_without_demo_key(self):
        for path, agent_id in (
            ("/defend/signed-url", "supportive-agent"),
            ("/defend/signed-url?examiner=critical", "critical-agent"),
        ):
            with self.subTest(path=path):
                FakeElevenLabsClient.expected_agent = agent_id
                with (
                    patch.object(defend, "get_settings", return_value=FakeSettings()),
                    patch.object(defend.httpx, "AsyncClient", FakeElevenLabsClient),
                ):
                    response = self.client.get(path)

                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), {"signed_url": "wss://example.test/session"})

    def test_unknown_examiner_is_rejected(self):
        response = self.client.get("/defend/signed-url?examiner=unknown")
        self.assertEqual(response.status_code, 422)

    def test_missing_critical_agent_has_a_helpful_error(self):
        with patch.object(defend, "get_settings", return_value=MissingCriticalSettings()):
            response = self.client.get("/defend/signed-url?examiner=critical")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Critical Reviewer is not configured on the backend")


if __name__ == "__main__":
    unittest.main()
