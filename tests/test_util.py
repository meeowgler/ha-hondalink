from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import util

FIXTURES = Path(__file__).parent / "fixtures"
DOOR_KEYS = ("firstRowDriver", "firstRowPassenger", "secondRowDriver", "secondRowPassenger")
TIRE_KEYS = ("frontLeft", "frontRight", "rearLeft", "rearRight")


def load_body(name: str) -> dict[str, Any]:
    with open(FIXTURES / name, encoding="utf-8") as file:
        return util.status_body(json.load(file))


@pytest.fixture
def body() -> dict[str, Any]:
    return load_body("dashboard_2025_crv_hybrid.json")


@pytest.fixture
def running_body() -> dict[str, Any]:
    return load_body("dashboard_2025_crv_hybrid_engine_running.json")


def _engine_body(status: Any) -> dict[str, Any]:
    return {"remoteEngineStart": {"vehicleStartEvent": {"resStatus": status}}}


# 1. Remote engine running


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ON", True),
        ("on", True),
        ("ENGINE START IG RUN", True),
        ("ENGINE START", True),
        ("IG RUN", True),
        ("OFF", False),
        ("off", False),
        ("SOMETHING ELSE", False),
        ("unknown", None),
        ("", None),
        (None, None),
    ],
)
def test_engine_running_from_status(status: Any, expected: bool | None) -> None:
    assert util.engine_running_from_status(status) is expected
    assert util.remote_engine_running(_engine_body(status)) is expected


def test_engine_running_missing() -> None:
    assert util.remote_engine_running({}) is None
    assert util.remote_engine_running({"remoteEngineStart": {}}) is None
    assert util.remote_engine_status({}) is None


def test_engine_running_fixtures(body, running_body) -> None:
    assert util.remote_engine_running(body) is False
    assert util.remote_engine_status(body) == "OFF"
    assert util.remote_engine_running(running_body) is True
    assert util.remote_engine_status(running_body) == "ENGINE START IG RUN"


def test_unexpected_engine_status_stays_visible() -> None:
    data = _engine_body("ENGINE STOP")
    assert util.remote_engine_running(data) is False
    assert util.remote_engine_status(data) == "ENGINE STOP"


# 2. Remote start details


def test_remote_start_attributes(body) -> None:
    assert util.remote_start_attributes(body) == {
        "res_start_counter": "1",
        "res_time": "1",
        "res_requester": "TCU",
        "delay_start_time": None,
    }


def test_remote_start_attributes_missing() -> None:
    assert util.remote_start_attributes({}) == {
        "res_start_counter": None,
        "res_time": None,
        "res_requester": None,
        "delay_start_time": None,
    }


# 3. "unknown" is no value


@pytest.mark.parametrize("value", [None, "", "unknown", "Unknown", " UNKNOWN "])
def test_clean_value_missing(value: Any) -> None:
    assert util.clean_value(value) is None
    assert util.to_int(value) is None
    assert util.to_float(value) is None


@pytest.mark.parametrize("value", ["OFF", "0", 0, 0.0, False, "Lock"])
def test_clean_value_keeps_real_values(value: Any) -> None:
    assert util.clean_value(value) == value


def _leaves(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}.{index}" if path else str(index))
    else:
        yield path, value


def test_every_fixture_unknown_parses_to_none(body) -> None:
    unknown_paths = [path for path, value in _leaves(body) if value == "unknown"]
    # 8 tire pressure/warning values, 10 in the evStatus block, and delayStartTime.
    assert len(unknown_paths) == 19
    for path in unknown_paths:
        value = util.get_path(body, path)
        assert util.clean_value(value) is None, path
        assert util.to_int(value) is None, path
        assert util.to_float(value) is None, path
        if path.endswith(".value"):
            node = util.get_path(body, path.rsplit(".", 1)[0])
            assert util.value_from_status_node(node) is None, path


def _contains_unknown(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "unknown"
    if isinstance(value, dict):
        return any(_contains_unknown(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_unknown(item) for item in value)
    return False


def _all_helper_outputs(data: dict[str, Any]) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "12v_battery_status": util.find_12v_battery_status(data),
        "12v_battery_candidates": util.find_12v_battery_candidates(data),
        "remote_engine_status": util.remote_engine_status(data),
        "remote_engine_running": util.remote_engine_running(data),
        "remote_start_attributes": util.remote_start_attributes(data),
        "cabin_temperature": util.cabin_temperature(data),
        "cabin_temperature_unit": util.cabin_temperature_unit(data),
        "maintenance_minder": util.maintenance_minder_state(data),
        "maintenance_minder_messages": util.maintenance_minder_messages(data),
        "warning_lamp_on": util.warning_lamp_on(data),
        "active_warnings": util.active_warning_lamps(data),
        "gps_attributes": util.gps_attributes(data),
        "all_door_locks_locked": util.all_door_locks_locked(data),
        "any_light_on": util.any_light_on(data),
        "any_door_open": util.any_open_state(data, "doorStatus", list(DOOR_KEYS)),
        "hood_open": util.any_open_state(data, "doorStatus", ["hood"]),
    }
    for key in DOOR_KEYS:
        outputs[f"{key}_unlocked"] = util.door_unlocked(data, key)
    for key in TIRE_KEYS:
        outputs[f"{key}_pressure"] = util.to_int(util.get_path(data, f"tireStatus.{key}.pressureData.value"))
    return outputs


def test_no_helper_returns_the_word_unknown(body, running_body) -> None:
    for data in (body, running_body):
        outputs = _all_helper_outputs(data)
        assert not _contains_unknown(outputs), outputs


def test_tire_pressures_are_none(body) -> None:
    for key in TIRE_KEYS:
        assert util.to_int(util.get_path(body, f"tireStatus.{key}.pressureData.value")) is None


def test_12v_battery_status_is_none(body) -> None:
    assert util.find_12v_battery_status(body) is None


def test_unknown_states_do_not_read_as_open_or_on() -> None:
    data = {
        "doorStatus": {"hood": {"openState": "unknown"}, "firstRowDriver": {"lockState": "unknown"}},
        "lightStatus": {"headlights": {"lightState": "unknown"}},
    }
    assert util.any_open_state(data, "doorStatus", ["hood"]) is None
    assert util.any_light_on(data) is None
    assert util.all_door_locks_locked(data) is None
    assert util.door_unlocked(data, "firstRowDriver") is None


def test_attribute_values_map_unknown_to_none() -> None:
    assert util.attribute_safe_value({"a": "unknown", "b": ["unknown", "x"]}) == {"a": None, "b": [None, "x"]}


# 4. New entities


def test_door_locks(body, running_body) -> None:
    for key in DOOR_KEYS:
        assert util.door_unlocked(body, key) is False
    assert util.all_door_locks_locked(body) is True

    assert util.door_unlocked(running_body, "firstRowDriver") is True
    for key in DOOR_KEYS[1:]:
        assert util.door_unlocked(running_body, key) is False
    assert util.all_door_locks_locked(running_body) is False


@pytest.mark.parametrize(
    ("state", "expected"),
    [("Lock", False), ("LOCK", False), ("lock", False), ("Unlock", True), ("UNLOCK", True), (None, None)],
)
def test_door_unlocked_case_insensitive(state: Any, expected: bool | None) -> None:
    data = {"doorStatus": {"firstRowDriver": {"lockState": state}}}
    assert util.door_unlocked(data, "firstRowDriver") is expected


def test_door_unlocked_missing_door() -> None:
    assert util.door_unlocked({}, "firstRowDriver") is None


def test_cabin_temperature(body) -> None:
    assert util.cabin_temperature(body) == 21
    assert util.cabin_temperature_unit(body) == "c"


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("c", "c"), ("C", "c"), ("celsius", "c"), ("f", "f"), ("F", "f"), ("Fahrenheit", "f"), ("unknown", None), (None, None)],
)
def test_cabin_temperature_unit(unit: Any, expected: str | None) -> None:
    assert util.cabin_temperature_unit({"temperature": {"cabin": {"value": "70", "unit": unit}}}) == expected


def test_cabin_temperature_unknown() -> None:
    assert util.cabin_temperature({"temperature": {"cabin": {"value": "unknown", "unit": "c"}}}) is None
    assert util.cabin_temperature({}) is None


def test_maintenance_minder_fixture(body) -> None:
    assert util.maintenance_minder_state(body) == "OK"
    assert util.maintenance_minder_messages(body) == []


def test_maintenance_minder_codes() -> None:
    data = {
        "maintenanceMinder": {
            "data": [
                {
                    "languageCode": "en",
                    "messages": [
                        {"code": "A1", "messageText": "Replace engine oil, rotate tires"},
                        {"code": "B12"},
                        {"code": "A1"},
                    ],
                }
            ]
        }
    }
    assert util.maintenance_minder_state(data) == "A1, B12"
    assert util.maintenance_minder_messages(data) == data["maintenanceMinder"]["data"][0]["messages"]


def test_maintenance_minder_code_inside_text() -> None:
    data = {"maintenanceMinder": {"data": [{"messages": [{"message": "B12"}]}]}}
    assert util.maintenance_minder_state(data) == "B12"


def test_maintenance_minder_text_only() -> None:
    data = {"maintenanceMinder": {"data": [{"messages": [{"messageText": "Maintenance due soon"}]}]}}
    assert util.maintenance_minder_state(data) == "Maintenance due soon"


def test_maintenance_minder_odd_shapes() -> None:
    # data as a single object, messages as a single object or a string.
    assert util.maintenance_minder_state({"maintenanceMinder": {"data": {"messages": {"code": "A"}}}}) == "A"
    assert util.maintenance_minder_state({"maintenanceMinder": {"data": [{"messages": "B1"}]}}) == "B1"
    assert util.maintenance_minder_state({"maintenanceMinder": {"data": [{"messages": [{"code": "unknown"}]}]}}) == "OK"
    assert util.maintenance_minder_state({"maintenanceMinder": "unknown"}) == "OK"
    assert util.maintenance_minder_state({}) == "OK"


def test_maintenance_minder_unrecognised_message() -> None:
    data = {"maintenanceMinder": {"data": [{"messages": [{"severity": "2"}]}]}}
    assert util.maintenance_minder_state(data) == "Due"


def test_maintenance_minder_state_fits_ha_limit() -> None:
    data = {"maintenanceMinder": {"data": [{"messages": [{"messageText": "x" * 400}]}]}}
    assert len(util.maintenance_minder_state(data)) <= 255


def test_warning_lamps_fixture(body) -> None:
    assert util.warning_lamp_on(body) is False
    assert util.active_warning_lamps(body) == []


def test_active_warning_lamps() -> None:
    on = {"condition": "ON", "messageText": "Check engine"}
    off = {"condition": "OFF", "messageText": "Brake system"}
    data = {"warningLamps": {"data": [{"languageCode": "en", "messages": [on, off]}]}}
    assert util.warning_lamp_on(data) is True
    assert util.active_warning_lamps(data) == [on]


def test_gps_attributes(body) -> None:
    assert util.gps_attributes(body) == {"heading": 0.0, "gps_time": "2026-10-22T23:52:40+00:00"}


def test_gps_attributes_missing() -> None:
    assert util.gps_attributes({}) == {"heading": None, "gps_time": None}


# 0.3.0: parked car, vehicle picture, enrollment status


@pytest.fixture
def parked_body() -> dict[str, Any]:
    # A later reply from the same car, parked: no cabin temperature, no recent remote start.
    return load_body("dashboard_2025_crv_hybrid_parked.json")


def load_json(name: str) -> Any:
    with open(FIXTURES / name, encoding="utf-8") as file:
        return json.load(file)


def test_parked_fixture(parked_body) -> None:
    assert util.cabin_temperature(parked_body) is None
    assert util.cabin_temperature_unit(parked_body) == "c"
    assert util.remote_engine_running(parked_body) is False
    assert util.remote_start_attributes(parked_body)["res_requester"] == "NO"
    assert util.remote_start_attributes(parked_body)["res_time"] == "0"
    assert not _contains_unknown(_all_helper_outputs(parked_body))


def test_vehicle_image_url() -> None:
    vehicle = load_json("vehicle_2025_crv_hybrid.json")
    url = util.vehicle_image_url(vehicle)
    assert url == vehicle["LargeFrontImage"]
    assert url.startswith("https://automobiles.honda.com/")


@pytest.mark.parametrize(
    ("vehicle", "expected"),
    [
        ({"Asset34FrontPath": "https://example.com/a.png"}, "https://example.com/a.png"),
        ({"LargeFrontImage": "", "Asset34FrontPath": "https://example.com/a.png"}, "https://example.com/a.png"),
        ({"LargeFrontImage": "http://example.com/a.png"}, None),
        ({"LargeFrontImage": None}, None),
        ({}, None),
        (None, None),
    ],
)
def test_vehicle_image_url_edge_cases(vehicle: Any, expected: str | None) -> None:
    assert util.vehicle_image_url(vehicle) == expected


def test_enrollment_status() -> None:
    assert util.enrollment_status(load_json("entitlement_2025_crv_hybrid.json")) == "Active"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"status": "failure", "responseBody": {"enrollmentStatus": "Active"}},
        {"status": "success", "responseBody": {"enrollmentStatus": "unknown"}},
        {"status": "success", "responseBody": None},
    ],
)
def test_enrollment_status_missing(data: dict[str, Any]) -> None:
    assert util.enrollment_status(data) is None
