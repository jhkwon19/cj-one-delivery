"""CJ O-NE 배송조회 설정 플로우."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import AuthSession, CJOneDeliveryClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_CODE,
    CONF_COMPLETED_RETENTION_DAYS,
    CONF_PHONE_NUMBER,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_USER_ID,
    DEFAULT_COMPLETED_RETENTION_DAYS,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_COMPLETED_RETENTION_DAYS,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_COMPLETED_RETENTION_DAYS,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .exceptions import CannotConnect, InvalidAuth


def _options_schema(options: dict[str, Any] | None = None) -> vol.Schema:
    """배송조회 옵션 입력 스키마를 반환합니다."""
    options = options or {}
    return vol.Schema(
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
                CONF_COMPLETED_RETENTION_DAYS,
                default=options.get(
                    CONF_COMPLETED_RETENTION_DAYS,
                    DEFAULT_COMPLETED_RETENTION_DAYS,
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_COMPLETED_RETENTION_DAYS,
                    max=MAX_COMPLETED_RETENTION_DAYS,
                ),
            ),
        }
    )


class CJOneDeliveryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """CJ O-NE 배송조회 설정 플로우를 처리합니다."""

    VERSION = 1
    _phone_number: str
    _auth_session: AuthSession

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
                self._auth_session = auth_session
                return await self.async_step_options()

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_CODE): str,
                }
            ),
            errors=errors,
        )

    async def async_step_options(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """최초 등록 시 배송조회 옵션 설정 단계를 처리합니다."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._phone_number,
                data={
                    CONF_PHONE_NUMBER: self._phone_number,
                    CONF_USER_ID: self._auth_session.user_id,
                    CONF_ACCESS_TOKEN: self._auth_session.access_token,
                    CONF_REFRESH_TOKEN: self._auth_session.refresh_token,
                },
                options=user_input,
            )

        return self.async_show_form(
            step_id="options",
            data_schema=_options_schema(),
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

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self._config_entry.options)),
        )
