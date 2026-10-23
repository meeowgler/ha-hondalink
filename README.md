<p align="center">
  <img src="assets/logo.png" alt="HondaLink Home Assistant integration logo" width="180">
</p>

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/github/v/release/daviddelahoz/ha-hondalink)](https://github.com/daviddelahoz/ha-hondalink/releases)
[![License](https://img.shields.io/github/license/daviddelahoz/ha-hondalink)](LICENSE)
[![Maintenance](https://img.shields.io/maintenance/yes/2026.svg)](https://github.com/daviddelahoz/ha-hondalink)

# HondaLink for Home Assistant

## Fork changes

This fork ([nickwilkie/ha-hondalink](https://github.com/nickwilkie/ha-hondalink)) adapts
[daviddelahoz/ha-hondalink](https://github.com/daviddelahoz/ha-hondalink) to a 2025 CR-V Hybrid (MY21 telematics). Changes in 0.2.0:

- **Remote engine running** now turns on for the status this car reports after a remote start
  (`ENGINE START IG RUN`), as well as `ON`. It uses the `running` device class.
- **Remote engine status** keeps the raw status string and adds `res_start_counter`, `res_time`,
  `res_requester` and `delay_start_time` attributes.
- Fields Honda reports as the literal string `unknown` now show as unknown in Home Assistant
  instead of the word "unknown" (sensors, attributes, and the door/light/lock state helpers).
- New entities: **Cabin temperature**, **Maintenance Minder** (active codes, or `OK`), and
  per-door **Front/Rear left/right door unlocked** binary sensors.
- **Warning lamp on** has an `active_warnings` attribute; the **Location** tracker has `heading`
  and `gps_time` attributes.
- Parsing lives in `util.py` with plain `pytest` tests against a redacted CR-V status reply
  (`python -m pytest tests`).

Unofficial Home Assistant custom integration for HondaLink MY21 telematics vehicles.

This integration uses the HondaLink Android app API flow, observed while debugging the app, to discover vehicles, poll vehicle state, and expose supported remote commands in Home Assistant.

> This project is not affiliated with, endorsed by, or supported by Honda. HondaLink is a trademark of its respective owner.

## Features

- Fuel level, range, odometer, oil life, 12V battery status, tire pressure, vehicle speed, and last update sensors
- Door, hood, trunk, window, lights, warning lamp, and remote engine binary sensors
- Lock and unlock entity for supported vehicles
- Buttons for engine start, engine stop, horn, lights, stop horn/lights, and refresh
- Device tracker from vehicle GPS data when returned by the HondaLink API
- Configurable lock and unlock command codes for vehicles or markets that use alternate CIG command names

## Status

This is early custom-component work built from a validated HondaLink Android app flow observed during app debugging. It has been tested against a MY21 HondaLink telematics flow, but Honda can change these private endpoints at any time.

## Installation

### HACS

This repository is ready for HACS custom repository installation.

1. In Home Assistant, open HACS.
2. Go to Integrations.
3. Open Custom repositories.
4. Add this repository URL.
5. Choose category `Integration`.
6. Install `HondaLink`.
7. Restart Home Assistant.

### Manual

Copy the integration folder to Home Assistant:

```text
/config/custom_components/hondalink
```

Then restart Home Assistant.

## Setup

In Home Assistant, go to:

```text
Settings > Devices & services > Add integration > HondaLink
```

The config flow asks for:

- HondaLink email
- HondaLink password
- Remote PIN from the HondaLink app
- VIN, optional if the vehicle can be discovered automatically
- Name, optional display name

If auto-discovery returns no vehicles, enter the VIN manually.

## API Flow

The integration currently follows this sequence:

1. Register app client with HIDAS.
2. Generate a HIDAS bearer token.
3. Discover vehicles from `GET /REST/NGT/MyVehicle/1.0`.
4. Poll latest vehicle state from `POST /REST/NGT/CIG/dbd/latest/{VIN}`.
5. Send remote CIG commands through `POST /REST/NGT/CIG/{engine}/async/{command}`.
6. Poll command results from `GET /REST/NGT/CIG/{engine}/results/{request_id}`.

### Token Generation

The live HIDAS token endpoint expects these form fields:

```text
username=<email>
password=<password>
description=Android
client_reg_key=<client_reg_key>
```

Earlier app-debugging notes may mention `email` and `device_description`, but those fields are not the confirmed working request shape for the live endpoint.

## Options

After setup, open the integration options to change:

- Remote PIN
- Polling interval
- Lock command code
- Unlock command code

The default lock command is `alk`; the default unlock command is `dulk`.

## Troubleshooting

### Could not connect to HondaLink

Restart Home Assistant after updating the custom component, then try setup again. The config flow logs the HondaLink response in a redacted form, so check Home Assistant logs for:

```text
HondaLink connection failed during config flow
```

### Invalid credentials or remote PIN

Confirm that the same email, password, and remote PIN work in the HondaLink mobile app. Some HondaLink accounts may require accepting updated terms or completing account verification in the app before API login succeeds.

### No vehicle discovered

Enter the VIN manually in the setup form. The integration will still try to fetch vehicle details by VIN after login.

## Security

- This integration stores your HondaLink email, password, and remote PIN in the Home Assistant config entry so it can re-authenticate after token expiry.
- The Honda app `CLIENT_ID` and `CLIENT_SECRET` values are app-level credentials observed from the HondaLink mobile app flow, not user-specific credentials. Honda ships and uses them as part of the mobile app authentication flow, which this integration mirrors.
- Honda may rotate or revoke those app-level credentials at any time. If that happens, authentication can stop working for all users until the integration is updated.
- Do not share logs or diagnostics that include tokens, remote PIN, VIN, or GPS coordinates.
- Remote commands can physically affect your vehicle. Use this only with your own HondaLink account and vehicle.

## Support

<a href="https://www.buymeacoffee.com/daviddelahoz" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" style="height: 60px !important;width: 217px !important;" ></a>

## Known Limitations

- Tested against a MY21 telematics HondaLink flow.
- EV fields are exposed only when the Honda dashboard payload returns actual values.
- Lock and unlock command behavior may vary by vehicle, subscription, market, or Honda API changes.
- HondaLink is a private cloud API; reliability depends on Honda's service and endpoint compatibility.

## Local Development

Useful validation commands:

```bash
python -m py_compile *.py
pip install pytest
python -m pytest tests
```

The tests only need `pytest`, not Home Assistant. Run them as `python -m pytest tests`: a bare
`pytest` from the repo root tries to import the root `__init__.py`, which needs Home Assistant.

HACS and hassfest workflow files are included under `.github/workflows/`.
