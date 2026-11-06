"""Explicit Docker opt-in: image execution behind a routing-only HTTP test double."""

from dataclasses import replace
import os
import subprocess
import time
import uuid

import pytest
import requests

from hermes_agent_sandbox.environment import SandboxEnvironment
from hermes_agent_sandbox.lifecycle import Lease
from hermes_agent_sandbox.router import RouterRuntime
from test_router import http_router


@pytest.mark.docker
def test_built_runner_arbitrary_uid_and_real_execution(identity):
    image = os.environ.get("HERMES_RUNNER_TEST_IMAGE")
    if not image:
        pytest.skip("set HERMES_RUNNER_TEST_IMAGE to the built runner image for Docker test")
    name = "hermes-runner-test-" + uuid.uuid4().hex[:12]
    started = False
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                name,
                "--user",
                "12345:0",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "256m",
                "--cpus",
                "1",
                "--tmpfs",
                "/tmp:rw,nosuid,size=64m,mode=1777",
                "--tmpfs",
                "/workspace:rw,nosuid,size=64m,mode=1777",
                "-p",
                "127.0.0.1::8888",
                image,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        started = True
        address = (
            subprocess.check_output(["docker", "port", name, "8888/tcp"], timeout=10)
            .decode()
            .strip()
        )
        upstream_url = "http://" + address
        with requests.Session() as session:
            session.trust_env = False
            ready = False
            for _ in range(60):
                try:
                    ready = session.get(upstream_url + "/", timeout=1).status_code == 200
                except requests.RequestException:
                    pass
                if ready:
                    break
                time.sleep(0.25)
            assert ready, subprocess.check_output(
                ["docker", "logs", name], stderr=subprocess.STDOUT
            ).decode()

            def forward(method, path, payload):
                response = session.request(method, upstream_url + path, json=payload, timeout=20)
                return response.status_code, response.content

            with http_router(forward) as (router_url, calls):
                identity = replace(
                    identity, profile=replace(identity.profile, router_url=router_url)
                )
                runtime = RouterRuntime(
                    identity.profile, Lease("claim", "uid", "container-sandbox")
                )
                try:
                    runtime.check_compatibility()
                    assert runtime.run("id -u", 3).stdout.strip() == "12345"
                    assert runtime.run("whoami", 3).stdout.strip() == "sandbox"
                    assert runtime.run("python --version", 3).stdout.startswith("Python 3.11")
                    assert runtime.run("touch /opt/runtime/forbidden", 3).exit_code != 0
                    assert (
                        runtime.run(
                            "test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token", 3
                        ).exit_code
                        == 0
                    )
                    split = runtime.run("printf stdout; printf stderr >&2; exit 17", 3)
                    assert (split.stdout, split.stderr, split.exit_code) == ("stdout", "stderr", 17)
                    expired = runtime.run("printf before; sleep 10", 1)
                    assert (
                        expired.exit_code == 124
                        and expired.timed_out
                        and expired.stdout == "before"
                    )
                    env = SandboxEnvironment(identity, runtime.lease, runtime)
                    env.init_session()
                    assert env.execute("mkdir child; cd child; export STATE=ok")["returncode"] == 0
                    assert env.cwd == "/workspace/child"
                    assert env.execute('printf %s "$STATE"')["output"].strip() == "ok"
                    assert (
                        env.execute("cat > remote.txt", stdin_data="exact\nno-final-newline")[
                            "returncode"
                        ]
                        == 0
                    )
                    from tools.file_operations import ShellFileOperations

                    files = ShellFileOperations(env)
                    result = files.read_file_raw("remote.txt")
                    assert not result.error and result.content == "exact\nno-final-newline"
                    assert not files.write_file("written.txt", "remote-write\n").error
                    assert files.read_file_raw("written.txt").content == "remote-write\n"
                    assert calls and all(c[2]["X-Sandbox-ID"] == "container-sandbox" for c in calls)
                    env.cleanup()
                finally:
                    runtime.close()
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
