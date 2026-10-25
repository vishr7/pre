"""CORS stays limited to PRE's loopback development origins."""

import unittest

from fastapi.testclient import TestClient

from backend.main import app


class LocalCorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_vite_localhost_and_loopback_origins_are_allowed_on_supported_ports(self):
        for port in range(5173, 5177):
            for host in ("localhost", "127.0.0.1"):
                origin = f"http://{host}:{port}"
                with self.subTest(origin=origin):
                    response = self.client.options(
                        "/defend/signed-url",
                        headers={
                            "Origin": origin,
                            "Access-Control-Request-Method": "GET",
                        },
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

    def test_production_origins_are_not_allowed(self):
        response = self.client.options(
            "/defend/signed-url",
            headers={
                "Origin": "https://pre.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
