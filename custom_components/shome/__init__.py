"""The sHome (Samsung SDS / Zigbang IHP) integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShomeApi
from .const import (
    CONF_BASE_URL,
    CONF_DEVICE_ID,
    CONF_LANGUAGE,
    CONF_PASSWORD,
    CONF_USER_ID,
    DEFAULT_BASE_URL,
    DEFAULT_LANGUAGE,
    DOMAIN,
)
from .coordinator import ShomeCoordinator

_LOGGER = logging.getLogger(__name__)

# Platforms are enabled incrementally as entity modules land.
PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.COVER,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.VALVE,
]

ShomeConfigEntry = ConfigEntry  # ConfigEntry[ShomeCoordinator] at runtime


async def async_setup_entry(hass: HomeAssistant, entry: ShomeConfigEntry) -> bool:
    """Set up sHome from a config entry."""
    session = async_get_clientsession(hass)
    api = ShomeApi(
        session,
        entry.data[CONF_USER_ID],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_DEVICE_ID],
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        language=entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
    )

    coordinator = ShomeCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ShomeConfigEntry) -> None:
    """Reload when options (e.g. scan interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ShomeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
