import os
from pathlib import Path
import sys
import pytest

root = Path(__file__).resolve().parents[1]
source = Path(os.environ.get("HERMES_SOURCE", root / ".upstream/hermes-agent-0.23.0"))
if not (source / "agent/terminal_env_provider.py").is_file():
    raise RuntimeError("Set HERMES_SOURCE to an unmodified Hermes v0.23.0 checkout")
sys.path.insert(0, str(source))
sys.path.insert(0, str(root / "src"))


@pytest.fixture
def identity(monkeypatch, tmp_path):
    from hermes_agent_sandbox.config import Policy, Profile
    from hermes_agent_sandbox.identity import Identity

    home = str(tmp_path.resolve())
    monkeypatch.setattr("hermes_agent_sandbox.identity.active_home", lambda: home)
    return Identity.resolve(
        Policy({home: Profile("alpha", "pilot-alpha", "approved")}), "collision"
    )
