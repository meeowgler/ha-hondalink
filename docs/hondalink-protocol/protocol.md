# HondaLink 5.5.2 (iOS) — Backend Protocol Reference
### For a Home Assistant integration targeting the 2025 Honda CR‑V

Reverse-engineered from `HondaLink_5.5.2_ios_decrypted.ipa` using REA (Ghidra/Hopper) plus
custom Mach-O parsers (Swift metadata, ObjC runtime, chained-fixups, Swift string-slot
decoding in `__data`). Everything below was extracted from the binary — evidence anchors
(symbol names / addresses) are inline.

---

## 1. Architecture at a glance

The app talks to **several independent backends**, each a "service" with its own host and
its own API-name→path table. Both tables are compiled into `SharedFramework` as static
Swift dictionaries (`HNDataSourceHostsAndPaths.getDataSourcesHostsAndPaths()` at
`0x5366c`, config builder `FUN_00085fa0` at `0x85fa0–0x868d3`; five copies exist —
Honda PROD, Acura PROD, QA×2, UAT).

### Service → host (Honda PROD copy, decoded from `__data` @ `0x233c68+`)

| service key | base URL |
|---|---|
| `gtc`  (Global Telematics Cloud) | `https://www.jp.hondalink.com/api` |
| `ngt`  (NGT account/vehicle mgmt) | `https://ws.hondaweb.com/REST/NGT` |
| `ngtCloud` | `https://wsc.hondaweb.com/REST/NGT` |
| `cig`  (Connected Infotainment Gateway — remote commands) | `https://wsc.hondaweb.com/REST/CIG` |
| `hidas` (identity) | `https://identity.services.honda.com` |
| `location` | `https://location.services.honda.com` |
| `gdo`  (garage doors) | `https://wsc.hondaweb.com` |
| `gdoAuth` | `https://www.myqservices.com` ← Honda Connected Garage **is MyQ/Chamberlain** |
| `sxm` | `https://connected.mygarage.honda.com/api/getSSO` |
| `gtc` JP/QA variants | `https://www-v.jp.hondalink.com/api` (QA/UAT) |

URL assembly: `NetworkResource.urlPathForAPI(_:server:)`
(`_$s15SharedFramework15NetworkResourceC13urlPathForAPI_6serverSSAC0F0O_AC6ServerOtFZ`)
= host[server] + path[server][apiName]. The `NetworkResource.API` enum case list
(`__cstring` @ `0x1c19b9–0x1c1b9b` neighborhood) matches the API map below 1:1.

> **Cross-check with this repo:** `api.py` calls CIG endpoints as
> `wsc.hondaweb.com/REST/NGT/CIG/...` (NGT host proxying CIG), while the app itself uses
> the direct `wsc.hondaweb.com/REST/CIG/...` base. Both work; the proxy form is what this
> integration already uses, so new CIG features can reuse `_async_cig_command()` unchanged.

---

## 2. Authentication

| flow | endpoint | notes |
|---|---|---|
| Login / token | `POST https://identity.services.honda.com/hidas/rs/token/generate` (`userAuth`) | HIDAS. Body keys seen in binaries: `username`, `password`, `deviceID`, `deviceType`, `userType`, `customerId`, `authCode`, `accessToken` (SF `__cstring`). |
| Token mgmt | `/hidas/rs/token/reissue` (`reissueToken`), `/hidas/rs/token/revoke` (`signOut`), `/hidas/rs/token/validate` (`tokenValidate`), `/hidas/rs/token/generate/shortlive` (`secondaryToken`), `/hidas/rs/client/register` (`clientRegister`), `/hidas/rs/user/password/change` | |
| SSO token | `GET/POST https://www.jp.hondalink.com/api/SSO/GetAccessToken/1.0` (`accessToken`) | used for GTC calls |
| VinService auth | `GET https://www.jp.hondalink.com/api/VinServiceAuth` (`vinServiceAuth`) | **SHA‑256 signed**: log strings `------ HLGetVinServiceAuth currentGmtDate:,` + `------ HLGetVinServiceAuth before hash:,` (`__cstring` `0x1d1320`); `sha256` helper in SF; class `COMGetGTCVinServiceAuth(deviceID:)`. Required for every `GW/VinService/*` call. |
| Signed MQTT token | `GET .../api/GetSignedToken/1.0` (`signedToken`) | returns AWS IoT credentials for the MQTT channel |
| MyQ (garage) | `https://www.myqservices.com/prelanding/index` (`gdoAuth`) | MyQ OAuth, then Honda proxies via `/REST/GDO/*` |
| SXM | `https://location.services.honda.com/m/idm/oauth2/access_token` (`clientAuth`) | |

**Headers** (decoded from `__data`/`__cstring`): `Authorization` (Basic + Bearer),
`X-Honda-wl-authorization` (`__cstring` `0x1cc880`), `Request-Timestamp` (`0x1c22a0`).
Config keys `basicToken*` (`basicTokenCloud`, `basicTokenTnC`, `basicTokenDashboardLatest`,
`basicTokenVolteStatus`, …) + `clientId`/`clientSecret`/`applicationKey`/`serviceKeySecret`
(`__data` `0x25b890–0x25bd40`) are **server-provisioned** (config download), not baked into
the binary — an HA integration must fetch or reuse them like the existing ones do.

**Certificate pinning is enforced**: `SSL Pinning is enabled, Host not in PINNED list`,
`Public Key Pinning Successful with Key:`, `acceptedSelfSignedServers` (AKNetworking),
plus FAU cert-mismatch checks for HIDAS. Expect to bypass pinning (objection/frida on a
jailbroken device or an emulator) if you want to capture live traffic to confirm bodies.

---

## 3. Vehicle data (the good stuff the basic integrations miss)

All on `gtc` = `https://www.jp.hondalink.com/api` unless noted:

| apiName | path | what you get |
|---|---|---|
| `getLatestVehicleData` | `/GW/VinService/GetLatestVehicleData` | latest telematics snapshot (fuel, odometer, door/window/light status, tire, oil, temps) |
| `getVehicleLocation` | `/GW/VinService/ServiceDataRequest` | lat/long (`lat`, `long`, `isGeoCodingDone`, `geoCodedName` fields seen in CoreData classes) |
| `getEVehicleStatus` | `/Vehicle/` | EV/hybrid status (`HLGetEVehicleStatus`) |
| `rdrInfo` | `/Vehicle/Rdr` | radar/driving events |
| `locationAddress` | `/VDS/vehicle/location` (ngtCloud) | vehicle location w/ address |
| `vehicleMessages` / `vehicleMessagesStatus` | `/VehicleMessage/Details/1.0/`, `/VehicleMessage/Status/1.0` | vehicle→owner messages |
| `sptWebURL` | `/REST/SPT/VehiclePartsHealth/1.0` (wsc.hondaweb.com) | **parts health / diagnostics** |
| `activityLog` | `/ActivityLog/1.0/` | command + event log |
| `tripLogs` / `drivingScores` | `/CVP/TripScores/1.0`, `/CVP/DrivingScores/1.0` (ngt) | trip/score data |
| `getServerNotification` / `registerServerNotification` / `deleteServerNotification` | `/GW/VinService/*Notification` | push/notification registry |
| `registerRemoteList` / `RegisterRemoteList` | `/GW/VinService/RegisterRemoteList` | registers the mobile device as a remote |
| `getHomeLocationStatus`, `setHomeLocation`, `removeHomeLocation`, `getCommuteSchedule`, `setCommuteSchedule` | `/HomeLocationStatus/1.0`, `/setHomeLocation/1.0`, … | home/commute settings |
| `featureList` | `/CBO/FeatureList/1.0/` (ngt) | **which features this VIN supports — query this first** |
| `vehicleEntitlement` | `/Enrollment/VehicleEntitlement/2.0` | subscription status per feature |

**DigitalTwin attribute keys** (main binary `__data` `0x1018a9948+`):
`doorStatus`, `windowStatus`, `lightStatus`, `tireStatus`, `odometer`, `fuelLevel`,
`warningLamps`, `oilLife`, `temperature`, `VEHICLE RANGE`, plus EV-only
`EV CHARGE STATE`, `EV PLUG STATE`, `EV PLUG VOLTAGE`, `GET CHARGE MODE`.
These are the attribute names the app requests/parses — request them explicitly where the
API takes an attribute list.

---

## 4. Remote commands (CIG) — async pattern

Every CIG command is **two-phase**: `POST /CIG/<cmd>/async` → response contains
`serviceRequestId` → poll `GET /CIG/<cmd>/results` (or receive it over MQTT, §6).
Verified request shapes from Swift constructors (symtab):

```
COMPostCIGLockUnlock.init(keys:[String:AnyObject]?, command:String?, messageId:String, role:String?)
COMPostCIGEngineStart.init(keys:, role:)            // role → /CIG/eng/async/srt
COMPostCIGEngineStop.init(keys:, role:)             // role → /CIG/eng/async/sop
COMPostExecuteHornCommand.init(keys:, vin:, accountId:)
COMGetExecuteEngineRequest.init(servReqId:, vin:, accountId:)   // results poll
COMPostCIGGeoFence.init(bodyDict:[String:AnyObject])
COMPostCIGDashboard.init(keys:, cabinTemperature:Bool)
COMPostCIGDashboardLatest.init(keys:, vin:)
COMPostCIGSendPOI.init(keys:)
```
`COMPostCIGLockUnlock.init` (`0xb41d0`) shows `messageId` defaults to a fresh UUID.
Body `keys` dictionaries are built in the app UI layer; key tokens seen in the main
binary: `action`, `commandType`, `status`, `lock`/`unlock`/`locked`/`unlocked`,
`open`/`close`/`closed`, `on`/`off`, `horn`, `light`, `pin`, `vin`, `deviceId`,
`featureName`, `serviceRequestId`, `geofenceId`, `latitude`, `longitude`, `radius`,
`speedLimit`, `alertType`, `poiName`, `destination`, `defroster`, `acOn`, `temperature`,
`duration` (`__data`/`__cstring` neighborhoods shown in §3/§4 addresses).

### Full CIG command table (host `https://wsc.hondaweb.com/REST/CIG`)

| apiName | path | function |
|---|---|---|
| `lockUnlockAsync` / `lockUnlockResults` | `/CIG/lk/async` / `/CIG/lk/results` | lock / unlock |
| `engineStart` / `engineStop` / `engineResults` | `/CIG/eng/async/srt` / `/CIG/eng/async/sop` / `/CIG/eng/results` | remote start / stop |
| `hornLightAsync` / `hornLightResults` | `/CIG/cfhl/async` / `/CIG/cfhl/results/` | horn & lights |
| `carfinderAsync` / `carfinderResults` | `/CIG/cfl/async` / `/CIG/cfl/results/` | car finder (flash+horn) |
| `dashboardAsync` / `dashboardLatest` / `dashboardResults` | `/CIG/dbd/async` / `/CIG/dbd/latest` / `/CIG/dbd/results` | **full dashboard status incl. cabin temp** (`COMPostCIGDashboard(cabinTemperature: true)`) |
| `cabinTemperatureAsync` | `/CIG/IdleCabinTemperature/async/` | idle climate (ICE preconditioning) |
| `geoFencAsync` / `geoFencResult` | `/CIG/gefe/async` / `/CIG/gefe/results` | geofence (5 fences) |
| `geoFencContact` / `geoFencUpdateContact` / `geoFencUpdateStatus` | `/CIGContactsResults/1.0`, `/CIGContacts/1.0`, `/CIGNotification/1.0` | geofence alerts to contacts |
| `speedAlertAsync` / `speedAlertResults` | `/CIG/spal/async` / `/CIG/spal/results` | speed alert (limit + alertType) |
| `poiAsync` / `poiResults` | `/CIG/pi/async` / `/CIG/pi/results` | send POI to nav |
| `dataWipeAsync` / `dataWipeResults` | `/CIG/wph/async` / `/CIG/wph/results` | data wipe |
| `vehicleLocator` | `/vehiclelocaterAsync/1.0` (gtc) | locator w/ MQTT push |
| `updatePin` | `/PinManagement/UpdatePinService/1.0/` | PIN mgmt (lock cmd needs PIN) |
| `igOn` / `igOnResult` | `/VehicleAccessVerification/igOn/1.0/` | vehicle access verification |
| `reportStolenVehicle` / `svlStatus` | `/SVLReportStolenVehicle/1.0`, `/SVLGetStatus/1.0` | stolen vehicle locator |

Legacy GTC vehicle commands (also `gtc` host): `startAC` → `/VehicleCommand/START_AC/`,
`stopAC` → `/VehicleCommand/STOP_AC/`, `evTimers` → `/EVTimers/`.

---

## 5. Garage doors (GDO) — HomeKit-style, perfect for HA

| apiName | path | host |
|---|---|---|
| `gdoEnrollment` | `/REST/GDO/enrollment/1.0` | wsc.hondaweb.com |
| `gdoDevices` | `/REST/GDO/devices/1.0` | wsc.hondaweb.com |
| `remoteCommand` | `/REST/GDO/remoteCommand_async/1.0` | wsc.hondaweb.com |
| `gdoAuth` | `/prelanding/index` | **www.myqservices.com** |

Body/state keys (main binary `__data` `0x101895090+`, `0x1018bd2d8+`):
`gdoPartnerName`, `deviceType`, `deviceStates`, `finalState`, `deviceId`, plus device
kinds `garage_door`, `gate`, `light`, `lock`, `lockitron`, `gdos`. The 2025 CR‑V supports
HomeLink; if the owner enrolled doors in Honda "Connected Garage", HA can open/close them
through these endpoints (async + state polling, same pattern as CIG).

---

## 6. Push / MQTT channel (AWS IoT)

- Stack: AWS IoT SDK (`AWSIoTMQTTStatus`, `iotDataManager`) + `HNMQTTManager`,
  `MQTTSubscriptionManager`, `MQTTResolver`, `MQTTMessage` (Core Data entity,
  `vin == %@ AND topicName == %@ AND serviceRequestId == %@`).
- Credentials come from `GET /api/GetSignedToken/1.0` (`GetSignedTokenC`); log strings
  `after updating mqtt url -`, `Subscribe topics for current VIN :-`.
- Topics are built as `topic(vin:featureName:)` (`MQTTSubscriptionManager` symbol
  `...LL3vin11featureNameSSSgSS_SStF`) — format is Swift-interpolated, not a static
  string; features seen: `Lock`, `Unlock`, `Dashboard`, `Car Finder`, `horn`, `light`,
  `start`, `stop horn/light`, `HybridStartStop`, `HybridUpdateTemperature`,
  `ChargeDelayScheduleCommand`, `ChargeMaxLevelCommand`, `Gdo Trial Activation`,
  `Vehicle Locator`.
- **HA doesn't need MQTT**: every MQTT result has a REST twin (`/CIG/*/results` polled by
  `COMGetExecute*Request(servReqId:vin:accountId:)` with a timeout fallback —
  `telemetryTag=timeout_no_autoretry source=mqtt_vehicle_locator`).

---

## 7. 2025 CR‑V applicability matrix

The 2025 CR‑V is a MY23+ platform on the CIG stack (not OnStar — ignore
`getClimateStatus`/`ChargeStartStop`/`ClimateAsync`/`CPO*`/`SCPM*`/`RAH*`/`SSM*`,
those are GM/OnStar + EV/EVSE features). Relevant for CR‑V (incl. Hybrid HEV):

- **Status**: `getLatestVehicleData`, `dashboardLatest`/`dashboardAsync` (cabin temp!),
  `getVehicleLocation`/`locationAddress`, `sptWebURL` (parts health), `activityLog`,
  `tripLogs`/`drivingScores`, `featureList`, `vehicleEntitlement`.
- **Commands**: lock/unlock (PIN), engine start/stop (`srt`/`sop`), horn & lights,
  car finder, idle cabin temperature, geofences + contact alerts, speed alert,
  POI send (navi-equipped trims), data wipe.
- **Garage**: full GDO/MyQ set if enrolled.
- **Not applicable**: EV charge endpoints (`ChargeAsyncLevel`, `TargetChargeLevel`,
  `ManageCharge`, `EV CHARGE STATE` …) — CR‑V HEV has no plug.

## 8. Gap analysis vs this repo (ha-hondalink @ main, 2026-10)

Already implemented in `api.py`: vehicles (`MyVehicle/1.0`), profile, dashboard
latest/async, engine start/stop (`eng`), lock/unlock (`lk`, with legacy fallback),
horn/lights/stop (`cfhl`), location from dashboard `gpsData`.

Endpoints in the app **not yet used here** — candidates for new entities:

| feature | endpoint(s) | HA entity idea |
|---|---|---|
| Cabin temp in dashboard | `dbd/async` body with `cabinTemperature: true` (`COMPostCIGDashboard(keys:cabinTemperature:)`) | temp sensor |
| Car finder | `/CIG/cfl/async` + `/CIG/cfl/results/` | button |
| Idle cabin temperature (ICE precondition) | `/CIG/IdleCabinTemperature/async/` | switch/climate |
| Geofences + contact alerts | `/CIG/gefe/async`, `/CIG/gefe/results`, `/CIGContacts/1.0`, `/CIGContactsResults/1.0`, `/CIGNotification/1.0` | geofence config + notify |
| Speed alert | `/CIG/spal/async` + `/CIG/spal/results` (`speedLimit`, `alertType`) | number + switch |
| Send POI to nav | `/CIG/pi/async` (`poiName`, `latitude`, `longitude`) | `notify`/service |
| Parts health / diagnostics | `wsc.hondaweb.com/REST/SPT/VehiclePartsHealth/1.0` (+ `.../VehiclePartsHealthFeedback/1.0`) | sensors + alert binary sensors |
| Trip history / driving scores | `/REST/NGT/CVP/TripScores/1.0`, `/CVP/DrivingScores/1.0` | sensors |
| Activity log | `/api/ActivityLog/1.0/` (GTC host) | event entities |
| Fresh location (not dashboard snapshot) | `/api/GW/VinService/ServiceDataRequest` (`lat`, `long`, `geoCodedName`) | device_tracker source |
| Garage doors (MyQ) | `/REST/GDO/devices/1.0`, `/REST/GDO/remoteCommand_async/1.0` (`deviceStates`, `finalState`) | cover entities |
| Capability gate | `/REST/NGT/CBO/FeatureList/1.0/`, `/api/Enrollment/VehicleEntitlement/2.0` | gate entity creation per VIN |
| PIN management | `/api/PinManagement/UpdatePinService/1.0/` | service |
| Stolen vehicle status | `/api/SVLGetStatus/1.0` | binary sensor |

Implementation notes:
1. Reuse `_async_cig_command()` / `_poll_cig_result()` for every new CIG feature — the
   async→`serviceRequestId`→results pattern is identical (mirrors the app's
   `MQTTResolver` timeout fallback; HA does not need MQTT).
2. `featureList`/`vehicleEntitlement` once per VIN to gate sensors/switches.
3. GDO needs a separate MyQ-flavored auth hop (`www.myqservices.com/prelanding/index`)
   but Honda proxies the actual commands through `wsc.hondaweb.com/REST/GDO/*`.
4. Ignore OnStar/EV-charge endpoints (`ClimateAsync`, `CPO*`, `ChargeStartStop`,
   `SCPM*`, `RAH*`, `SSM*`) — GM and PHEV/EV paths, not applicable to the 2025 CR-V Hybrid.
5. To capture live reference traffic: the app enforces public-key pinning
   (`SSL Pinning is enabled, Host not in PINNED list`) — use frida/objection on a
   rooted/jailbroken device plus mitmproxy.

## 9. Evidence index

- Host table: `SharedFramework __data 0x233c68–0x234278` (5 env copies).
- Path tables: `SharedFramework __data 0x23b600–0x247000` (Swift small/large string
  slots; large-string data at `ptr+32`, chained-fixup offset = low 36 bits).
- API enum: `__cstring 0x1c19b9+`; config builder `FUN_00085fa0`; URL builder
  `NetworkResource.urlPathForAPI`.
- Auth keys: `__data 0x25b890–0x25bd40`; headers `X-Honda-wl-authorization` `0x1cc880`,
  `Request-Timestamp` `0x1c22a0`; VinServiceAuth logs `0x1d1320`.
- CIG ctors: symtab `COMPostCIG*` (e.g. `COMPostCIGLockUnlock…cfc` @ `0xb41d0`).
- DigitalTwin keys: main binary `__data 0x1018a9948+`; GDO keys `0x101895090+`,
  `0x1018bd2d8+`.
- MQTT: classes `HNMQTTManager`, `MQTTSubscriptionManager`, `MQTTResolver`,
  `GetSignedTokenC`; Core Data predicate `vin == %@ AND topicName == %@ AND serviceRequestId == %@`.
