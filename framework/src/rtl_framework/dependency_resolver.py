from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Set, Optional
from .models import ModuleInfo, DependencyResolutionResult
from .parser import extract_file_includes

class DependencyResolver:
    """
    Resolves multi-level hierarchical submodule dependencies, shared submodules,
    recursive include files, missing dependencies, and circular dependency chains.
    """

    def __init__(self, all_modules: Dict[str, ModuleInfo], include_dirs: Optional[List[Path]] = None):
        self.all_modules = all_modules
        self.include_dirs = [p.resolve() for p in (include_dirs or []) if p.exists()]

    def resolve_dependencies(self, target_module: ModuleInfo, ignore_modules: Optional[Set[str]] = None) -> DependencyResolutionResult:
        """
        Recursively resolves all required dependency source files and includes for target_module.
        Supports multi-level submodule instantiations and nested `include files.
        Optionally ignores specified module types (e.g. DUT when resolving testbench dependencies).
        """
        result = DependencyResolutionResult(target_module=target_module.name)
        visited_modules: Set[str] = {target_module.name}
        ignored_set = set(ignore_modules or [])
        resolved_files: List[Path] = []
        visited_files: Set[Path] = {target_module.file_path.resolve()}
        visited_includes: Set[Path] = set()
        call_stack: List[str] = [target_module.name]

        def resolve_include_path(inc_str: str, base_dir: Path) -> Optional[Path]:
            # 1. Relative to base_dir
            cand1 = (base_dir / inc_str).resolve()
            if cand1.exists():
                return cand1
            # 2. In configured include directories
            for idir in self.include_dirs:
                cand2 = (idir / inc_str).resolve()
                if cand2.exists():
                    return cand2
            # 3. Direct absolute path
            cand3 = Path(inc_str).resolve()
            if cand3.exists():
                return cand3
            return None

        def recursively_resolve_include(inc_file: Path):
            if inc_file in visited_includes:
                return
            visited_includes.add(inc_file)
            if inc_file not in result.include_files:
                result.include_files.append(inc_file)

            nested_includes = extract_file_includes(inc_file)
            for n_inc in nested_includes:
                n_path = resolve_include_path(n_inc, inc_file.parent)
                if n_path:
                    recursively_resolve_include(n_path)
                else:
                    miss_tag = f"include:{n_inc}"
                    if miss_tag not in result.missing_dependencies:
                        result.missing_dependencies.append(miss_tag)

        def resolve_includes_for_mod(mod: ModuleInfo):
            for inc in mod.includes:
                inc_path = resolve_include_path(inc, mod.file_path.parent)
                if inc_path:
                    recursively_resolve_include(inc_path)
                else:
                    miss_tag = f"include:{inc}"
                    if miss_tag not in result.missing_dependencies:
                        result.missing_dependencies.append(miss_tag)

        # Resolve includes for top module
        resolve_includes_for_mod(target_module)

        def traverse(mod: ModuleInfo):
            for inst in mod.instantiations:
                sub_type = inst.module_type
                if sub_type in ignored_set:
                    continue

                # Check circular dependency
                if sub_type in call_stack:
                    cycle = call_stack[call_stack.index(sub_type):] + [sub_type]
                    if cycle not in result.circular_dependencies:
                        result.circular_dependencies.append(cycle)
                    continue

                # Check missing dependency
                if sub_type not in self.all_modules:
                    if sub_type not in result.missing_dependencies:
                        result.missing_dependencies.append(sub_type)
                    continue

                sub_mod = self.all_modules[sub_type]
                sub_file = sub_mod.file_path.resolve()

                # Resolve includes for submodule
                resolve_includes_for_mod(sub_mod)

                if sub_type not in visited_modules:
                    visited_modules.add(sub_type)
                    call_stack.append(sub_type)
                    traverse(sub_mod)
                    call_stack.pop()

                # Add dependency file if not already visited (post-order: deepest dependencies first!)
                if sub_file not in visited_files:
                    visited_files.add(sub_file)
                    resolved_files.append(sub_file)

        traverse(target_module)
        result.required_source_files = resolved_files
        return result
