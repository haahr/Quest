"""Unit Tests for Quest Build Manifest (.qm).

Tests ModuleManifest serialization, deserialization, and staleness evaluations:
- JSON schema fidelity
- Object file presence check
- Source vs. artifact timestamp comparison
- Transitive interface invalidation rule
- Precompiled / binary-only distribution mode
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap", "python"))

from quest.build.manifest import (
    ImportedInterfaceRef,
    ImportedModuleRef,
    ModuleManifest,
    is_manifest_stale,
    read_qm,
    write_qm,
)


class TestBuildManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_manifest_roundtrip(self) -> None:
        """Tests serializing and deserializing a ModuleManifest to and from a .qm file."""
        qm_path = self.dir_path / "test.qm"
        manifest = ModuleManifest(
            name="util/path",
            interface="util/Path",
            source="lib/util/path.mod.quest",
            object=".build/util/path.o",
            imported_modules=[
                ImportedModuleRef(name="util/strutil", interface="util/Strutil"),
            ],
            imported_interfaces=[
                ImportedInterfaceRef(name="util/Path", source="lib/util/path.int.quest", mtime=100.0),
                ImportedInterfaceRef(name="util/Strutil", source="lib/util/strutil.int.quest", mtime=200.0),
            ],
        )

        write_qm(manifest, qm_path)
        self.assertTrue(qm_path.is_file())

        loaded = read_qm(qm_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "util/path")
        self.assertEqual(loaded.interface, "util/Path")
        self.assertEqual(loaded.source, "lib/util/path.mod.quest")
        self.assertEqual(loaded.object, ".build/util/path.o")
        self.assertEqual(len(loaded.imported_modules), 1)
        self.assertEqual(loaded.imported_modules[0].name, "util/strutil")
        self.assertEqual(loaded.imported_modules[0].interface, "util/Strutil")
        self.assertEqual(len(loaded.imported_interfaces), 2)
        self.assertEqual(loaded.imported_interfaces[1].name, "util/Strutil")
        self.assertEqual(loaded.imported_interfaces[1].mtime, 200.0)

    def test_staleness_missing_object(self) -> None:
        """Tests that a missing object file marks manifest as stale."""
        qm_path = self.dir_path / "foo.qm"
        src_path = self.dir_path / "foo.mod.quest"
        src_path.write_text("module foo: Foo export end;\n", encoding="utf-8")
        manifest = ModuleManifest(
            name="foo",
            interface="Foo",
            source=str(src_path),
            object=str(self.dir_path / "missing.o"),
        )
        write_qm(manifest, qm_path)
        self.assertTrue(is_manifest_stale(manifest, qm_path))

    def test_staleness_newer_source(self) -> None:
        """Tests that a source file newer than .qm marks manifest as stale."""
        src_path = self.dir_path / "bar.mod.quest"
        src_path.write_text("module bar: Bar export end;\n", encoding="utf-8")
        obj_path = self.dir_path / "bar.o"
        obj_path.write_text("fake object\n", encoding="utf-8")
        qm_path = self.dir_path / "bar.qm"

        manifest = ModuleManifest(
            name="bar",
            interface="Bar",
            source=str(src_path),
            object=str(obj_path),
        )
        write_qm(manifest, qm_path)

        # Force source to be strictly newer than .qm
        future = time.time() + 10.0
        os.utime(src_path, (future, future))
        self.assertTrue(is_manifest_stale(manifest, qm_path))

    def test_staleness_transitive_interface(self) -> None:
        """Tests that a newer imported interface source invalidates the module."""
        src_path = self.dir_path / "baz.mod.quest"
        src_path.write_text("module baz: Baz export end;\n", encoding="utf-8")
        obj_path = self.dir_path / "baz.o"
        obj_path.write_text("fake object\n", encoding="utf-8")
        iface_src = self.dir_path / "iface.int.quest"
        iface_src.write_text("interface Iface export end;\n", encoding="utf-8")
        qm_path = self.dir_path / "baz.qm"

        manifest = ModuleManifest(
            name="baz",
            interface="Baz",
            source=str(src_path),
            object=str(obj_path),
            imported_interfaces=[
                ImportedInterfaceRef(name="Iface", source=str(iface_src), mtime=100.0),
            ],
        )
        write_qm(manifest, qm_path)

        # Baseline: everything at current timestamp or interface older -> not stale
        past = time.time() - 10.0
        os.utime(iface_src, (past, past))
        self.assertFalse(is_manifest_stale(manifest, qm_path))

        # Update interface source timestamp into future
        future = time.time() + 10.0
        os.utime(iface_src, (future, future))
        self.assertTrue(is_manifest_stale(manifest, qm_path))

    def test_precompiled_mode_not_stale(self) -> None:
        """Tests that when source does not exist but .qm and .o exist, it is not stale."""
        obj_path = self.dir_path / "precompiled.o"
        obj_path.write_text("fake object\n", encoding="utf-8")
        qm_path = self.dir_path / "precompiled.qm"

        manifest = ModuleManifest(
            name="precompiled",
            interface="Precompiled",
            source=str(self.dir_path / "nonexistent.mod.quest"),
            object=str(obj_path),
        )
        write_qm(manifest, qm_path)
        self.assertFalse(is_manifest_stale(manifest, qm_path))


if __name__ == "__main__":
    unittest.main()
