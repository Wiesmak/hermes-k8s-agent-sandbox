# Changelog

## 0.2.1 — 2026-11-06

- Use Kubernetes client 35.0.0 so the plugin can share the released Hermes v0.23.0 Python 3.14 environment and its urllib3 2.8.0 lock.
- Test against the final Hermes release commit and include the hashed runner requirements used by its Containerfile.

## 0.2.0 — 2026-11-06

- Implement official SDK 1.0.9 HTTP router command execution and buffered Hermes process handles.
- Strict responses, bounded reception, no replay, payload stdin, server deadlines and remote file tools.
- Enable provider after local configuration checks; retain scoped claims and safe cleanup.
- Package pinned upstream Python runtime, hashed dependencies and arbitrary-UID runner example.
- Add generated OpenShift policies using actual discovered selectors and an executable two-profile smoke test.

## 0.1.0 — 2026-11-06

Initial provider, protected policy, identity, claim lifecycle and adapter tests.
Execution was disabled; this limitation is removed in 0.2.0.
