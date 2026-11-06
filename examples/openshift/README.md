# Functional pilot resources

Follow docs/openshift.md from the repository root. render.py consumes actual gateway,
router and Operator Deployment JSON plus the actual DNS Service JSON and explicit
network ports/API CIDRs. It emits a reviewable namespaced Kubernetes List without
accessing the cluster. There are no fabricated vendor selectors.

The Red Hat Operator and its router must already be installed. Supply your own runner
image digest, built from runner/Containerfile. Merge hermes-config.yaml into each profile
and mount the adapted policy.json in the existing gateway. No replacement gateway or
cluster-wide component is installed.

The two namespaces are dedicated hermes-pilot-test-alpha and hermes-pilot-test-beta.
Run the opt-in live smoke command in docs/testing.md. The example uses emptyDir for
minimal operation; use approved PVC storage for surviving sandbox Pod replacement.
NetworkPolicies require actual allowed/denied connection verification, including
auditing other additive policies and site-specific platform traffic.
