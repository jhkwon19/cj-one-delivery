"""CJ O-NE 배송조회 통합구성요소."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CJOneDeliveryClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_PHONE_NUMBER,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import CJOneDeliveryCoordinator

type CJOneDeliveryConfigEntry = ConfigEntry[CJOneDeliveryCoordinator]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CJOneDeliveryConfigEntry,
) -> bool:
    """설정 항목에서 CJ O-NE 배송조회를 설정합니다."""
    session = async_get_clientsession(hass)
    client = CJOneDeliveryClient(
        session=session,
        phone_number=entry.data[CONF_PHONE_NUMBER],
        user_id=entry.data[CONF_USER_ID],
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
    )
    coordinator = CJOneDeliveryCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: CJOneDeliveryConfigEntry,
) -> bool:
    """설정 항목을 언로드합니다."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
