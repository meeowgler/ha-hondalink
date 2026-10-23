# ha-hondalink (nickwilkie fork)

Fork of daviddelahoz/ha-hondalink, a Home Assistant custom integration for HondaLink
(Honda's private cloud API). This fork adapts it to Nick's car and is installed on his
HA through HACS from this repo's `main` branch.

## The car
- 2025 Honda CR-V Hybrid AWD Sport Touring, US, telematics platform `MY21`
  (same platform upstream was built and tested against, so the remote commands match).
- A real, redacted status reply is in `tests/fixtures/dashboard_2025_crv_hybrid.json`.
  That is the ground truth for which fields this car fills in. Build and test against it.
- `tools/hondalink_dump.py` regenerates that kind of dump (Nick runs it on his Mac; it
  reuses `api.py`). Cloud sessions cannot reach Honda's API, Nick's HA, or the car.

## Repo layout
- `content_in_root: true` in `hacs.json`: the integration's files live at the repo root,
  and HACS copies the root into `custom_components/hondalink`. Keep it that way.
- `api.py` (HTTP client, no HA imports), `const.py`, `util.py` (parsing helpers, no HA
  imports), and the HA platforms: `sensor.py`, `binary_sensor.py`, `lock.py`,
  `button.py`, `device_tracker.py`, plus `coordinator.py` and `config_flow.py`.
- Entity names come from `translations/en.json` via `translation_key`; every new entity
  needs an entry there.

## Rules
- Do not change the login/auth flow, the app credentials in `const.py`, or command codes
  unless a task says to. They work for this car today.
- Never commit real VINs, GPS coordinates, emails, PINs or tokens. Fixtures must stay
  redacted (the dump tool's default output is).
- Keep parsing logic in `util.py` (no `homeassistant` imports) so it can be unit tested
  with plain `pytest` against the fixture. Tests live in `tests/`.
- Keep existing entity `key`s / unique IDs stable so Nick's dashboards and history keep working.
- Bump `version` in `manifest.json` for every change set that should reach HA, since HACS
  uses it to offer the update.

## Current work
See `docs/fork-plan.md`.
