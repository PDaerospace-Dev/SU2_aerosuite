"""Start the NiceGUI server for `aerosuite serve`."""
from pathlib import Path

from nicegui import app, ui
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Receive, Scope, Send

from .app import register_pages

LOCAL_HOST_NAMES = ("localhost", "127.0.0.1", "::1", "[::1]")
WILDCARD_BINDS = ("0.0.0.0", "::")


def allowed_hosts(host: str) -> list[str]:
    """The Host header values the server answers when bound to `host` (the port is not checked).

    Rejecting other names defends against DNS rebinding: a web page whose domain is re-pointed
    at 127.0.0.1 reaches this server, but its requests still carry that domain as their Host.
    """
    if host in WILDCARD_BINDS:
        return ["*"]  # listening on every interface was explicitly allowed (--i-understand-no-auth)
    allowed = list(LOCAL_HOST_NAMES)
    name = f"[{host}]" if ":" in host else host  # a browser sends an IPv6 address in brackets
    if host not in allowed and name not in allowed:
        allowed.append(name)
    return allowed


class LocalHostMiddleware(TrustedHostMiddleware):
    """Starlette's TrustedHostMiddleware that also reads a bracketed IPv6 Host ("[::1]:8080").

    Starlette takes the text before the first ':' as the host, which is "[" for an IPv6
    address, so it would refuse every request to a server bound to ::1.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not self.allow_any:
            host = Headers(scope=scope).get("host", "")
            if host.startswith("[") and host[: host.find("]") + 1] in self.allowed_hosts:
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


def run_server(root: Path, host: str, port: int) -> None:
    register_pages(root)
    app.add_middleware(LocalHostMiddleware, allowed_hosts=allowed_hosts(host))
    ui.run(host=host, port=port, reload=False, show=False, title="AeroSuite")
