from __future__ import annotations

from datetime import datetime
import re
from typing import Any

# Honda sends the literal string "unknown" for fields a car doesn't report.
UNKNOWN_VALUE = "unknown"
# Home Assistant rejects states longer than this.
MAX_STATE_LENGTH = 255
DOOR_KEYS = ("firstRowDriver", "firstRowPassenger", "secondRowDriver", "secondRowPassenger")
MAINTENANCE_CODE_RE = re.compile(r"^[AB][1-7]*$")


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and value.strip().lower() in ("", UNKNOWN_VALUE)


def clean_value(value: Any) -> Any:
    return None if is_missing(value) else value


def get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return default
        if cur is None:
            return default
    return cur


def status_body(data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("responseBody")
    return body if isinstance(body, dict) else {}


def to_int(value: Any) -> int | None:
    try:
        if is_missing(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    try:
        if is_missing(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def first_path(data: dict[str, Any], paths: tuple[str, ...]) -> Any:
    for path in paths:
        value = get_path(data, path)
        if not is_missing(value):
            return value
    return None


def value_from_status_node(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in (
        "status",
        "state",
        "condition",
        "value",
        "text",
        "displayValue",
        "message",
        "messageText",
        "statusText",
        "displayText",
        "description",
    ):
        item = value.get(key)
        if not is_missing(item):
            return value_from_status_node(item)
    return None


def find_12v_battery_status(data: dict[str, Any]) -> Any:
    warning_lamp_status = _find_12v_warning_lamp_status(data)
    if not is_missing(warning_lamp_status):
        return warning_lamp_status

    direct = first_path(
        data,
        (
            "12VBatteryStatus",
            "12VBattery.status",
            "12VBattery.value",
            "twelveVoltBatteryStatus",
            "twelveVoltBattery.status",
            "twelveVoltBattery.value",
            "auxBatteryStatus",
            "auxBattery.status",
            "auxBattery.value",
            "auxiliaryBatteryStatus",
            "auxiliaryBattery.status",
            "auxiliaryBattery.value",
            "battery12VStatus",
            "battery12V.status",
            "battery12V.value",
            "batteryStatus12V",
            "batteryVoltageStatus",
            "batteryStatus.batteryVoltageStatus",
            "batteryStatus.batteryChargeStatus",
            "batteryStatus.status",
            "batteryStatus.value",
        ),
    )
    if not is_missing(direct):
        return value_from_status_node(direct)
    text_status = _find_12v_text_status(data)
    if not is_missing(text_status):
        return text_status
    return _find_12v_battery_status(data)


def find_12v_battery_candidates(data: dict[str, Any]) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    _collect_12v_battery_candidates(data, "", candidates)
    return candidates


def leaf_paths(data: dict[str, Any], *, limit: int = 300) -> list[str]:
    paths: list[str] = []
    _collect_leaf_paths(data, "", paths, limit)
    return paths


def _find_12v_warning_lamp_status(data: dict[str, Any]) -> Any:
    for message in group_messages(data, "warningLamps"):
        if isinstance(message, dict):
            text = " ".join(str(value) for value in message.values() if isinstance(value, str))
            text_lower = text.lower()
            has_12v = "12v" in text_lower or "12 v" in text_lower or "12 volt" in text_lower
            has_battery = "battery" in text_lower or "batt" in text_lower
            if has_12v and has_battery:
                return (
                    message.get("condition")
                    or message.get("status")
                    or message.get("state")
                    or message.get("value")
                    or message.get("message")
                    or message.get("messageText")
                    or message.get("text")
                    or "Detected"
                )
    return None


def _find_12v_text_status(value: Any) -> Any:
    if isinstance(value, dict):
        text = " ".join(str(item) for item in value.values() if isinstance(item, str))
        if _text_mentions_12v_battery(text):
            status = value_from_status_node(value)
            if not is_missing(status) and not _text_mentions_12v_battery(str(status)):
                return status
            for key in (
                "normal",
                "ok",
                "active",
                "on",
                "off",
                "severity",
                "alertState",
                "lampState",
                "indicator",
                "available",
            ):
                item = value.get(key)
                if not is_missing(item):
                    return item
            return "Detected"
        for item in value.values():
            status = _find_12v_text_status(item)
            if not is_missing(status):
                return status
    elif isinstance(value, list):
        for item in value:
            status = _find_12v_text_status(item)
            if not is_missing(status):
                return status
    elif isinstance(value, str) and _text_mentions_12v_battery(value):
        return value
    return None


def _find_12v_battery_status(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if _looks_like_12v_battery_key(str(key)):
                status = value_from_status_node(item)
                if not is_missing(status):
                    return status
            status = _find_12v_battery_status(item)
            if not is_missing(status):
                return status
    if isinstance(value, list):
        for item in value:
            status = _find_12v_battery_status(item)
            if not is_missing(status):
                return status
    return None


def _collect_12v_battery_candidates(value: Any, path: str, candidates: dict[str, Any]) -> None:
    if len(candidates) >= 20:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if _looks_like_12v_battery_key(str(key)) or (
                isinstance(item, str) and _text_mentions_12v_battery(item)
            ):
                candidate = value_from_status_node(item)
                candidates[item_path] = attribute_safe_value(candidate if candidate is not None else item)
            _collect_12v_battery_candidates(item, item_path, candidates)
    elif isinstance(value, list):
        for index, item in enumerate(value[:20]):
            _collect_12v_battery_candidates(item, f"{path}.{index}" if path else str(index), candidates)


def _collect_leaf_paths(value: Any, path: str, paths: list[str], limit: int) -> None:
    if len(paths) >= limit:
        return
    if isinstance(value, dict):
        if not value and path:
            paths.append(path)
            return
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            _collect_leaf_paths(item, item_path, paths, limit)
    elif isinstance(value, list):
        if not value and path:
            paths.append(path)
            return
        for index, item in enumerate(value[:20]):
            item_path = f"{path}.{index}" if path else str(index)
            _collect_leaf_paths(item, item_path, paths, limit)
    elif path:
        paths.append(path)


def _looks_like_12v_battery_key(key: str) -> bool:
    key_lower = key.lower()
    has_12v = "12v" in key_lower or "12_v" in key_lower or "twelvevolt" in key_lower or "twelve_volt" in key_lower
    has_battery = "battery" in key_lower or "batt" in key_lower
    has_voltage = "volt" in key_lower
    has_status = "status" in key_lower or "state" in key_lower or "condition" in key_lower
    has_aux = "aux" in key_lower or "auxiliary" in key_lower
    has_power_supply = "powersupply" in key_lower or "power_supply" in key_lower
    return (
        has_12v
        or (has_aux and (has_battery or has_voltage or has_status))
        or (has_battery and (has_status or has_voltage))
        or (has_voltage and has_status)
        or has_power_supply
    )


def _text_mentions_12v_battery(text: str) -> bool:
    text_lower = text.lower()
    has_12v = "12v" in text_lower or "12 v" in text_lower or "12 volt" in text_lower
    has_battery = "battery" in text_lower or "batt" in text_lower
    return has_12v and has_battery


def attribute_safe_value(value: Any) -> Any:
    if is_missing(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:10]:
            safe[str(key)] = attribute_safe_value(item)
        return safe
    if isinstance(value, list):
        return [attribute_safe_value(item) for item in value[:10]]
    return str(value)


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value or is_missing(value):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def dms_to_decimal(value: Any) -> float | None:
    if not value or is_missing(value):
        return None
    try:
        parts = str(value).split(",")
        if len(parts) != 3:
            return None
        degrees = float(parts[0])
        sign = -1 if degrees < 0 else 1
        minutes = float(parts[1])
        seconds = float(parts[2])
        return sign * (abs(degrees) + minutes / 60 + seconds / 3600)
    except (TypeError, ValueError):
        return None


def lock_state_locked(state: Any) -> bool | None:
    if is_missing(state):
        return None
    return str(state).strip().lower() in ("lock", "locked")


def door_unlocked(body: dict[str, Any], door_key: str) -> bool | None:
    locked = lock_state_locked(get_path(body, f"doorStatus.{door_key}.lockState"))
    return None if locked is None else not locked


def all_door_locks_locked(body: dict[str, Any]) -> bool | None:
    doors = get_path(body, "doorStatus", {})
    if not isinstance(doors, dict):
        return None
    states = [lock_state_locked(get_path(doors, f"{key}.lockState")) for key in DOOR_KEYS]
    states = [state for state in states if state is not None]
    if not states:
        return None
    return all(states)


def any_open_state(body: dict[str, Any], base: str, keys: list[str], state_key: str = "openState") -> bool | None:
    found = False
    for key in keys:
        value = get_path(body, f"{base}.{key}.{state_key}")
        if not is_missing(value):
            found = True
            if str(value).lower() != "closed":
                return True
    return False if found else None


def any_light_on(body: dict[str, Any]) -> bool | None:
    lights = get_path(body, "lightStatus", {})
    if not isinstance(lights, dict):
        return None
    found = False
    for item in lights.values():
        if isinstance(item, dict) and not is_missing(item.get("lightState")):
            found = True
            if str(item.get("lightState")).upper() != "OFF":
                return True
    return False if found else None


def engine_running_from_status(value: Any) -> bool | None:
    if is_missing(value):
        return None
    status = str(value).strip().upper()
    return status == "ON" or status.startswith("ENGINE START") or "IG RUN" in status


def remote_engine_status(body: dict[str, Any]) -> Any:
    return clean_value(get_path(body, "remoteEngineStart.vehicleStartEvent.resStatus"))


def remote_engine_running(body: dict[str, Any]) -> bool | None:
    return engine_running_from_status(get_path(body, "remoteEngineStart.vehicleStartEvent.resStatus"))


def remote_start_attributes(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "res_start_counter": clean_value(get_path(body, "remoteEngineStart.vehicleStartEvent.resStartCounter")),
        "res_time": clean_value(get_path(body, "remoteEngineStart.vehicleStartEvent.resTime")),
        "res_requester": clean_value(get_path(body, "remoteEngineStart.vehicleStartEvent.resRequester")),
        "delay_start_time": clean_value(get_path(body, "remoteEngineStart.delayStart.delayStartTime")),
    }


def cabin_temperature(body: dict[str, Any]) -> float | None:
    return to_float(get_path(body, "temperature.cabin.value"))


def cabin_temperature_unit(body: dict[str, Any]) -> str | None:
    """Return "c" or "f" for the cabin temperature unit, or None if not reported."""
    unit = get_path(body, "temperature.cabin.unit")
    if is_missing(unit):
        return None
    unit = str(unit).strip().lower().lstrip("°")
    if unit in ("c", "celsius"):
        return "c"
    if unit in ("f", "fahrenheit"):
        return "f"
    return None


def group_messages(body: dict[str, Any], base: str) -> list[Any]:
    """Collect messages from a `{base}.data[*].messages[*]` block.

    Shared by warning lamps and Maintenance Minder. Tolerates `data` or `messages`
    being a single object instead of a list, and drops "unknown" messages.
    """
    groups = get_path(body, f"{base}.data")
    if isinstance(groups, dict):
        groups = [groups]
    if not isinstance(groups, list):
        return []
    messages: list[Any] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        items = group.get("messages")
        if not isinstance(items, list):
            items = [items]
        messages.extend(item for item in items if not is_missing(item) and item != {})
    return messages


def warning_lamp_on(body: dict[str, Any]) -> bool:
    return bool(active_warning_lamps(body))


def active_warning_lamps(body: dict[str, Any]) -> list[Any]:
    return [
        attribute_safe_value(message)
        for message in group_messages(body, "warningLamps")
        if isinstance(message, dict) and str(message.get("condition", "")).upper() == "ON"
    ]


MAINTENANCE_CODE_KEYS = (
    "code",
    "maintenanceCode",
    "maintenanceMinderCode",
    "minderCode",
    "mmCode",
    "serviceCode",
    "mainCode",
)
MAINTENANCE_TEXT_KEYS = (
    "messageText",
    "message",
    "text",
    "displayText",
    "description",
    "title",
)


def maintenance_minder_messages(body: dict[str, Any]) -> list[Any]:
    messages: list[Any] = []
    for message in group_messages(body, "maintenanceMinder"):
        if isinstance(message, dict):
            if all(is_missing(value) or key == "languageCode" for key, value in message.items()):
                continue
        messages.append(message)
    return messages


def maintenance_minder_state(body: dict[str, Any]) -> str:
    """Active Maintenance Minder code(s) (e.g. "A1, B12"), message text, or "OK"."""
    messages = maintenance_minder_messages(body)
    if not messages:
        return "OK"
    codes: list[str] = []
    texts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            message = {"message": message}
        code = next((message[key] for key in MAINTENANCE_CODE_KEYS if not is_missing(message.get(key))), None)
        if code is not None:
            codes.append(str(code).strip())
            continue
        for key in MAINTENANCE_TEXT_KEYS:
            value = message.get(key)
            if is_missing(value) or not isinstance(value, (str, int, float)):
                continue
            value = str(value).strip()
            if MAINTENANCE_CODE_RE.match(value.upper()):
                codes.append(value.upper())
            else:
                texts.append(value)
            break
    found = codes or texts
    if not found:
        return "Due"
    return ", ".join(dict.fromkeys(found))[:MAX_STATE_LENGTH]


def gps_attributes(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "heading": to_float(get_path(body, "gpsData.courseHeading")),
        "gps_time": clean_value(get_path(body, "gpsData.dtTime")),
    }


def vehicle_image_url(vehicle: dict[str, Any] | None) -> str | None:
    """Honda's stock photo of the car (model, trim and color) from the vehicle record."""
    if not isinstance(vehicle, dict):
        return None
    for key in ("LargeFrontImage", "Asset34FrontPath"):
        url = vehicle.get(key)
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def enrollment_status(data: dict[str, Any]) -> str | None:
    """HondaLink enrollment status (e.g. "Active") from a VehicleEntitlement reply."""
    if str(data.get("status") or "").lower() != "success":
        return None
    return clean_value(get_path(status_body(data), "enrollmentStatus"))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def _recall_record(data: dict[str, Any]) -> dict[str, Any] | None:
    response = get_path(data, "response.recalls_response.Response")
    if not isinstance(response, dict) or str(response.get("error", "")).lower() == "true":
        return None
    recall = response.get("Recall")
    if not isinstance(recall, dict) or recall.get("warning"):
        # A warning (e.g. "Invalid VIN") means the lookup couldn't check this car.
        return None
    return recall


def recall_campaigns(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Campaigns from a GetRecalls.ashx reply, flattened and with readable keys.

    CampaignType and Campaign are each an object when there is one and a list when
    there are several.
    """
    recall = _recall_record(data)
    if recall is None:
        return []
    campaigns: list[dict[str, Any]] = []
    for campaign_type in _as_list(recall.get("CampaignType")):
        if not isinstance(campaign_type, dict):
            continue
        for campaign in _as_list(campaign_type.get("Campaign")):
            if not isinstance(campaign, dict):
                continue
            status = clean_value(campaign.get("CampaignDispositionStatusDesc"))
            mfr_status = clean_value(get_path(campaign, "MfrRecallStatus.value"))
            closed = str(status or "").lower() in ("closed", "complete", "completed") or (
                "complete" in str(mfr_status or "").lower() and "incomplete" not in str(mfr_status).lower()
            )
            campaigns.append(
                {
                    "recall_number": clean_value(campaign.get("RecallNumber")),
                    "campaign_id": clean_value(campaign.get("CampaignID")),
                    "description": clean_value(campaign.get("CampaignDescription")),
                    "type": clean_value(campaign.get("CampaignTypeDesc")),
                    "status": status,
                    "manufacturer_status": mfr_status,
                    "start_date": clean_value(campaign.get("CampaignStartDate")),
                    "safety_risk": clean_value(campaign.get("SafetyRiskDescription")),
                    "remedy": clean_value(campaign.get("RemedyDescription")),
                    "open": not closed,
                }
            )
    return campaigns


def open_recalls(data: dict[str, Any]) -> int | None:
    """Number of open recall campaigns, or None if the lookup gave no usable answer."""
    if _recall_record(data) is None:
        return None
    return sum(1 for campaign in recall_campaigns(data) if campaign["open"])
