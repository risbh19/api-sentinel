import unittest

from httpx import ASGITransport, AsyncClient

from api_sentinel.main import app


class LivenessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_live_returns_only_process_status(self) -> None:
        response = await self.client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_input_is_not_reflected(self) -> None:
        response = await self.client.get(
            "/health/live?detail=example", headers={"X-Request-ID": "example"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertNotIn("example", str(response.headers))

    async def test_method_is_read_only(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                response = await self.client.request(method, "/health/live")
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.headers["allow"], "GET")

    async def test_unimplemented_routes_return_404(self) -> None:
        for path in ("/health/ready", "/docs", "/openapi.json", "/v1/ingest/events"):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 404)
