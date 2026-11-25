import hashlib
import io
import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import generate


BUNDLE_ID = "com.kdt.livecontainer"
COMBO_URL = f"{generate.UPSTREAM}/releases/download/nightly/LiveContainer%2BSideStore.ipa"


def ipa_fixture():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("Payload/LiveContainer.app/Info.plist", plistlib.dumps({
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleShortVersionString": "3.8.14",
            "CFBundleVersion": "0092",
            "MinimumOSVersion": "15.0",
            "NSAlarmKitUsageDescription": "Allow guest apps to use alarms.",
        }))
        zip_file.writestr(
            "Payload/LiveContainer.app/Frameworks/SideStoreApp.framework/Info.plist",
            plistlib.dumps({"CFBundleShortVersionString": "0.7.0", "CFBundleVersion": "0700"}),
        )
    return buffer.getvalue()


class GenerateTest(unittest.TestCase):
    def test_combo_version_uses_main_plist_and_current_release(self):
        ipa = ipa_fixture()
        sha256 = hashlib.sha256(ipa).hexdigest()
        private_description = "Allow guest apps to use alarms."
        source = generate.build_source(
            {"published_at": "2026-11-20T15:07:22Z"},
            {"apps": [{
                "bundleIdentifier": BUNDLE_ID,
                "developerName": "LiveContainer Team",
                "iconURL": generate.ICON,
                "downloadURL": f"{generate.UPSTREAM}/releases/download/nightly/LiveContainer.ipa",
                "versions": [{"version": "9.9", "size": 1, "date": "2026-11-20T13:13:05Z"}],
                "appPermissions": {"entitlements": [], "privacy": {}},
            }]},
            {"browser_download_url": COMBO_URL},
            ipa,
            sha256,
        )
        app, = source["apps"]
        self.assertEqual(app["bundleIdentifier"], BUNDLE_ID)
        self.assertEqual(app["appPermissions"]["privacy"]["NSAlarmKitUsageDescription"], private_description)
        self.assertEqual(app["versions"], [{
            "version": "3.8.14",
            "buildVersion": "0092",
            "date": "2026-11-20T15:07:22Z",
            "localizedDescription": "",
            "downloadURL": COMBO_URL,
            "size": len(ipa),
            "sha256": sha256,
            "minOSVersion": "15.0",
        }])

    def test_download_rejects_mismatched_digest_even_if_size_matches(self):
        with patch.object(generate, "fetch", return_value=b"other"):
            with self.assertRaisesRegex(ValueError, "differs from the GitHub release asset"):
                generate.download_asset({
                    "name": generate.IPA_NAME,
                    "browser_download_url": COMBO_URL,
                    "size": 5,
                    "digest": f"sha256:{hashlib.sha256(b'first').hexdigest()}",
                })

    def test_write_changes_only_when_content_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "source.json"
            source = {"apps": [{"versions": [{"version": "3.8.14"}]}]}
            self.assertTrue(generate.write_source(source, output))
            before = output.stat().st_mtime_ns
            self.assertFalse(generate.write_source(source, output))
            self.assertEqual(output.stat().st_mtime_ns, before)
            self.assertEqual(json.loads(output.read_bytes()), source)


if __name__ == "__main__":
    unittest.main()
