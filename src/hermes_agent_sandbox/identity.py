"""Identity is bound to trusted Hermes context, never to command arguments."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from .config import Policy, Profile
from .errors import OwnershipMismatch


def active_home() -> str:
    from hermes_constants import get_hermes_home

    return str(Path(get_hermes_home()).resolve())


@dataclass(frozen=True)
class Identity:
    home: str
    profile: Profile
    session_digest: str

    @classmethod
    def resolve(cls, policy: Policy, task_id: str):
        home = active_home()
        if home not in policy.profiles:
            raise OwnershipMismatch("active Hermes home has no operator-approved sandbox mapping")
        if not isinstance(task_id, str) or not task_id or len(task_id) > 4096:
            raise OwnershipMismatch("a bounded trusted task identifier is required")
        return cls(home, policy.profiles[home], sha256(task_id.encode()).hexdigest())

    @property
    def owner(self):
        return sha256((self.home + "\0" + self.profile.profile_id).encode()).hexdigest()

    @property
    def claim_name(self):
        scope = self.owner if self.profile.persistent else self.owner + self.session_digest
        return "hermes-" + sha256(scope.encode()).hexdigest()[:48]

    def assert_current(self):
        if active_home() != self.home:
            raise OwnershipMismatch("cached environment belongs to a different Hermes profile")
