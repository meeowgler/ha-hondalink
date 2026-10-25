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
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_VIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENROLLMENT_CHECK_INTERVAL,
    RECALL_CHECK_INTERVAL,
)
from .util import enrollment_status, open_recalls, recall_campaigns

# Errors from the slow side checks (enrollment, recalls). They are logged and the last
# known value is kept; they never fail the dashboard update.
_SIDE_CHECK_ERRORS = (HondaLinkError, aiohttp.ClientError, TimeoutError)

_LOGGER = logging.getLogger(__name__)


class HondaLinkDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: HondaLinkAPI) -> None:
        self.api = api
        self.vin = entry.data[CONF_VIN]
        self.enrollment_status: str | None = None
        self.open_recalls: int | None = None
        self.recalls: list[dict[str, Any]] = []
        self._checked_at: dict[str, float] = {}
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
        await self._async_check_recalls()
        return data

    def _due(self, check: str, interval: timedelta) -> bool:
        # Slow-changing data is checked every few hours rather than on every poll.
        now = time.monotonic()
        last = self._checked_at.get(check)
        if last is not None and now - last < interval.total_seconds():
            return False
        self._checked_at[check] = now
        return True

    async def _async_check_enrollment(self) -> None:
        if not self._due("enrollment", ENROLLMENT_CHECK_INTERVAL):
            return
        try:
            # Keep only the status: the rest of the reply is the owner's personal details.
            self.enrollment_status = enrollment_status(await self.api.async_get_vehicle_entitlement(self.vin))
        except _SIDE_CHECK_ERRORS as err:
            _LOGGER.debug("HondaLink enrollment check failed: %s", err)

    async def _async_check_recalls(self) -> None:
        if not self._due("recalls", RECALL_CHECK_INTERVAL):
            return
        try:
            data = await self.api.async_get_recalls(self.vin)
        except _SIDE_CHECK_ERRORS as err:
            _LOGGER.debug("Honda recall lookup failed: %s", err)
            return
        count = open_recalls(data)
        if count is None:
            _LOGGER.debug("Honda recall lookup gave no usable answer")
            return
        self.open_recalls = count
        self.recalls = recall_campaigns(data)

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
