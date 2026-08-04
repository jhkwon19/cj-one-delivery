"""CJ O-NE 배송조회 설정 플로우."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import CJOneDeliveryClient
from .const import (
    ACTIVE_SLOT_LIMIT,
    CONF_ACCESS_TOKEN,
    CONF_ACTIVE_SLOT_COUNT,
    CONF_AUTH_CODE,
    CONF_COMPLETED_SLOT_COUNT,
    CONF_PHONE_NUMBER,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_USER_ID,
    COMPLETED_RECENT_LIMIT,
    DEFAULT_ACTIVE_SLOT_COUNT,
    DEFAULT_COMPLETED_SLOT_COUNT,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .exceptions import CannotConnect, InvalidAuth


class CJOneDeliveryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """CJ O-NE 배송조회 설정 플로우를 처리합니다."""

    VERSION = 1
    _phone_number: str

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CJOneDeliveryOptionsFlow:
        """옵션 플로우를 반환합니다."""
        return CJOneDeliveryOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """초기 설정 단계를 처리합니다."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._phone_number = user_input[CONF_PHONE_NUMBER]
            session = async_create_clientsession(self.hass)
            client = CJOneDeliveryClient(
                session=session,
                phone_number=self._phone_number,
            )

            try:
                await client.async_send_verification_code()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_code()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PHONE_NUMBER): str,
                }
            ),
            errors=errors,
        )

    async def async_step_code(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """인증번호 입력 단계를 처리합니다."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_create_clientsession(self.hass)
            client = CJOneDeliveryClient(
                session=session,
                phone_number=self._phone_number,
            )

            try:
                auth_session = await client.async_verify_code(user_input[CONF_AUTH_CODE])
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(self._phone_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self._phone_number,
                    data={
                        CONF_PHONE_NUMBER: self._phone_number,
                        CONF_USER_ID: auth_session.user_id,
                        CONF_ACCESS_TOKEN: auth_session.access_token,
                        CONF_REFRESH_TOKEN: auth_session.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_CODE): str,
                }
            ),
            errors=errors,
        )


class CJOneDeliveryOptionsFlow(config_entries.OptionsFlow):
    """CJ O-NE 배송조회 옵션 플로우."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """옵션 플로우를 초기화합니다."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """옵션 설정 단계를 처리합니다."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_MINUTES,
                        default=options.get(
                            CONF_SCAN_INTERVAL_MINUTES,
                            DEFAULT_SCAN_INTERVAL_MINUTES,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=MAX_SCAN_INTERVAL_MINUTES,
                        ),
                    ),
                    vol.Required(
                        CONF_ACTIVE_SLOT_COUNT,
                        default=options.get(
                            CONF_ACTIVE_SLOT_COUNT,
                            DEFAULT_ACTIVE_SLOT_COUNT,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=1, max=ACTIVE_SLOT_LIMIT),
                    ),
                    vol.Required(
                        CONF_COMPLETED_SLOT_COUNT,
                        default=options.get(
                            CONF_COMPLETED_SLOT_COUNT,
                            DEFAULT_COMPLETED_SLOT_COUNT,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=1, max=COMPLETED_RECENT_LIMIT),
                    ),
                }
            ),
        )
