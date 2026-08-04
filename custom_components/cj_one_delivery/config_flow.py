"""CJ O-NE 배송조회 설정 플로우."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import CJOneDeliveryClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_CODE,
    CONF_PHONE_NUMBER,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DOMAIN,
)
from .exceptions import CannotConnect, InvalidAuth


class CJOneDeliveryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """CJ O-NE 배송조회 설정 플로우를 처리합니다."""

    VERSION = 1
    _phone_number: str

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
