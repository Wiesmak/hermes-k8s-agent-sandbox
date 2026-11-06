"""Verified Kubernetes custom-object API; runtime deliberately separate."""

from typing import Any, Protocol
from .errors import (
    AuthorizationDenied,
    Conflict,
    NotFound,
    TransportUnavailable,
)

GROUP = "extensions.agents.x-k8s.io"
VERSION = "v1beta1"


class ClaimAPI(Protocol):
    def get(self, namespace: str, name: str) -> dict: ...
    def create(self, namespace: str, body: dict) -> dict: ...
    def delete(self, namespace: str, name: str, uid: str) -> None: ...


class Runtime(Protocol):
    """Hermes process adapter; disconnect only, no replay of execution requests."""

    def start(
        self,
        sandbox: str,
        script: str,
        *,
        login: bool,
        timeout: int,
        stdin_data: str | None,
        max_output_bytes: int,
    ) -> Any: ...
    def close(self) -> None: ...


class KubernetesClaims:
    def __init__(self, api: Any, api_client: Any = None):
        self.api, self.api_client = api, api_client

    @classmethod
    def in_cluster(cls):
        try:
            from kubernetes import client, config

            cfg = client.Configuration()
            config.load_incluster_config(client_configuration=cfg)
            api_client = client.ApiClient(cfg)
            return cls(client.CustomObjectsApi(api_client), api_client)
        except ImportError:
            raise TransportUnavailable(
                "install the pinned kubernetes dependency at image build"
            ) from None
        except Exception:
            raise TransportUnavailable("in-cluster Kubernetes identity is unavailable") from None

    def _call(self, method, *args, **kwargs):
        try:
            return method(GROUP, VERSION, *args, **kwargs, _request_timeout=(5, 10))
        except Exception as exc:
            status = getattr(exc, "status", None)
            error = {
                403: AuthorizationDenied,
                401: AuthorizationDenied,
                404: NotFound,
                409: Conflict,
            }.get(status if isinstance(status, int) else 0, TransportUnavailable)
            raise error(
                "sandbox claim API request failed; inspect RBAC and cluster health"
            ) from None

    def get(self, namespace, name):
        return self._call(self.api.get_namespaced_custom_object, namespace, "sandboxclaims", name)

    def create(self, namespace, body):
        return self._call(
            self.api.create_namespaced_custom_object, namespace, "sandboxclaims", body
        )

    def delete(self, namespace, name, uid):
        self._call(
            self.api.delete_namespaced_custom_object,
            namespace,
            "sandboxclaims",
            name,
            body={"preconditions": {"uid": uid}},
        )

    def close(self):
        if self.api_client is not None:
            self.api_client.close()
