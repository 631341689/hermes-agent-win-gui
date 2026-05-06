"""Tests for Dashboard MCP REST API (``hermes_cli.web_mcp``)."""

import json
from unittest.mock import MagicMock, patch

import pytest

try:
    from starlette.testclient import TestClient
except ImportError:
    TestClient = None  # type: ignore[misc, assignment]


@pytest.fixture
def mcp_client(monkeypatch, _isolate_hermes_home):
    if TestClient is None:
        pytest.skip("starlette not installed")
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return client


class TestWebMcpListAndSanitize:
    def test_get_servers_empty(self, mcp_client):
        r = mcp_client.get("/api/mcp/servers")
        assert r.status_code == 200
        data = r.json()
        assert data["servers"] == []
        assert "reload_hint" in data

    def test_get_servers_masks_headers(self, mcp_client, monkeypatch):
        import hermes_cli.config as cfg_mod
        import hermes_cli.mcp_config as mcp_cfg

        def fake_load():
            return {
                "_config_version": cfg_mod.DEFAULT_CONFIG["_config_version"],
                "mcp_servers": {
                    "gh": {
                        "url": "https://example.com/mcp",
                        "headers": {
                            "Authorization": "Bearer supersecretlongtoken",
                            "X-Debug": "ok",
                        },
                    },
                },
            }

        monkeypatch.setattr(mcp_cfg, "load_config", fake_load)
        r = mcp_client.get("/api/mcp/servers")
        assert r.status_code == 200
        servers = {s["name"]: s["config"] for s in r.json()["servers"]}
        auth = servers["gh"]["headers"]["Authorization"]
        assert "***" in auth
        assert "supersecretlongtoken" not in auth
        assert servers["gh"]["headers"]["X-Debug"] == "ok"


class TestWebMcpPutValidation:
    def test_put_rejects_both_command_and_url(self, mcp_client):
        r = mcp_client.put(
            "/api/mcp/servers/bad",
            json={"command": "npx", "url": "https://x/mcp"},
        )
        assert r.status_code == 400
        assert "not both" in r.json()["detail"].lower()

    def test_put_rejects_neither_transport(self, mcp_client):
        r = mcp_client.put("/api/mcp/servers/bad", json={"enabled": True})
        assert r.status_code == 400

    def test_put_invalid_name(self, mcp_client):
        r = mcp_client.put(
            "/api/mcp/servers/bad name",
            json={"command": "npx", "args": []},
        )
        assert r.status_code == 400

    def test_put_stdio_roundtrip(self, mcp_client, monkeypatch):
        import hermes_cli.config as cfg_mod
        import hermes_cli.mcp_config as mcp_cfg

        saved: dict = {}

        def fake_load():
            base = dict(cfg_mod.DEFAULT_CONFIG)
            base["mcp_servers"] = dict(saved.get("mcp_servers", {}))
            return base

        def fake_save(cfg):
            saved["mcp_servers"] = dict(cfg.get("mcp_servers") or {})

        monkeypatch.setattr(mcp_cfg, "load_config", fake_load)
        monkeypatch.setattr(mcp_cfg, "save_config", fake_save)

        body = {"command": "npx", "args": ["-y", "pkg"], "enabled": True}
        r = mcp_client.put("/api/mcp/servers/my_srv", json=body)
        assert r.status_code == 200
        assert saved["mcp_servers"]["my_srv"]["command"] == "npx"

        r2 = mcp_client.get("/api/mcp/servers/my_srv")
        assert r2.status_code == 200
        assert r2.json()["config"]["command"] == "npx"


class TestWebMcpDelete:
    def test_delete_404(self, mcp_client):
        r = mcp_client.delete("/api/mcp/servers/nonexistent")
        assert r.status_code == 404


class TestWebMcpProbe:
    def test_test_404(self, mcp_client):
        r = mcp_client.post("/api/mcp/servers/nope/test", json={})
        assert r.status_code == 404

    def test_test_success_mocked(self, mcp_client, monkeypatch):
        import hermes_cli.config as cfg_mod
        import hermes_cli.mcp_config as mcp_cfg

        def fake_load():
            base = dict(cfg_mod.DEFAULT_CONFIG)
            base["mcp_servers"] = {"x": {"command": "true", "args": []}}
            return base

        monkeypatch.setattr(mcp_cfg, "load_config", fake_load)

        with patch(
            "hermes_cli.mcp_config._probe_single_server",
            return_value=[("t1", "d1")],
        ):
            r = mcp_client.post("/api/mcp/servers/x/test", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["tools"][0]["name"] == "t1"


class TestWebMcpOAuth:
    def test_oauth_rejects_stdio(self, mcp_client, monkeypatch):
        import hermes_cli.config as cfg_mod
        import hermes_cli.mcp_config as mcp_cfg

        def fake_load():
            base = dict(cfg_mod.DEFAULT_CONFIG)
            base["mcp_servers"] = {"x": {"command": "npx", "args": []}}
            return base

        monkeypatch.setattr(mcp_cfg, "load_config", fake_load)
        r = mcp_client.post("/api/mcp/servers/x/oauth-login", json={})
        assert r.status_code == 400

    def test_oauth_success_mocked(self, mcp_client, monkeypatch):
        import hermes_cli.config as cfg_mod
        import hermes_cli.mcp_config as mcp_cfg

        def fake_load():
            base = dict(cfg_mod.DEFAULT_CONFIG)
            base["mcp_servers"] = {
                "x": {"url": "https://example.com/m", "auth": "oauth"},
            }
            return base

        monkeypatch.setattr(mcp_cfg, "load_config", fake_load)

        mgr = MagicMock()
        mgr.remove = MagicMock()
        with patch("tools.mcp_oauth_manager.get_manager", return_value=mgr):
            with patch(
                "hermes_cli.mcp_config._probe_single_server",
                return_value=[("a", "")],
            ):
                r = mcp_client.post("/api/mcp/servers/x/oauth-login", json={})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["tool_count"] == 1


class TestWebMcpParseInstall:
    def test_parse_install_requires_raw(self, mcp_client):
        r = mcp_client.post("/api/mcp/parse-install", json={})
        assert r.status_code == 400

    def test_parse_install_503_without_api_key(self, mcp_client, monkeypatch):
        import copy

        import hermes_cli.config as cfg_mod

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        def fake_load():
            c = copy.deepcopy(cfg_mod.DEFAULT_CONFIG)
            aux = dict(c.get("auxiliary") or {})
            aux["mcp"] = {"api_key": "", "model": "", "base_url": ""}
            c["auxiliary"] = aux
            return c

        monkeypatch.setattr(cfg_mod, "load_config", fake_load)
        monkeypatch.setattr(cfg_mod, "get_env_value", lambda _k: None)

        r = mcp_client.post("/api/mcp/parse-install", json={"raw": "npx -y foo"})
        assert r.status_code == 503

    def test_parse_install_success_mocked(self, mcp_client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        llm_json = {
            "recommended_transport": "stdio",
            "confidence": "high",
            "server_name_suggestion": "uvx-demo",
            "stdio": {"command": "uvx", "args": ["mcpstore-cli", "install", "https://x"]},
            "http": {"url": "", "headers": {}, "auth": ""},
            "notes": "stdio installer",
        }

        class FakeResponse:
            status_code = 200
            text = "{}"

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": json.dumps(llm_json)}}]}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def post(self, *a, **kw):
                return FakeResponse()

        with patch("hermes_cli.web_mcp.httpx.Client", FakeClient):
            r = mcp_client.post("/api/mcp/parse-install", json={"raw": "uvx mcpstore-cli install https://x"})
        assert r.status_code == 200
        d = r.json()
        assert d["stdio"]["command"] == "uvx"
        assert d["stdio"]["args"] == ["mcpstore-cli", "install", "https://x"]
        assert d["recommended_transport"] == "stdio"
        assert d["server_name_suggestion"] == "uvx-demo"
        assert d["model_used"]
