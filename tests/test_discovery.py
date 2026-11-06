"""Use the real Hermes discovery and registration machinery."""

from pathlib import Path


def test_entrypoint_metadata():
    from hermes_cli.plugins_discovery import discover_entrypoint_manifests

    manifests = discover_entrypoint_manifests()
    plugin = next(m for m in manifests if m.name == "agent_sandbox")
    assert plugin.source == "entrypoint"
    assert plugin.path == "hermes_agent_sandbox"


def test_real_context_registration(tmp_path):
    from hermes_cli.plugins import PluginContext, PluginManager
    from hermes_cli.plugins_manifest import parse_manifest_file
    from agent.terminal_env_registry import get_provider
    from hermes_agent_sandbox import register

    root = Path(__file__).resolve().parents[1]
    manifest = parse_manifest_file(root / "plugin.yaml", root, "user", "")
    manager = PluginManager(scope_key=str(tmp_path))
    ctx = PluginContext(manifest, manager)
    register(ctx)
    provider = get_provider("agent_sandbox", scope=str(tmp_path))
    assert provider.name == "agent_sandbox"
    assert provider.skip_container_guards is False
