"""Real pinned Hermes imports; no substitute ABC, factory, or shell wrapper."""

from importlib.metadata import entry_points
from pathlib import Path
from unittest.mock import Mock
import pytest


def test_wheel_entrypoint_and_registration():
    from hermes_agent_sandbox import register
    from agent.terminal_env_provider import TerminalEnvironmentProvider

    ctx = Mock()
    register(ctx)
    provider = ctx.register_terminal_environment_provider.call_args.args[0]
    assert isinstance(provider, TerminalEnvironmentProvider)
    eps = entry_points(group="hermes_agent.plugins")
    assert any(ep.name == "agent_sandbox" for ep in eps)


def test_hermes_factory_selection(monkeypatch):
    from tools import terminal_tool_backends as factory
    from hermes_agent_sandbox.provider import AgentSandboxProvider
    from hermes_agent_sandbox.errors import OwnershipMismatch
    from hermes_agent_sandbox.config import Policy

    monkeypatch.setattr(factory, "_get_plugin_env_provider", lambda name: AgentSandboxProvider())
    monkeypatch.setattr("hermes_agent_sandbox.provider.load_policy", lambda: Policy({}))
    with pytest.raises(OwnershipMismatch):
        factory._create_environment("agent_sandbox", "ignored", "/workspace", 30)


def test_native_manifest():
    from hermes_cli.plugins_manifest import parse_manifest_file

    root = Path(__file__).resolve().parents[1]
    manifest = parse_manifest_file(root / "plugin.yaml", root, "user", "")
    assert manifest.name == "agent_sandbox"


def test_environment_remote_contract(identity, monkeypatch):
    from hermes_agent_sandbox.environment import SandboxEnvironment
    from hermes_agent_sandbox.lifecycle import Lease
    from hermes_agent_sandbox.errors import OwnershipMismatch, TransferLimit

    runtime = Mock()
    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), runtime)
    assert not env.uses_host_filesystem
    env._run_bash("printf hi", stdin_data="payload")
    assert runtime.start.call_args.args == ("remote", "printf hi")
    assert runtime.start.call_args.kwargs["stdin_data"] == "payload"
    with pytest.raises(TransferLimit):
        env._run_bash("cat", stdin_data="x" * (identity.profile.max_file_bytes + 1))
    monkeypatch.setattr("hermes_agent_sandbox.identity.active_home", lambda: "/another-profile")
    with pytest.raises(OwnershipMismatch):
        env.execute("id")
    env.cleanup()
    env.cleanup()
    runtime.close.assert_called_once()
