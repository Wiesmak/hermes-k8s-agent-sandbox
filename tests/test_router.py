"""Real SDK and loopback HTTP; no mocked CommandExecutor.run or synthetic provider."""

from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading

import pytest

from hermes_agent_sandbox.config import Policy, Profile
from hermes_agent_sandbox.errors import (
    ConfigurationError,
    TransferLimit,
    TransportUnavailable,
    UnsupportedRuntime,
)
from hermes_agent_sandbox.lifecycle import Lease
from hermes_agent_sandbox.router import RouterRuntime

OPENAPI = {
    "components": {
        "schemas": {
            "ExecuteRequest": {"properties": {"timeout_seconds": {}}},
            "ExecuteResponse": {"properties": {"timed_out": {}}},
        }
    },
    "paths": {"/execute": {}},
}


@contextmanager
def http_router(responder=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.reply()

        def do_POST(self):
            self.reply()

        def reply(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = json.loads(body) if body else None
            calls.append((self.command, self.path, dict(self.headers), payload))
            if responder:
                status, data = responder(self.command, self.path, payload)
            else:
                status, data = (
                    200,
                    (
                        OPENAPI
                        if self.path == "/openapi.json"
                        else {"stdout": "out", "stderr": "err", "exit_code": 7, "timed_out": False}
                    ),
                )
            data = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def runtime_at(url):
    return RouterRuntime(
        Profile("alpha", "pilot-alpha", "pool", router_url=url),
        Lease("claim", "uid", "owned-sandbox"),
    )


def test_sdk_router_headers_and_response():
    with http_router() as (url, calls):
        runtime = runtime_at(url)
        try:
            runtime.check_compatibility()
            result = runtime.run("echo hello", 12)
            assert (result.stdout, result.stderr, result.exit_code) == ("out", "err", 7)
            method, endpoint, headers, payload = calls[-1]
            assert method == "POST" and endpoint == "/execute"
            assert headers["X-Sandbox-ID"] == "owned-sandbox"
            assert headers["X-Sandbox-Namespace"] == "pilot-alpha"
            assert headers["X-Sandbox-Port"] == "8888"
            assert "X-Sandbox-Pod-IP" not in headers
            assert "Authorization" not in headers
            assert payload == {"command": "echo hello", "timeout_seconds": 12}
            assert runtime.connector.connection_config.api_url == url
            assert not runtime.connector.session.trust_env
        finally:
            runtime.close()


@pytest.mark.parametrize(
    "body",
    [
        b"invalid json",
        {},
        {"stdout": "x", "exit_code": 0},
        {"stdout": "x", "stderr": "", "exit_code": "0", "timed_out": False},
        {"stdout": "x", "stderr": "", "exit_code": 0, "timed_out": True},
    ],
)
def test_malformed_responses(body):
    with http_router(lambda *a: (200, body)) as (url, _):
        runtime = runtime_at(url)
        try:
            with pytest.raises(UnsupportedRuntime):
                runtime.run("echo", 1)
        finally:
            runtime.close()


def test_ambiguous_http_error_is_not_retried():
    with http_router(lambda *a: (502, {"message": "private-content"})) as (url, calls):
        runtime = runtime_at(url)
        try:
            with pytest.raises(TransportUnavailable) as error:
                runtime.run("mutate", 1)
            assert "private-content" not in str(error.value)
            assert len(calls) == 1
        finally:
            runtime.close()


def test_router_unreachable():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    sock.close()
    runtime = runtime_at(url)
    try:
        with pytest.raises(TransportUnavailable):
            runtime.run("echo", 1)
    finally:
        runtime.close()


def test_process_wait_cancel_and_payload():
    gate = threading.Event()

    def respond(*args):
        gate.wait(1)
        return 200, {"stdout": "done", "stderr": "", "exit_code": 0, "timed_out": False}

    with http_router(respond) as (url, calls):
        runtime = runtime_at(url)
        handle = runtime.start(
            "owned-sandbox",
            "cat",
            login=False,
            timeout=3,
            stdin_data="hello\n",
            max_output_bytes=2097152,
        )
        assert handle.poll() is None
        handle.kill()
        assert handle.poll() == -9
        gate.set()
        handle._worker.join(2)
        assert calls[0][3]["timeout_seconds"] == 3
        assert "aGVsbG8K" in calls[0][3]["command"]
        assert not handle.error
        runtime.close()


def test_runtime_timeout_result():
    with http_router(
        lambda *a: (200, {"stdout": "", "stderr": "timed out", "exit_code": 124, "timed_out": True})
    ) as (url, _):
        runtime = runtime_at(url)
        try:
            result = runtime.run("sleep 9", 1)
            assert result.timed_out and result.exit_code == 124
        finally:
            runtime.close()


def test_output_cap():
    with http_router(
        lambda *a: (
            200,
            {"stdout": "X" * 2097153, "stderr": "", "exit_code": 0, "timed_out": False},
        )
    ) as (url, _):
        runtime = runtime_at(url)
        try:
            with pytest.raises(TransferLimit):
                runtime.run("too much", 1)
        finally:
            runtime.close()


def test_infrastructure_error_propagates_through_hermes(identity):
    from hermes_agent_sandbox.environment import SandboxEnvironment

    with http_router(lambda *a: (500, {})) as (url, _):
        identity = replace(identity, profile=replace(identity.profile, router_url=url))
        runtime = RouterRuntime(identity.profile, Lease("claim", "uid", "sandbox"))
        env = SandboxEnvironment(identity, runtime.lease, runtime)
        try:
            with pytest.raises(TransportUnavailable):
                env.execute("echo")
        finally:
            env.cleanup()


def test_provider_acquires_and_runs_via_real_sdk(identity, monkeypatch):
    from hermes_agent_sandbox.provider import AgentSandboxProvider
    from test_core import Claims

    api = Claims()
    api.close = lambda: None
    with http_router() as (url, calls):
        identity = replace(identity, profile=replace(identity.profile, router_url=url))
        monkeypatch.setattr(
            "hermes_agent_sandbox.provider.load_policy",
            lambda: Policy({identity.home: identity.profile}),
        )
        monkeypatch.setattr("hermes_agent_sandbox.client.KubernetesClaims.in_cluster", lambda: api)
        provider = AgentSandboxProvider()
        assert provider.is_available()
        assert calls == []  # UI probe is offline
        env = provider.create_environment(cwd="/ignored", timeout=999, task_id="collision")
        result = env.execute("echo routed")
        assert result["returncode"] == 7
        assert result["output"] == "outerr"
        lease = env.lease
        env.cleanup()
        second = provider.create_environment(cwd="/ignored", timeout=1, task_id="collision")
        assert second.lease == lease and api.creates == 1
        second.cleanup()
        assert not api.deletes


@pytest.mark.parametrize(
    "url",
    [
        "ssh://host:22",
        "http://user:secret@host:80",
        "http://host:80/execute",
        "http://host:80/?q=x",
    ],
)
def test_router_url_validation(url):
    with pytest.raises(ConfigurationError):
        Profile("a", "b", "c", router_url=url)
