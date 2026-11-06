from argparse import Namespace
import importlib.util
from pathlib import Path
import pytest


def renderer():
    spec = importlib.util.spec_from_file_location(
        "pilot_renderer", Path(__file__).resolve().parents[1] / "examples/openshift/render.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discovered_selectors_and_rbac_are_narrow():
    module = renderer()

    def deployment(name, ns, labels):
        return {
            "metadata": {"name": name, "namespace": ns},
            "spec": {"selector": {"matchLabels": labels}},
        }

    args = Namespace(
        dns_pod_port=5353,
        api_cidr=["10.0.0.1/32"],
        api_port=[443, 6443],
        gateway_account="gateway-sa",
        router_pod_port=8080,
        runner_image="registry.invalid/runner@sha256:" + "a" * 64,
    )
    docs = module.render(
        args,
        deployment("existing-gateway", "gateway-ns", {"site-gateway": "actual"}),
        deployment("vendor-router", "operator-ns", {"vendor-router-label": "actual"}),
        {"metadata": {"namespace": "dns-ns"}, "spec": {"selector": {"dns-pod": "actual"}}},
        deployment("vendor-operator", "operator-ns", {"operator-label": "actual"}),
    )["items"]
    ingress = next(d for d in docs if d["metadata"]["name"] == "hermes-pilot-router-ingress")
    peer = ingress["spec"]["ingress"][0]["from"][0]
    assert peer == {
        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "gateway-ns"}},
        "podSelector": {"matchLabels": {"site-gateway": "actual"}},
    }
    templates = [d for d in docs if d["kind"] == "SandboxTemplate"]
    assert len(templates) == 2
    for template in templates:
        assert template["apiVersion"] == "extensions.agents.x-k8s.io/v1beta1"
        assert template["spec"]["service"] is True
        spec = template["spec"]["podTemplate"]["spec"]
        assert spec["automountServiceAccountToken"] is False
        assert spec["containers"][0]["ports"][0]["containerPort"] == 8888
        assert spec["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True
    ordinary = [d for d in docs if d["kind"] == "Role" and d["metadata"]["name"] == "hermes-claims"]
    assert all(d["rules"][0]["verbs"] == ["get", "create"] for d in ordinary)


def test_empty_or_placeholder_selector_denied():
    module = renderer()
    for labels in ({}, {"REPLACE": "value"}):
        with pytest.raises(ValueError):
            module.selector({"spec": {"selector": {"matchLabels": labels}}})
