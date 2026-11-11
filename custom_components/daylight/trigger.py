"""Triggers for lights entering and leaving manual control."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, override

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.helpers.trigger import (
    ENTITY_STATE_TRIGGER_SCHEMA,
    Trigger,
    TriggerActionRunner,
    TriggerConfig,
    TriggerNotTriggeredReporter,
)
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_CONFIG_ENTRY_ID, SIGNAL_MANUAL_CONTROL
from .hub import DATA_HUB

if TYPE_CHECKING:
    from .profile import Profile


def resolve_lights(hass: HomeAssistant, target: dict[str, Any]) -> set[str]:
    """Lights a trigger or condition target refers to, groups expanded."""
    selected = async_extract_referenced_entity_ids(
        hass, TargetSelection(target), expand_group=False
    )
    lights = {
        e
        for e in selected.referenced | selected.indirectly_referenced
        if e.startswith("light.")
    }
    if (hub := hass.data.get(DATA_HUB)) is None:
        return lights
    return hub.expand(lights)[0]


class ManualControlTrigger(Trigger):
    """Fires when a light in the target starts or stops being manual."""

    _manual: bool

    @override
    @classmethod
    async def async_validate_config(
        cls, hass: HomeAssistant, config: ConfigType
    ) -> ConfigType:
        """Validate config."""
        return cast(ConfigType, ENTITY_STATE_TRIGGER_SCHEMA(config))

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        """Initialise."""
        super().__init__(hass, config)
        assert config.target is not None
        self._target = config.target

    @override
    async def async_attach_runner(
        self,
        run_action: TriggerActionRunner,
        did_not_trigger: TriggerNotTriggeredReporter | None = None,
    ) -> CALLBACK_TYPE:
        """Listen for manual-control changes."""

        @callback
        def changed(entity_id: str, manual: bool, reason: str, profile: Profile) -> None:
            if manual != self._manual:
                return
            # Resolved at fire time so lights added to the target later count.
            if entity_id not in resolve_lights(self._hass, self._target):
                return
            run_action(
                {
                    ATTR_ENTITY_ID: entity_id,
                    ATTR_CONFIG_ENTRY_ID: profile.entry.entry_id,
                    "profile": profile.title,
                    "reason": reason,
                },
                f"manual control {'started' if manual else 'ended'} on {entity_id}",
            )

        return async_dispatcher_connect(self._hass, SIGNAL_MANUAL_CONTROL, changed)


class ManualControlStartedTrigger(ManualControlTrigger):
    """A light went under manual control."""

    _manual = True


class ManualControlEndedTrigger(ManualControlTrigger):
    """A light left manual control."""

    _manual = False


TRIGGERS: dict[str, type[Trigger]] = {
    "manual_control_started": ManualControlStartedTrigger,
    "manual_control_ended": ManualControlEndedTrigger,
}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return the triggers for Daylight."""
    return TRIGGERS
