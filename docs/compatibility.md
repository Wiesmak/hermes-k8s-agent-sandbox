# Compatibility

## Pinned implementation

| Component | Version / evidence | Behavior used |
|---|---|---|
| Hermes | v0.23.0, df1774294af26285ae758c6114f3f2f60e2a602d | Native provider/context registration, wheel entry points, BaseEnvironment |
| Agent Sandbox SDK | published k8s-agent-sandbox==1.0.9 | SandboxDirectConnectionConfig, SandboxConnector, CommandExecutor.run |
| Official workload runtime | python-runtime-sandbox/main.py at v1.0.9, b1277676f8bf0e82ea299928997ecf5d696a92f1 | HTTP /execute, timeout_seconds, stdout/stderr/exit_code/timed_out |
| Kubernetes Python | kubernetes==34.1.0 | Namespace claim get/create and UID-preconditioned explicit cleanup |
| Red Hat distribution | OpenShift Sandboxed Containers 1.13, Technology Preview | Documented v1beta1 Sandbox and extension CRDs; official HTTP router |
| Runner API dependencies | FastAPI 0.121.0, Uvicorn 0.38.0, python-multipart 0.0.20 | Hashed runner/requirements.txt; upstream source retained |

SDK 1.0.10 is an upstream Git tag but was not published to PyPI at investigation time;
1.0.9 is the installed and locked release. SDK pyproject requires Python >=3.11,
kubernetes!=36.0.0, requests, urllib3, pydantic and prometheus-client.
This release uses neither its gRPC extra nor a sandboxd direct transport.

Red Hat's examples demonstrate HTTP workload routing, not a standard installed execution
server. We package the pinned upstream Python runtime as an ordinary custom workload.
This does not require modifying the Red Hat Operator/router or assuming sandboxd is bundled.
It does not imply Red Hat support for that upstream SDK or custom workload image.

## Exact routed contract

The SDK DirectConnectionStrategy returns the configured router origin and injects
X-Sandbox-ID, X-Sandbox-Namespace, X-Sandbox-Port. No pod-IP callback is supplied.
A bounded connector subclass disables retries and environment-derived proxies/.netrc,
reads JSON with a wire/output cap, rejects redirects through the SDK, and strictly
validates execution fields before the SDK decodes its ExecutionResult.

We use the SDK's connector/executor components after the existing ownership-checked
lifecycle resolves a Lease. The high-level SandboxClient was inspected: create_sandbox
and get_sandbox exist, but get_sandbox performs additional claim/Sandbox discovery and
can attach cleanup semantics not needed here. Supplying the known lease to the SDK
connector avoids duplicating lifecycle and avoids Pod-IP hints. No private plugin
loader or alternate execution protocol is introduced.

CommandExecutor.run POSTs /execute with command and timeout_seconds. The legacy API
does not accept SDK cwd/env arguments; Hermes embeds those in explicit bash scripts.
Payload stdin is base64-decoded into the bash pipeline. Stdout/stderr are merged in
the sandbox for Hermes' output contract; SDK run() itself retains the separate fields.
Missing fields, malformed JSON, incompatible OpenAPI and inconsistent timeout data fail
as infrastructure/compatibility errors, not success or ordinary command failures.

The runner timeout is min(request, server limit); its timeout kills the process group,
returns exit 124, timed_out=true and captured output. A child that creates a new session
can escape that group. Native remote signals/streaming are unavailable in this routed
HTTP runtime. Local wait cancellation does not stop submitted remote work immediately.

## Hermes source findings

Provider accepts future **kwargs; custom terminal config keys are not forwarded by the
v0.23.0 factory. Protected policy is separate. get_hermes_home uses routed context scope;
task ID alone is insufficient. Scoped terminal caches exist; every environment call
also checks the current home to deny accidental cache reuse across profiles.

BaseEnvironment spawns per call, snapshots exported env/functions/aliases, carries CWD
through markers, and accepts payload stdin. The custom process handle blocks its output
stream until the buffered HTTP result arrives and preserves errors separately.
File tools use ShellFileOperations because uses_host_filesystem=false. Wheel entry
points and real PluginContext registration are tested without patching core.

Current online docs describe newer sandboxd gRPC features; those are not enabled here.
Persistent workspace identity survives gateway restart. A newly created environment
has a fresh shell snapshot; login shell state and background processes are not restored.
The example emptyDir does not survive Pod replacement; use approved persistent storage
for that guarantee.

## Evidence

- [Pinned SDK/runtime source](https://github.com/kubernetes-sigs/agent-sandbox/tree/b1277676f8bf0e82ea299928997ecf5d696a92f1)
- [Python SDK guide](https://agent-sandbox.sigs.k8s.io/docs/python-client/)
- [SDK reference](https://agent-sandbox.sigs.k8s.io/docs/getting_started/sdk_reference/python/)
- [Hermes pinned provider](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/agent/terminal_env_provider.py)
- [Hermes pinned base](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/environments/base.py)
- [Hermes terminal scoping](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/tools/terminal_tool.py)
- [Red Hat configure / CRDs / router](https://docs.redhat.com/en/documentation/openshift_sandboxed_containers/1.13/html/deploying_red_hat_build_of_agent_sandbox/configure-agent-sandbox-overview_agent-sandbox)
- [Red Hat preview limitations](https://docs.redhat.com/fr/documentation/openshift_sandboxed_containers/1.13/html/release_notes/technology-previews)

The runtime has a real implementation and offline protocol tests. Operator compatibility,
CNI enforcement, Kata behavior, image SCC admission and actual routed execution on
OpenShift still require the live smoke procedure.
