from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrimlightApi, TrimlightCredentials
from .const import (
    CONF_COMMIT_CUSTOM_PRESET,
    CONF_DEVICE_ID,
    DEFAULT_COMMIT_CUSTOM_PRESET,
    DOMAIN,
)


class TrimlightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return TrimlightOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            creds = TrimlightCredentials(
                client_id=user_input[CONF_CLIENT_ID],
                client_secret=user_input[CONF_CLIENT_SECRET],
                device_id=user_input[CONF_DEVICE_ID],
            )
            api = TrimlightApi(async_get_clientsession(self.hass), creds)

            try:
                await api.get_device_detail()
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                title = f"Trimlight {creds.device_id[-6:]}"
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_CLIENT_SECRET): str,
                vol.Required(CONF_DEVICE_ID): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class TrimlightOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_COMMIT_CUSTOM_PRESET,
                    default=options.get(
                        CONF_COMMIT_CUSTOM_PRESET, DEFAULT_COMMIT_CUSTOM_PRESET
                    ),
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
