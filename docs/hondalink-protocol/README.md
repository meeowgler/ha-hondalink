# HondaLink app protocol — reverse-engineering findings

Findings from reverse engineering **HondaLink 5.5.2 for iOS** (decrypted IPA) to map the
backend protocol, with an eye toward features the integration does not yet expose for the
**2025 CR-V Hybrid**.

- `protocol.md` — full write-up: service hosts, auth flows, vehicle-data endpoints,
  CIG remote-command pattern, MQTT channel, 2025 CR-V applicability, gap analysis vs
  this repo, and evidence anchors (symbols/addresses).
- `api-map.txt` — every `apiName → path` pair reconstructed from the app's static
  config dictionaries (~200 endpoints, grouped by path prefix; QA/UAT variants merged).
- `deep-dive.md` — second pass: exact command bodies (inline Swift string recovery),
  command state machine and polling statuses, the remote-climate stack, data models
  from Swift reflection metadata, service→host table, GET/POST catalog.
  Third pass (§10): `acSetting` wire fields, server vs app status strings,
  MY21 location / car finder bodies, vehicle-messages inbox, recall GET.
- `com-classes.txt` — the 171 `COM*` operation classes (class-name prefix = HTTP verb).
- `bundle/` — catalogs shipped inside the app: `warningLamps.json`,
  `dashboard.json`, `FeatureFilterMapper.json` (FeatureID → filter group),
  `FeatureLocalisationMapper.json`.

Method: REA (Ghidra/Hopper) + custom Mach-O parsers for Swift metadata, ObjC runtime,
dyld chained fixups, and Swift string slots in `__data`. The app's two static tables —
service→host (`SharedFramework.__data 0x233c68+`) and service→{apiName:path}
(`0x23b600+`) — were decoded directly; five copies exist (Honda PROD, Acura PROD, QA×2,
UAT). The PROD copy is documented.

Key takeaways for this repo are in `protocol.md` §8 (gap analysis). Highlights:

- CIG commands are async two-phase (`POST /CIG/<cmd>/async` → `serviceRequestId` →
  poll `/CIG/<cmd>/results`); this repo's `_async_cig_command()` already implements the
  pattern, so new commands are mostly one-liners.
- Not yet used here: car finder, geofences + contact alerts, speed alert, POI send,
  idle cabin temperature, parts health (`/REST/SPT/VehiclePartsHealth/1.0`), trip
  scores, activity log, GDO garage doors (MyQ-backed), feature/entitlement gating.
- The app pushes command results over AWS IoT MQTT (`/GetSignedToken/1.0` creds), but
  every push has a REST results twin — polling is sufficient.

Generated 2026-10-23.
