"""The server answers only requests whose Host header names this machine (DNS-rebinding defence)."""
import httpx
import pytest
from nicegui import app
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from aerosuite.web import server

LOCAL = ["localhost", "127.0.0.1", "::1", "[::1]"]


@pytest.mark.parametrize("bind", ["127.0.0.1", "localhost", "::1"])
def test_a_local_bind_allows_only_local_host_names(bind):
    assert server.allowed_hosts(bind) == LOCAL


def test_an_explicit_non_local_bind_is_added():
    assert server.allowed_hosts("192.168.1.5") == LOCAL + ["192.168.1.5"]
    assert server.allowed_hosts("workstation") == LOCAL + ["workstation"]
    assert server.allowed_hosts("fe80::1") == LOCAL + ["[fe80::1]"]  # as a browser sends it


@pytest.mark.parametrize("bind", ["0.0.0.0", "::"])
def test_a_wildcard_bind_allows_any_host(bind):
    assert server.allowed_hosts(bind) == ["*"]


def _served_middleware(monkeypatch, tmp_path, bind: str) -> list:
    """Run `run_server` without starting anything; return the middleware it registered."""
    monkeypatch.setattr(app, "user_middleware", [])
    monkeypatch.setattr(app, "middleware_stack", None)
    monkeypatch.setattr(server, "register_pages", lambda root: None)
    runs = []
    monkeypatch.setattr(server.ui, "run", lambda **kwargs: runs.append(kwargs))
    server.run_server(tmp_path, bind, 8765)
    assert len(runs) == 1
    return list(app.user_middleware)


def test_run_server_registers_the_host_check(monkeypatch, tmp_path):
    middleware = _served_middleware(monkeypatch, tmp_path, "127.0.0.1")
    checks = [m for m in middleware if issubclass(m.cls, TrustedHostMiddleware)]
    assert len(checks) == 1
    assert checks[0].kwargs["allowed_hosts"] == LOCAL


@pytest.mark.parametrize(
    "host_header, status",
    [
        ("evil.example", 400),
        ("evil.example:8765", 400),
        ("localhost:8765", 200),
        ("localhost:9999", 200),  # the port is ignored, so a tunnel on any local port works
        ("127.0.0.1:8765", 200),
        ("[::1]:8765", 200),
    ],
)
async def test_requests_are_checked_by_host_header(monkeypatch, tmp_path, host_header, status):
    middleware = _served_middleware(monkeypatch, tmp_path, "127.0.0.1")
    tiny = Starlette(routes=[Route("/", lambda request: PlainTextResponse("ok"))], middleware=middleware)
    # httpx's ASGI transport rather than starlette's TestClient, which warns about deprecations.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=tiny), base_url="http://testserver") as client:
        response = await client.get("/", headers={"host": host_header})
    assert response.status_code == status
