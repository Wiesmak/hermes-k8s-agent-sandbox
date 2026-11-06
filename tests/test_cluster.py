import os
import pytest


@pytest.mark.cluster
def test_prepared_namespace_read_only():
    if os.environ.get("AGENT_SANDBOX_LIVE_READ_ONLY") != "1":
        pytest.skip("explicit read-only cluster opt-in required")
    namespace = os.environ["AGENT_SANDBOX_TEST_NAMESPACE"]
    assert namespace.startswith("hermes-pilot-test-"), "dedicated test namespace required"
    from hermes_agent_sandbox.client import KubernetesClaims

    api = KubernetesClaims.in_cluster()
    try:
        # Exact resource only; no create, delete, shell execution or discovery mutation.
        claim = api.get(namespace, os.environ["AGENT_SANDBOX_TEST_CLAIM"])
        assert claim["apiVersion"] == "extensions.agents.x-k8s.io/v1beta1"
        assert claim["status"]["sandbox"]["name"]
    finally:
        api.close()
