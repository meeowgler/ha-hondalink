# Fork plan: adapt to the 2025 CR-V Hybrid

Work through these in order. Each section says what is observed in the fixture
(`tests/fixtures/dashboard_2025_crv_hybrid.json`, all paths below are under `responseBody`)
and what to change. Finish with tests and a version bump.

## 1. Fix "Remote engine running" (bug)
- Observed: after a successful remote start, `remoteEngineStart.vehicleStartEvent.resStatus`
  was `"ENGINE START IG RUN"`. When off it is `"OFF"`. Upstream's binary sensor is only on
  when the value is exactly `"ON"`, so it never turns on for this car.
- Change: move the decision into a `util.py` helper. Treat as running: `"ON"`, anything
  starting with `"ENGINE START"`, or containing `"IG RUN"`. Treat `"OFF"` as off.
  Treat `None` / `""` / `"unknown"` as no value (`None`, so HA shows unknown).
  Any other value: off, but keep the raw value visible (next section).
- Keep the entity key `remote_engine_running`. Give it `BinarySensorDeviceClass.RUNNING`.

## 2. Remote start details
- Observed fields under `remoteEngineStart`: `vehicleStartEvent.resStartCounter` ("1"),
  `vehicleStartEvent.resTime` ("1", meaning not yet confirmed, possibly minutes),
  `vehicleStartEvent.resRequester` ("TCU"), `delayStart.delayStartTime` ("unknown").
- Change: keep `remote_engine_status` as the raw string, and add these four as
  extra state attributes on it (snake_case names, `"unknown"` → `None`).

## 3. Treat `"unknown"` as no value everywhere
- Observed: Honda sends the literal string `"unknown"` for fields this car doesn't report
  (all four tire pressures and tire warning states, the whole `evStatus` block,
  `delayStartTime`). `to_int`/`to_float` already handle it; make sure every value_fn,
  attribute and state helper does too (string-valued sensors like
  `remote_engine_status` and `12v_battery_status` included), so HA shows unknown instead
  of the word "unknown".
- This car will never fill tire pressures, 12V battery or EV fields. Do not delete those
  entities (other cars may report them). Leave them as they are; Nick will disable them in HA.

## 4. New entities
All read from the fixture paths; add translation entries and keep keys snake_case.
- **Cabin temperature** sensor: `temperature.cabin.value` with unit from
  `temperature.cabin.unit` (`"c"` here; map `c`/`f` to HA's Celsius/Fahrenheit),
  `SensorDeviceClass.TEMPERATURE`, `SensorStateClass.MEASUREMENT`. Key `cabin_temperature`.
- **Per-door lock** binary sensors for `doorStatus.{firstRowDriver, firstRowPassenger,
  secondRowDriver, secondRowPassenger}.lockState` (`"Lock"` here; expect `"Unlock"`
  otherwise, compare case-insensitively). `BinarySensorDeviceClass.LOCK`, where on means
  unlocked. Keys like `front_left_door_unlocked` (driver side is left in the US).
- **Maintenance Minder** sensor: `maintenanceMinder.data[*].messages[*]`. Today the only
  content is `languageCode`, meaning nothing is due. When due, Honda sends Maintenance
  Minder codes (e.g. A1, B12) and/or text. State: the active code(s) joined, or `"OK"`
  when there are no messages; attributes: the raw message list. Parse defensively (reuse
  the shape handling from the warning-lamp helpers in `util.py`). Key `maintenance_minder`.
- **Active warnings** attribute: add the list of active warning-lamp messages as an
  attribute on the existing `warning_lamp_on` binary sensor.
- **Device tracker**: add `gpsData.courseHeading` as a `heading` attribute and
  `gpsData.dtTime` as `gps_time`. Leave `location_accuracy` as it is.

## 5. Tests
- Add `tests/test_util.py` (plain pytest, no HA install needed) covering: engine running
  for `"ON"`, `"ENGINE START IG RUN"`, `"OFF"`, `"unknown"`, missing; the fixture's door
  locks, cabin temperature (21, Celsius), maintenance minder (`"OK"`), and that every
  `"unknown"` in the fixture parses to `None`.
- Add a second fixture made by copying the first with `resStatus` set to
  `"ENGINE START IG RUN"` and one door set to `"Unlock"`, and test against it too.
- If you also want to import the HA platform modules in tests, `pip install homeassistant
  pytest-homeassistant-custom-component` works on the Trusted network, but util-level
  tests are enough for this change.

## 6. Housekeeping
- `manifest.json`: bump `version` to `0.2.0`, point `documentation` and `issue_tracker`
  at `https://github.com/nickwilkie/ha-hondalink`. Keep `codeowners` as is.
- README: add a short "Fork changes" section at the top listing what changed.
- Run `python -m py_compile *.py` and the tests before pushing.

## Later (not in this round)
- The start command accepts `extend: true` (see `api.py`), which no button uses yet.
- New commands (e.g. climate presets) need a capture of the HondaLink app's traffic first.
