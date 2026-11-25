#!/usr/bin/env python3
"""Generate a source for the official LiveContainer + SideStore Nightly IPA."""

import hashlib
import io
import json
import os
import plistlib
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


UPSTREAM = "https://github.com/LiveContainer/LiveContainer"
RELEASE_API = "https://api.github.com/repos/LiveContainer/LiveContainer/releases/tags/nightly"
IPA_NAME = "LiveContainer+SideStore.ipa"
METADATA_NAME = "apps_nightly.json"
SOURCE_PATH = Path(__file__).with_name("source.json")
APP_NAME = "LiveContainer + SideStore (Nightly)"
ICON = "https://raw.githubusercontent.com/LiveContainer/LiveContainer/main/screenshots/AppIcon1024.png"
APP_PLIST = re.compile(r"Payload/[^/]+\.app/Info\.plist")
EXTENSION_PLIST = re.compile(r"Payload/[^/]+\.app/PlugIns/[^/]+\.appex/Info\.plist")


def fetch(url, *, release_api=False):
    headers = {"User-Agent": "livecontainer-altsource", "Cache-Control": "no-cache"}
    if release_api:
        headers["Accept"] = "application/vnd.github+json"
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=60) as response:
        return response.read()


def named_asset(release, name):
    return next(
        (asset for asset in release["assets"] if asset["name"] == name and asset["state"] == "uploaded"),
        None,
    )


def download_asset(asset):
    url = asset["browser_download_url"]
    expected_url = f'{UPSTREAM}/releases/download/nightly/{asset["name"]}'
    if unquote(url) != expected_url:
        raise ValueError(f'Unexpected download URL for {asset["name"]}')
    data = fetch(url)
    sha256 = hashlib.sha256(data).hexdigest()
    if len(data) != asset["size"] or (
        asset.get("digest") and asset["digest"].lower() != f"sha256:{sha256}"
    ):
        raise ValueError(f'{asset["name"]} differs from the GitHub release asset. Retry after publication.')
    return data, sha256


def read_ipa(data):
    with ZipFile(io.BytesIO(data)) as ipa:
        paths = ipa.namelist()
        main_paths = [path for path in paths if APP_PLIST.fullmatch(path)]
        if len(main_paths) != 1:
            raise ValueError("Expected one top-level app Info.plist in the IPA")
        main_plist = plistlib.loads(ipa.read(main_paths[0]))
        privacy = {
            key: value
            for path in sorted(paths)
            if EXTENSION_PLIST.fullmatch(path)
            for key, value in plistlib.loads(ipa.read(path)).items()
            if "UsageDescription" in key and isinstance(value, str)
        }
    privacy.update({
        key: value for key, value in main_plist.items()
        if "UsageDescription" in key and isinstance(value, str)
    })
    for key in ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion", "MinimumOSVersion"):
        if not isinstance(main_plist.get(key), str) or not main_plist[key].strip():
            raise ValueError(f"Missing or invalid {key} in the main app Info.plist")
    return main_plist, privacy


def asset_filename(url):
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1])


def build_source(release, metadata, asset, ipa, sha256):
    info, privacy = read_ipa(ipa)
    bundle_id = info["CFBundleIdentifier"]
    upstream_apps = [app for app in metadata["apps"] if app.get("bundleIdentifier") == bundle_id]
    # Prefer the combo listing if upstream adds one. The standalone listing supplies
    # shared artwork and permissions only. All version fields come from the combo release.
    upstream_app = next(
        (app for app in upstream_apps if any(
            asset_filename(entry.get("downloadURL", "")) == IPA_NAME
            for entry in [app, *app.get("versions", [])]
        )),
        upstream_apps[0] if upstream_apps else None,
    )
    if upstream_app is None:
        raise ValueError(f"No upstream app metadata for {bundle_id}")
    permissions = upstream_app["appPermissions"]
    date = release["published_at"]
    if datetime.fromisoformat(date).utcoffset() is None:
        raise ValueError("GitHub published_at must include a timezone")
    version = {
        "version": info["CFBundleShortVersionString"],
        "buildVersion": info["CFBundleVersion"],
        "date": date,
        "localizedDescription": (release.get("body") or "").strip(),
        "downloadURL": asset["browser_download_url"],
        "size": len(ipa),
        "sha256": sha256,
        "minOSVersion": info["MinimumOSVersion"],
    }
    app = {
        "name": APP_NAME,
        "bundleIdentifier": bundle_id,
        "developerName": upstream_app["developerName"],
        "subtitle": "LiveContainer with SideStore built in.",
        "localizedDescription": "Run iOS apps inside LiveContainer and use the bundled SideStore to install and refresh apps.",
        "iconURL": upstream_app["iconURL"],
        "tintColor": upstream_app.get("tintColor", "#0784FC"),
        "category": "utilities",
        "screenshotURLs": upstream_app.get("screenshotURLs", []),
        "appPermissions": {
            "entitlements": permissions["entitlements"],
            "privacy": dict(sorted((permissions["privacy"] | privacy).items())),
        },
        "versions": [version],
    }
    return {
        "name": APP_NAME,
        "identifier": "io.github.saki3525.livecontainer-altsource",
        "subtitle": "The combined Nightly build of LiveContainer and SideStore.",
        "description": "An independently maintained source for the official LiveContainer + SideStore Nightly IPA.",
        "website": UPSTREAM,
        "iconURL": ICON,
        "tintColor": "#0784FC",
        "featuredApps": [bundle_id],
        "apps": [app],
        "news": [],
    }


def write_source(source, output):
    data = (json.dumps(source, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if output.exists() and output.read_bytes() == data:
        return False
    # Keep the previous source intact if validation or a write fails.
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        temporary_path.write_bytes(data)
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return True


def main():
    try:
        release = json.loads(fetch(RELEASE_API, release_api=True))
        asset = named_asset(release, IPA_NAME)
        metadata_asset = named_asset(release, METADATA_NAME)
        if release["draft"] or asset is None or metadata_asset is None:
            raise ValueError("Nightly Release is missing an uploaded IPA or apps_nightly.json")
        metadata, _ = download_asset(metadata_asset)
        ipa, sha256 = download_asset(asset)
        source = build_source(release, json.loads(metadata), asset, ipa, sha256)
        latest = json.loads(fetch(RELEASE_API, release_api=True))
        if any(latest[key] != release[key] for key in ("id", "updated_at")) or any(
            named_asset(latest, item["name"]) != item for item in (asset, metadata_asset)
        ):
            raise ValueError("Nightly Release changed during the download. Retry after publication.")
        changed = write_source(source, SOURCE_PATH)
    except (OSError, URLError, ValueError, KeyError, TypeError, BadZipFile, plistlib.InvalidFileException) as error:
        print(f"Could not refresh source.json: {error}", file=sys.stderr)
        return 1
    version = source["apps"][0]["versions"][0]
    status = "Updated" if changed else "Unchanged"
    print(f'{status}: {version["version"]} (build {version["buildVersion"]}), {version["size"]} bytes')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
