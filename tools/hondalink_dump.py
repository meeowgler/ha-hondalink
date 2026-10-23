#!/usr/bin/env python3
"""Dump what the HondaLink cloud API returns for your car.

Reuses the ha-hondalink integration's own api.py, so the login and requests are
exactly what Home Assistant sends. Read-only by default: nothing is sent to the
car unless you pass --wake.

Writes, into ./hondalink_dump_<timestamp>/ :
  vehicles.json         GET /REST/NGT/MyVehicle/1.0           (vehicle list, may include feature flags)
  vehicle.json          GET /REST/NGT/MyVehicle/1.0/{VIN}     (single vehicle record)
  profile.json          GET /REST/NGT/myProfile/1.0/{VIN}     (account / subscription profile)
  dashboard.json        POST /REST/NGT/CIG/dbd/latest/{VIN}   (the status data the integration polls)
  wake_result.json      only with --wake (POST /REST/NGT/CIG/dbd/async, asks the car for fresh data)
  probe_<name>.json     only with --probe: read-only endpoints found in the iOS app (see
                        docs/hondalink-protocol/) that answered with JSON
  probe_summary.txt     only with --probe: every URL tried, its HTTP status and what came back
  fields.txt            every leaf field from all of the above as "path = value", easiest to read
  errors.txt            any request that failed, with the error message

Everything is redacted (tokens, PIN, password, email, VIN, GPS, names, addresses,
phone numbers) unless you pass --raw, which ALSO writes unredacted copies to a
raw/ subfolder. Never share the raw/ folder.

Usage:
  pip install aiohttp
  python3 hondalink_dump.py --integration-dir /path/to/hondalink
  python3 hondalink_dump.py --integration-dir ... --vin <VIN> --wake
  python3 hondalink_dump.py --integration-dir ... --probe

--probe tries 17 read-only endpoints on Honda's servers, using the HTTP method the app
uses where it is known. None of them is a vehicle command: nothing reaches the car.
Paths and methods come from the app, but the host and VIN placement are guesses, so
expect most attempts to fail; probe_summary.txt shows which ones didn't.

Credentials come from HONDALINK_EMAIL / HONDALINK_PASSWORD (and optionally
HONDALINK_VIN), or you are prompted. The PIN is not needed for these reads.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib
import json
import os
import re
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

DEFAULT_DIRS = [
    "/config/custom_components/hondalink",  # HA terminal / container
    "/homeassistant/custom_components/hondalink",  # Advanced SSH app on HAOS
    "./custom_components/hondalink",
    "./ha-hondalink",  # a git clone of the repo
    ".",
]

# Keys whose values are replaced outright, matched case-insensitively.
# Substring match (safe because these words don't hide inside useful field names):
SECRET_KEY_PARTS = (
    "token", "password", "passwd", "secret", "client_reg_key", "clientregkey",
    "authorization", "cookie", "session", "hidas", "ident", "userid", "user_id",
    "email", "phone", "mobile", "address", "street", "postal", "zipcode",
    "firstname", "lastname", "first_name", "last_name", "fullname", "nickname",
    "latitude", "longitude", "device", "plate", "license",
)
# Exact match only ("city" would otherwise hit velocity/batteryCapacity, "pin" hits spinner):
SECRET_KEYS_EXACT = {"pin", "vin", "lat", "lon", "lng", "city", "zip", "state_code", "name"}
# Keys that contain a secret-looking part but are safe and useful to keep.
SAFE_KEYS = {
    "plugstatus", "lightstate", "openstate", "closestate", "lockstate",
    "pressuredata", "deviceid_type", "commandstatus",
}
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")

class Probe(NamedTuple):
    name: str
    path: str  # appended to each of PROBE_HOSTS, unless it is a full URL
    method: str = "GET"  # from the app's operation class (COMGet*/COMPost*), deep-dive.md section 7
    post_on_405: bool = False  # method unknown: also try POST if the server refuses GET
    vin_style: str = "path"  # how to add the VIN: "path" (/VIN) or "query" (?vin=VIN)


# Read-only endpoints from the HondaLink iOS app (docs/hondalink-protocol/) that could give
# this integration something new. The app's tables don't pin down which host each path is
# on, so each is tried on both Honda web-service hosts, with and without the VIN.
PROBE_HOSTS = ("https://wsc.hondaweb.com", "https://ws.hondaweb.com")
PROBES: tuple[Probe, ...] = (
    Probe("feature_list", "/REST/NGT/FeatureList/1.0/"),
    Probe("feature_list_cbo", "/REST/NGT/CBO/FeatureList/1.0/"),
    Probe("vehicle_entitlement", "/REST/NGT/Enrollment/VehicleEntitlement/2.0", "POST"),
    Probe("customer_entitlement", "/REST/NGT/EnrollmentCustomerEntitlement/1.0", "POST"),
    Probe("telematics_profile", "/REST/NGT/VTP/telematics/profile"),
    Probe("account_status", "/REST/NGT/CSAccountStatus/1.0"),
    Probe("trip_scores", "/REST/NGT/CVP/TripScores/1.0"),
    Probe("driving_scores", "/REST/NGT/CVP/DrivingScores/1.0"),
    Probe("activity_log", "/REST/NGT/ActivityLog/1.0/"),
    # Inbox: Maintenance Minder, warning and recall messages (deep-dive.md section 5).
    Probe("vehicle_messages", "/REST/NGT/VehicleMessage/Details/1.0/"),
    Probe("vehicle_messages_query", "/REST/NGT/VehicleMessage/Details/1.0/", vin_style="query"),
    Probe("vehicle_location", "/REST/NGT/VDS/vehicle/location", post_on_405=True),
    Probe("fota_campaigns", "/REST/NGT/FOTAvehiclesGetVincampaigns/1.0"),
    Probe("stolen_vehicle_status", "/REST/NGT/SVLGetStatus/1.0"),
    Probe("parts_health", "/REST/SPT/VehiclePartsHealth/1.0", post_on_405=True),
    Probe("garage_devices", "/REST/GDO/devices/1.0"),
    # Honda's public US recall lookup (service maintenanceRecallUs); no login needed.
    # GET ?vin= returns recalls_response.Response.Recall (a POST gets no recall data).
    Probe("recalls", "https://content.services.honda.com/recalls/GetRecalls.ashx", vin_style="query"),
)
# Probes whose "name" fields are feature/campaign names, not people, so worth keeping.
PROBES_KEEP_NAME = {"feature_list", "feature_list_cbo", "vehicle_entitlement", "fota_campaigns"}


def load_api(integration_dir: Path):
    """Import const.py and api.py as a package WITHOUT running __init__.py.

    __init__.py imports homeassistant, which isn't installed on a laptop; api.py
    and const.py only need aiohttp.
    """
    for name in ("api.py", "const.py"):
        if not (integration_dir / name).is_file():
            raise SystemExit(f"{integration_dir} has no {name}. Point --integration-dir at the hondalink folder.")
    pkg = types.ModuleType("hondalink_dump_pkg")
    pkg.__path__ = [str(integration_dir)]
    sys.modules["hondalink_dump_pkg"] = pkg
    return importlib.import_module("hondalink_dump_pkg.api")


def find_integration_dir(arg: str | None) -> Path:
    candidates = [arg] if arg else DEFAULT_DIRS
    for cand in candidates:
        path = Path(cand).expanduser().resolve()
        if (path / "api.py").is_file() and (path / "const.py").is_file():
            return path
    raise SystemExit(
        "Couldn't find the integration's api.py. Pass --integration-dir pointing at the folder "
        "that contains api.py and const.py (e.g. /config/custom_components/hondalink, or a git "
        "clone of https://github.com/daviddelahoz/ha-hondalink)."
    )


def is_secret_key(key: str) -> bool:
    k = key.lower().replace("-", "").replace(".", "")
    if k in SAFE_KEYS:
        return False
    return k in SECRET_KEYS_EXACT or any(part in k for part in SECRET_KEY_PARTS)


def redact(value: Any, vins: set[str], keep: frozenset[str] = frozenset()) -> Any:
    if isinstance(value, dict):
        return {k: ("**REDACTED**" if is_secret_key(str(k)) and str(k) not in keep and v not in (None, "", [], {})
                    else redact(v, vins, keep))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, vins, keep) for v in value]
    if isinstance(value, str):
        out = value
        for vin in vins:
            out = out.replace(vin, "VIN-REDACTED")
        return VIN_RE.sub("VIN-REDACTED", out)
    return value


def leaf_lines(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        if not value:
            return [f"{prefix} = {{}}"]
        lines: list[str] = []
        for k, v in value.items():
            lines += leaf_lines(v, f"{prefix}.{k}" if prefix else str(k))
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix} = []"]
        lines = []
        for i, v in enumerate(value):
            lines += leaf_lines(v, f"{prefix}[{i}]")
        return lines
    return [f"{prefix} = {json.dumps(value, ensure_ascii=False)}"]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")


def _body_summary(payload: Any) -> str:
    if isinstance(payload, dict):
        status = payload.get("status") or (payload.get("Header") or {}).get("ErrorCode")
        keys = ", ".join(list(payload)[:8])
        return f"status={status!r} keys=[{keys}]" if status is not None else f"keys=[{keys}]"
    if isinstance(payload, list):
        return f"list of {len(payload)}"
    return type(payload).__name__


def _failed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or "").lower()
    return status in ("failure", "failed", "error") or bool((payload.get("Header") or {}).get("ErrorCode"))


async def probe_endpoints(session, api, vin: str | None, hosts=None, probes=PROBES, delay: float = 0.3):
    """Try each read-only endpoint; return ({name: response}, [summary lines], {name: raw text})."""
    hosts = hosts or PROBE_HOSTS
    found: dict[str, Any] = {}
    raw_text: dict[str, str] = {}
    lines: list[str] = []
    for name, path, first_method, post_on_405, vin_style in probes:
        hit = False
        for host in ("",) if path.startswith("http") else hosts:
            for suffix in ("", vin) if vin else ("",):
                if not suffix:
                    url = host + path
                elif vin_style == "query":
                    url = f"{host}{path}?vin={suffix}"
                else:
                    url = f"{host}{path.rstrip('/')}/{suffix}"
                shown = url.replace(vin, "{VIN}") if vin else url
                methods = [first_method]
                while methods:
                    method = methods.pop(0)
                    await api.async_ensure_login()
                    body = {"device": vin, "vin": vin} if method == "POST" and vin else None
                    try:
                        async with session.request(method, url, headers=api._api_headers(), json=body) as resp:
                            text = await resp.text()
                            ctype = resp.headers.get("Content-Type", "")
                            status = resp.status
                    except Exception as err:  # noqa: BLE001  (DNS errors etc. are just a miss)
                        lines.append(f"{name:22} {method:4} {shown} -> {type(err).__name__}")
                        continue
                    try:
                        payload: Any = json.loads(text) if text else None
                    except json.JSONDecodeError:
                        payload = None
                    if payload is not None:
                        info = _body_summary(payload)
                    else:
                        title = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
                        info = f"{ctype or 'no content-type'}, {len(text)} chars"
                        if title:
                            info += f", title={title.group(1).strip()[:60]!r}"
                    lines.append(f"{name:22} {method:4} {shown} -> HTTP {status} {info}")
                    if status == 405 and method == "GET" and post_on_405:
                        methods.append("POST")
                    if 200 <= status < 300 and text:
                        record = {"method": method, "url": shown, "http_status": status, "content_type": ctype}
                        if payload is not None:
                            record["response"] = payload
                        else:
                            # Non-JSON (probably a web page): keep it out of the shareable dump.
                            record["response_chars"] = len(text)
                            raw_text[name] = text
                        if name not in found or (_failed(found[name].get("response")) and not _failed(payload)):
                            found[name] = record
                        hit = hit or (payload is not None and not _failed(payload))
                    await asyncio.sleep(delay)
                if hit:
                    break
            if hit:
                break
    return found, lines, raw_text


async def run(args: argparse.Namespace) -> int:
    integration_dir = find_integration_dir(args.integration_dir)
    api_mod = load_api(integration_dir)
    import aiohttp  # noqa: PLC0415  (imported late so a missing integration dir errors first)

    email = os.environ.get("HONDALINK_EMAIL") or input("HondaLink email: ").strip()
    password = os.environ.get("HONDALINK_PASSWORD") or getpass.getpass("HondaLink password: ")
    vin = args.vin or os.environ.get("HONDALINK_VIN") or None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out or f"hondalink_dump_{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "raw"
    if args.raw:
        raw_dir.mkdir(exist_ok=True)

    results: dict[str, Any] = {}
    errors: list[str] = []
    probe_lines: list[str] = []
    probe_raw_text: dict[str, str] = {}

    async with aiohttp.ClientSession() as session:
        api = api_mod.HondaLinkAPI(session, email=email, password=password, pin=None, vin=vin)

        async def grab(name: str, coro_fn):
            try:
                results[name] = await coro_fn()
                print(f"  ok    {name}")
            except Exception as err:  # noqa: BLE001  (we want every failure recorded, not raised)
                errors.append(f"{name}: {type(err).__name__}: {err}")
                print(f"  FAIL  {name}: {type(err).__name__}")

        print("Logging in…")
        try:
            await api.async_login()
        except Exception as err:  # noqa: BLE001
            print(f"Login failed: {type(err).__name__}: {redact(str(err), set())}")
            return 1

        await grab("vehicles", api.async_get_vehicles)
        if not vin:
            vehicles = results.get("vehicles") or []
            vins = [v.get("vin") or v.get("VIN") for v in vehicles if isinstance(v, dict)]
            vins = [v for v in vins if v]
            if len(vins) == 1:
                vin = vins[0]
            elif len(vins) > 1:
                print(f"Found {len(vins)} vehicles; using the first. Pass --vin to choose another.")
                vin = vins[0]
            else:
                print("No VIN discovered. Pass --vin (or HONDALINK_VIN) and run again.")
        if vin:
            api.vin = vin
            await grab("vehicle", lambda: api.async_get_vehicle_by_vin(vin))
            await grab("profile", lambda: api.async_get_profile(vin))
            if args.wake:
                print("Asking the car for fresh data (--wake), this can take up to a minute…")

                async def wake():
                    res = await api.async_request_dashboard_update(vin)
                    return {"request_id": res.request_id, "response": res.response}

                await grab("wake_result", wake)
            await grab("dashboard", lambda: api.async_get_dashboard_latest(vin))
        if args.probe:
            print("Probing read-only endpoints from the app (--probe), about a minute…")
            try:
                found, probe_lines, probe_raw_text = await probe_endpoints(session, api, vin)
            except Exception as err:  # noqa: BLE001
                errors.append(f"probe: {type(err).__name__}: {err}")
                print(f"  FAIL  probe: {type(err).__name__}")
            else:
                for name, record in found.items():
                    results[f"probe_{name}"] = record
                    print(f"  ok    probe_{name}  (HTTP {record['http_status']} {record['method']} {record['url']})")
                print(f"  {len(found)} of {len(PROBES)} probed endpoints answered; see probe_summary.txt")

    vins_to_hide = {vin} if vin else set()
    all_lines: list[str] = []
    for name, data in results.items():
        keep = frozenset({"name"}) if name.removeprefix("probe_") in PROBES_KEEP_NAME and name.startswith("probe_") else frozenset()
        safe = redact(data, vins_to_hide, keep)
        write_json(out / f"{name}.json", safe)
        all_lines.append(f"# ===== {name} =====")
        all_lines += leaf_lines(safe)
        all_lines.append("")
        if args.raw:
            write_json(raw_dir / f"{name}.json", data)
    (out / "fields.txt").write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    if args.probe:
        (out / "probe_summary.txt").write_text(
            "\n".join(str(redact(line, vins_to_hide)) for line in probe_lines) + "\n", encoding="utf-8"
        )
        if args.raw:
            for name, text in probe_raw_text.items():
                (raw_dir / f"probe_{name}.html").write_text(text, encoding="utf-8")
    if errors:
        (out / "errors.txt").write_text("\n".join(str(redact(e, vins_to_hide)) for e in errors) + "\n", encoding="utf-8")

    print(f"\nSaved to {out.resolve()}")
    print("  Start with fields.txt. Values of null, \"\" or \"--\" are fields Honda knows about but isn't filling for your car.")
    if args.raw:
        print("  raw/ holds UNREDACTED copies (VIN, GPS, account details). Don't share it.")
    return 0 if results else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump HondaLink API responses (read-only by default).")
    parser.add_argument("--integration-dir", help="Folder containing the integration's api.py and const.py")
    parser.add_argument("--vin", help="VIN to query (otherwise discovered from your account)")
    parser.add_argument("--wake", action="store_true",
                        help="Ask the car to report fresh data first (same as the Refresh button; pings the car)")
    parser.add_argument("--probe", action="store_true",
                        help="Also try read-only endpoints found in the iOS app (no vehicle commands)")
    parser.add_argument("--raw", action="store_true", help="Also write unredacted copies to raw/")
    parser.add_argument("--out", help="Output folder (default: hondalink_dump_<timestamp>)")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
