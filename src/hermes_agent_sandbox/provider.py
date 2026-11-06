"""Hermes v0.23.0 provider; lightweight probes never contact Kubernetes or router."""

from importlib.util import find_spec
from typing import Any
from agent.terminal_env_provider import TerminalEnvironmentProvider
from .config import load_policy
from .errors import BackendError
from .identity import Identity


class AgentSandboxProvider(TerminalEnvironmentProvider):
    name = "agent_sandbox"
    display_name = "Red Hat Agent Sandbox"
    is_remote = True
    is_container = True
    session_isolated_when_nonpersistent = True
    supports_streams = False

    @property
    def skip_container_guards(self):
        return False

    @property
    def default_cwd(self):
        return "/workspace"

    @property
    def cache_path_base(self):
        return "/workspace/.hermes"

    @property
    def strip_env_keys(self):
        return frozenset(
            {
                "HERMES_AGENT_SANDBOX_POLICY",
                "KUBECONFIG",
                "KUBERNETES_SERVICE_HOST",
                "KUBERNETES_SERVICE_PORT",
            }
        )

    def is_available(self):
        try:
            if find_spec("k8s_agent_sandbox") is None:
                return False
            Identity.resolve(load_policy(), "probe")
            return True
        except (BackendError, ImportError):
            return False

    def probe(self):
        if self.is_available():
            return "ready", "Configured; cluster/router connectivity checked on first execution"
        return "needs_setup", "Install SDK and mount an operator policy for the active profile"

    def doctor_checks(self):
        ok = self.is_available()
        return [(ok, "agent_sandbox configuration", self.probe()[1])]

    def setup_instructions(self):
        return [
            "Mount policy at /etc/hermes-agent-sandbox/policy.json.",
            "Restrict access to the unauthenticated router with NetworkPolicies.",
        ]

    def create_environment(
        self,
        *,
        cwd: str,
        timeout: int,
        task_id: str = "default",
        image=None,
        container_config=None,
        **kwargs: Any,
    ):
        from .client import KubernetesClaims
        from .lifecycle import Lifecycle
        from .environment import SandboxEnvironment
        from .router import RouterRuntime

        identity = Identity.resolve(load_policy(), task_id)
        api = KubernetesClaims.in_cluster()
        runtime = None
        try:
            lease = Lifecycle(api).acquire(identity)
            runtime = RouterRuntime(identity.profile, lease)
            runtime.check_compatibility()
            env = SandboxEnvironment(identity, lease, runtime)
            env.init_session()
            return env
        except BaseException:
            if runtime is not None:
                runtime.close()
            raise
        finally:
            api.close()
