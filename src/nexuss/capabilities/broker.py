"""Map AI-requested actions to the authoritative Nexuss registry."""

from __future__ import annotations

import json
from collections.abc import Iterable

from nexuss.ai.models import RequestedAction
from nexuss.capabilities.models import (
    CapabilityCatalogEntry,
    CapabilityMappingState,
    MappedRequestedAction,
)
from nexuss.core.registry import get_capability, list_capabilities
from nexuss.domain.models import ApprovalPolicy, CapabilityStatus

_SENSITIVE_ARGUMENT_KEYS = frozenset(
    {
        "api_key",
        "approval_token",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "private_key",
        "secret",
        "token",
    }
)


class CapabilityBrokerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CapabilityBroker:
    """Sanitize the registry and fail closed on requested actions."""

    def __init__(
        self,
        *,
        maximum_actions: int = 12,
        maximum_argument_bytes: int = 20_000,
    ) -> None:
        if maximum_actions < 1:
            raise ValueError("maximum_actions must be positive")
        self._maximum_actions = maximum_actions
        self._maximum_argument_bytes = maximum_argument_bytes

    def catalog(self) -> tuple[CapabilityCatalogEntry, ...]:
        entries: list[CapabilityCatalogEntry] = []

        for manifest in list_capabilities():
            provider_can_request = (
                manifest.status
                in {CapabilityStatus.ACTIVE, CapabilityStatus.SIMULATED}
                and manifest.approval_policy is not ApprovalPolicy.PROHIBITED
            )
            approval_channel = (
                manifest.approval_channel.value
                if manifest.approval_channel is not None
                else None
            )
            entries.append(
                CapabilityCatalogEntry(
                    capability_id=manifest.capability_id,
                    title=manifest.title,
                    risk_tier=manifest.risk_tier.value,
                    approval_policy=manifest.approval_policy.value,
                    approval_channel=approval_channel,
                    execution_mode=manifest.execution_mode,
                    status=manifest.status.value,
                    reversible=manifest.reversible,
                    provider_can_request=provider_can_request,
                    provider_can_execute=False,
                )
            )

        return tuple(sorted(entries, key=lambda item: item.capability_id))

    def provider_catalog_summary(self) -> str:
        compact = [
            {
                "capability_id": item.capability_id,
                "title": item.title,
                "risk_tier": item.risk_tier,
                "approval_policy": item.approval_policy,
                "approval_channel": item.approval_channel,
                "execution_mode": item.execution_mode,
                "status": item.status,
                "provider_can_request": item.provider_can_request,
                "provider_can_execute": False,
            }
            for item in self.catalog()
        ]
        return json.dumps(
            compact,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def map_actions(
        self,
        actions: Iterable[RequestedAction],
    ) -> tuple[MappedRequestedAction, ...]:
        normalized = tuple(actions)
        self._validate_actions(normalized)
        return tuple(self._map_action(action) for action in normalized)

    def _validate_actions(
        self,
        actions: tuple[RequestedAction, ...],
    ) -> None:
        if len(actions) > self._maximum_actions:
            raise CapabilityBrokerError(
                "AI_ACTION_LIMIT_EXCEEDED",
                (
                    f"The provider requested {len(actions)} actions; "
                    f"the maximum is {self._maximum_actions}."
                ),
            )

        keys = [action.action_key for action in actions]
        if len(keys) != len(set(keys)):
            raise CapabilityBrokerError(
                "AI_ACTION_KEY_DUPLICATE",
                "Requested action keys must be unique.",
            )

        key_set = set(keys)
        for action in actions:
            serialized = json.dumps(
                action.arguments,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            ).encode("utf-8")
            if len(serialized) > self._maximum_argument_bytes:
                raise CapabilityBrokerError(
                    "AI_ACTION_ARGUMENTS_TOO_LARGE",
                    f"Arguments for {action.action_key!r} are too large.",
                )

            self._reject_sensitive_keys(
                action.arguments,
                path=f"actions.{action.action_key}.arguments",
            )

            for dependency in action.depends_on:
                if dependency not in key_set:
                    raise CapabilityBrokerError(
                        "AI_ACTION_DEPENDENCY_UNKNOWN",
                        (
                            f"Action {action.action_key!r} depends on "
                            f"unknown action {dependency!r}."
                        ),
                    )
                if dependency == action.action_key:
                    raise CapabilityBrokerError(
                        "AI_ACTION_DEPENDENCY_SELF_REFERENCE",
                        f"Action {action.action_key!r} depends on itself.",
                    )

        graph = {
            action.action_key: tuple(action.depends_on)
            for action in actions
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visited:
                return
            if key in visiting:
                raise CapabilityBrokerError(
                    "AI_ACTION_DEPENDENCY_CYCLE",
                    "Requested actions contain a dependency cycle.",
                )
            visiting.add(key)
            for dependency in graph[key]:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in graph:
            visit(key)

    def _reject_sensitive_keys(
        self,
        value: object,
        *,
        path: str,
    ) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).strip().casefold()
                if normalized in _SENSITIVE_ARGUMENT_KEYS:
                    raise CapabilityBrokerError(
                        "AI_ACTION_SENSITIVE_ARGUMENT_DENIED",
                        (
                            f"Sensitive argument key {key!r} is not "
                            f"allowed at {path}."
                        ),
                    )
                self._reject_sensitive_keys(
                    nested,
                    path=f"{path}.{key}",
                )
        elif isinstance(value, (list, tuple)):
            for index, nested in enumerate(value):
                self._reject_sensitive_keys(
                    nested,
                    path=f"{path}[{index}]",
                )

    @staticmethod
    def _map_action(
        action: RequestedAction,
    ) -> MappedRequestedAction:
        manifest = get_capability(action.capability_id)

        if manifest is None:
            return MappedRequestedAction(
                action=action,
                mapping_state=CapabilityMappingState.UNKNOWN,
                reason_code="CAPABILITY_NOT_REGISTERED",
                explanation=(
                    "The requested capability is not registered and "
                    "cannot execute."
                ),
            )

        approval_channel = (
            manifest.approval_channel.value
            if manifest.approval_channel is not None
            else None
        )
        common = {
            "action": action,
            "risk_tier": manifest.risk_tier.value,
            "approval_policy": manifest.approval_policy.value,
            "approval_channel": approval_channel,
            "execution_mode": manifest.execution_mode,
            "capability_status": manifest.status.value,
            "reversible": manifest.reversible,
            "execution_authorized": False,
        }

        if (
            manifest.status is CapabilityStatus.PROHIBITED
            or manifest.approval_policy is ApprovalPolicy.PROHIBITED
        ):
            return MappedRequestedAction(
                **common,
                mapping_state=CapabilityMappingState.PROHIBITED,
                reason_code="CAPABILITY_PROHIBITED",
                explanation="The Nexuss registry prohibits this capability.",
            )

        if manifest.status is CapabilityStatus.SIMULATED:
            return MappedRequestedAction(
                **common,
                mapping_state=CapabilityMappingState.SIMULATED,
                reason_code="CAPABILITY_SIMULATED",
                explanation="The capability exists only as a simulation.",
            )

        return MappedRequestedAction(
            **common,
            mapping_state=CapabilityMappingState.VERIFIED_EXISTING,
            reason_code="CAPABILITY_REGISTERED",
            explanation=(
                "The capability is registered. Execution remains "
                "unauthorized in this planning gate."
            ),
        )
