# ADR 0001: runtime and lifecycle separation

Status: superseded in part by the controlled-pilot correction in 0.2.0.

Keep native Hermes providers, SDK transport, trusted identity and operator claim
lifecycle separate. Do not add a broker or patch Hermes.

The original 0.1.0 release disabled execution pending authenticated runtime qualification.
The operator explicitly accepts Red Hat's unauthenticated internal router limitation
for a NetworkPolicy-restricted pilot. 0.2.0 therefore enables the official SDK HTTP
router path and packages its pinned Python execution runtime. Authentication and
Technology Preview status are documented limitations, not blanket execution gates.

Use the published SDK 1.0.9 DirectConnectionConfig and command executor. Its Python
runtime provides request deadlines and process-group kill on timeout. Immediate cancel,
PTY and streaming remain unsupported. Reuse existing ownership-checked lifecycle;
SDK high-level lifecycle/automatic cleanup is unnecessary. No alternative transport
or insecure-mode switch is introduced.
