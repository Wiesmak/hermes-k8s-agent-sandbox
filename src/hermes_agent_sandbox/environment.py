"""Hermes shell snapshot, CWD and remote file semantics via its real BaseEnvironment."""

import threading
from typing import Any
from tools.environments.base import BaseEnvironment
from .client import Runtime
from .identity import Identity
from .lifecycle import Lease
from .errors import TransferLimit, TransportUnavailable


class SandboxEnvironment(BaseEnvironment):
    _stdin_mode = "payload"
    uses_host_filesystem = False
    is_local = False

    def __init__(self, identity: Identity, lease: Lease, runtime: Runtime):
        self.identity, self.lease, self.runtime = identity, lease, runtime
        self._execution_lock = threading.RLock()
        self._closed = False
        self._persistent = identity.profile.persistent
        self._session_scoped = not self._persistent
        super().__init__(cwd=identity.profile.cwd, timeout=identity.profile.command_timeout, env={})

    def _run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None):
        self.identity.assert_current()
        if self._closed:
            raise TransportUnavailable("environment connection is closed; reacquire the claim")
        if (
            stdin_data is not None
            and len(stdin_data.encode()) > self.identity.profile.max_file_bytes
        ):
            raise TransferLimit("stdin exceeds operator transfer limit")
        return self.runtime.start(
            self.lease.sandbox,
            cmd_string,
            login=login,
            timeout=min(timeout, self.identity.profile.command_timeout),
            stdin_data=stdin_data,
            max_output_bytes=self.identity.profile.max_output_bytes,
        )

    def execute(self, command: str, timeout=None, **kwargs: Any):
        self.identity.assert_current()
        with self._execution_lock:
            return super().execute(
                command, timeout=min(timeout or self.timeout, self.timeout), **kwargs
            )

    def fetch_file(self, remote_path, local_dest, *, max_bytes):
        self.identity.assert_current()
        return super().fetch_file(
            remote_path, local_dest, max_bytes=min(max_bytes, self.identity.profile.max_file_bytes)
        )

    def _wait_for_process(self, proc, timeout=120, **kwargs):
        result = super()._wait_for_process(proc, timeout=timeout, **kwargs)
        # SDK infrastructure failures must never masquerade as a command exit.
        check = getattr(proc, "raise_if_failed", None)
        if check is not None:
            check()
        return result

    def exec_prefix(self, *, user=None, interactive=True):
        self.identity.assert_current()
        return None

    def cleanup(self):
        # Includes __del__, idle reaper, process exit. Never deletes Kubernetes resources.
        with self._execution_lock:
            if not self._closed:
                self.runtime.close()
                self._closed = True
