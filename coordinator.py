from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HondaLinkAPI, HondaLinkCommandError, HondaLinkError
from .const import CONF_SCAN_INTERVAL, CONF_VIN, DEFAULT_SCAN_INTERVAL, DOMAIN, ENROLLMENT_CHECK_INTERVAL
from .util import enrollment_status

_LOGGER = logging.getLogger(__name__)


class HondaLinkDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: HondaLinkAPI) -> None:
        self.api = api
        self.vin = entry.data[CONF_VIN]
        self.enrollment_status: str | None = None
        self._enrollment_checked_at: float | None = None
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name=f"{DOMAIN}-{self.vin}",
            update_interval=timedelta(minutes=interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.async_get_dashboard_latest(self.vin)
        except HondaLinkError as err:
            raise UpdateFailed(str(err)) from err
        await self._async_check_enrollment()
        return data

    async def _async_check_enrollment(self) -> None:
        # Slow-changing, so checked every few hours rather than on every poll. A failure
        # keeps the last known status and never fails the dashboard update.
        now = time.monotonic()
        if (
            self._enrollment_checked_at is not None
            and now - self._enrollment_checked_at < ENROLLMENT_CHECK_INTERVAL.total_seconds()
        ):
            return
        self._enrollment_checked_at = now
        try:
            # Keep only the status: the rest of the reply is the owner's personal details.
            self.enrollment_status = enrollment_status(await self.api.async_get_vehicle_entitlement(self.vin))
        except (HondaLinkError, aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("HondaLink enrollment check failed: %s", err)

    async def async_force_refresh(self) -> None:
        try:
            await self.api.async_request_dashboard_update(self.vin)
        except HondaLinkCommandError as err:
            _LOGGER.warning("HondaLink live dashboard refresh request failed: %s", err)
        except HondaLinkError as err:
            _LOGGER.warning("HondaLink live dashboard refresh request failed: %s", err)
        await self.async_refresh()

    async def async_start_engine(self) -> None:
        await self._run_command(self.api.async_start_engine)

    async def async_stop_engine(self) -> None:
        await self._run_command(self.api.async_stop_engine)

    async def async_lock(self) -> None:
        await self._run_command(self.api.async_lock)

    async def async_unlock(self) -> None:
        await self._run_command(self.api.async_unlock)

    async def async_horn(self) -> None:
        await self._run_command(self.api.async_horn)

    async def async_lights(self) -> None:
        await self._run_command(self.api.async_lights)

    async def async_stop_horn_lights(self) -> None:
        await self._run_command(self.api.async_stop_horn_lights)

    async def _run_command(self, command) -> None:
        try:
            await command()
        except HondaLinkCommandError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
