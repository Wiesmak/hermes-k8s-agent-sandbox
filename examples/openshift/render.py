"""Render namespaced pilot resources using selectors discovered from actual workloads.

JSON is valid YAML. This script only writes manifests to stdout; it never calls the cluster.
"""

from __future__ import annotations
import argparse
import ipaddress
import json
from pathlib import Path


def selector(deployment):
    result = deployment["spec"]["selector"]["matchLabels"]
    if not result or any("REPLACE" in k + v for k, v in result.items()):
        raise ValueError("nonempty actual Deployment matchLabels required")
    if deployment["spec"]["selector"].get("matchExpressions"):
        raise ValueError("matchExpressions require a site-reviewed selector")
    return result


def peer(namespace, labels):
    return {
        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": namespace}},
        "podSelector": {"matchLabels": labels},
    }


def policy(name, namespace, labels, types, **rules):
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"podSelector": {"matchLabels": labels}, "policyTypes": types, **rules},
    }


def role(name, namespace, rules):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": {"name": name, "namespace": namespace},
        "rules": rules,
    }


def bind(name, namespace, gateway_ns, account):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": name, "namespace": namespace},
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": name},
        "subjects": [{"kind": "ServiceAccount", "name": account, "namespace": gateway_ns}],
    }


def render(args, gateway, router, dns_service, operator):
    gateway_ns = gateway["metadata"]["namespace"]
    router_ns = router["metadata"]["namespace"]
    gateway_labels, router_labels = selector(gateway), selector(router)
    runner_labels = {"app.kubernetes.io/name": "hermes-sandbox-runner"}
    dns_peer = peer(dns_service["metadata"]["namespace"], dns_service["spec"]["selector"])
    dns = {
        "to": [dns_peer],
        "ports": [{"protocol": p, "port": args.dns_pod_port} for p in ("UDP", "TCP")],
    }
    api = []
    for cidr in args.api_cidr:
        network = ipaddress.ip_network(cidr, strict=True)
        if network.prefixlen < (24 if network.version == 4 else 64):
            raise ValueError("supply narrow API Service/endpoint CIDRs, not broad network access")
        api.append(
            {
                "to": [{"ipBlock": {"cidr": str(network)}}],
                "ports": [{"protocol": "TCP", "port": p} for p in args.api_port],
            }
        )
    resources = []
    runner_peers = []
    for suffix in ("alpha", "beta"):
        ns = "hermes-pilot-test-" + suffix
        name = "approved-" + suffix
        runner_peers.append(peer(ns, runner_labels))
        resources.extend(
            [
                {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}},
                {
                    "apiVersion": "v1",
                    "kind": "ServiceAccount",
                    "metadata": {"name": "sandbox-execution", "namespace": ns},
                    "automountServiceAccountToken": False,
                },
                role(
                    "hermes-claims",
                    ns,
                    [
                        {
                            "apiGroups": ["extensions.agents.x-k8s.io"],
                            "resources": ["sandboxclaims"],
                            "verbs": ["get", "create"],
                        }
                    ],
                ),
                bind("hermes-claims", ns, gateway_ns, args.gateway_account),
                # Separate explicit smoke preflight read access; remove this RoleBinding after testing.
                role(
                    "hermes-smoke-preflight",
                    ns,
                    [
                        {
                            "apiGroups": ["extensions.agents.x-k8s.io"],
                            "resources": ["sandboxtemplates", "sandboxwarmpools"],
                            "resourceNames": [name],
                            "verbs": ["get"],
                        }
                    ],
                ),
                bind("hermes-smoke-preflight", ns, gateway_ns, args.gateway_account),
                {
                    "apiVersion": "v1",
                    "kind": "ResourceQuota",
                    "metadata": {"name": "pilot-budget", "namespace": ns},
                    "spec": {
                        "hard": {
                            "pods": "4",
                            "requests.cpu": "2",
                            "requests.memory": "2Gi",
                            "limits.cpu": "4",
                            "limits.memory": "4Gi",
                            "count/sandboxclaims.extensions.agents.x-k8s.io": "1",
                        }
                    },
                },
                policy(
                    "runner-isolation",
                    ns,
                    runner_labels,
                    ["Ingress", "Egress"],
                    ingress=[
                        {
                            "from": [peer(router_ns, router_labels)],
                            "ports": [{"protocol": "TCP", "port": 8888}],
                        }
                    ],
                    egress=[dns],
                ),
                {
                    "apiVersion": "extensions.agents.x-k8s.io/v1beta1",
                    "kind": "SandboxTemplate",
                    "metadata": {"name": name, "namespace": ns},
                    "spec": {
                        "service": True,
                        "podTemplate": {
                            "metadata": {"labels": runner_labels},
                            "spec": {
                                "serviceAccountName": "sandbox-execution",
                                "automountServiceAccountToken": False,
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                                "containers": [
                                    {
                                        "name": "runtime",
                                        "image": args.runner_image,
                                        "workingDir": "/workspace",
                                        "ports": [{"name": "runtime", "containerPort": 8888}],
                                        "env": [
                                            {"name": "HOME", "value": "/workspace"},
                                            {"name": "SANDBOX_BASE_DIR", "value": "/workspace"},
                                            {
                                                "name": "SANDBOX_EXEC_TIMEOUT_SECONDS",
                                                "value": "150",
                                            },
                                        ],
                                        "securityContext": {
                                            "allowPrivilegeEscalation": False,
                                            "readOnlyRootFilesystem": True,
                                            "capabilities": {"drop": ["ALL"]},
                                        },
                                        "resources": {
                                            "requests": {
                                                "cpu": "100m",
                                                "memory": "256Mi",
                                                "ephemeral-storage": "256Mi",
                                            },
                                            "limits": {
                                                "cpu": "1",
                                                "memory": "1Gi",
                                                "ephemeral-storage": "1Gi",
                                            },
                                        },
                                        "readinessProbe": {"httpGet": {"path": "/", "port": 8888}},
                                        "volumeMounts": [
                                            {"name": "workspace", "mountPath": "/workspace"},
                                            {"name": "tmp", "mountPath": "/tmp"},
                                        ],
                                    }
                                ],
                                "volumes": [
                                    {"name": "workspace", "emptyDir": {"sizeLimit": "512Mi"}},
                                    {"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}},
                                ],
                            },
                        },
                    },
                },
                {
                    "apiVersion": "extensions.agents.x-k8s.io/v1beta1",
                    "kind": "SandboxWarmPool",
                    "metadata": {"name": name, "namespace": ns},
                    "spec": {"replicas": 1, "sandboxTemplateRef": {"name": name}},
                },
            ]
        )
    resources.extend(
        [
            role(
                "hermes-smoke-operator",
                operator["metadata"]["namespace"],
                [
                    {
                        "apiGroups": ["apps"],
                        "resources": ["deployments"],
                        "resourceNames": [operator["metadata"]["name"]],
                        "verbs": ["get"],
                    }
                ],
            ),
            bind(
                "hermes-smoke-operator",
                operator["metadata"]["namespace"],
                gateway_ns,
                args.gateway_account,
            ),
            policy(
                "hermes-router-egress",
                gateway_ns,
                gateway_labels,
                ["Egress"],
                egress=[
                    dns,
                    *api,
                    {
                        "to": [peer(router_ns, router_labels)],
                        "ports": [{"protocol": "TCP", "port": args.router_pod_port}],
                    },
                ],
            ),
            policy(
                "hermes-pilot-router-ingress",
                router_ns,
                router_labels,
                ["Ingress"],
                ingress=[
                    {
                        "from": [peer(gateway_ns, gateway_labels)],
                        "ports": [{"protocol": "TCP", "port": args.router_pod_port}],
                    }
                ],
            ),
            policy(
                "hermes-pilot-router-egress",
                router_ns,
                router_labels,
                ["Egress"],
                egress=[
                    dns,
                    *api,
                    {"to": runner_peers, "ports": [{"protocol": "TCP", "port": 8888}]},
                ],
            ),
            role(
                "hermes-smoke-router",
                router_ns,
                [
                    {
                        "apiGroups": ["apps"],
                        "resources": ["deployments"],
                        "resourceNames": [router["metadata"]["name"]],
                        "verbs": ["get"],
                    }
                ],
            ),
            bind("hermes-smoke-router", router_ns, gateway_ns, args.gateway_account),
        ]
    )
    return {"apiVersion": "v1", "kind": "List", "items": resources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-deployment", type=Path, required=True)
    parser.add_argument("--router-deployment", type=Path, required=True)
    parser.add_argument("--dns-service", type=Path, required=True)
    parser.add_argument("--operator-deployment", type=Path, required=True)
    parser.add_argument("--gateway-account", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--api-cidr", action="append", required=True)
    parser.add_argument("--api-port", action="append", type=int, required=True)
    parser.add_argument("--dns-pod-port", type=int, required=True)
    parser.add_argument("--router-pod-port", type=int, required=True)
    args = parser.parse_args()
    if "@sha256:" not in args.runner_image or "REPLACE" in args.runner_image:
        parser.error("supply the real published runner image digest")
    docs = [
        json.loads(path.read_text())
        for path in (
            args.gateway_deployment,
            args.router_deployment,
            args.dns_service,
            args.operator_deployment,
        )
    ]
    print(json.dumps(render(args, *docs), indent=2))


if __name__ == "__main__":
    main()
