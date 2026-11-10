"""Tests of catalog_ci.py's publishing, against the tools of an Ampify checkout.

    AMPIFY=<Ampify checkout> python3 -m unittest discover -s .github/scripts -v

AMPIFY defaults to an `ampify` folder beside this repository's. Standard library only.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog_ci  # noqa: E402

AMPIFY = os.environ.get("AMPIFY", os.path.join(HERE, "..", "..", "..", "ampify"))
RAW = catalog_ci.RAW


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="catalog-ci-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "packages"))
        self.catalog = os.path.join(self.root, "catalog.json")
        self.write_catalog([])
        self.pack = catalog_ci.import_tools(AMPIFY)
        self.old_root = catalog_ci.ROOT
        catalog_ci.ROOT = self.root
        self.addCleanup(setattr, catalog_ci, "ROOT", self.old_root)

    def write_catalog(self, entries):
        with open(self.catalog, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"catalogVersion": 1, "extensions": entries}, handle)

    def entries(self):
        with open(self.catalog, encoding="utf-8") as handle:
            return json.load(handle)["extensions"]

    def source(self, version, min_ampify=None):
        folder = os.path.join(self.root, "sources", "demo")
        shutil.rmtree(folder, True)
        os.makedirs(folder)
        manifest = {"id": "demo", "name": "Demo", "version": version, "kind": "extension", "author": "Shirowwww",
                    "description": "A test element.", "kitApi": "1.0", "main": "main.js"}
        if min_ampify:
            manifest["minAmpify"] = min_ampify
        with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle)
        with open(os.path.join(folder, "main.js"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write('Ampify.log("ok");\n')
        return folder

    def test_a_version_for_a_newer_ampify_leaves_the_entry_to_the_older_ones(self):
        self.source("1.0.0")
        catalog_ci.publish_one(self.pack, "demo", self.catalog)
        self.source("1.1.0", min_ampify="1.3.0")
        self.assertEqual(catalog_ci.publish_one(self.pack, "demo", self.catalog), "demo 1.1.0")
        [entry] = self.entries()
        self.assertEqual(entry["version"], "1.0.0")
        self.assertNotIn("minAmpify", entry)
        self.assertEqual([(item["version"], item["minAmpify"]) for item in entry["newer"]], [("1.1.0", "1.3.0")])

    def test_a_version_without_min_ampify_replaces_the_entry(self):
        self.source("1.0.0")
        catalog_ci.publish_one(self.pack, "demo", self.catalog)
        self.source("1.0.1")
        catalog_ci.publish_one(self.pack, "demo", self.catalog)
        [entry] = self.entries()
        self.assertEqual(entry["version"], "1.0.1")
        self.assertNotIn("newer", entry)

    def test_an_archive_packed_elsewhere_with_the_same_files_is_already_published(self):
        folder = self.source("1.0.0")
        archive = os.path.join(self.root, "packages", "demo-1.0.0.zip")
        # Compressed, as the archives packed on Windows were: other bytes, the same files.
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name in ("main.js", "manifest.json"):
                bundle.write(os.path.join(folder, name), name)
        self.assertIsNone(catalog_ci.publish_one(self.pack, "demo", self.catalog))

    def test_an_archive_with_other_files_under_the_same_version_is_refused(self):
        self.source("1.0.0")
        with zipfile.ZipFile(os.path.join(self.root, "packages", "demo-1.0.0.zip"), "w") as bundle:
            bundle.writestr("main.js", "changed\n")
        with self.assertRaises(self.pack.PackError):
            catalog_ci.publish_one(self.pack, "demo", self.catalog)


class TwoCatalogTests(PublishTests):
    def setUp(self):
        super().setUp()
        self.legacy = os.path.join(self.root, "catalog-legacy.json")
        with open(self.legacy, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"catalogVersion": 1, "extensions": []}, handle)

    def legacy_entries(self):
        with open(self.legacy, encoding="utf-8") as handle:
            return json.load(handle)["extensions"]

    def test_a_version_for_ampify_1_3_stays_out_of_the_old_catalog(self):
        self.source("1.0.0", min_ampify="1.3.0")
        self.assertEqual(catalog_ci.publish_one(self.pack, "demo", self.catalog, self.legacy), "demo 1.0.0")
        self.assertEqual([entry["version"] for entry in self.entries()], ["1.0.0"])
        self.assertEqual(self.legacy_entries(), [])

    def test_a_version_older_releases_take_goes_to_both_catalogs(self):
        self.source("1.0.0")
        catalog_ci.publish_one(self.pack, "demo", self.catalog, self.legacy)
        [entry] = self.legacy_entries()
        self.assertEqual(entry["version"], "1.0.0")
        self.assertEqual(entry, self.entries()[0])

    def test_the_old_catalog_keeps_its_version_when_a_1_3_one_arrives(self):
        self.source("1.0.0")
        catalog_ci.publish_one(self.pack, "demo", self.catalog, self.legacy)
        self.source("1.1.0", min_ampify="1.3.0")
        catalog_ci.publish_one(self.pack, "demo", self.catalog, self.legacy)
        [old] = self.legacy_entries()
        self.assertEqual((old["version"], old.get("newer")), ("1.0.0", None))
        self.assertEqual([item["version"] for item in self.entries()[0]["newer"]], ["1.1.0"])


class CheckTests(PublishTests):
    def with_preview(self, folder):
        manifest_path = os.path.join(folder, "manifest.json")
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["preview"] = "preview.png"
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle)
        with open(os.path.join(folder, "preview.png"), "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n")

    def test_an_element_without_a_preview_is_refused(self):
        self.source("1.0.0")
        _, errors = catalog_ci.check_element(self.pack, "demo", {})
        self.assertTrue(any("preview" in error for error in errors), errors)

    def test_an_element_with_its_preview_passes(self):
        self.with_preview(self.source("1.0.0"))
        manifest, errors = catalog_ci.check_element(self.pack, "demo", {})
        self.assertIsNotNone(manifest)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
