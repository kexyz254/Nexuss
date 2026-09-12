"""Provider-neutral AI provider registry and selection."""

from __future__ import annotations

from nexuss.ai.models import AIProviderProfile
from nexuss.cognitive.models import CognitiveMode


class AIProviderRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AIProviderRegistry:
    def __init__(
        self,
        profiles: tuple[AIProviderProfile, ...] = (),
    ) -> None:
        self._profiles: dict[str, AIProviderProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: AIProviderProfile) -> None:
        if profile.provider_id in self._profiles:
            raise AIProviderRegistryError(
                "AI_PROVIDER_DUPLICATE",
                f"Provider {profile.provider_id!r} is already registered.",
            )
        self._profiles[profile.provider_id] = profile

    def get(self, provider_id: str) -> AIProviderProfile | None:
        return self._profiles.get(provider_id.strip().casefold())

    def list_profiles(self) -> tuple[AIProviderProfile, ...]:
        return tuple(
            sorted(
                self._profiles.values(),
                key=lambda item: (item.priority, item.provider_id),
            )
        )

    def select(
        self,
        *,
        provider_id: str,
        mode: CognitiveMode,
    ) -> AIProviderProfile:
        normalized = provider_id.strip().casefold()

        if normalized == "auto":
            selected = next(
                (
                    profile
                    for profile in self.list_profiles()
                    if profile.enabled
                    and profile.supports_action_planning
                    and mode in profile.supported_modes
                ),
                None,
            )
            if selected is None:
                raise AIProviderRegistryError(
                    "AI_PROVIDER_AUTO_SELECTION_FAILED",
                    f"No enabled provider supports {mode.value!r}.",
                )
            return selected

        profile = self.get(normalized)
        if profile is None:
            raise AIProviderRegistryError(
                "AI_PROVIDER_UNKNOWN",
                f"Provider {normalized!r} is not registered.",
            )
        if not profile.enabled:
            raise AIProviderRegistryError(
                "AI_PROVIDER_DISABLED",
                f"Provider {profile.provider_id!r} is disabled.",
            )
        if not profile.supports_action_planning:
            raise AIProviderRegistryError(
                "AI_PROVIDER_ACTION_PLANNING_UNSUPPORTED",
                f"Provider {profile.provider_id!r} cannot plan actions.",
            )
        if mode not in profile.supported_modes:
            raise AIProviderRegistryError(
                "AI_PROVIDER_MODE_UNSUPPORTED",
                f"Provider {profile.provider_id!r} does not support {mode.value!r}.",
            )
        return profile


def default_provider_registry() -> AIProviderRegistry:
    modes = tuple(CognitiveMode)
    return AIProviderRegistry(
        (
            AIProviderProfile(
                provider_id="deepseek",
                display_name="DeepSeek",
                adapter_kind="openai_compatible",
                supported_modes=modes,
                supports_structured_output=True,
                supports_action_planning=True,
                supports_long_context=True,
                enabled=True,
                priority=10,
            ),
            AIProviderProfile(
                provider_id="openai",
                display_name="OpenAI",
                adapter_kind="openai",
                supported_modes=modes,
                supports_structured_output=True,
                supports_action_planning=True,
                supports_vision=True,
                supports_long_context=True,
                enabled=False,
                priority=20,
            ),
            AIProviderProfile(
                provider_id="anthropic",
                display_name="Anthropic",
                adapter_kind="anthropic",
                supported_modes=modes,
                supports_structured_output=True,
                supports_action_planning=True,
                supports_vision=True,
                supports_long_context=True,
                enabled=False,
                priority=30,
            ),
            AIProviderProfile(
                provider_id="local",
                display_name="Local Model",
                adapter_kind="local",
                supported_modes=modes,
                supports_structured_output=True,
                supports_action_planning=True,
                local_processing=True,
                enabled=False,
                priority=40,
            ),
            AIProviderProfile(
                provider_id="custom_openai_compatible",
                display_name="Custom OpenAI-Compatible Provider",
                adapter_kind="openai_compatible",
                supported_modes=modes,
                supports_structured_output=True,
                supports_action_planning=True,
                enabled=False,
                priority=50,
            ),
        )
    )
