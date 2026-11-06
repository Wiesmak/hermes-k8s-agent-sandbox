from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import RLock
import pytest
from hermes_agent_sandbox.config import Profile, Policy
from hermes_agent_sandbox.identity import Identity
from hermes_agent_sandbox.lifecycle import Lifecycle, OWNER
from hermes_agent_sandbox.errors import (
    ConfigurationError,
    OwnershipMismatch,
    NotFound,
    Conflict,
    AuthorizationDenied,
    TransportUnavailable,
    ProvisioningTimeout,
)


class Claims:
    def __init__(self):
        self.objects = {}
        self.lock = RLock()
        self.creates = 0
        self.deletes = []
        self.ambiguous = False

    def get(self, ns, name):
        with self.lock:
            if (ns, name) not in self.objects:
                raise NotFound("missing")
            return self.objects[ns, name]

    def create(self, ns, body):
        import copy

        with self.lock:
            key = (ns, body["metadata"]["name"])
            if key in self.objects:
                raise Conflict("exists")
            obj = copy.deepcopy(body)
            obj["metadata"]["uid"] = "immutable-uid"
            obj["status"] = {
                "sandbox": {"name": "remote-sandbox"},
                "conditions": [{"type": "Ready", "status": "True"}],
            }
            self.objects[key] = obj
            self.creates += 1
            if self.ambiguous:
                raise TransportUnavailable("lost create reply")
            return obj

    def delete(self, ns, name, uid):
        assert self.objects[ns, name]["metadata"]["uid"] == uid
        self.deletes.append(name)
        del self.objects[ns, name]


@pytest.mark.parametrize(
    "setting",
    [
        {"namespace": "../other"},
        {"persistent": "false"},
        {"command_timeout": 601},
        {"cwd": "../../etc"},
        {"cwd": "/a/../b"},
        {"max_file_bytes": 99999999},
        {"retention": "delete"},
        {"runtime": "insecure"},
        {"warm_pool": "bad/name"},
    ],
)
def test_validation(setting):
    args = dict(profile_id="a", namespace="b", warm_pool="c")
    args.update(setting)
    with pytest.raises(ConfigurationError):
        Profile(**args)


def test_defaults():
    p = Profile("a", "b", "c")
    assert p.persistent and p.cwd == "/workspace"


def test_restart_concurrent_and_ambiguous_create(identity):
    api = Claims()
    api.ambiguous = True
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(lambda _: Lifecycle(api).acquire(identity), range(20)))
    assert len(set(leases)) == 1
    assert api.creates == 1
    assert Lifecycle(api).acquire(identity) == leases[0]


def test_ownership_and_replaced_uid(identity):
    api = Claims()
    manager = Lifecycle(api)
    lease = manager.acquire(identity)
    obj = api.get(identity.profile.namespace, lease.name)
    obj["metadata"]["annotations"][OWNER] = "attacker"
    with pytest.raises(OwnershipMismatch):
        manager.acquire(identity)
    assert not api.deletes


def test_persistent_delete_denied(identity):
    api = Claims()
    manager = Lifecycle(api)
    with pytest.raises(OwnershipMismatch):
        manager.delete_ephemeral(identity, manager.acquire(identity))
    assert not api.deletes


def test_ephemeral_delete_uid(identity):
    identity = replace(identity, profile=replace(identity.profile, persistent=False))
    api = Claims()
    manager = Lifecycle(api)
    lease = manager.acquire(identity)
    api.get(identity.profile.namespace, lease.name)["metadata"]["uid"] = "replacement"
    with pytest.raises(OwnershipMismatch):
        manager.delete_ephemeral(identity, lease)
    assert not api.deletes


def test_two_profiles_colliding_sessions(identity, monkeypatch, tmp_path):
    home2 = str((tmp_path / "second").resolve())
    policy = Policy(
        {identity.home: identity.profile, home2: Profile("beta", "pilot-beta", "approved-beta")}
    )
    first = Identity.resolve(policy, "same-task")
    monkeypatch.setattr("hermes_agent_sandbox.identity.active_home", lambda: home2)
    second = Identity.resolve(policy, "same-task")
    assert first.claim_name != second.claim_name
    assert first.owner != second.owner
    with pytest.raises(OwnershipMismatch):
        first.assert_current()
    with pytest.raises(OwnershipMismatch):
        Lifecycle(Claims()).acquire(first)


def test_unknown_home(identity, monkeypatch):
    monkeypatch.setattr("hermes_agent_sandbox.identity.active_home", lambda: "/unapproved")
    with pytest.raises(OwnershipMismatch):
        Identity.resolve(Policy({identity.home: identity.profile}), "same")


def test_provider_requires_profile_policy(monkeypatch):
    from hermes_agent_sandbox.provider import AgentSandboxProvider

    monkeypatch.setattr("hermes_agent_sandbox.provider.load_policy", lambda: Policy({}))
    provider = AgentSandboxProvider()
    assert not provider.is_available()
    assert provider.probe()[0] == "needs_setup"
    assert not provider.skip_container_guards
    assert not provider.supports_streams
    assert "KUBECONFIG" in provider.strip_env_keys
    with pytest.raises(OwnershipMismatch):
        provider.create_environment(cwd="/", timeout=1, future_kwarg=True)


@pytest.mark.parametrize(
    "status,error",
    [
        (403, AuthorizationDenied),
        (404, NotFound),
        (409, Conflict),
        (500, TransportUnavailable),
        (None, TransportUnavailable),
    ],
)
def test_kubernetes_errors_sanitized(status, error):
    from hermes_agent_sandbox.client import KubernetesClaims

    class API:
        def get_namespaced_custom_object(self, *args, **kwargs):
            exc = RuntimeError("secret-token")
            exc.status = status
            raise exc

    with pytest.raises(error) as caught:
        KubernetesClaims(API()).get("n", "claim")
    assert "secret-token" not in str(caught.value)


def test_partial_provisioning_timeout(identity, monkeypatch):
    api = Claims()
    lifecycle = Lifecycle(api)
    lease = lifecycle.acquire(identity)
    api.get(identity.profile.namespace, lease.name)["status"] = {}
    times = iter([0, 9999])
    monkeypatch.setattr("hermes_agent_sandbox.lifecycle.time.monotonic", lambda: next(times))
    with pytest.raises(ProvisioningTimeout):
        lifecycle.acquire(identity)
    assert api.creates == 1 and not api.deletes
