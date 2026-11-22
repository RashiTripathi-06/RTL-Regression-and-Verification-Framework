from __future__ import annotations
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Any
from .models import TestResult, VerificationPlan

class CacheManager:
    r"""
    Cryptographic SHA-256 Merkle Tree Incremental Regression Cache Manager.

    Merkle Topology:
                  Root Hash: H_root = sha256(H_design || H_harness)
                   /                                   \
        H_design = sha256(H_dut || H_deps)        H_harness = sha256(H_tb || H_env)
         /               \                         /                      \
      H_dut            H_deps                    H_tb                   H_env = sha256(H_refs || H_wrap || H_cfg)
                                                                        /       |       \
                                                                    H_refs   H_wrap    H_cfg

    Guarantees strict cache invalidation when any input affecting verification changes:
    - DUT source
    - Submodule dependencies
    - Testbench source
    - Reference / LUT data files
    - Wrapper synthesis & port mappings
    - Compiler options, parameters, and watchdog timeouts
    """

    def __init__(self, cache_file_path: Path):
        self.cache_file = cache_file_path.resolve()
        self._cache: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def save(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")

    def compute_hash(self, plan: VerificationPlan) -> str:
        """
        Computes a cryptographic Merkle root hash across all verification inputs.
        """
        # Leaf 1: DUT source file
        dut_bytes = plan.dut_file.read_bytes() if plan.dut_file.exists() else b""
        h_dut = hashlib.sha256(b"leaf:dut:" + dut_bytes).hexdigest()

        # Leaf Subtree 2: Submodule Dependencies (excluding DUT and TB and wrapper)
        dep_files = [
            p.resolve() for p in plan.required_sources
            if p.resolve() != plan.dut_file.resolve()
            and p.resolve() != plan.tb_file.resolve()
            and (not plan.wrapper_path or p.resolve() != plan.wrapper_path.resolve())
            and p.exists()
        ]
        dep_leaf_hashes = []
        for df in sorted(set(dep_files), key=lambda p: str(p)):
            h_df = hashlib.sha256(f"leaf:dep:{df.name}:".encode("utf-8") + df.read_bytes()).hexdigest()
            dep_leaf_hashes.append(h_df)
        h_deps = hashlib.sha256(b"node:deps:" + "".join(dep_leaf_hashes).encode("utf-8")).hexdigest()

        # Leaf Subtree 2b: Include files (.vh, .svh, macros)
        inc_files = getattr(plan, "include_files", [])
        inc_leaf_hashes = []
        for inc_f in sorted({p.resolve() for p in inc_files if p.exists()}, key=lambda p: str(p)):
            h_inc = hashlib.sha256(f"leaf:inc:{inc_f.name}:".encode("utf-8") + inc_f.read_bytes()).hexdigest()
            inc_leaf_hashes.append(h_inc)
        h_includes = hashlib.sha256(b"node:includes:" + "".join(inc_leaf_hashes).encode("utf-8")).hexdigest()

        # Node A: H_design
        h_design = hashlib.sha256(f"node:design:{h_dut}:{h_deps}:{h_includes}".encode("utf-8")).hexdigest()

        # Leaf 3: Testbench source file
        tb_bytes = plan.tb_file.read_bytes() if plan.tb_file.exists() else b""
        h_tb = hashlib.sha256(b"leaf:tb:" + tb_bytes).hexdigest()

        # Leaf Subtree 4: Reference / LUT data files
        ref_leaf_hashes = []
        for rf in sorted({p.resolve() for p in plan.data_files if p.exists()}, key=lambda p: str(p)):
            h_rf = hashlib.sha256(f"leaf:ref:{rf.name}:".encode("utf-8") + rf.read_bytes()).hexdigest()
            ref_leaf_hashes.append(h_rf)
        h_refs = hashlib.sha256(b"node:refs:" + "".join(ref_leaf_hashes).encode("utf-8")).hexdigest()

        # Leaf 5: Wrapper file and structural port mapping
        wrapper_bytes = b""
        if plan.wrapper_path and plan.wrapper_path.exists():
            wrapper_bytes = plan.wrapper_path.read_bytes()
        mapping_str = json.dumps(plan.compatibility.port_mapping, sort_keys=True)
        h_wrapper = hashlib.sha256(b"leaf:wrap:" + wrapper_bytes + mapping_str.encode("utf-8")).hexdigest()

        # Leaf 6: Compiler flags, simulator backend, license and environment settings
        lic_env = os.environ.get("SALT_LICENSE_SERVER", "")
        lic_hash = ""
        if lic_env and Path(lic_env).exists():
            try:
                lic_hash = hashlib.sha256(Path(lic_env).read_bytes()).hexdigest()
            except Exception:
                lic_hash = lic_env

        cfg_salt = json.dumps({
            "iverilog_flags": sorted(plan.iverilog_flags),
            "questa_flags": sorted(getattr(plan, "questa_flags", [])),
            "vsim_flags": sorted(getattr(plan, "vsim_flags", [])),
            "simulator_name": getattr(plan, "simulator_name", "icarus"),
            "verification_path": getattr(plan, "verification_path", "PATH_A"),
            "license_hash": lic_hash,
            "timeout": plan.timeout_seconds,
            "tb_module": plan.tb_module,
            "dut_module": plan.dut_module,
            "confidence": plan.compatibility.confidence,
        }, sort_keys=True)
        h_config = hashlib.sha256(b"leaf:config:" + cfg_salt.encode("utf-8")).hexdigest()

        # Node B: H_env
        h_env = hashlib.sha256(f"node:env:{h_refs}:{h_wrapper}:{h_config}".encode("utf-8")).hexdigest()

        # Node C: H_harness
        h_harness = hashlib.sha256(f"node:harness:{h_tb}:{h_env}".encode("utf-8")).hexdigest()

        # Merkle Root
        h_root = hashlib.sha256(f"root:merkle:{h_design}:{h_harness}".encode("utf-8")).hexdigest()
        return h_root

    def get(self, plan: VerificationPlan) -> Optional[TestResult]:
        plan_id = plan.plan_id
        if plan_id not in self._cache:
            return None

        current_hash = self.compute_hash(plan)
        cached_data = self._cache[plan_id]

        if cached_data.get("content_hash") == current_hash:
            res = TestResult(**cached_data)
            res.cached = True
            return res

        return None

    def put(self, plan: VerificationPlan, result: TestResult):
        content_hash = self.compute_hash(plan)
        result.content_hash = content_hash
        data = asdict(result)
        self._cache[plan.plan_id] = data
        self.save()

    def clear(self):
        self._cache.clear()
        if self.cache_file.exists():
            self.cache_file.unlink()
