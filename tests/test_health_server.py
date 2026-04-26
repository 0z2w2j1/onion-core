"""Health check HTTP server tests."""

from __future__ import annotations

import asyncio
import json
import time
from http.client import HTTPConnection

import pytest

from onion_core import EchoProvider, Pipeline
from onion_core.health_server import HealthServer, start_health_server


@pytest.fixture
def pipeline():
    return Pipeline(provider=EchoProvider())


@pytest.fixture
def server_info(pipeline):
    hs = HealthServer(pipeline, host="127.0.0.1", port=0)
    hs.start()
    port = hs._server.server_address[1]
    time.sleep(0.05)
    yield hs, port
    hs.stop()


def _get(path: str, port: int) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    conn.close()
    return resp.status, data


class TestHealthCheckHandler:
    def test_liveness(self, server_info):
        _, port = server_info
        status, data = _get("/health/live", port)
        assert status == 200
        assert data["status"] == "alive"

    def test_readiness_healthy(self, server_info):
        hs, port = server_info
        asyncio.run(hs.pipeline.startup())
        time.sleep(0.05)
        status, data = _get("/health/ready", port)
        assert status == 200
        assert "status" in data
        asyncio.run(hs.pipeline.shutdown())

    def test_readiness_not_ready(self, server_info):
        _, port = server_info
        status, data = _get("/health/ready", port)
        assert status == 503
        assert "error" in data

    def test_startup_started(self, server_info):
        hs, port = server_info
        asyncio.run(hs.pipeline.startup())
        time.sleep(0.05)
        status, data = _get("/health/startup", port)
        assert status == 200
        assert "status" in data
        asyncio.run(hs.pipeline.shutdown())

    def test_startup_not_started(self, server_info):
        _, port = server_info
        status, data = _get("/health/startup", port)
        assert status == 503

    def test_health_healthy(self, server_info):
        hs, port = server_info
        asyncio.run(hs.pipeline.startup())
        time.sleep(0.05)
        status, data = _get("/health", port)
        assert status == 200
        assert data["status"] == "healthy"
        asyncio.run(hs.pipeline.shutdown())

    def test_health_not_started(self, server_info):
        _, port = server_info
        status, data = _get("/health", port)
        assert status == 503

    def test_unknown_route(self, server_info):
        _, port = server_info
        status, data = _get("/unknown", port)
        assert status == 404
        assert "Not found" in data["error"]


class TestHealthServer:
    def test_start_stop(self, pipeline):
        hs = HealthServer(pipeline, host="127.0.0.1", port=0)
        hs.start()
        time.sleep(0.05)
        assert hs._server is not None
        port = hs._server.server_address[1]
        status, _ = _get("/health/live", port)
        assert status == 200
        hs.stop()
        assert hs._server is None

    def test_start_health_server_convenience(self, pipeline):
        hs = start_health_server(pipeline, host="127.0.0.1", port=0)
        assert isinstance(hs, HealthServer)
        time.sleep(0.05)
        port = hs._server.server_address[1]
        status, _ = _get("/health/live", port)
        assert status == 200
        hs.stop()


@pytest.mark.asyncio
async def test_pipeline_health_check_states():
    p = Pipeline(provider=EchoProvider())
    health = p.health_check()
    assert health["status"] == "not_started"
    assert "started" in health

    await p.startup()
    health = p.health_check()
    assert health["status"] == "healthy"
    assert health["started"] is True

    await p.shutdown()
