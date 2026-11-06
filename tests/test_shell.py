"""Linux-only contract execution: local subprocess is a TEST DOUBLE only."""

import os
import signal
import subprocess
import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux shell contract requires POSIX")


class TestRuntime:
    __test__ = False

    def __init__(self):
        self.closed = False

    def start(self, sandbox, script, *, login, timeout, stdin_data, max_output_bytes):
        # Emulates the required process contract, NOT an implementation of remote transport.
        proc = subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        )
        if stdin_data is not None:
            proc.stdin.write(stdin_data)
        proc.stdin.close()
        native_kill = proc.kill

        def kill():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                native_kill()

        proc.kill = kill
        return proc

    def close(self):
        self.closed = True


def test_shell_state_files_and_exit(identity, tmp_path):
    from dataclasses import replace
    from hermes_agent_sandbox.environment import SandboxEnvironment
    from hermes_agent_sandbox.lifecycle import Lease

    identity = replace(identity, profile=replace(identity.profile, cwd=str(tmp_path)))
    env = SandboxEnvironment(identity, Lease("test", "uid", "fake"), TestRuntime())
    try:
        env.init_session()
        result = env.execute(
            "mkdir child; cd child; export PILOT_VALUE=ok; printf hello; printf error >&2; false"
        )
        assert result["returncode"] == 1
        assert "hello" in result["output"] and "error" in result["output"]
        assert env.cwd == str(tmp_path / "child")
        assert "ok" in env.execute('printf %s "$PILOT_VALUE"')["output"]
        assert env.execute("cat > payload", stdin_data="file-data")["returncode"] == 0
        target = tmp_path / "download"
        env.fetch_file(str(tmp_path / "child/payload"), target, max_bytes=20)
        assert target.read_text() == "file-data"
        assert env.execute("sleep 30", timeout=1)["returncode"] == 124
    finally:
        env.cleanup()
