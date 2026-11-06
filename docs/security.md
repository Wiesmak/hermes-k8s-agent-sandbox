# Controlled pilot security

Red Hat Agent Sandbox 1.13 is Technology Preview. Its router accepts unauthenticated
requests. This pilot deliberately permits internal HTTP through that official router.
Anyone who can reach it can select sandbox ID, namespace and port and access execution
APIs. NetworkPolicy is a network-level mitigation, not per-request authentication.
Do not expose a public Route or claim unrestricted production multitenancy.

Use dedicated profile namespaces and administrator-owned templates/pools. Apply policies
using actual router/gateway selectors, permit only gateway→router and router→runner,
and verify denied traffic from unrelated pods. Policies are additive: another broad
allow policy defeats a restrictive example. Audit controller-generated policies and
test enforcement after reconciliation, including with the chosen Kata/CNI mode.
See docs/openshift.md for discovery and verification procedures.

Gateway RBAC is get/create claims in approved namespaces; no Pod/Job creation, exec,
secret reads, privilege escalation or cluster-admin. Sandboxes have no mounted API
token and no management RoleBinding. Claims cannot select arbitrary images, volumes
or ServiceAccounts through plugin input. Admission/namespace controls must constrain
approved pools if defending against a compromised gateway rather than accidental input.

No gateway env is forwarded to execution. SDK sessions ignore .netrc and proxy/CA
environment variables. strip_env_keys additionally removes management selector names
from Hermes subprocess handling. The runtime's own environment contains only its
operator-controlled configuration. Credentials for cluster inspection, if needed,
must be explicitly delivered as a separate minimal read-only identity; writable
workspace files grant no OpenShift mutation permission.

Ownership checks validate home-derived identity, claim UID, namespace, pool and session.
Mutable annotations are not secure against namespace writers. All profiles/plugins
inside one gateway share process trust and management authority; separate gateways
are required for mutually hostile tenants. Per-call context checks prevent accidental
cross-profile cached-environment reuse.

Hermes dangerous-command guards remain enabled. Configure Hermes' native human
approval controls for consequential actions; no independent approval system is added.
Shell execution is intentionally useful and unrestricted within the assigned workload's
OS/container permissions. restricted-v2, arbitrary UID, dropped capabilities,
read-only rootfs, resource limits and token-free execution are represented in examples,
but must be verified on the actual cluster.

Commands are not replayed automatically. Network failure can leave an unknown outcome;
inspect state before resubmitting a mutating command. Output is bounded client-side.
The upstream runtime buffers server output in memory: pod memory/storage quotas remain
necessary. Disconnect/interrupt cannot signal the remote process through this API;
the server deadline kills its process group. Deliberately detached children can escape
the group, so detached process management is unsupported. Container lifetime and quotas
are the outer boundary; this release makes no perfect cancellation claim.

Errors/logs exclude command payloads and raw response bodies. Retained profile workspace
contents and runtime-readable secrets remain accessible to all sessions in that profile.
