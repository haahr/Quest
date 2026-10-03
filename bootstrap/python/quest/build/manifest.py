"""Quest Module Manifest (.qm) serialization and deserialization.

A .qm file records the build metadata for an implementation module (.mod.quest)
or main routine (.quest), tracking imported modules and interface dependencies.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ImportedModuleRef:
    """Reference to an imported module and its declared interface."""
    name: str
    interface: str


@dataclass
class ImportedInterfaceRef:
    """Reference to an imported interface and its source/timestamp."""
    name: str
    source: str
    mtime: float


@dataclass
class ModuleManifest:
    """Build manifest stored in a .qm file."""
    name: str
    interface: Optional[str]
    source: str
    object: str
    imported_modules: list[ImportedModuleRef] = field(default_factory=list)
    imported_interfaces: list[ImportedInterfaceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializes manifest to a dictionary."""
        return {
            "name": self.name,
            "interface": self.interface,
            "source": self.source,
            "object": self.object,
            "imported_modules": [asdict(m) for m in self.imported_modules],
            "imported_interfaces": [asdict(i) for i in self.imported_interfaces],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModuleManifest:
        """Constructs a ModuleManifest from a dictionary."""
        imported_modules = [
            ImportedModuleRef(name=m["name"], interface=m["interface"])
            for m in data.get("imported_modules", [])
        ]
        imported_interfaces = [
            ImportedInterfaceRef(
                name=i["name"],
                source=i.get("source", ""),
                mtime=float(i.get("mtime", 0.0)),
            )
            for i in data.get("imported_interfaces", [])
        ]
        return cls(
            name=data["name"],
            interface=data.get("interface"),
            source=data.get("source", ""),
            object=data.get("object", ""),
            imported_modules=imported_modules,
            imported_interfaces=imported_interfaces,
        )


def write_qm(manifest: ModuleManifest, path: Path) -> None:
    """Writes a ModuleManifest to a .qm JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, indent=2)
        f.write("\n")


def read_qm(path: Path) -> Optional[ModuleManifest]:
    """Reads a ModuleManifest from a .qm JSON file, or None if unreadable."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return ModuleManifest.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


def is_manifest_stale(manifest: ModuleManifest, qm_path: Path) -> bool:
    """Checks whether the compiled artifacts for a module or main routine are out of date."""
    obj_path = Path(manifest.object)
    if not obj_path.is_file():
        return True

    src_path = Path(manifest.source) if manifest.source else None
    if src_path and src_path.is_file():
        try:
            qm_mtime = qm_path.stat().st_mtime
            if src_path.stat().st_mtime > qm_mtime:
                return True
            if src_path.stat().st_mtime > obj_path.stat().st_mtime:
                return True
        except OSError:
            return True
    elif not src_path or not src_path.exists():
        # Precompiled / binary mode: if .qm and .o exist without source, it is up to date
        return False

    # Transitive interface staleness check
    try:
        qm_mtime = qm_path.stat().st_mtime
        for iface_ref in manifest.imported_interfaces:
            if iface_ref.source:
                iface_src = Path(iface_ref.source)
                if iface_src.is_file() and iface_src.stat().st_mtime > qm_mtime:
                    return True
    except OSError:
        return True

    return False

