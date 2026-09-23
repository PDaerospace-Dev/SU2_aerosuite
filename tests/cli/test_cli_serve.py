from typer.testing import CliRunner

from aerosuite.cli import app

runner = CliRunner()


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr("aerosuite.web.server.run_server", lambda *args: calls.append(args))
    return calls


def test_serve_starts_on_localhost(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    result = runner.invoke(app, ["serve", "--root", str(tmp_path), "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert calls == [(tmp_path, "127.0.0.1", 9000)]
    assert "http://127.0.0.1:9000" in result.output


def test_serve_refuses_a_non_local_host(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--root", str(tmp_path)])
    assert result.exit_code == 1
    assert "no login" in result.output
    assert calls == []


def test_serve_allows_a_non_local_host_when_told(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--root", str(tmp_path), "--i-understand-no-auth"])
    assert result.exit_code == 0, result.output
    assert calls == [(tmp_path, "0.0.0.0", 8080)]


def test_serve_needs_an_existing_root(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    result = runner.invoke(app, ["serve", "--root", str(tmp_path / "missing")])
    assert result.exit_code == 1
    assert "is not a folder" in result.output
    assert calls == []


def test_serve_prints_an_ipv6_address_in_brackets(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    result = runner.invoke(app, ["serve", "--host", "::1", "--root", str(tmp_path), "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert calls == [(tmp_path, "::1", 9000)]
    assert "http://[::1]:9000" in result.output
