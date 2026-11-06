"""Native Hermes plugin; importing this module performs no network operations."""


def register(ctx):
    from .provider import AgentSandboxProvider

    ctx.register_terminal_environment_provider(AgentSandboxProvider())
