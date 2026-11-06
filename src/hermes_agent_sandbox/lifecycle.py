"""Durable deterministic claim mapping; Kubernetes arbitrates concurrent creation."""

from dataclasses import dataclass
import logging
import time
from .client import ClaimAPI, GROUP, VERSION
from .identity import Identity
from .errors import Conflict, NotFound, OwnershipMismatch, ProvisioningTimeout, TransportUnavailable

log = logging.getLogger(__name__)
OWNER = "hermes-agent-sandbox.io/owner"
SESSION = "hermes-agent-sandbox.io/session"


@dataclass(frozen=True)
class Lease:
    name: str
    uid: str
    sandbox: str


class Lifecycle:
    def __init__(self, api: ClaimAPI):
        self.api = api

    def _verify(self, identity, obj, uid=None):
        meta = obj.get("metadata", {})
        annotations = meta.get("annotations", {})
        expected = identity.session_digest if not identity.profile.persistent else "profile"
        if (
            meta.get("name") != identity.claim_name
            or meta.get("namespace") != identity.profile.namespace
            or annotations.get(OWNER) != identity.owner
            or annotations.get(SESSION) != expected
            or obj.get("spec", {}).get("warmPoolRef", {}).get("name") != identity.profile.warm_pool
            or not meta.get("uid")
            or (uid and uid != meta["uid"])
            or meta.get("deletionTimestamp")
        ):
            log.warning("ownership_mismatch", extra={"claim": identity.claim_name})
            raise OwnershipMismatch("claim ownership, UID, template policy or lifecycle mismatch")
        return meta["uid"]

    def acquire(self, identity: Identity) -> Lease:
        identity.assert_current()
        profile = identity.profile
        deadline = time.monotonic() + profile.provisioning_timeout
        name, namespace = identity.claim_name, profile.namespace
        try:
            obj = self.api.get(namespace, name)
        except NotFound:
            body = {
                "apiVersion": f"{GROUP}/{VERSION}",
                "kind": "SandboxClaim",
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "annotations": {
                        OWNER: identity.owner,
                        SESSION: identity.session_digest if not profile.persistent else "profile",
                    },
                },
                "spec": {"warmPoolRef": {"name": profile.warm_pool}},
            }
            try:
                obj = self.api.create(namespace, body)
                log.info("claim_created", extra={"claim": name, "profile": identity.owner[:12]})
            except (Conflict, TransportUnavailable):
                # Create may have committed despite a lost reply. Reconcile by exact name,
                # never allocate a second claim. A second failure is surfaced.
                obj = self.api.get(namespace, name)
        uid = self._verify(identity, obj)
        while True:
            self._verify(identity, obj, uid)
            status = obj.get("status", {})
            sandbox = status.get("sandbox", {}).get("name")
            ready = any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in status.get("conditions", [])
            )
            if sandbox and ready:
                log.info("claim_attached", extra={"claim": name, "profile": identity.owner[:12]})
                return Lease(name, uid, sandbox)
            if time.monotonic() >= deadline:
                raise ProvisioningTimeout(
                    "claim did not become Ready before provisioning deadline; retained for reconciliation"
                )
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
            obj = self.api.get(namespace, name)

    def delete_ephemeral(self, identity: Identity, lease: Lease):
        identity.assert_current()
        if identity.profile.persistent:
            raise OwnershipMismatch("persistent claim deletion is an operator-only operation")
        obj = self.api.get(identity.profile.namespace, lease.name)
        self._verify(identity, obj, lease.uid)
        self.api.delete(identity.profile.namespace, lease.name, lease.uid)
