"""Config flow for sHome."""
from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShomeApi, ShomeAuthError, ShomeConnectionError
from .const import (
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    CONF_DEVICE_ID,
    CONF_LANGUAGE,
    CONF_PASSWORD,
    CONF_USER_ID,
    DEFAULT_BASE_URL,
    DEFAULT_LANGUAGE,
    DOMAIN,
)


class ShomeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for sHome."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "ShomeOptionsFlow":
        return ShomeOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_id = user_input[CONF_USER_ID].strip()
            password = user_input[CONF_PASSWORD]
            base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
            language = DEFAULT_LANGUAGE  # 한국 아파트 표준(KOR). 필요 시 옵션/재설정으로 확장 가능
            # stable per-install device id (android_id slot)
            device_id = uuid.uuid4().hex[:16]

            await self.async_set_unique_id(f"{user_id}")
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = ShomeApi(
                session, user_id, password, device_id,
                base_url=base_url, language=language,
            )
            try:
                vo = await api.login()
            except ShomeAuthError as err:
                errors["base"] = "invalid_auth"
                self._auth_message = str(err)
            except ShomeConnectionError:
                errors["base"] = "cannot_connect"
            else:
                title = vo.get("bizName") or vo.get("address") or user_id
                dong, ho = vo.get("dong"), vo.get("ho")
                if dong and ho:
                    title = f"{title} {dong}-{ho}"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_USER_ID: user_id,
                        CONF_PASSWORD: password,
                        CONF_BASE_URL: base_url,
                        CONF_DEVICE_ID: device_id,
                        CONF_LANGUAGE: language,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USER_ID): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"note": getattr(self, "_auth_message", "")},
        )


class ShomeOptionsFlow(OptionsFlow):
    """폴링 주기 등 옵션."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
