"""Exercise Hermes' real waiter without starting any local or remote command."""

from io import StringIO
from unittest.mock import Mock
import pytest
from hermes_agent_sandbox.environment import SandboxEnvironment
from hermes_agent_sandbox.lifecycle import Lease


class Handle:
    def __init__(self, code=None, output=""):
        self.returncode = code
        self.stdout = StringIO(output)
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_stdout_and_status(identity):
    runtime = Mock()
    runtime.start.return_value = Handle(7, "stdout\nstderr\n")
    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), runtime)
    result = env.execute("some-command")
    assert result["returncode"] == 7
    assert result["output"] == "stdout\nstderr\n"
    env.cleanup()


def test_timeout_calls_remote_handle_kill(identity):
    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), Mock())
    handle = Handle()
    result = env._wait_for_process(handle, timeout=0.01)
    assert handle.killed
    assert result["returncode"] == 124
    env.cleanup()


def test_keyboard_interrupt_cancels_handle(identity, monkeypatch):
    env = SandboxEnvironment(identity, Lease("claim", "uid", "remote"), Mock())
    handle = Handle()

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("tools.environments.base.is_interrupted", interrupt)
    with pytest.raises(KeyboardInterrupt):
        env._wait_for_process(handle, timeout=1)
    assert handle.killed
    env.cleanup()
