# Controlled OpenShift pilot

Red Hat build of Agent Sandbox 1.13 is the intended Operator platform. It is Technology
Preview and its router is unauthenticated. Use the internal Service only; do not create
an execution Route. The plugin is functional through that router without authentication
patches, but the pilot requires enforced network isolation.

## Prepare artifacts and discover site values

1. Have the administrator install the Red Hat Operator and extension CRDs normally.
   This repository installs no operator or cluster-wide resources.
2. Build runner/Containerfile from an approved UBI 9 minimal base digest
   (microdnf repositories with Python 3.11 and nss_wrapper packages). Publish the runner image and
   record its actual digest. See runner/README.md. Validate arbitrary UID, read-only rootfs,
   workspace write permissions and readiness before using the template.
3. Install plugin wheel 0.2.1 into the existing immutable Hermes image.
4. Discover the existing gateway, Operator and router Deployments and DNS Service. Do
   not assume labels from an upstream manifest match the Red Hat installation.

```sh
oc -n agent-sandbox-system get deployment sandbox-router-deployment -o json > router.json
oc -n YOUR_GATEWAY_NAMESPACE get deployment YOUR_GATEWAY_DEPLOYMENT -o json > gateway.json
oc -n YOUR_OPERATOR_NAMESPACE get deployment YOUR_RED_HAT_OPERATOR_DEPLOYMENT -o json > operator.json
oc -n openshift-dns get service dns-default -o json > dns.json
oc -n agent-sandbox-system get service sandbox-router-svc -o yaml
oc -n openshift-dns get service dns-default -o yaml
oc -n default get service kubernetes -o yaml
oc -n default get endpoints kubernetes -o yaml
```

Router namespace/Deployment/Service defaults above are from Red Hat's 1.13 guide;
adjust them if your installation differs. Get the router Pod target port from its
Service/Deployment, and DNS Pod target port from the actual DNS Service/endpoints.
OpenShift DNS commonly uses a different Pod port from Service port 53; do not guess it.
For named target ports, resolve the port from the selected Pod/DaemonSet.

Record narrow CIDRs for the Kubernetes API Service IP and actual backend endpoints,
plus their actual destination ports. CNI/DNAT processing may enforce policies against
the backend address/port rather than the Service address. Include both as needed and
verify traffic. Do not open all RFC1918 or Internet egress as a shortcut.

## Render and review

examples/openshift/render.py produces a JSON Kubernetes List (valid YAML). It reads
selectors from these actual objects; it never changes the cluster.

```sh
python examples/openshift/render.py \
  --gateway-deployment gateway.json --router-deployment router.json \
  --operator-deployment operator.json --dns-service dns.json \
  --gateway-account YOUR_EXISTING_GATEWAY_SERVICEACCOUNT \
  --runner-image YOUR_REGISTRY/runner@sha256:YOUR_PUBLISHED_DIGEST \
  --router-pod-port ACTUAL_ROUTER_POD_PORT --dns-pod-port ACTUAL_DNS_POD_PORT \
  --api-cidr API_SERVICE_IP/32 --api-cidr API_BACKEND_IP/32 \
  --api-port ACTUAL_SERVICE_PORT --api-port ACTUAL_BACKEND_PORT > pilot.json
```

The generated resources are:
- Two dedicated hermes-pilot-test-alpha/beta namespaces with token-free sandbox accounts.
- Claim get/create Roles and bindings to the existing gateway account.
- Approved v1beta1 SandboxTemplates and pools; workload service=true, execution port 8888.
- Bounded resources, arbitrary UID, no capabilities/escalation, RuntimeDefault seccomp,
  read-only rootfs and writable workspace/tmp volumes.
- Gateway egress to actual router selectors, DNS and approved API endpoints.
- Router ingress only from actual gateway selectors; router egress to runner selectors,
  DNS and approved API endpoints.
- Runner ingress only from actual router selectors on 8888; runner egress only to DNS.
- Separate get-only smoke preflight permissions for named Operator/router Deployments
  and approved pools/templates. Remove those smoke RoleBindings after validation.

No gateway Deployment is replaced. Existing model endpoints, webhooks, observability
destinations and necessary platform traffic must be added as explicit site-reviewed
NetworkPolicy rules. The collector sidecar uses loopback within the gateway Pod, but
its exporter destination still needs egress. If the router already serves other
approved clients or exposes metrics to platform collectors, add those exact peers/ports
to the rendered ingress rules before applying; do not use an unrestricted namespace peer.

Review against installed Red Hat CRDs with server-side dry run. The example uses only
the documented v1beta1 template/pool/claim architecture and ordinary Pod fields, not
newer upstream networkPolicyManagement or env injection API fields.

```sh
oc apply --dry-run=server -f pilot.json
# After review/approval:
oc apply -f pilot.json
```

Mount examples/openshift/policy.json read-only at /etc/hermes-agent-sandbox/policy.json;
adapt homes to the actual gateway paths. Merge examples/openshift/hermes-config.yaml
into each served profile. The policy must remain administrator-owned outside writable
profile homes. No tokens or kubeconfigs belong in runner images or profile workspaces.

## Verify enforcement, not just object creation

NetworkPolicies are additive. Audit all policies selecting gateway, router and runners,
including controller-generated ones. A broad policy from another source can allow
traffic that the examples intend to deny. If the installed controller generates a
broader policy, use its installed CRD-supported template controls and verify the final
policy set after reconciliation. Do not blindly copy newer upstream policy fields.

Run the positive live smoke procedure in docs/testing.md. From a separately approved
probe Pod with labels that do NOT match the gateway selector, test that TCP/router
health and routed /execute are unreachable (short connect timeout, no retries).
Use only an echo request against a dedicated test sandbox for that negative check.
Also verify an unrelated Pod cannot reach the runner Service on 8888 directly, that
the gateway cannot bypass the router to that Service, and that one runner cannot reach
another runner or the API. From the allowed gateway, /healthz and routed commands
must work; from the router namespace, DNS and runner traffic must work for router pods
and not unrelated pods. Use your approved diagnostic image and explicit probe RBAC;
do not grant the agent Pod creation or Kubernetes exec as an execution fallback.

For example, from an administrator-prepared probe environment:

```sh
curl --connect-timeout 2 --max-time 3 http://sandbox-router-svc.agent-sandbox-system.svc.cluster.local:8080/healthz
curl --connect-timeout 2 --max-time 3 http://TEST_SANDBOX.hermes-pilot-test-alpha.svc.cluster.local:8888/
```

These should time out/refuse from unrelated workloads. An HTTP 200 or 4xx proves
reachability and fails a deny test. Verify probe labels, policies and CNI flow logs.
The default pilot does not expose the router externally.

## Persistence and cleanup

The minimal example uses emptyDir: it survives a Hermes gateway restart while the
sandbox Pod remains. For data durability across Pod replacement, provide administrator-
owned PVC-backed template storage appropriate to the storage class and pool semantics.
Never mount one writable workspace into different profile namespaces/trust domains.
Do not infer data durability from claim retention alone.

Normal cleanup never deletes persistent claims. The smoke command prints exact claim
names, namespaces and UIDs and retains its marker files. Inspect ownership annotations,
UID and pool before an approved operator deletion. Claim deletion may cascade into
Sandbox/Pod/storage deletion. Remove test claims, then pools/templates and test
namespaces only after checking that they contain no other resources. Remove generated
pilot policies/smoke RoleBindings from shared namespaces explicitly; do not delete
the Operator/router/gateway namespaces.
