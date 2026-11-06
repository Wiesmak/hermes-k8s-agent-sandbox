# hermes-agent-sandbox-backend

Standalone Hermes terminal backend **agent_sandbox**, version **0.2.0**.
Runs shell commands and Hermes file operations in Agent Sandbox-managed workloads
through the **official sandbox-router-svc**. No Hermes core patch or execution fallback.

Targets Hermes v0.23.0, the v1beta1 CRDs documented in Red Hat build of Agent Sandbox
1.13, and the pinned upstream Python runtime/SDK described below. Red Hat 1.13 is
**Technology Preview**. No live OpenShift validation or Red Hat production support is claimed.

**Security warning:** Red Hat's router accepts unauthenticated requests. Anyone who
can reach it can target sandbox workloads. Internal HTTP is the accepted controlled
pilot mode; namespace isolation and verified NetworkPolicies are mandatory mitigations,
not per-request authentication. Do not expose the execution router through a public Route
or use this configuration for unrestricted multitenancy.

## Capabilities

- Official SDK 1.0.9 HTTP /execute via SandboxDirectConnectionConfig.
- Deterministic claim acquisition and reattachment, one persistent sandbox per profile.
- Real Hermes BaseEnvironment CWD and shell snapshots; payload stdin and remote file tools.
- Strict command status/timeout decoding, bounded response reception, no execution retries.
- Disconnect-only cleanup; claims survive gateway restarts.
- Dangerous-command approval guards remain enabled.

Native PTYs, interactive streaming, immediate remote cancellation and detached background
process management are not supported. Interrupts stop the local wait; submitted commands
remain bounded by their server-side deadline. Persistent workspace files survive gateway
restarts; surviving sandbox Pod replacement requires persistent storage.

## Install and select

Build/install in the same Python environment as Hermes, during CI/image build:

```sh
uv sync --frozen --extra dev
uv build
pip install dist/hermes_agent_sandbox_backend-0.2.0-py3-none-any.whl
hermes plugins enable agent_sandbox
```

```yaml
plugins:
  isolation: in_process
  enabled: [agent_sandbox]
terminal:
  backend: agent_sandbox
  cwd: /workspace
  container_persistent: true
```

Mount administrator-controlled policy at /etc/hermes-agent-sandbox/policy.json.
See [two-profile policy](examples/openshift/policy.json). No namespace, image,
ServiceAccount or management credential is accepted from tool arguments.

Build the [runner image](runner/README.md), then follow the
[OpenShift preparation](docs/openshift.md) and [real smoke test](docs/testing.md).
Directory discovery is also supported: install the wheel and place plugin.yaml plus
the root __init__.py under each profile's plugins/agent_sandbox directory. Prefer
wheel discovery in immutable images and avoid shadowing it with writable plugins.

See [compatibility](docs/compatibility.md), [configuration](docs/configuration.md),
[security](docs/security.md), [container integration](docs/container-integration.md),
and [local validation report](docs/implementation-status.md).
