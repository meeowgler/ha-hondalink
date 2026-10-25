from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_VEHICLE_INFO, CONF_VIN, DATA_COORDINATOR, DATA_FEATURES, DOMAIN
from .coordinator import HondaLinkDataUpdateCoordinator
from .util import entity_supported, status_body

_LOGGER = logging.getLogger(__name__)


def entity_wanted(hass: HomeAssistant, entry, key: str) -> bool:
    """Whether this car supports the entity (see util.ENTITY_REQUIREMENTS)."""
    data = hass.data[DOMAIN][entry.entry_id]
    body = status_body(data[DATA_COORDINATOR].data or {})
    if entity_supported(key, data[DATA_FEATURES], body):
        return True
    _LOGGER.debug("Not creating %s: this vehicle doesn't support it", key)
    return False


class HondaLinkEntity(CoordinatorEntity[HondaLinkDataUpdateCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HondaLinkDataUpdateCoordinator, entry, key: str) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.vin = entry.data[CONF_VIN]
        self._attr_unique_id = f"{self.vin}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        vehicle = self.entry.data.get(CONF_VEHICLE_INFO) or {}
        year = vehicle.get("ModelYear")
        model = vehicle.get("ModelGroupNameFriendly") or vehicle.get("ModelCode")
        trim = vehicle.get("ModelTrimTypeCode")
        model_name = " ".join(str(x) for x in (year, model, trim) if x)
        return DeviceInfo(
            identifiers={(DOMAIN, self.vin)},
            manufacturer=vehicle.get("DivisionName") or "Honda",
            model=model_name or None,
            name=vehicle.get("Alias Name") or model_name or f"Honda {self.vin[-6:]}",
            serial_number=self.vin,
            configuration_url="https://mygarage.honda.com/",
        )
