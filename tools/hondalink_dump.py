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
  fields.txt            every leaf field from all of the above as "path = value", easiest to read
  errors.txt            any request that failed, with the error message

Everything is redacted (tokens, PIN, password, email, VIN, GPS, names, addresses,
phone numbers) unless you pass --raw, which ALSO writes unredacted copies to a
raw/ subfolder. Never share the raw/ folder.

Usage:
  pip install aiohttp
  python3 hondalink_dump.py --integration-dir /path/to/hondalink
  python3 hondalink_dump.py --integration-dir ... --vin <VIN> --wake

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
from typing import Any

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


def redact(value: Any, vins: set[str]) -> Any:
    if isinstance(value, dict):
        return {k: ("**REDACTED**" if is_secret_key(str(k)) and v not in (None, "", [], {}) else redact(v, vins))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, vins) for v in value]
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

    vins_to_hide = {vin} if vin else set()
    all_lines: list[str] = []
    for name, data in results.items():
        safe = redact(data, vins_to_hide)
        write_json(out / f"{name}.json", safe)
        all_lines.append(f"# ===== {name} =====")
        all_lines += leaf_lines(safe)
        all_lines.append("")
        if args.raw:
            write_json(raw_dir / f"{name}.json", data)
    (out / "fields.txt").write_text("\n".join(all_lines) + "\n", encoding="utf-8")
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
    parser.add_argument("--raw", action="store_true", help="Also write unredacted copies to raw/")
    parser.add_argument("--out", help="Output folder (default: hondalink_dump_<timestamp>)")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
