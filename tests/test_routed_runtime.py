"""Real HTTP SDK -> router double -> unmodified official runtime -> real shell.

The router double only routes HTTP; it never manufactures command results.
Linux covers native deadlines. Windows optionally uses Git Bash as a test-shell shim.
"""

from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from hermes_agent_sandbox.config import Policy
from hermes_agent_sandbox.environment import SandboxEnvironment
from hermes_agent_sandbox.lifecycle import Lease
from hermes_agent_sandbox.provider import AgentSandboxProvider
from hermes_agent_sandbox.router import RouterRuntime
from test_router import http_router


@pytest.fixture
def routed_runner(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "runner/main.py"
    spec = importlib.util.spec_from_file_location("official_pilot_runtime", source)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    monkeypatch.setenv("SANDBOX_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("SANDBOX_EXEC_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    if os.name != "posix":
        bash = Path("C:/Program Files/Git/bin/bash.exe")
        if not bash.is_file():
            pytest.skip("real shell test requires Linux or installed Git Bash")
        original = runtime._run_command
        monkeypatch.setattr(
            runtime, "_run_command", lambda args, timeout: original([str(bash), *args[1:]], timeout)
        )
    with TestClient(runtime.app) as upstream:

        def forward(method, path, payload):
            result = upstream.request(method, path, json=payload)
            return result.status_code, result.content

        with http_router(forward) as (url, calls):
            yield url, calls


def test_real_execution_state_and_files(identity, routed_runner, tmp_path):
    from tools.file_operations import ShellFileOperations

    url, calls = routed_runner
    identity = replace(
        identity, profile=replace(identity.profile, router_url=url, cwd=tmp_path.as_posix())
    )
    runtime = RouterRuntime(identity.profile, Lease("claim", "uid", "sandbox"))
    runtime.check_compatibility()
    env = SandboxEnvironment(identity, runtime.lease, runtime)
    try:
        env.init_session()
        result = env.execute("printf stdout; printf stderr >&2; false")
        assert result["returncode"] == 1
        assert "stdout" in result["output"] and "stderr" in result["output"]
        assert env.execute("mkdir child; cd child; export STATE=kept")["returncode"] == 0
        assert env.cwd.endswith("/child")
        assert env.execute('printf %s "$STATE"')["output"].strip() == "kept"
        assert (
            env.execute("cat > payload.txt", stdin_data="exact\nno-final-newline")["returncode"]
            == 0
        )
        files = ShellFileOperations(env)
        result = files.read_file_raw("payload.txt")
        assert not result.error and result.content == "exact\nno-final-newline"
        written = files.write_file("written.txt", "file-tool-write\n")
        assert not written.error
        assert files.read_file_raw("written.txt").content == "file-tool-write\n"
        assert any(call[3] and "command" in call[3] for call in calls)
        assert all(call[2]["X-Sandbox-ID"] == "sandbox" for call in calls)
    finally:
        env.cleanup()


@pytest.mark.skipif(os.name != "posix", reason="official process-group deadline requires Linux")
def test_real_runtime_timeout(identity, routed_runner, tmp_path):
    url, _ = routed_runner
    identity = replace(
        identity, profile=replace(identity.profile, router_url=url, cwd=str(tmp_path))
    )
    runtime = RouterRuntime(identity.profile, Lease("claim", "uid", "sandbox"))
    try:
        result = runtime.run("printf before; sleep 10", 1)
        assert result.exit_code == 124 and result.timed_out
        assert result.stdout == "before"
    finally:
        runtime.close()


def test_normal_provider_real_runner(identity, routed_runner, monkeypatch, tmp_path):
    from test_core import Claims

    url, calls = routed_runner
    identity = replace(
        identity, profile=replace(identity.profile, router_url=url, cwd=tmp_path.as_posix())
    )
    api = Claims()
    api.close = lambda: None
    monkeypatch.setattr(
        "hermes_agent_sandbox.provider.load_policy",
        lambda: Policy({identity.home: identity.profile}),
    )
    monkeypatch.setattr("hermes_agent_sandbox.client.KubernetesClaims.in_cluster", lambda: api)
    provider = AgentSandboxProvider()
    env = provider.create_environment(cwd="/ignored", timeout=99)
    try:
        assert env.execute("echo actual-runtime")["output"].strip() == "actual-runtime"
        assert calls[-1][2]["X-Sandbox-ID"] == env.lease.sandbox
    finally:
        env.cleanup()
    attached = provider.create_environment(cwd="/ignored", timeout=99)
    try:
        assert attached.lease == env.lease
        assert api.creates == 1 and not api.deletes
    finally:
        attached.cleanup()
