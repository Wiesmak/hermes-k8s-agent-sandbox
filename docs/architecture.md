# Architecture

Hermes → native provider → trusted profile home/policy → deterministic SandboxClaim →
official SDK HTTP connector → official sandbox router → pinned Python runtime → bash.

No direct Pod/Service execution, Kubernetes exec, SSH, local fallback or broker exists.
Kubernetes is used only by lifecycle and the opt-in smoke preflight.

provider.py registers metadata and creates environments. config.py validates protected
policy. identity.py resolves context-scoped home, not model arguments. lifecycle.py
reconciles deterministic claims with ownership/UID/pool checks. client.py wraps custom
resource calls. router.py uses SDK DirectConnectionConfig and CommandExecutor with a
small bounded connector and buffered process handle. environment.py retains Hermes'
real snapshot, CWD and file-tool behavior.

Kubernetes create conflicts and lost create replies reconcile by exact name. No second
claim is allocated. Ready claims are reused after gateway restart. Pending claims remain
inspectable after bounded provisioning timeout. Environment cleanup closes HTTP sessions
and local waits but does not delete claims; persistent deletion is operator-owned.

Each environment serializes commands to protect its snapshot. Sessions in one profile
share workspace trust but have independent shell snapshots. No cross-process filesystem
locking is imposed. Concurrent workspace edits require application coordination.

SDK exceptions are stored on the process handle and surfaced after Hermes' waiter,
rather than turning infrastructure failure into a command exit code. Output is bounded
on the wire and after JSON decode, with errors instead of file-data truncation.
Execution is never automatically replayed after an ambiguous response.

There is no remote streaming in this HTTP runtime. Its worker thread executes a bounded
request; the stdout reader waits for completion. kill() stops the Hermes wait and the
server-side deadline remains in force. close() never calls SDK terminate/delete APIs.

Ownership annotations are consistency checks, not credentials. Namespace writers and
the gateway process remain trusted. Running mutually hostile profiles in a single
gateway is outside this pilot's security model. NetworkPolicy restrictions apply to
workloads, not to per-request sandbox identity.
