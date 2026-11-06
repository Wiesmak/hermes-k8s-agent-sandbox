# Configuration

Select terminal.backend: agent_sandbox and plugins.isolation: in_process in each profile.
Hermes v0.23.0 does not forward arbitrary custom terminal options to providers.
Policy is a separately mounted operator-owned JSON file, default
/etc/hermes-agent-sandbox/policy.json; the process may relocate it with
HERMES_AGENT_SANDBOX_POLICY. On Linux it must be root-owned and not group/world writable.
Its directory/mount must also be protected; never place it in agent-writable HERMES_HOME.

The profiles mapping keys are canonical absolute routed Hermes home paths.
See examples/openshift/policy.json for two distinct profile mappings and resources.

| Field | Default / requirement |
|---|---|
| profile_id | Required unique, stable DNS label |
| namespace | Required approved namespace |
| warm_pool | Required existing approved pool referencing an administrator-owned template |
| router_url | http://sandbox-router-svc.agent-sandbox-system.svc.cluster.local:8080 |
| runtime_port | 8888, execution runtime destination port through the router |
| cwd | /workspace, absolute remote path |
| persistent | true; false includes task digest in claim identity |
| provisioning_timeout | 120 seconds, maximum 1800 |
| command_timeout | 120 seconds, maximum 150 for the pilot router timeout margin |
| max_output_bytes | 2097152; UTF-8 output plus bounded JSON wire reception |
| max_file_bytes | 524288; payload stdin and fetch_file limit |
| retention | retain only |
| runtime | redhat-1.13, retained compatibility selector |

router_url must be an explicit http(s) origin with a port and no credentials, query or
path. Configure it to the official router Service, never a sandbox endpoint. No automatic
TLS downgrade, direct connection mode or fallback exists. Internal HTTP requires the
pilot's network protections; HTTPS uses the default verified trust store if supplied.

The runtime and router need sufficient deadline headroom. The documented router default
is 180 seconds; plugin commands are capped at 150, server limit is 150, HTTP read deadline
is command+10. Verify the actual Red Hat router timeout. A lower site timeout must be
matched by a lower command_timeout. Do not patch the router to enable basic functionality.

Resource limits, ServiceAccounts, images, runtime classes, workspace volumes and pool
retention are administrator-owned template/namespace policy. Tool arguments cannot
override them. No gateway environment values are forwarded in command requests.
Hermes' per-call timeout can shorten the profile limit. The profile policy sets the
initial remote cwd; execute(cwd=...) can select another remote directory.

Persistent mode keeps one claim per home+profile_id. Moving the home or changing the
ID requires an operator migration. Nonpersistent mode maps one claim per task digest,
but retains resources on cleanup under this release's explicit retain policy; operators
must reconcile unused claims. No automatic idle deletion is implemented.

A claim's existence does not guarantee durable data: choose PVC-backed storage for
Pod replacement. The initial emptyDir examples retain files across gateway restart only.
