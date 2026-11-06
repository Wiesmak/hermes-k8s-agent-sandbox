# Implementation report — 0.2.0

The backend now implements actual shell execution through the official Agent Sandbox
router. The 0.1.0 blanket execution refusal is removed. The controller, router and
sandbox workloads are still operator-managed; no core patches, alternate transport,
broker or replacement controller were introduced.

## Implemented path and versions

Hermes native provider resolves the trusted routed profile home, validates operator
policy and acquires the deterministic SandboxClaim. The SDK connector receives only
the owned sandbox ID/namespace and the configured official router origin. SDK
CommandExecutor.run sends POST /execute with timeout_seconds through that router.
Hermes BaseEnvironment supplies bash, CWD/shell snapshot state and remote file tools.
The buffered process handle preserves actual output/status and surfaces infrastructure
errors separately. Cleanup closes local connections without deleting persistent claims.

- Plugin: 0.2.0; Python >=3.11,<3.15.
- Hermes: v0.23.0, df1774294af26285ae758c6114f3f2f60e2a602d.
- SDK: published k8s-agent-sandbox==1.0.9, locked with all transitive dependencies.
- Runtime: official examples/python-runtime-sandbox/main.py from SDK repository
  v1.0.9 / b1277676f8bf0e82ea299928997ecf5d696a92f1, packaged unchanged.
- Kubernetes Python: 34.1.0; build backend hatchling 1.27.0.
- Runner: FastAPI 0.121.0, Uvicorn 0.38.0, python-multipart 0.0.20; hashed requirements.
- Intended Red Hat platform: Agent Sandbox in OpenShift Sandboxed Containers 1.13,
  Technology Preview. This is not a Red Hat support or certification claim.

Router mode is SandboxDirectConnectionConfig with the internal router Service URL,
not SandboxInClusterConnectionConfig. The small connector extension bounds responses,
turns off all retries and inherited proxy/.netrc settings, and validates strict fields.
No Pod-IP callback or direct sandbox endpoint is used.

## Validation actually completed

- RHEL 10.1 WSL, Python 3.12.14: **62 passed, 2 skipped**. Skips are the opt-in live
  cluster and Docker tests. Real SDK→loopback routing double→official runtime→bash
  tests passed, including CWD, exported state, exact stdin, file reads/writes and
  process-group timeout behavior.
- Windows Python 3.14.3 with Docker enabled: **59 passed, 5 skipped**. The skips are
  native Linux/Git-Bash shell cases and the live-cluster case.
- Docker image built from verified pulled UBI 9 minimal base:
  registry.access.redhat.com/ubi9/ubi-minimal@sha256:4b79c93106c14ad1c234907f83441ff0e4f8d24e78426a36e159098e9f7e6fa5.
  Local tag hermes-sandbox-runner:0.2.0. No registry publication was performed.
- Docker test passed with UID 12345:0, read-only rootfs, all capabilities dropped,
  no-new-privileges and writable tmpfs workspace/tmp. It verified whoami, Python 3.11,
  separate stdout/stderr, nonzero exits, timeout, shell state and real Hermes files
  through the SDK and a routing-only HTTP test double. Test containers were removed.
- Ruff, formatting and mypy (including untyped function bodies) checked.
- Wheel and source archive built; dependency lock checked; built-wheel entry-point
  loading/registration validated in a separate environment.
- The IDE run-configuration tool timed out; suite execution used the IDE terminal.
  A reusable Offline tests run configuration is provided.
- One external Starlette/AnyIO deprecation warning was emitted; tests passed.

No live OpenShift router, Operator, SCC, Kata or NetworkPolicy enforcement test was run.
Local HTTP routing doubles do not prove the actual Red Hat router/CNI deployment.
The Docker constraints demonstrate image behavior, not SCC admission certification.

## Changed/added files for the correction

Functional source:
- src/hermes_agent_sandbox/client.py
- src/hermes_agent_sandbox/config.py
- src/hermes_agent_sandbox/environment.py
- src/hermes_agent_sandbox/errors.py
- src/hermes_agent_sandbox/provider.py
- src/hermes_agent_sandbox/router.py (new)
- src/hermes_agent_sandbox/smoke.py (new)

The existing registration, identity and lifecycle modules are retained; source/test
formatting also appears in the working diff. No Hermes or upstream SDK source is patched.

Packaging/CI:
- pyproject.toml, uv.lock, plugin.yaml, .gitignore, .dockerignore
- .github/workflows/ci.yml, .run/Offline tests.run.xml
- README.md, CHANGELOG.md

Runner (new):
- runner/Containerfile, runner/entrypoint.sh, runner/main.py
- runner/requirements.in, runner/requirements.txt, runner/README.md

Deployment:
- examples/openshift.yaml (redirects to the functional generated pilot)
- examples/openshift/render.py, examples/openshift/README.md
- examples/openshift/policy.json, examples/openshift/hermes-config.yaml

Tests:
- tests/test_core.py, tests/test_hermes.py (disabled-execution assertions replaced)
- tests/test_router.py, tests/test_routed_runtime.py
- tests/test_docker_runner.py, tests/test_manifests.py
- Existing discovery, boundary, process, claim and isolation tests retained.

Documentation:
- docs/architecture.md, docs/compatibility.md, docs/configuration.md
- docs/container-integration.md, docs/openshift.md, docs/security.md, docs/testing.md
- docs/decisions/0001-runtime-qualification.md, docs/implementation-status.md
- docs/docker-testing.md

IDE-managed .idea changes are not part of the backend implementation.

## Pilot procedure and remaining limitations

Build the wheel with uv build and install
dist/hermes_agent_sandbox_backend-0.2.0-py3-none-any.whl into Hermes' Python environment.
Build/publish the runner with runner/Containerfile using an approved UBI base digest.
Discover the actual gateway/router/Operator selectors, DNS target port and API endpoints;
render and review the namespaced resources with examples/openshift/render.py.
Mount the protected two-profile policy and select terminal.backend: agent_sandbox.

Run the executable two-profile smoke command in docs/testing.md from the configured
Hermes container. It verifies platform readiness, real routed commands/files, timeouts,
profile separation, cleanup retention and reconnect. Resources are retained and printed
with UIDs for approved operator cleanup. Verify denied connections separately.

The unauthenticated internal router is accepted for this controlled pilot. NetworkPolicy
is a network mitigation, not authentication; no public execution Route is recommended.
Shared gateway process trust, output buffering in the runner, lack of immediate remote
cancel/PTY/streaming/detached-process support, and required PVC configuration for Pod
replacement are explicit limitations. Cluster admission, router timeout configuration,
network isolation and actual Red Hat integration await operator validation.
