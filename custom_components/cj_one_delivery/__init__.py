"""CJ O-NE 배송조회 통합구성요소."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthSession, CJOneDeliveryClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACTIVE_SLOT_COUNT,
    CONF_COMPLETED_SLOT_COUNT,
    CONF_PHONE_NUMBER,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DEFAULT_ACTIVE_SLOT_COUNT,
    DEFAULT_COMPLETED_SLOT_COUNT,
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

    async def async_update_tokens(auth_session: AuthSession) -> None:
        """갱신된 앱 인증 토큰을 설정 항목에 저장합니다."""
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_USER_ID: auth_session.user_id,
                CONF_ACCESS_TOKEN: auth_session.access_token,
                CONF_REFRESH_TOKEN: auth_session.refresh_token,
            },
        )

    client = CJOneDeliveryClient(
        session=session,
        phone_number=entry.data[CONF_PHONE_NUMBER],
        user_id=entry.data[CONF_USER_ID],
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        completed_recent_limit=entry.options.get(
            CONF_COMPLETED_SLOT_COUNT,
            DEFAULT_COMPLETED_SLOT_COUNT,
        ),
        token_update_callback=async_update_tokens,
    )
    coordinator = CJOneDeliveryCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    coordinator.loaded_active_slot_count = _active_slot_count(entry)
    coordinator.loaded_completed_slot_count = _completed_slot_count(entry)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: CJOneDeliveryConfigEntry,
) -> bool:
    """설정 항목을 언로드합니다."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant,
    entry: CJOneDeliveryConfigEntry,
) -> None:
    """옵션 변경사항을 적용합니다."""
    if (
        entry.runtime_data.loaded_active_slot_count != _active_slot_count(entry)
        or entry.runtime_data.loaded_completed_slot_count != _completed_slot_count(entry)
    ):
        from .sensor import remove_unconfigured_slot_entries

        remove_unconfigured_slot_entries(
            hass,
            entry,
            active_slot_count=_active_slot_count(entry),
            completed_slot_count=_completed_slot_count(entry),
        )
        await hass.config_entries.async_reload(entry.entry_id)
        return

    entry.runtime_data.apply_options()
    entry.runtime_data.client.set_completed_recent_limit(
        entry.options.get(CONF_COMPLETED_SLOT_COUNT, DEFAULT_COMPLETED_SLOT_COUNT)
    )
    await entry.runtime_data.async_request_refresh()


def _active_slot_count(entry: ConfigEntry) -> int:
    """옵션에 설정된 진행중 슬롯 개수를 반환합니다."""
    return int(entry.options.get(CONF_ACTIVE_SLOT_COUNT, DEFAULT_ACTIVE_SLOT_COUNT))


def _completed_slot_count(entry: ConfigEntry) -> int:
    """옵션에 설정된 완료 슬롯 개수를 반환합니다."""
    return int(entry.options.get(CONF_COMPLETED_SLOT_COUNT, DEFAULT_COMPLETED_SLOT_COUNT))
