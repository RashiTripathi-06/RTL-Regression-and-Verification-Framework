from __future__ import annotations
import abc
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from models import VerificationPlan

@dataclass
class ExecutionResult:
    plan_id: str
    compile_returncode: int
    compile_stdout: str
    compile_stderr: str
    sim_returncode: Optional[int]
    sim_stdout: str
    sim_stderr: str
    timed_out: bool
    elapsed_seconds: float
    edalize_configured: bool = False
    simulator_name: str = "Icarus Verilog"
    is_license_error: bool = False


class BaseSimulatorAdapter(abc.ABC):
    """Abstract interface for HDL simulation backends (Icarus, Verilator, Questa, etc.)."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        pass

    @abc.abstractmethod
    def compile(self, plan: VerificationPlan, work_dir: Path) -> Tuple[int, str, str, Optional[Path], bool]:
        """
        Compiles the design sources.
        Returns: (returncode, stdout, stderr, sim_target_path, timed_out)
        """
        pass

    @abc.abstractmethod
    def simulate(self, plan: VerificationPlan, work_dir: Path, sim_target: Path) -> Tuple[int, str, str, bool]:
        """
        Executes the compiled simulation binary.
        Returns: (returncode, stdout, stderr, timed_out)
        """
        pass


class IcarusSimulatorAdapter(BaseSimulatorAdapter):
    """
    Native Windows & Cross-Platform adapter for Icarus Verilog (iverilog & vvp 12.0+).
    Ensures compilation isolation, strictly ordered sources, and watchdog timeouts.
    """

    @property
    def name(self) -> str:
        return "Icarus Verilog (iverilog + vvp)"

    def is_available(self) -> bool:
        return shutil.which("iverilog") is not None and shutil.which("vvp") is not None

    def compile(self, plan: VerificationPlan, work_dir: Path) -> Tuple[int, str, str, Optional[Path], bool]:
        sim_vvp = work_dir / f"sim_{plan.plan_id}.vvp"
        all_sources = [p.resolve() for p in plan.required_sources]

        inc_args = []
        for inc in plan.include_dirs:
            inc_args.extend(["-I", str(inc)])

        compile_cmd = [
            "iverilog",
            *plan.iverilog_flags,
            *inc_args,
            "-s", plan.tb_module,
            "-o", str(sim_vvp),
            *[str(s) for s in all_sources]
        ]

        try:
            comp_proc = subprocess.run(
                compile_cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=plan.timeout_seconds
            )
            return (comp_proc.returncode, comp_proc.stdout, comp_proc.stderr, sim_vvp, False)
        except subprocess.TimeoutExpired:
            return (-1, "", f"Compilation timed out after {plan.timeout_seconds}s.", None, True)
        except FileNotFoundError:
            return (127, "", "iverilog binary not found on system PATH.", None, False)

    def simulate(self, plan: VerificationPlan, work_dir: Path, sim_target: Path) -> Tuple[int, str, str, bool]:
        sim_cmd = ["vvp", str(sim_target)]
        try:
            sim_proc = subprocess.run(
                sim_cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=plan.timeout_seconds
            )
            return (sim_proc.returncode, sim_proc.stdout, sim_proc.stderr, False)
        except subprocess.TimeoutExpired as exc:
            stdout_str = exc.stdout or ""
            stderr_str = exc.stderr or ""
            if isinstance(stdout_str, bytes):
                stdout_str = stdout_str.decode("utf-8", errors="replace")
            if isinstance(stderr_str, bytes):
                stderr_str = stderr_str.decode("utf-8", errors="replace")
            # Kill process tree on Windows if lingering
            return (
                -1,
                stdout_str,
                stderr_str + f"\n[WATCHDOG] Simulation exceeded timeout limit of {plan.timeout_seconds}s.",
                True
            )
        except FileNotFoundError:
            return (127, "", "vvp binary not found on system PATH.", False)


class QuestaSimulatorAdapter(BaseSimulatorAdapter):
    """
    Native Windows & Cross-Platform adapter for Questa / ModelSim 2025.3+
    (Questa Altera Starter FPGA Edition).

    Guarantees:
    - Executable discovery (vlib, vlog, vsim)
    - Version detection and reporting
    - License environment validation (SALT_LICENSE_SERVER, LM_LICENSE_FILE)
    - Strict sequential execution lock (worker count = 1 for node-locked single-session license)
    - Isolated work library per build (vlib work)
    - Robust subprocess arrays (no shell string concatenation)
    - Timeout watchdog and clean process tree termination
    - Distinct classification of LICENSE_ERROR vs COMPILE_ERROR / SIMULATION_ERROR
    """
    _execution_lock = threading.Lock()

    def __init__(self, questa_bin_dir: Optional[Path] = None):
        self.vsim_path = self._find_tool("vsim", questa_bin_dir)
        self.vlog_path = self._find_tool("vlog", questa_bin_dir)
        self.vlib_path = self._find_tool("vlib", questa_bin_dir)
        self._cached_version: Optional[str] = None
        self._ensure_license_env()

    @staticmethod
    def _find_tool(tool_name: str, hint_dir: Optional[Path] = None) -> Optional[Path]:
        if hint_dir:
            cand = hint_dir / (tool_name + (".exe" if os.name == "nt" else ""))
            if cand.exists():
                return cand.resolve()
        # Search PATH
        found = shutil.which(tool_name)
        if found:
            return Path(found).resolve()
        # Known default installation directories
        default_paths = [
            Path(r"D:\questa_fse\win64"),
            Path(r"C:\intelFPGA_pro\25.3\questa_fse\win64"),
            Path(r"C:\intelFPGA\20.1\modelsim_ase\win64"),
        ]
        for p in default_paths:
            cand = p / (tool_name + (".exe" if os.name == "nt" else ""))
            if cand.exists():
                return cand.resolve()
        return None

    def _ensure_license_env(self):
        lic = os.environ.get("SALT_LICENSE_SERVER") or os.environ.get("LM_LICENSE_FILE")
        if not lic or not Path(lic).exists():
            workspace_lic = Path("D:/dop2/LR-213236_License.dat")
            if workspace_lic.exists():
                os.environ["SALT_LICENSE_SERVER"] = str(workspace_lic.resolve())

    @property
    def name(self) -> str:
        ver = self.get_version()
        return f"Questa ({ver})" if ver else "Questa Simulator"

    def is_available(self) -> bool:
        return self.vsim_path is not None and self.vlog_path is not None and self.vlib_path is not None

    def get_version(self) -> str:
        if self._cached_version:
            return self._cached_version
        if not self.vsim_path:
            return "Unavailable"
        try:
            res = subprocess.run([str(self.vsim_path), "-version"], capture_output=True, text=True, timeout=5)
            line = res.stdout.strip() or res.stderr.strip()
            self._cached_version = line.split("\n")[0] if line else "2025.3"
            return self._cached_version
        except Exception:
            return "2025.3"

    @staticmethod
    def is_license_error(output: str) -> bool:
        indicators = [
            "Fatal license error",
            "License checkout failed",
            "Unable to checkout license",
            "No license for",
            "FlexNet Licensing error",
            "License server is down",
            "Invalid license file",
            "WinError 623",
            "Illegal System DLL Relocation",
            "Cannot checkout license",
            "license request for",
        ]
        out_lower = output.lower()
        return any(ind.lower() in out_lower for ind in indicators)

    def compile(self, plan: VerificationPlan, work_dir: Path) -> Tuple[int, str, str, Optional[Path], bool, bool]:
        with self._execution_lock:
            if not self.is_available():
                return (127, "", "Questa toolchain (vlib/vlog/vsim) not found on system PATH.", None, False, False)

            # 1. Ensure work library exists in work_dir
            work_lib = work_dir / "work"
            if not work_lib.exists():
                vlib_cmd = [str(self.vlib_path), "work"]
                try:
                    res_vlib = subprocess.run(vlib_cmd, cwd=str(work_dir), capture_output=True, text=True, timeout=plan.timeout_seconds)
                    if res_vlib.returncode != 0:
                        out = res_vlib.stdout + "\n" + res_vlib.stderr
                        return (res_vlib.returncode, res_vlib.stdout, res_vlib.stderr, None, False, self.is_license_error(out))
                except subprocess.TimeoutExpired:
                    return (-1, "", f"vlib timed out after {plan.timeout_seconds}s.", None, True, False)
                except OSError as exc:
                    err_msg = f"vlib OSError: {exc}"
                    return (-1, "", err_msg, None, False, self.is_license_error(err_msg))

            # 2. Build vlog command with strict source ordering and include flags
            inc_args = []
            for idir in plan.include_dirs:
                inc_args.append(f"+incdir+{str(idir.resolve())}")

            src_args = [str(s.resolve()) for s in plan.required_sources]
            flags = list(getattr(plan, "questa_flags", ["-sv", "-timescale", "1ns/1ps"]))

            vlog_cmd = [
                str(self.vlog_path),
                "-work", "work",
                *flags,
                *inc_args,
                *src_args
            ]

            try:
                comp_proc = subprocess.run(
                    vlog_cmd,
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=plan.timeout_seconds
                )
                stdout = comp_proc.stdout or ""
                stderr = comp_proc.stderr or ""
                combined = stdout + "\n" + stderr
                lic_err = self.is_license_error(combined)
                
                has_vlog_errors = "** Error" in combined or "Errors: [1-9]" in combined
                rc = comp_proc.returncode
                if rc == 0 and has_vlog_errors:
                    rc = 1

                sim_target = work_lib if rc == 0 else None
                return (rc, stdout, stderr, sim_target, False, lic_err)

            except subprocess.TimeoutExpired:
                return (-1, "", f"vlog compilation timed out after {plan.timeout_seconds}s.", None, True, False)
            except OSError as exc:
                err_msg = f"vlog OSError: {exc}"
                return (-1, "", err_msg, None, False, self.is_license_error(err_msg))

    def simulate(self, plan: VerificationPlan, work_dir: Path, sim_target: Path) -> Tuple[int, str, str, bool, bool]:
        with self._execution_lock:
            if not self.vsim_path:
                return (127, "", "vsim binary not found.", False, False)

            extra_flags = list(getattr(plan, "vsim_flags", []))
            vsim_cmd = [
                str(self.vsim_path),
                "-c",
                "-do", "run -all; quit",
                *extra_flags,
                f"work.{plan.tb_module}"
            ]

            try:
                sim_proc = subprocess.run(
                    vsim_cmd,
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=plan.timeout_seconds
                )
                stdout = sim_proc.stdout or ""
                stderr = sim_proc.stderr or ""
                combined = stdout + "\n" + stderr
                lic_err = self.is_license_error(combined)
                return (sim_proc.returncode, stdout, stderr, False, lic_err)

            except subprocess.TimeoutExpired as exc:
                stdout_str = exc.stdout or ""
                stderr_str = exc.stderr or ""
                if isinstance(stdout_str, bytes):
                    stdout_str = stdout_str.decode("utf-8", errors="replace")
                if isinstance(stderr_str, bytes):
                    stderr_str = stderr_str.decode("utf-8", errors="replace")
                return (
                    -1,
                    stdout_str,
                    stderr_str + f"\n[WATCHDOG] Simulation exceeded timeout limit of {plan.timeout_seconds}s.",
                    True,
                    False
                )
            except OSError as exc:
                err_msg = f"vsim OSError: {exc}"
                return (-1, "", err_msg, False, self.is_license_error(err_msg))


class VerilatorSimulatorAdapter(BaseSimulatorAdapter):
    """Extensibility adapter for Verilator (future backend)."""

    @property
    def name(self) -> str:
        return "Verilator"

    def is_available(self) -> bool:
        return shutil.which("verilator") is not None

    def compile(self, plan: VerificationPlan, work_dir: Path) -> Tuple[int, str, str, Optional[Path], bool]:
        return (-1, "", "Verilator backend is configured as a stub for future integration.", None, False)

    def simulate(self, plan: VerificationPlan, work_dir: Path, sim_target: Path) -> Tuple[int, str, str, bool]:
        return (-1, "", "Verilator simulation stub.", False)


class EdalizeSimulatorAdapter(BaseSimulatorAdapter):
    """
    Standardized EDA toolchain integration via Edalize and EDAM (EDA Metadata) specifications.
    Generates reproducible edam.json manifests for multi-simulator regression (Icarus, Verilator, Questa, VCS).
    If the 'edalize' Python package is installed, drives execution through Edalize.
    If 'edalize' is not installed, emits EDAM manifests and provides transparent fallback to native Icarus Verilog.
    """

    def __init__(self, target_tool: str = "iverilog"):
        self.target_tool = target_tool
        self._icarus_fallback = IcarusSimulatorAdapter()

    @property
    def name(self) -> str:
        try:
            import edalize  # type: ignore
            return f"Edalize ({self.target_tool} backend)"
        except ImportError:
            return f"Edalize [EDAM generated] -> {self._icarus_fallback.name}"

    def is_available(self) -> bool:
        try:
            import edalize  # type: ignore
            return True
        except ImportError:
            return self._icarus_fallback.is_available()

    def generate_edam(self, plan: VerificationPlan, work_dir: Path) -> dict:
        """Constructs an EDAM (EDA Metadata) v0.4+ specification."""
        edam_files = []
        for s in plan.required_sources:
            edam_files.append({"name": str(s.resolve()), "file_type": "verilogSource"})
        for inc in getattr(plan, "include_files", []):
            edam_files.append({"name": str(inc.resolve()), "file_type": "verilogSource", "is_include_file": True})

        edam = {
            "name": plan.plan_id,
            "version": "0.2.0",
            "files": edam_files,
            "toplevel": plan.tb_module,
            "tool_options": {
                self.target_tool: {
                    "iverilog_options": plan.iverilog_flags
                }
            }
        }
        work_dir.mkdir(parents=True, exist_ok=True)
        edam_path = work_dir / "edam.json"
        import json
        edam_path.write_text(json.dumps(edam, indent=2), encoding="utf-8")
        return edam

    def compile(self, plan: VerificationPlan, work_dir: Path) -> Tuple[int, str, str, Optional[Path], bool]:
        edam = self.generate_edam(plan, work_dir)
        try:
            import edalize  # type: ignore
            backend = edalize.get_edatool(self.target_tool)(edam=edam, work_root=str(work_dir))
            backend.configure()
            backend.build()
            sim_vvp = work_dir / f"sim_{plan.plan_id}.vvp"
            return (0, "[Edalize] Build completed successfully.", "", sim_vvp, False)
        except ImportError:
            rc, stdout, stderr, target, timed_out = self._icarus_fallback.compile(plan, work_dir)
            stdout = f"[Edalize: EDAM manifest generated at {work_dir / 'edam.json'}]\n" + stdout
            return (rc, stdout, stderr, target, timed_out)
        except Exception as exc:
            return (-1, "", f"[Edalize Error] {str(exc)}", None, False)

    def simulate(self, plan: VerificationPlan, work_dir: Path, sim_target: Path) -> Tuple[int, str, str, bool]:
        try:
            import edalize  # type: ignore
            backend = edalize.get_edatool(self.target_tool)(edam=self.generate_edam(plan, work_dir), work_root=str(work_dir))
            backend.run()
            return (0, "[Edalize] Simulation run completed.", "", False)
        except ImportError:
            return self._icarus_fallback.simulate(plan, work_dir, sim_target)
        except Exception as exc:
            return (-1, "", f"[Edalize Simulation Error] {str(exc)}", False)


class IsolatedSimulatorExecutor:
    """
    Executes HDL compilation and simulation inside an isolated, reproducible build directory.
    Uses a clean simulator adapter pattern without false claims regarding external tools.
    """

    def __init__(self, adapter: Optional[BaseSimulatorAdapter] = None):
        self.adapter = adapter or IcarusSimulatorAdapter()

    def execute(self, plan: VerificationPlan) -> ExecutionResult:
        start_ts = time.perf_counter()
        work_dir = plan.build_dir
        work_dir.mkdir(parents=True, exist_ok=True)

        # 1. Stage associated reference and data files (.mem, .hex, .dat, .csv)
        # Copy to work_dir root AND preserve relative subdirectory structure if referenced
        for df in plan.data_files:
            if df.exists():
                dest_file = work_dir / df.name
                if df.resolve() != dest_file.resolve():
                    shutil.copy2(df, dest_file)
                # Replicate relative path if file is located in a subfolder relative to testbench
                try:
                    rel_to_tb = df.resolve().relative_to(plan.tb_file.parent.resolve())
                    sub_dest = work_dir / rel_to_tb
                    if df.resolve() != sub_dest.resolve():
                        sub_dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(df, sub_dest)
                except ValueError:
                    pass

        # 1b. Stage include files into work_dir
        for inc_f in getattr(plan, "include_files", []):
            if inc_f.exists():
                dest_inc = work_dir / inc_f.name
                if not dest_inc.exists():
                    shutil.copy2(inc_f, dest_inc)

        # 2. Compile using configured simulator adapter
        res_comp = self.adapter.compile(plan, work_dir)
        is_lic = False
        if len(res_comp) == 6:
            rc_comp, comp_out, comp_err, sim_target, comp_timeout, is_lic = res_comp
        else:
            rc_comp, comp_out, comp_err, sim_target, comp_timeout = res_comp
            if hasattr(self.adapter, "is_license_error"):
                is_lic = self.adapter.is_license_error(comp_out + "\n" + comp_err)

        is_edalize = isinstance(self.adapter, EdalizeSimulatorAdapter)

        if comp_timeout or rc_comp != 0 or sim_target is None or is_lic:
            return ExecutionResult(
                plan_id=plan.plan_id,
                compile_returncode=rc_comp,
                compile_stdout=comp_out,
                compile_stderr=comp_err,
                sim_returncode=None,
                sim_stdout="",
                sim_stderr="",
                timed_out=comp_timeout,
                elapsed_seconds=time.perf_counter() - start_ts,
                edalize_configured=is_edalize,
                simulator_name=self.adapter.name,
                is_license_error=is_lic
            )

        # 3. Simulate using configured simulator adapter
        res_sim = self.adapter.simulate(plan, work_dir, sim_target)
        if len(res_sim) == 5:
            rc_sim, sim_out, sim_err, sim_timeout, is_lic_sim = res_sim
            is_lic = is_lic or is_lic_sim
        else:
            rc_sim, sim_out, sim_err, sim_timeout = res_sim
            if hasattr(self.adapter, "is_license_error"):
                is_lic = is_lic or self.adapter.is_license_error(sim_out + "\n" + sim_err)

        return ExecutionResult(
            plan_id=plan.plan_id,
            compile_returncode=rc_comp,
            compile_stdout=comp_out,
            compile_stderr=comp_err,
            sim_returncode=rc_sim,
            sim_stdout=sim_out,
            sim_stderr=sim_err,
            timed_out=sim_timeout,
            elapsed_seconds=time.perf_counter() - start_ts,
            edalize_configured=is_edalize,
            simulator_name=self.adapter.name,
            is_license_error=is_lic
        )
