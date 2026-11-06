"""Opt-in live smoke test using the normal provider and real Hermes file tools.

Run from a configured Hermes container: python -m hermes_agent_sandbox.smoke
No mocked paths; creates files/claims only in dedicated test namespaces; retains them.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import shlex
import sys
import uuid

from .config import load_policy
from .errors import BackendError


@contextmanager
def profile_scope(home: str):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)
    print("PASS", message, flush=True)


def command(env, text, *, expected=0, timeout=None):
    result = env.execute(text, timeout=timeout)
    require(result.get("returncode") == expected, f"command status {expected}: {text}")
    return result.get("output", "")


def preflight(
    policy, homes, router_namespace, router_deployment, operator_namespace, operator_deployment
):
    from kubernetes import client, config

    config.load_incluster_config()
    with client.ApiClient() as api:
        operator = client.AppsV1Api(api).read_namespaced_deployment(
            operator_deployment, operator_namespace, _request_timeout=(5, 10)
        )
        require(bool(operator.status.available_replicas), "Red Hat Operator Deployment available")
        deployment = client.AppsV1Api(api).read_namespaced_deployment(
            router_deployment, router_namespace, _request_timeout=(5, 10)
        )
        require(bool(deployment.status.available_replicas), "official router Deployment available")
        for home in homes:
            profile = policy.profiles[home]
            pool = client.CustomObjectsApi(api).get_namespaced_custom_object(
                "extensions.agents.x-k8s.io",
                "v1beta1",
                profile.namespace,
                "sandboxwarmpools",
                profile.warm_pool,
                _request_timeout=(5, 10),
            )
            template = pool["spec"]["sandboxTemplateRef"]["name"]
            client.CustomObjectsApi(api).get_namespaced_custom_object(
                "extensions.agents.x-k8s.io",
                "v1beta1",
                profile.namespace,
                "sandboxtemplates",
                template,
                _request_timeout=(5, 10),
            )
            require(True, f"approved pool/template readable in {profile.namespace}")
            # Health request is to the router itself, not a sandbox endpoint.
            import requests

            with requests.Session() as session:
                session.trust_env = False
                response = session.get(
                    profile.router_url + "/healthz", timeout=(5, 10), allow_redirects=False
                )
                require(response.status_code == 200, "internal router /healthz reachable")
        # Claim readiness below is also the end-to-end controller/extension readiness check.


def run(args):
    from .provider import AgentSandboxProvider
    from .client import KubernetesClaims
    from .identity import Identity
    from tools.file_operations import ShellFileOperations

    policy = load_policy()
    homes = args.profile_home
    require(len(homes) == 2 and len(set(homes)) == 2, "two distinct profile homes selected")
    for home in homes:
        require(home in policy.profiles, "profile has an operator policy mapping")
        profile = policy.profiles[home]
        require(
            profile.namespace.startswith("hermes-pilot-test-"),
            "dedicated hermes-pilot-test-* namespace",
        )
        require(profile.persistent, "persistent profile policy")
    preflight(
        policy,
        homes,
        args.router_namespace,
        args.router_deployment,
        args.operator_namespace,
        args.operator_deployment,
    )
    provider = AgentSandboxProvider()
    run_id = uuid.uuid4().hex
    resources = []
    marker_paths = []
    try:
        for index, home in enumerate(homes):
            with profile_scope(home):
                require(provider.is_available(), "native provider available")
                env = provider.create_environment(
                    cwd="/workspace", timeout=30, task_id="colliding-smoke-session"
                )
                lease = env.lease
                resources.append(
                    {
                        "namespace": policy.profiles[home].namespace,
                        "claim": lease.name,
                        "uid": lease.uid,
                        "sandbox": lease.sandbox,
                        "marker": run_id,
                    }
                )
                try:
                    require(run_id in command(env, "echo " + shlex.quote(run_id)), "echo output")
                    require(command(env, "pwd").strip().startswith("/"), "remote absolute pwd")
                    require(bool(command(env, "whoami").strip()), "remote whoami")
                    require("Python" in command(env, "python --version"), "runner Python")
                    filename = f"/workspace/hermes-smoke-{run_id}-{index}.txt"
                    marker_paths.append(filename)
                    command(env, f"printf %s {shlex.quote(run_id)} > {shlex.quote(filename)}")
                    result = ShellFileOperations(env).read_file_raw(filename)
                    require(
                        not result.error and result.content == run_id,
                        "Hermes file tool reads sandbox marker",
                    )
                    directory = f"/workspace/hermes-smoke-{run_id}-{index}"
                    command(env, f"mkdir {shlex.quote(directory)}; cd {shlex.quote(directory)}")
                    require(command(env, "pwd").strip() == directory, "CWD persists across calls")
                    command(env, "export HERMES_SMOKE_STATE=retained")
                    require(
                        "retained" in command(env, 'printf %s "$HERMES_SMOKE_STATE"'),
                        "supported shell state persists",
                    )
                    command(env, "exit 23", expected=23)
                    command(env, "sleep 5", expected=124, timeout=1)
                    if index:
                        require(
                            lease.sandbox != resources[0]["sandbox"]
                            or policy.profiles[home].namespace != resources[0]["namespace"],
                            "profiles receive different sandbox identities",
                        )
                        absent = env.execute(f"test ! -e {shlex.quote(marker_paths[0])}")
                        require(absent["returncode"] == 0, "second profile cannot see first marker")
                finally:
                    env.cleanup()
                # Re-enter normal lifecycle with a fresh environment/client.
                identity = Identity.resolve(policy, "colliding-smoke-session")
                api = KubernetesClaims.in_cluster()
                try:
                    require(
                        api.get(identity.profile.namespace, lease.name)["metadata"]["uid"]
                        == lease.uid,
                        "cleanup retains persistent claim UID",
                    )
                finally:
                    api.close()
                reconnected = provider.create_environment(
                    cwd="/workspace", timeout=30, task_id="colliding-smoke-session"
                )
                try:
                    require(reconnected.lease == lease, "fresh client reconnects to same claim")
                    retained = ShellFileOperations(reconnected).read_file_raw(filename)
                    require(
                        not retained.error and retained.content == run_id,
                        "workspace state retained after reconnect",
                    )
                finally:
                    reconnected.cleanup()
        print("SUCCESS: real execution through official router; no resources deleted.")
    finally:
        print("RETAINED_RESOURCES=" + json.dumps(resources, sort_keys=True))
        print("Verify claim UID/ownership before approved cleanup; see docs/testing.md.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-home", action="append", required=True)
    parser.add_argument("--router-namespace", default="agent-sandbox-system")
    parser.add_argument("--router-deployment", default="sandbox-router-deployment")
    parser.add_argument("--operator-namespace", required=True)
    parser.add_argument("--operator-deployment", required=True)
    parser.add_argument(
        "--allow-provision",
        action="store_true",
        help="explicitly allow normal provider claim/file creation in test namespaces",
    )
    args = parser.parse_args()
    if not args.allow_provision:
        parser.error(
            "--allow-provision is required; this smoke test creates retained test resources"
        )
    try:
        run(args)
    except (BackendError, RuntimeError, KeyError) as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Kubernetes/HTTP raw exception text may contain headers or response bodies.
        print(
            f"FAIL {type(exc).__name__}: inspect platform readiness, policy and NetworkPolicies",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
