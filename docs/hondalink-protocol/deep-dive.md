# HondaLink iOS deep-dive: commands, models, states

Static analysis of `HondaLink_5.5.2_ios_decrypted.ipa` (main binary + `SharedFramework`),
second pass. Everything below was recovered from the binaries; items marked *(inferred)*
are the only remaining judgment calls. Companion to [protocol.md](protocol.md).

## 1. Command request bodies (verified)

Dictionary keys are built as inline Swift small-strings (`MOVZ`/`MOVK` immediates), which
is why `strings` never shows them. Recovered by dataflow over the builder functions.

### Engine start — `COMPostCIGEngineStart(keys:role:)`
Builder at `HondaLink!0x100dbf614`, init call at `0x100dc10f8`. Body keys seen inline:

| key | notes |
|---|---|
| `device` | VIN |
| `pin` | 4-digit user PIN |
| `extend` | extend an already-running remote start |
| `acSetting` | climate block sent **with** start (see §3) |
| `isChanged` | Bool, whether climate settings differ from last sent |
| `vehicleControl` | control selector string |
| `command`, `commandData`, `type` | command routing fields |
| `vin` | also present |

So the iOS engine-start body is richer than the minimal `{device,pin,extend}` the
integration sends today — the app attaches climate settings to the start itself.

### Lock / unlock — `COMPostCIGLockUnlock(keys:command:messageId:role:)`
Builder at `0x100c15e04`. Body keys: `device`, `pin`. Role suffixes (inline strings,
verified): `alk` (lock), `dulk` (unlock), `NONE`. URL = `/CIG/lk/async` + `/alk` or
`/dulk` at runtime. The repo's `dulk` matches iOS exactly.

### Car finder — `COMPostVehicleLocator(keys:role:)`
Call site `0x1009a08b8`. Body keys: `device`, `pin`. Role appended to `/CIG/cfl/async`
the same way as lock.

### Send POI — `COMPostCIGSendPOI(keys:)`
Response handling at `0x100a0aba4` (`IN_PROGRESS`, `responseBody`, `errorCode`,
`errorMessage`, `vin`). Body keys not recovered statically; the working
`poiName`/`latitude`/`longitude` shape from the integration is consistent with the
redirect utility strings (`Redirect Utility: POI Name`, `Destination Coordinates`).

### Speed alert — full CRUD
- `COMPostSpeedAlerts(speedAlertKeys:vin:accountId:servReqId:)` — call `0x1003b7c38`
- `COMPutSpeedAlerts(speedAlertKeys:vin:accountId:servReqId:)` — call `0x100795e3c`
- `COMGetSpeedAlerts(vin:accountId:servReqId:)` — call `0x100b0f6bc`
- `COMGetSpeedAlertsCIG(vin:)`, `COMPostSpeedAlertCIG(speedAlertsKeys:)`

Body keys at the call sites: `customerId`, `speedKeys`, `vin`.
Speed-alert record model (reflection metadata): `name`, `enable`, `speedValue`,
`speedType`, `selectedDays`, `frequency`, `status`, `startDateTime`, `endDateTime`,
`serviceRequestId`, `sxmId`, `duration`, `dailySwitch`, `startDate`, `endDate`,
`startTime`, `endTime`, `activationSetup`, `isTargetSystemCIG`.

### Dashboard — `COMPostCIGDashboard(keys:cabinTemperature:)`
Init call `0x1004317d4`. Body keys: `device`, `onstarcid`, `filters` (array). The
`cabinTemperature:` Bool parameter adds the cabin-temp attribute to the request —
that is the `cabinTemperature: true` knob.

## 2. Command state machine and polling

Command-state enum raw values (three variants found, increasing capability):

```
new, processing, delayStart, engineStarted, done, failed
new, processing, delayStart, engineStarted, done, failed, engineStop
new, processing, delayStart, engineStarted, done, failed, engineStop, rsuInProgress, turnOnClimate
```

- still running: `new`, `processing`, `delayStart`, `engineStarted`, `rsuInProgress`
- done: `done`, `engineStop`
- failed: `failed`

State classes: `NewCIGCommandState → ProcessingCIGCommandState →
EngineStartedCIGCommandState / EngineStopCIGCommandState`, with parallel
`CIGClimate`, `SXM`, `BEV`, `Agero` families and a `DelaySXMCommandState`.

Response envelope keys (verified): `status`, `responseBody`, `errorCode`,
`errorMessage`, `message`, `success`, `failure`, `IN_PROGRESS`, `SERVICE_COMPLETED`.

Result-polling operations (SF class names; `Get` = GET):
`COMGetCIGRemoteEngineResult(servReqId:)`, `COMGetCIGLockUnlockResult(servReqId:)`,
`COMGetCIGDashboardResult(servReqId:)`, `COMGetCIGClimateResult(servReqId:commandName:)`,
`COMGetCIGChargeResult(servReqId:commandName:)`, `COMGetCIGSendPOI(cigServiceReqId:)`,
`COMGetCIGGeoFence(vin:)`, `COMGetCIGActivityLog(vin:)`.

Polling knobs live in `HNDataSourceHostsAndPaths.getConfigurableParameters()`
(SharedFramework `0x5b590`): per-command `retryCount`, `timeInterval`, `maxCount`,
`timeoutInterval`, `expiryInterval`. Numeric constants seen in the builder: `20`,
`60`, `1800`, `90` (mqtt timeout), `30`, `24` (tnc expiry hours), `0.33`, `50.0`.
Exact per-command pairing not statically resolvable (values are runtime params).

## 3. Remote climate (the CR-V Hybrid path)

- apiName `cabinTemperatureAsync` → `/CIG/IdleCabinTemperature/async/` (path table).
- Operation class: `PostRemoteEngineStartCIGClimateOperation`; command class
  `StartEngineCIG` / `StartEngineCIGClimate`; invoker `RemoteClimateCommandInvoker`.
- MQTT command type constant: `CLIMATE_SETTING_ASYNC`.
- UI stack: `HNCIGClimateRemote{Builder,Interactor,Presenter,Utility,ViewController}`,
  views `CIGClimateRemoteInitialView`, `CIGClimateRemoteSettingView`,
  `CIGClimateRemoteExtendedView`, `CIGClimateTurnOnView`, `CIGClimateStopView`,
  `CIGClimateHybridSettingView`, `CIGClimateSettingGradientSlider`.
- `CIGClimateRemoteViewModel` fields (reflection metadata): `temp`, `minTemp`,
  `maxTemp`, `sliderValue`, `tempUnit`, `scheduledClimateTime`, `currentState`,
  `previousState`, `enginOnOff`, `acDefrosterFront`, `acDefrosterRear`,
  `acDriverHeated`, `acPassengerHeater`, `acHeaterSteering`, `acVentedDriver`,
  `acVentedPassenger`, `temperatureValue`, `featureList`, `autoOff`,
  `climateSetting`, `desiredCabinTemp`, `insideTemp`, `mins`, `delayEnginStartTitle`,
  `action`, `timerInfo`, `isTimerOn`, `totalTime`, `totalRemainingTime`,
  `totalStartTime`, `engineStartTime`, `resStatus`, `isResStatusOff`,
  `isFromscheduleClimate`, `restoreFailureState`, `vin`, `targetSystem`.
- Turn-on presets (`CIGClimateTurnOnView`): `initialTemprature`, `midTemprature`,
  `higherTemprature`, `defroster`, `none` (sic — app typo).
- Hybrid setting view: `minCabinTemp`, `maxCabinTemp`, `desiredCabinTemp`,
  `tempSlider`, `showDriverPassengerView`, `isWarmerHidden`.
- Climate status enum: `acOff`, `acOn`, `pendingOn`, `pendingOff`.
- Scheduled climate: `UpdateScheduleClimateOperation`, `HybridUpdateSchedule`.

`resStatus` is a real app field (with `isResStatusOff` special-case) — but
`resTime`, `resStartCounter`, `lockState`, `openState` appear **nowhere** in the iOS
binary (strings, Swift metadata, inline). Those are Android-side names; iOS derives
lock state from DigitalTwin `doorStatus` and command state from the enum in §2.

## 4. Feature vocabulary

Internal command/feature enum (36 cases) — what the app checks before showing a
feature (`commandVariationType` on the dashboard VM):

```
start, extend, stop, lock, unLock, locate, horn, lights,
locateFMC, hornFMC, lightsFMC, sendDestination, activityLog, personalDataWipe,
geoFence, speedAlert, stopHorn, stopLights, stopHornFMC, stopLightsFMC,
startCharge, stopCharge, turnOnClimate, turnOffClimate, startSmartCharge,
stopSmartCharge, gdoStartLight, gdoStopLight, gdoOpen, gdoClose, gdoLock,
gdoUnlock, setTargetChargeLevel, climateOn, climateOff, none
```

A second 33-case enum adds `temperature`, `doorUnlock`, `trunkUnlock`, `setting`,
`steeringWheel`, `frontDefrosters`, `rearDefrosters`, `rearSideDefrosters`,
`driverSeat`, `passengerSeat`, `updateSetting`, `driverVentedSeat`,
`passengerVentedSeat`, `climateSettings`. The `*FMC` variants are the
Find-My-Car-style short commands. Feature gating from the server is numeric
(FeatureIDs `50001–50086` in `dashboard.json`/`FeatureFilterMapper.json`), not names.

## 5. Status reply models

- Inbox/notification types enum: `recall`, `maintenanceMinder`, `warningMinder`, `none`.
  Maintenance Minder messages arrive as inbox items (`COMGetVehicleMessages`), not as
  dashboard fields.
- Warning lamps: DigitalTwin attribute `warningLamps` + bundled `warningLamps.json`
  catalog (`id`, `sabCode`, `englishTitle`).
- DigitalTwin attribute list (verified contiguous block): `doorStatus`,
  `windowStatus`, `lightStatus`, `tireStatus`, `odometer`, `fuelLevel`,
  `warningLamps`, `oilLife`, `temperature`, plus EV attributes `EV CHARGE STATE`,
  `EV PLUG STATE`, `EV PLUG VOLTAGE`, `GET CHARGE MODE`, `VEHICLE RANGE`.
- Dashboard VM fields include `cabinTemp`, `selectedTemp`, `remoteEngineInfo`,
  `vehicleStatusModel`, `odoAndOilLifeData`, `fuelAndRangeData`,
  `lastUpdatedTimeData`, `climateSettingfeatureList`, `callingClimateApi`.
- Geofence model: `name`, `type`, `alertType`, `latitude`, `longitude`, `frequency`,
  `status`, `serviceRequestId`, `idValue`, `sxmId`, `duration`, `dailySwitch`,
  `selectedDays`, `selectedStartTime`, `selectedEndTime`, address parts, `radius`,
  `scheduleDict`, `unit`, `enable`, `isTargetCIG`, `geofenceEnabledStatus`.
- Trip model: `locationName`, `duration`, `energyUsed`, `date`, `sessionId`,
  `locationId`.

## 6. Service → host (Honda production)

| service key | host |
|---|---|
| `cig` | `https://wsc.hondaweb.com/REST/CIG` |
| `ngtjwt` | `https://wsc.hondaweb.com/REST/CIG` |
| `ngtcig` | `https://wsc.hondaweb.com/REST/NGT` (CIG via NGT proxy — the repo's URL form) |
| `ngt` | `https://ws.hondaweb.com/REST/NGT` |
| `ngtCloud` | `https://wsc.hondaweb.com/REST/NGT` |
| `ngtcbo` `ngtahm` `ngtvtivtp` `ngtdealer` `ngttnc` `pinGateway` | `https://ws.hondaweb.com/REST/NGT` |
| `ngtcsm` `ngtvtivtp` `ngtoutage` `ngtscm` `ngtsvl` `ngtfota` `chargerUx` | `https://wsc.hondaweb.com/REST/NGT` |
| `ngtpush` | `https://ws.hondaweb.com/REST/NGT` |
| `hidas` | `https://identity.services.honda.com` |
| `location` | `https://location.services.honda.com` |
| `gtc` | `https://www.jp.hondalink.com/api` |
| `gdo` | `https://wsc.hondaweb.com` |
| `gdoAuth` | `https://www.myqservices.com` |
| `plugshare` | `https://api.plugshare.com` |
| `maintenanceRecallUs` | `https://content.services.honda.com/recalls/GetRecalls.ashx` |
| `maintenanceRecallCa` | `https://webservices.honda.ca/VinRecall/VinRecallServiceREST.svc/` |

All `/CIG/*` apiNames resolve under `cig` (or `ngtcig` via proxy). `CBO`, `GW`,
`CVP`, `ActivityLog`, `SSO` paths live in the NGT-family tables.

## 7. Methods

HTTP method is encoded in the SharedFramework operation class name: `COMGet*` = GET,
`COMPost*` = POST, `COMPut*` = PUT, `COMDelete*` = DELETE. Full catalog (171
operations) in [com-classes.txt](com-classes.txt). CR-V-relevant subset:

| operation | method | apiName/path |
|---|---|---|
| `COMPostCIGDashboardLatest` | POST | `/CIG/dbd/latest` |
| `COMPostCIGDashboard` | POST | `/CIG/dbd/async` |
| `COMGetCIGDashboardResult` | GET | `/CIG/dbd/results` |
| `COMPostCIGEngineStart` | POST | `/CIG/eng/async` + role |
| `COMPostCIGEngineStop` | POST | `/CIG/eng/async/sop` |
| `COMGetCIGRemoteEngineResult` | GET | `/CIG/eng/results` |
| `COMPostCIGLockUnlock` | POST | `/CIG/lk/async` + role |
| `COMGetCIGLockUnlockResult` | GET | `/CIG/lk/results` |
| `COMPostExecuteHornCommand` / `COMPostHornLight` | POST | `/CIG/cfhl/async` |
| `COMPostVehicleLocator` | POST | `/CIG/cfl/async` + role |
| `COMPostCIGSendPOI` | POST | `/CIG/pi/async` |
| `COMPostCIGGeoFence` / `COMGetCIGGeoFence` | POST/GET | `/CIG/gefe/async`, `/CIG/gefe/results` |
| `COMPost/Put/GetSpeedAlerts` | POST/PUT/GET | `/CIG/spal/async`, `/CIG/spal/results` |
| `COMGetFeatureList` | GET | `/CBO/FeatureList/1.0/` |
| `COMGetActivityLog` / `COMGetCIGActivityLog` | GET | `/ActivityLog/1.0/`, CIG twin |
| `COMGetVehicleMessages` | GET | inbox (MM/warning/recall) |
| `COMGetDrivingScores` | GET | `/CVP/TripScores` |
| `COMPostLatestVehicleData` | POST | `/GW/VinService/GetLatestVehicleData` |
| `COMReissueToken(clientKeys:)` | POST | `/hidas/rs/token/reissue` |

## 8. Token reissue

`COMReissueToken` has one ivar: `clientKeys: [String:AnyObject]?` — the same
`clientKeys` dict pattern as `COMPostUserAuthenticate`, `COMPostSignOut`,
`COMPostClientRegister`, `COMPostGenerateSecondaryToken`. Token endpoints:
`/hidas/rs/token/generate`, `/hidas/rs/token/generate/shortlive`,
`/hidas/rs/token/reissue`. The dict is assembled in the login layer upstream of any
call site we could pin statically, so exact field names (e.g. `refreshToken` vs
`shortlivedToken`) are not confirmed from the binary; the repo's current
reissue-by-login flow remains the safe path.

## 9. Not found in the iOS binary (negative results)

- `resTime`, `resStartCounter`, `lockState`, `openState` — absent everywhere.
- No iOS command class for OnStar climate (`ClimateAsync`, `getClimateStatus`) —
  those apiNames exist for OnStar-equipped models only.
- FeatureList gating is numeric FeatureIDs, not string names.
- MQTT topic templates are Swift-interpolated, not static strings.
