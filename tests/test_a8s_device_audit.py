"""No hardware required: simulate an A8S removable volume and package lifecycle."""
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import a8s_device_audit as audit


class DeviceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.drive = self.base / "drive"
        (self.drive / "BOOK").mkdir(parents=True)
        (self.drive / "DIY BOOK").mkdir()

    def put(self, filename, contents=b"12345"):
        p = self.drive / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(contents)
        return p

    def test_inventory_with_realistic_names(self):
        self.put("BOOK/story.nob", b"nob-placeholder")
        self.put("DIY BOOK/1.mp3", b"ID3-audio-placeholder")
        self.put("MUSIC/general.mp3", b"IGNORE")
        self.put("other.bin", b"IGNORE")
        self.put("root_file.nod", b"candidate")
        report = audit.snapshot(self.drive)
        self.assertEqual(report["summary"]["files"], 3)
        paths = {x["path"] for x in report["files"]}
        self.assertEqual(paths, {"BOOK/story.nob", "DIY BOOK/1.mp3", "root_file.nod"})
        self.assertFalse(report["root_absolute_path_recorded"])
        self.assertTrue(report["read_only"])
        self.assertEqual(report["summary"]["candidate_packages"], 2)

    def test_same_file_unchanged_and_changed_diffs(self):
        pkg = self.put("BOOK/sample.nob", b"A")
        old = audit.snapshot(self.drive)
        pkg.write_bytes(b"B")
        self.put("BOOK/added.nod", b"C")
        cur = audit.snapshot(self.drive)
        delta = audit.difference(old, cur)
        self.assertEqual([x["path"] for x in delta["added"]], ["BOOK/added.nod"])
        self.assertEqual([x["path"] for x in delta["changed"]], ["BOOK/sample.nob"])
        self.assertEqual(delta["removed"], [])
        self.assertEqual(delta["same_size_unverified"], [])

    def test_removal(self):
        p = self.put("BOOK/old.nos", b"abc")
        old = audit.snapshot(self.drive)
        p.unlink()
        delta = audit.difference(old, audit.snapshot(self.drive))
        self.assertEqual(delta["removed"][0]["path"], "BOOK/old.nos")

    def test_hidden_and_sensitive_excluded(self):
        self.put("BOOK/.secrets/something.nod", b"skip")
        self.put("BOOK/creds.key", b"skip")
        self.put(".Trashes/files.nos", b"skip")
        self.put("BOOK/ok.nob", b"ok")
        self.assertEqual([x["path"] for x in audit.snapshot(self.drive)["files"]], ["BOOK/ok.nob"])

    def test_no_symlink(self):
        external = self.base / "private.nod"
        external.write_bytes(b"secret")
        try:
            (self.drive / "BOOK" / "linked.nod").symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertEqual(audit.snapshot(self.drive)["files"], [])

    def test_large_file_not_hashed(self):
        self.put("BOOK/large.nod", b"larger")
        row = audit.snapshot(self.drive, max_hash_mb=0)["files"][0]
        self.assertIsNone(row["sha256"])
        self.assertEqual(row["integrity"], "size_only_too_large")

    def test_uncertain_large_same_size(self):
        p = self.put("BOOK/large.nod", b"0000")
        old = audit.snapshot(self.drive, max_hash_mb=0)
        p.write_bytes(b"XXXX")
        current = audit.snapshot(self.drive, max_hash_mb=0)
        result = audit.difference(old, current)
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["same_size_unverified"], ["BOOK/large.nod"])

    def test_header_only_known_bytes(self):
        p = self.put("BOOK/test.nob", b"NOB\x00\x01\x02hello")
        result = audit.inspect_header(p, count=5)
        self.assertEqual(result["header_hex"], "4e 4f 42 00 01")
        self.assertEqual(result["header_ascii"], "NOB..")
        self.assertEqual(result["extension_guess_only"], ".nob")
        self.assertIn("not a decoded", result["warning"])

    def test_nonoverwrite(self):
        result = self.base / "snapshot.json"
        audit.write_json(result, audit.snapshot(self.drive))
        with self.assertRaises(FileExistsError):
            audit.write_json(result, audit.snapshot(self.drive))

    def test_json_roundtrip_and_cli(self):
        output = self.base / "snap.json"
        audit.main(["snapshot", "--root", str(self.drive), "--out", str(output)])
        loaded = audit.load_snapshot(output)
        self.assertEqual(loaded["kind"], "snapshot")
        self.put("BOOK/new.nos", b"new")
        later = self.base / "snap2.json"
        audit.main(["snapshot", "--root", str(self.drive), "--out", str(later)])
        delta = self.base / "delta.json"
        audit.main(["diff", "--before", str(output), "--after", str(later), "--out", str(delta)])
        self.assertEqual(json.loads(delta.read_text())["added"][0]["path"], "BOOK/new.nos")

    def test_filename_not_used_to_infer_raw_oid(self):
        self.put("BOOK/56001.nob", b"opaque")
        entry = audit.snapshot(self.drive)["files"][0]
        self.assertNotIn("raw_oid", entry)
        self.assertNotIn("codec", entry)


if __name__ == "__main__":
    unittest.main()
