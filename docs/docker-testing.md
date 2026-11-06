# Optional local Docker validation

After building the runner image with the approved base digest:

    HERMES_RUNNER_TEST_IMAGE=hermes-sandbox-runner:0.2.0 uv run --frozen pytest -m docker -q

The test starts only a uniquely named hermes-runner-test-* container, binds an ephemeral
loopback port, and removes its own container in finally. It uses UID 12345:0, a read-only
root filesystem, dropped capabilities, no-new-privileges, resource limits and tmpfs
workspace/tmp. It runs actual commands in the built image via the SDK and an HTTP
routing test double, including stdout/stderr, nonzero exits, deadlines, shell state
and Hermes file-tool read/write. No Kubernetes API or live cluster is used.

The double forwards HTTP requests unchanged; it is not a production broker and is not
part of the plugin runtime. Actual Red Hat router and NetworkPolicy verification still
uses docs/testing.md. CI runs this optional job when the repository RUNNER_BASE variable
is set to an approved UBI base digest.
