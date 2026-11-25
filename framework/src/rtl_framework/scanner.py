from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from .models import ModuleInfo
from .parser import VerilogASTParser

@dataclass
class DiscoveredProject:
    root_dir: Path
    all_modules: Dict[str, ModuleInfo] = field(default_factory=dict) # canonical name -> ModuleInfo
    modules_by_design_id: Dict[str, ModuleInfo] = field(default_factory=dict)
    testbenches: List[ModuleInfo] = field(default_factory=list)
    candidate_duts: List[ModuleInfo] = field(default_factory=list)
    internal_modules: List[ModuleInfo] = field(default_factory=list)
    supporting_modules: Dict[str, ModuleInfo] = field(default_factory=dict)
    include_files: List[Path] = field(default_factory=list)
    data_files: Dict[str, Path] = field(default_factory=dict) # filename -> Path
    source_files: List[Path] = field(default_factory=list)
    duplicate_modules: Dict[str, List[Path]] = field(default_factory=dict) # name -> list of defining files
    module_classifications: Dict[str, str] = field(default_factory=dict) # design_id -> classification

class ProjectScanner:
    """Scans and classifies RTL files, testbenches, dependencies and data files across the workspace."""

    def __init__(
        self,
        root_dir: Path,
        library_dirs: Optional[List[str]] = None,
        ignore_dirs: Optional[List[str]] = None
    ):
        self.root_dir = root_dir.resolve()
        self.ignore_dirs = set(ignore_dirs or [".git", "build", "__pycache__", ".regression_cache", "reports"])
        self.library_dirs = [
            (self.root_dir / d).resolve() for d in (library_dirs or ["designs/common"])
        ]
        self.parser = VerilogASTParser()

    @staticmethod
    def _is_license_file(path: Path) -> bool:
        """Determines if a file is a simulator license file rather than a simulation data file."""
        name_lower = path.name.lower()
        if any(k in name_lower for k in ("license", "lic_", "_lic")):
            return True
        try:
            head = path.read_bytes()[:600].decode("utf-8", errors="ignore").lower()
            if any(k in head for k in ("server", "daemon", "feature", "increment", "package", "flexnet", "salt_license", "siemens", "mentor")):
                return True
        except Exception:
            pass
        return False

    def scan(self) -> DiscoveredProject:
        project = DiscoveredProject(root_dir=self.root_dir)

        # 1. Discover all source files (.v, .sv, .vh, .svh) and data files (.mem, .hex, .dat, .csv, .json)
        for path in sorted(self.root_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part in self.ignore_dirs for part in path.parts):
                continue

            ext = path.suffix.lower()
            if ext in (".v", ".sv"):
                project.source_files.append(path)
                parsed_mods = self.parser.parse_file(path)
                for mod in parsed_mods:
                    # Track all declarations of this module name across files
                    project.duplicate_modules.setdefault(mod.name, []).append(path)
                    if len(project.duplicate_modules[mod.name]) > 1:
                        warn = f"Duplicate module '{mod.name}' detected in {path} (previously defined in {project.duplicate_modules[mod.name][0]})"
                        mod.parser_warnings.append(warn)

                    # Register by design_id
                    project.modules_by_design_id[mod.design_id] = mod
                    if mod.name not in project.all_modules:
                        project.all_modules[mod.name] = mod

                    is_library_file = any(lib_d in path.parents or path == lib_d for lib_d in self.library_dirs)
                    if is_library_file:
                        project.supporting_modules[mod.name] = mod
                        project.module_classifications[mod.design_id] = "SUPPORTING_MODULE"
                    else:
                        if mod.is_testbench:
                            if not any(tb.name == mod.name for tb in project.testbenches):
                                project.testbenches.append(mod)
                                project.module_classifications[mod.design_id] = "TESTBENCH"
                            else:
                                project.module_classifications[mod.design_id] = "DUPLICATE_TESTBENCH"
                        else:
                            project.candidate_duts.append(mod)
                            project.supporting_modules[mod.name] = mod
                            project.module_classifications[mod.design_id] = "TOP_LEVEL_DUT"

            elif ext in (".vh", ".svh"):
                project.include_files.append(path)
            elif ext in (".mem", ".hex", ".dat", ".csv", ".json", ".txt"):
                if self._is_license_file(path):
                    continue
                # For plain txt, only include if name indicates tabular reference or lookup
                if ext == ".txt" and not any(k in path.name.lower() for k in ("lut", "table", "ref", "golden", "vector", "mem")):
                    continue
                project.data_files[path.name] = path

        self.classify_hierarchy(project)
        return project

    @staticmethod
    def classify_hierarchy(project: DiscoveredProject, explicit_targets: Optional[Set[str]] = None) -> None:
        """
        Uses actual module-instantiation hierarchy to distinguish top-level DUTs from internal submodules.
        A module instantiated by another non-testbench RTL module is classified as INTERNAL_MODULE unless
        it is explicitly instantiated by a testbench or explicitly targeted in configuration.
        """
        targets = set(explicit_targets or ())
        non_tb_mods = list(project.candidate_duts) + list(project.internal_modules)

        instantiated_by_rtl: Set[str] = set()
        for mod in non_tb_mods:
            for inst in mod.instantiations:
                if inst.module_type != mod.name:
                    instantiated_by_rtl.add(inst.module_type)

        tb_instantiated: Set[str] = set()
        for tb in project.testbenches:
            for inst in tb.instantiations:
                tb_instantiated.add(inst.module_type)

        top_duts: List[ModuleInfo] = []
        internal_mods: List[ModuleInfo] = []
        for mod in non_tb_mods:
            is_instantiated = mod.name in instantiated_by_rtl
            is_tb_target = mod.name in tb_instantiated
            is_explicit = mod.name in targets or mod.file_path.stem in targets
            if is_instantiated and not is_tb_target and not is_explicit:
                internal_mods.append(mod)
                project.module_classifications[mod.design_id] = "INTERNAL_MODULE"
            else:
                top_duts.append(mod)
                project.module_classifications[mod.design_id] = "TOP_LEVEL_DUT"

        project.candidate_duts = top_duts
        project.internal_modules = internal_mods
