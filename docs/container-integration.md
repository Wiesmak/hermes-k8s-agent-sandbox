# Immutable Hermes image and Tekton integration

The plugin is an independently versioned wheel. Install it during the existing Hermes
image build, using the exact interpreter Hermes invokes. Do not install/download on
startup or write into the Hermes source repository.

```sh
uv sync --frozen --extra dev
uv build
uv export --frozen --no-dev --no-emit-project --output-file requirements.lock.txt
```

Build a target-platform wheelhouse from that hashed export and add the release wheel
with its SHA-256 to the requirements. Use examples/Containerfile.hermes as the small
integration addition to your existing image build. It installs offline with
--no-index/--require-hashes and checks hermes_agent.plugins entry-point metadata.
Use the unchanged wheel basename hermes_agent_sandbox_backend-0.2.0-py3-none-any.whl.

Tekton should retrieve the immutable release wheel and lock by artifact digest, verify
hashes/signatures, prepare the target Linux wheelhouse, and pass these into the existing
image task. Keep existing base image/Hermes digest pins. Run tests and installed-wheel
registration checks before publishing; integrate SBOM/scanning into existing CI.
No pipeline replacement or plugin-specific controller is needed.

Build the execution runner separately with runner/Containerfile and a site-approved
UBI 9 minimal base digest. Runner dependencies are pinned with hashes in
runner/requirements.txt. Publish its actual digest for the SandboxTemplate. The image
packages the official upstream Python runtime, not a custom execution API.
The arbitrary-UID entrypoint uses nss_wrapper from the approved base repositories.

Persistent HERMES_HOME volumes hold profile state/config, not wheel code. Enable
agent_sandbox in each profile; use plugins.isolation: in_process. Avoid a writable
directory plugin shadowing the installed wheel. For native directory discovery,
install the wheel and place repository plugin.yaml plus root __init__.py under
$HERMES_HOME/plugins/agent_sandbox; use one discovery path per plugin.

Mount the administrator-owned policy separately at /etc/hermes-agent-sandbox/policy.json.
It must not be writable by profile commands. Gateway management credentials stay in
the gateway; the runner has no automatic ServiceAccount token mount.
Validate final-image provider discovery, arbitrary UID and the two-profile smoke in CI/pilot.
