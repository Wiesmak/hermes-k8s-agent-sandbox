"""Operator-only policy. Never consume task overrides or profile-writable config."""

from dataclasses import dataclass, fields
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit
from .errors import ConfigurationError

_DNS = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")


@dataclass(frozen=True)
class Profile:
    profile_id: str
    namespace: str
    warm_pool: str
    cwd: str = "/workspace"
    persistent: bool = True
    provisioning_timeout: int = 120
    command_timeout: int = 120
    max_output_bytes: int = 2097152
    max_file_bytes: int = 524288
    retention: str = "retain"
    runtime: str = "redhat-1.13"
    router_url: str = "http://sandbox-router-svc.agent-sandbox-system.svc.cluster.local:8080"
    runtime_port: int = 8888

    def __post_init__(self):
        for key in ("profile_id", "namespace", "warm_pool"):
            if not isinstance(getattr(self, key), str) or not _DNS.fullmatch(getattr(self, key)):
                raise ConfigurationError(f"{key} must be a DNS label")
        if (
            not isinstance(self.cwd, str)
            or not self.cwd.startswith("/")
            or ".." in PurePosixPath(self.cwd).parts
            or "\x00" in self.cwd
        ):
            raise ConfigurationError("cwd must be an absolute remote path without traversal")
        if type(self.persistent) is not bool:
            raise ConfigurationError("persistent must be a boolean")
        for key in (
            "provisioning_timeout",
            "command_timeout",
            "max_output_bytes",
            "max_file_bytes",
        ):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= 16777216:
                raise ConfigurationError(f"{key} must be a bounded positive integer")
        if self.provisioning_timeout > 1800 or self.command_timeout > 600:
            raise ConfigurationError(
                "provisioning timeout <=1800 and command timeout <=600 required"
            )
        if self.retention != "retain" or self.runtime != "redhat-1.13":
            raise ConfigurationError(
                "only retain policy and redhat-1.13 mode are qualified for lifecycle"
            )
        try:
            url = urlsplit(self.router_url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in {"", "/"}
                or not url.port
            ):
                raise ValueError("router URL")
        except (ValueError, TypeError, AttributeError):
            raise ConfigurationError(
                "router_url must be an explicit http(s) origin with port"
            ) from None
        if type(self.runtime_port) is not int or not 1 <= self.runtime_port <= 65535:
            raise ConfigurationError("runtime_port must be between 1 and 65535")
        if self.command_timeout > 150:
            raise ConfigurationError(
                "router pilot command_timeout must be <=150 seconds (router proxy margin)"
            )
        if self.max_output_bytes < 2 * self.max_file_bytes + 4096:
            raise ConfigurationError(
                "output budget must accommodate base64 file payloads and markers"
            )


@dataclass(frozen=True)
class Policy:
    profiles: dict[str, Profile]

    @classmethod
    def load(cls, path: Path):
        try:
            if os.name == "posix":
                st = path.stat()
                if st.st_mode & 0o022 or st.st_uid != 0:
                    raise ConfigurationError(
                        "policy must be root-owned and not group/world writable"
                    )
            if path.stat().st_size > 65536:
                raise ConfigurationError("policy exceeds 64 KiB")
            raw = json.loads(path.read_text(encoding="utf-8"))
            if set(raw) != {"profiles"} or not isinstance(raw["profiles"], dict):
                raise ConfigurationError("policy requires only a profiles mapping")
            result = {}
            ids = set()
            for home, values in raw["profiles"].items():
                if not Path(home).is_absolute() or str(Path(home).resolve()) != home:
                    raise ConfigurationError("profile homes must be canonical absolute paths")
                if set(values) - {f.name for f in fields(Profile)}:
                    raise ConfigurationError("unknown profile setting")
                profile = Profile(**values)
                if profile.profile_id in ids:
                    raise ConfigurationError("profile_id must be unique")
                ids.add(profile.profile_id)
                result[home] = profile
            return cls(result)
        except ConfigurationError:
            raise
        except (OSError, ValueError, TypeError):
            raise ConfigurationError(
                "cannot load operator policy; check schema and mount"
            ) from None


def load_policy():
    return Policy.load(
        Path(os.environ.get("HERMES_AGENT_SANDBOX_POLICY", "/etc/hermes-agent-sandbox/policy.json"))
    )
