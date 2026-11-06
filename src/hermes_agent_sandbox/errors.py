"""Public errors contain fixed messages, never response bodies or credentials."""


class BackendError(RuntimeError):
    pass


class ConfigurationError(BackendError):
    pass


class OwnershipMismatch(BackendError):
    pass


class NotFound(BackendError):
    pass


class Conflict(BackendError):
    pass


class AuthorizationDenied(BackendError):
    pass


class TransportUnavailable(BackendError):
    pass


class ProvisioningTimeout(BackendError):
    pass


class UnsupportedRuntime(BackendError):
    pass


class TransferLimit(BackendError):
    pass
