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


# Recalls (Honda's public recall lookup)


def _recall_reply(campaign_types: Any, **recall: Any) -> dict[str, Any]:
    return {"response": {"recalls_response": {"Response": {"error": "false", "Recall": {"CampaignType": campaign_types, **recall}}}}}


def _campaign(number: str, disposition: str = "Open", mfr: str = "Recall INCOMPLETE") -> dict[str, Any]:
    return {
        "RecallNumber": number,
        "CampaignID": f"C{number}",
        "CampaignDescription": f"Recall {number}",
        "CampaignTypeDesc": "Safety Recall Campaign",
        "CampaignDispositionStatusDesc": disposition,
        "MfrRecallStatus": {"cd": "11", "value": mfr},
        "CampaignStartDate": "2026-06-05",
    }


def test_recalls_fixture() -> None:
    data = load_json("recalls_2025_crv_hybrid.json")
    assert util.open_recalls(data) == 1
    (recall,) = util.recall_campaigns(data)
    assert recall["recall_number"] == "26V-366"
    assert recall["campaign_id"] == "DOV"
    assert recall["description"] == "2023-26 Accord Hyb/CR-V Hyb/FC Tire Repair Kit Recall"
    assert recall["status"] == "Open"
    assert recall["manufacturer_status"] == "Recall INCOMPLETE"
    assert recall["start_date"] == "2026-06-05"
    assert recall["open"] is True
    assert recall["safety_risk"].startswith("If the bottle cap detaches")
    assert recall["remedy"].startswith("Parts are available")


def test_recalls_lists_and_closed() -> None:
    # Several campaign types, each with one campaign or a list of them.
    data = _recall_reply(
        [
            {"cd": "C", "Campaign": [_campaign("1"), _campaign("2", "Closed", "Recall COMPLETE")]},
            {"cd": "P", "Campaign": _campaign("3")},
        ]
    )
    assert [r["recall_number"] for r in util.recall_campaigns(data)] == ["1", "2", "3"]
    assert [r["open"] for r in util.recall_campaigns(data)] == [True, False, True]
    assert util.open_recalls(data) == 2


def test_recalls_none_open() -> None:
    assert util.open_recalls(_recall_reply({"cd": "C", "num_campaigns": "0"})) == 0
    assert util.recall_campaigns(_recall_reply({"cd": "C", "num_campaigns": "0"})) == []


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"response": {"recalls_response": None}},
        {"response": {"recalls_response": {"Response": {"error": "true"}}}},
        # What the lookup returns for a VIN it doesn't know.
        _recall_reply({"cd": "C", "num_campaigns": "0"}, warning={"code": "1000", "desc": "Invalid VIN"}),
    ],
)
def test_recalls_unknown(data: dict[str, Any]) -> None:
    assert util.open_recalls(data) is None


# 0.4.0: create only the entities the car supports


# Every entity key the integration has, by platform.
ALL_ENTITY_KEYS = {
    # sensor
    "fuel_level", "range", "odometer", "oil_life", "12v_battery_status",
    "front_left_tire_pressure", "front_right_tire_pressure", "rear_left_tire_pressure", "rear_right_tire_pressure",
    "vehicle_speed", "remote_engine_status", "cabin_temperature", "maintenance_minder", "last_update",
    "open_recalls", "enrollment_status",
    # binary_sensor
    "any_door_open", "hood_open", "trunk_open", "any_window_open", "any_light_on", "warning_lamp_on",
    "remote_engine_running", "front_left_door_unlocked", "front_right_door_unlocked",
    "rear_left_door_unlocked", "rear_right_door_unlocked",
    # button
    "start_engine", "extend_engine", "stop_engine", "horn", "lights", "stop_horn_lights", "refresh",
    # lock, device_tracker
    "doors_lock", "location",
}
TIRE_KEYS_HA = {"front_left_tire_pressure", "front_right_tire_pressure", "rear_left_tire_pressure", "rear_right_tire_pressure"}


def _created(features: set[str] | None, body: dict[str, Any]) -> set[str]:
    return {key for key in ALL_ENTITY_KEYS if util.entity_supported(key, features, body)}


def test_requirements_cover_every_entity() -> None:
    assert set(util.ENTITY_REQUIREMENTS) == ALL_ENTITY_KEYS


def test_feature_ids_fixture() -> None:
    features = util.feature_ids(load_json("feature_list_2025_crv_hybrid.json"))
    assert len(features) == 37
    assert {"50012", "50026", "50029", "50034", "50035", "50037", "50071"} <= features
    # No tire pressure, remote climate or EV charging on this car.
    assert not {"50025", "50011", "50030"} & features


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"VEHICLE": {}},
        {"VEHICLE": {"Model": {"Feature": []}}},  # an empty list would hide everything: treat as unknown
        {"VEHICLE": {"Model": {"Feature": [{"FeatureName": "Find My Car"}]}}},  # no numeric IDs
    ],
)
def test_feature_ids_unknown(data: dict[str, Any]) -> None:
    assert util.feature_ids(data) is None


def test_feature_ids_single_feature_object() -> None:
    data = {"VEHICLE": {"Model": {"Feature": {"FeatureName": "50037|Remote Start"}}}}
    assert util.feature_ids(data) == {"50037"}


def test_entities_for_this_car(body, parked_body) -> None:
    features = util.feature_ids(load_json("feature_list_2025_crv_hybrid.json"))
    # Tire pressure (no feature 50025) and 12V battery (no such field) go; everything else stays.
    expected = ALL_ENTITY_KEYS - TIRE_KEYS_HA - {"12v_battery_status"}
    assert _created(features, body) == expected
    # The parked reply (cabin temperature "unknown") keeps the same set.
    assert _created(features, parked_body) == expected


def test_unknown_features_create_everything_the_data_has(body) -> None:
    assert _created(None, body) == ALL_ENTITY_KEYS - {"12v_battery_status"}


def test_no_data_creates_everything() -> None:
    assert _created(None, {}) == ALL_ENTITY_KEYS


def test_car_with_tire_pressure_but_no_remote_start(body) -> None:
    features = (util.feature_ids(load_json("feature_list_2025_crv_hybrid.json")) | {"50025"}) - {"50037"}
    created = _created(features, body)
    assert TIRE_KEYS_HA <= created
    assert not {"start_engine", "extend_engine", "stop_engine", "remote_engine_running", "remote_engine_status"} & created


def test_data_presence_gates() -> None:
    body = {"odometer": {"value": "1"}, "timestamp": "x"}
    created = _created(None, body)
    assert {"odometer", "last_update", "refresh", "enrollment_status"} <= created
    assert not {"fuel_level", "range", "oil_life", "cabin_temperature", "vehicle_speed", "location", "warning_lamp_on"} & created


def test_12v_battery_created_when_reported() -> None:
    body = {"odometer": {"value": "1"}, "batteryStatus": {"batteryVoltageStatus": "Normal"}}
    assert util.entity_supported("12v_battery_status", None, body)


def test_unknown_entity_key_is_created() -> None:
    assert util.entity_supported("something_new", set(), {"odometer": {}})
