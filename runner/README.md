# Pinned official Python execution runtime

main.py is copied without semantic changes from kubernetes-sigs/agent-sandbox
v1.0.9, b1277676f8bf0e82ea299928997ecf5d696a92f1,
examples/python-runtime-sandbox/main.py. Its Apache copyright/license header is retained.
It implements the official /execute, /upload, /download and filesystem endpoints;
the plugin uses /execute for Hermes shell/file operations and /openapi.json for
compatibility. This is an upstream workload component packaged for a Red Hat
Operator-managed Sandbox, not a claim of Red Hat support for this custom image.

Build from the repository root:
    podman build -f runner/Containerfile --build-arg RUNNER_BASE=<approved-python311-base@sha256:digest> -t <your-registry/runner:0.2.0> .

Choose a UBI 9 minimal base with microdnf and approved RPM repositories, and test the supplied
command in your image pipeline. Publish and record your built image digest.
No ML packages are needed: only the API dependencies are installed; bash, coreutils,
Python and git form the initial CLI toolset. No packages install at runtime.

Use an SCC-assigned arbitrary UID, read-only root filesystem and writable workspace/
tmp mounts. The runtime HOME is workspace, not /root. On mounted PVCs, OpenShift
fsGroup/storage permissions must make the workspace writable. Probe both the final
image and mounted volume; a Containerfile alone does not prove SCC compatibility.

Server timeout is min(request.timeout_seconds, SANDBOX_EXEC_TIMEOUT_SECONDS).
Timeout sends SIGKILL to the spawned process group. Detached children that call
setsid can escape the group; native cancel is unavailable, and disconnect does not
cancel server work. The server buffers output in memory: pod memory limits bound
the workload, while the plugin separately bounds HTTP response reception.
Do not expose this unauthenticated API outside the protected pilot network.
