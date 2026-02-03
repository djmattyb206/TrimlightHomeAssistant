from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrimlightApi, TrimlightCredentials
from .const import CONF_DEVICE_ID, DOMAIN


class TrimlightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
