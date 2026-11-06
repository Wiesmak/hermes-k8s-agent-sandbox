"""Official SDK HTTP execution, always routed; no Kubernetes or local exec fallback."""

from __future__ import annotations

import base64
import io
import json
import logging
import shlex
import threading
import uuid
from typing import Any, cast

from k8s_agent_sandbox.commands.command_executor import CommandExecutor
from k8s_agent_sandbox.connector import SandboxConnector
from k8s_agent_sandbox.models import ExecutionResult, SandboxDirectConnectionConfig

from .config import Profile
from .errors import TransferLimit, TransportUnavailable, UnsupportedRuntime
from .lifecycle import Lease

log = logging.getLogger(__name__)


class RouterConnector(SandboxConnector):
    """Add bounded decoding to SDK 1.0.9; retain its routing and redirect checks."""

    def __init__(self, profile: Profile, lease: Lease):
        self.limit = profile.max_output_bytes
        super().__init__(
            sandbox_id=lease.sandbox,
            namespace=profile.namespace,
            connection_config=SandboxDirectConnectionConfig(
                api_url=profile.router_url, server_port=profile.runtime_port
            ),
            # DirectConnectionStrategy never uses Kubernetes helpers or discovery.
            # No pod-IP callback: only ID/namespace/port routing headers are emitted.
            k8s_helper=cast(Any, None),
        )
        for session in (self.session, self._no_retry_session):
            # Never inherit gateway proxy variables, .netrc credentials, or CA overrides.
            session.trust_env = False

    def send_request(self, method: str, endpoint: str, **kwargs: Any):
        kwargs["stream"] = True
        kwargs["_disable_retries"] = True
        response = None
        try:
            response = super().send_request(method, endpoint, **kwargs)
            if response.status_code != 200:
                raise UnsupportedRuntime("runtime returned an unexpected HTTP status")
            chunks = []
            size = 0
            # JSON escaping can use six bytes per output character. Bound the wire
            # body first, then decoded UTF-8 output. Never truncate file-tool data.
            wire_limit = 6 * self.limit + 65536
            for chunk in response.iter_content(chunk_size=8192):
                size += len(chunk)
                if size > wire_limit:
                    raise TransferLimit("runtime response exceeds configured output budget")
                chunks.append(chunk)
            body = b"".join(chunks)
            try:
                data = json.loads(body)
            except (ValueError, UnicodeError):
                raise UnsupportedRuntime(
                    "runtime returned invalid JSON; verify the pinned runner"
                ) from None
            if endpoint == "execute":
                if (
                    not isinstance(data, dict)
                    or not all(isinstance(data.get(k), str) for k in ("stdout", "stderr"))
                    or type(data.get("exit_code")) is not int
                    or type(data.get("timed_out")) is not bool
                ):
                    raise UnsupportedRuntime(
                        "runtime response lacks strict execution fields; verify SDK/runner versions"
                    )
                if len(data["stdout"].encode()) + len(data["stderr"].encode()) > self.limit:
                    raise TransferLimit("command output exceeds configured output budget")
                if data["timed_out"] and data["exit_code"] != 124:
                    raise UnsupportedRuntime("runtime returned an inconsistent timeout status")
            # SDK CommandExecutor consumes Response.json(); reuse the bounded body.
            response._content = body
            response._content_consumed = True
            return response
        except (TransferLimit, UnsupportedRuntime):
            raise
        except Exception:
            # Never include SDK response bodies, command payloads or request headers.
            raise TransportUnavailable(
                "router request failed; command outcome may be unknown; it was not retried"
            ) from None
        finally:
            if response is not None:
                response.close()


class BufferedOutput(io.TextIOBase):
    """Blocking, file-like output for Hermes' in-memory stream drain."""

    def __init__(self, process):
        self.process = process

    def readline(self, size=-1):
        self.process._done.wait()
        return self.process._output.readline(size)

    def read(self, size=-1):
        self.process._done.wait()
        return self.process._output.read(size)


class RoutedProcess:
    """Hermes process contract for buffered HTTP execution.

    No local subprocess is created. kill() stops waiting; the already-submitted
    command remains bounded by the runtime's server-side deadline.
    """

    def __init__(self, execute):
        self._output = io.StringIO()
        self.stdout = BufferedOutput(self)
        self.returncode: int | None = None
        self.error: Exception | None = None
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        # A single worker belongs to this request; shutdown never cancels server work.
        self._worker = threading.Thread(target=self._run, args=(execute,), daemon=True)
        self._worker.start()

    def _run(self, execute):
        try:
            result = execute()
            with self._lock:
                if not self._cancelled.is_set():
                    self._output.write(result.stdout + result.stderr)
                    self._output.seek(0)
                    self.returncode = result.exit_code
        except Exception as exc:
            with self._lock:
                if not self._cancelled.is_set():
                    self.error = exc
                    self.returncode = 1
        finally:
            self._done.set()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise TimeoutError("router execution is still pending")
        return self.returncode

    def kill(self):
        with self._lock:
            self._cancelled.set()
            self.returncode = -9
            self._done.set()

    def raise_if_failed(self):
        if self.error is not None:
            raise self.error


class RouterRuntime:
    def __init__(self, profile: Profile, lease: Lease):
        self.profile, self.lease = profile, lease
        self.connector = RouterConnector(profile, lease)
        self.commands = CommandExecutor(self.connector, None, "hermes-agent-sandbox")
        self._closed = False
        self._handles: list[RoutedProcess] = []
        self._lock = threading.Lock()

    def check_compatibility(self):
        response = self.connector.send_request("GET", "openapi.json", timeout=(5, 10))
        data = response.json()
        try:
            schemas = data["components"]["schemas"]
            if "timeout_seconds" not in schemas["ExecuteRequest"]["properties"]:
                raise KeyError("timeout")
            if "timed_out" not in schemas["ExecuteResponse"]["properties"]:
                raise KeyError("timeout response")
            if "/execute" not in data["paths"]:
                raise KeyError("execute")
        except (KeyError, TypeError):
            raise UnsupportedRuntime(
                "runner does not expose the pinned Python runtime timeout API"
            ) from None

    def run(self, command: str, timeout: int) -> ExecutionResult:
        if self._closed:
            raise TransportUnavailable("router runtime connection is closed")
        fields = {
            "request_id": uuid.uuid4().hex,
            "profile": self.profile.profile_id,
            "sandbox": self.lease.sandbox,
            "claim": self.lease.name,
        }
        log.debug("command_started", extra=fields)
        try:
            # Legacy HTTP runtime rejects SDK cwd/env options. Hermes wraps cwd/env
            # in the shell script instead. API timeout_seconds enforces the deadline.
            result = self.commands.run(command, timeout=timeout + 10, command_timeout=timeout)
            if result.timed_out:
                log.info("command_timeout", extra={**fields, "timeout": timeout})
            else:
                log.debug("command_finished", extra={**fields, "exit_code": result.exit_code})
            return result
        except (TransferLimit, UnsupportedRuntime, TransportUnavailable):
            log.warning("command_infrastructure_error", extra=fields)
            raise
        except Exception:
            raise UnsupportedRuntime("SDK/runtime execution compatibility failure") from None

    def start(
        self,
        sandbox: str,
        script: str,
        *,
        login: bool,
        timeout: int,
        stdin_data: str | None,
        max_output_bytes: int,
    ) -> RoutedProcess:
        if sandbox != self.lease.sandbox:
            raise UnsupportedRuntime("runtime is bound to a different sandbox")
        # Bash is explicit: runtime /execute itself launches /bin/sh -c.
        argv = "/bin/bash " + ("-l " if login else "") + "-c " + shlex.quote(script)
        if stdin_data is not None:
            if len(stdin_data.encode()) > self.profile.max_file_bytes:
                raise TransferLimit("stdin exceeds operator transfer limit")
            encoded = base64.b64encode(stdin_data.encode()).decode("ascii")
            argv = "printf %s " + shlex.quote(encoded) + " | base64 -d | " + argv
        # Merge on the shell side, preserving relative order and CWD markers.
        argv = "{ " + argv + "; } 2>&1"
        with self._lock:
            if self._closed:
                raise TransportUnavailable("router runtime connection is closed")
            self._handles = [h for h in self._handles if h.poll() is None]
            handle = RoutedProcess(lambda: self.run(argv, timeout))
            self._handles.append(handle)
            return handle

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for handle in self._handles:
                if handle.poll() is None:
                    handle.kill()
            self._handles.clear()
            self.connector.close()
