import json
import os
from unittest.mock import Mock
import pytest

from hermes_agent_sandbox.config import Policy
from hermes_agent_sandbox.errors import ConfigurationError, TransportUnavailable, TransferLimit
from hermes_agent_sandbox.lifecycle import Lease


def test_policy_load_and_unknown_field(tmp_path):
    path = tmp_path / "policy.json"
    home = str(tmp_path.resolve())
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    home: {"profile_id": "alpha", "namespace": "approved", "warm_pool": "pool"}
                }
            }
        )
    )
    if os.name == "posix" and os.geteuid() != 0:
        with pytest.raises(ConfigurationError):
            Policy.load(path)
        return
    assert Policy.load(path).profiles[home].profile_id == "alpha"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    home: {
                        "profile_id": "alpha",
                        "namespace": "approved",
                        "warm_pool": "pool",
                        "image": "evil",
                    }
                }
            }
        )
    )
    with pytest.raises(ConfigurationError):
        Policy.load(path)


def test_policy_missing_and_malformed(tmp_path):
    path = tmp_path / "missing"
    with pytest.raises(ConfigurationError):
        Policy.load(path)
    path.write_text("{ broken")
    with pytest.raises(ConfigurationError):
        Policy.load(path)


def test_ambiguous_execution_never_replayed(identity):
    from hermes_agent_sandbox.environment import SandboxEnvironment

    runtime = Mock()
    runtime.start.side_effect = TransportUnavailable("execution outcome unknown")
    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), runtime)
    with pytest.raises(TransportUnavailable):
        env._run_bash("potentially-mutating-command")
    runtime.start.assert_called_once()
    env.cleanup()


def test_payload_limit_before_runtime(identity):
    from hermes_agent_sandbox.environment import SandboxEnvironment

    runtime = Mock()
    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), runtime)
    with pytest.raises(TransferLimit):
        env._run_bash("cat", stdin_data="X" * (identity.profile.max_file_bytes + 1))
    runtime.start.assert_not_called()
    env.cleanup()


def test_file_tools_dispatch_remote_env(identity, monkeypatch):
    from tools.file_operations import ShellFileOperations
    from hermes_agent_sandbox.environment import SandboxEnvironment

    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), Mock())
    # Exercise real ShellFileOperations dispatch; execution transport remains a fake.
    execute = Mock(return_value={"output": "remote-content", "returncode": 0})
    monkeypatch.setattr(env, "execute", execute)
    operations = ShellFileOperations(env)
    operations._exec("cat file")
    assert execute.call_args.kwargs["cwd"] == "/workspace"
    env.cwd = "/workspace/changed"
    operations._exec("cat another")
    assert execute.call_args.kwargs["cwd"] == "/workspace/changed"
    env.cleanup()


def test_safe_cleanup_disconnect_only(identity):
    from hermes_agent_sandbox.environment import SandboxEnvironment

    runtime = Mock()
    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), runtime)
    env.cleanup()
    env.cleanup()
    runtime.close.assert_called_once()
    with pytest.raises(TransportUnavailable):
        env._run_bash("id")


def test_delete_precondition_on_wire():
    from hermes_agent_sandbox.client import KubernetesClaims

    api = Mock()
    KubernetesClaims(api).delete("namespace", "claim", "expected-uid")
    kwargs = api.delete_namespaced_custom_object.call_args.kwargs
    assert kwargs["body"]["preconditions"] == {"uid": "expected-uid"}
    assert kwargs["_request_timeout"] == (5, 10)
