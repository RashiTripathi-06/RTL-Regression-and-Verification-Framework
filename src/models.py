from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

# Verification Statuses
STATUS_PASS_REFERENCE_VERIFIED = "PASS_REFERENCE_VERIFIED"
STATUS_PASS_TESTBENCH_ONLY = "PASS_TESTBENCH_ONLY"
STATUS_PASS = "PASS"
STATUS_FUNCTIONAL_FAIL = "FUNCTIONAL FAIL"
STATUS_COMPILE_ERROR = "COMPILE ERROR"
STATUS_SIMULATION_ERROR = "SIMULATION ERROR"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_INVALID_RESULTS = "INVALID RESULTS"
STATUS_INTERFACE_ERROR = "INTERFACE ERROR"
STATUS_NO_MATCH = "NO MATCH"
STATUS_AMBIGUOUS_MATCH = "AMBIGUOUS MATCH"
STATUS_MISSING_REFERENCE = "MISSING REFERENCE"
STATUS_NOT_VERIFIED = "EXECUTED / NOT VERIFIED"
STATUS_LICENSE_ERROR = "LICENSE_ERROR"
STATUS_REFERENCE_DISPUTED = "REFERENCE_DISPUTED"
STATUS_REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"
STATUS_FAIL_REFERENCE = "FAIL_REFERENCE"

ALL_STATUSES = [
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_PASS,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR,
    STATUS_SIMULATION_ERROR,
    STATUS_TIMEOUT,
    STATUS_INCOMPLETE,
    STATUS_INVALID_RESULTS,
    STATUS_INTERFACE_ERROR,
    STATUS_NO_MATCH,
    STATUS_AMBIGUOUS_MATCH,
    STATUS_MISSING_REFERENCE,
    STATUS_NOT_VERIFIED,
    STATUS_LICENSE_ERROR,
    STATUS_REFERENCE_DISPUTED,
    STATUS_REFERENCE_UNAVAILABLE,
    STATUS_FAIL_REFERENCE,
]

# Execution Statuses
EXEC_SUCCESS = "EXEC_SUCCESS"
EXEC_COMPILE_ERROR = "EXEC_COMPILE_ERROR"
EXEC_SIMULATION_ERROR = "EXEC_SIMULATION_ERROR"
EXEC_TIMEOUT = "EXEC_TIMEOUT"
EXEC_SKIPPED = "EXEC_SKIPPED"
EXEC_LICENSE_ERROR = "EXEC_LICENSE_ERROR"

# Functional Verification Statuses
VERIF_PASS = "VERIF_PASS"
VERIF_FAIL = "VERIF_FAIL"
VERIF_INVALID = "VERIF_INVALID"
VERIF_INCOMPLETE = "VERIF_INCOMPLETE"
VERIF_NOT_VERIFIED = "VERIF_NOT_VERIFIED"
VERIF_UNCHECKED = "VERIF_UNCHECKED"

# Reference Audit Statuses
AUDIT_MATCH = "AUDIT_MATCH"
AUDIT_MISMATCH = "AUDIT_MISMATCH"
AUDIT_MISSING_REF = "AUDIT_MISSING_REF"
AUDIT_SKIPPED = "AUDIT_SKIPPED"
AUDIT_INVALID = "AUDIT_INVALID"

@dataclass
class PortSpec:
    name: str
    direction: str  # "input", "output", "inout", or "" if unresolved
    width: int      # bit width (e.g. 4 for [3:0], 1 for single bit, -1 if dynamic/unresolved)
    range_str: str = "" # e.g. "[3:0]"
    is_signed: bool = False

@dataclass
class InstanceInfo:
    instance_name: str
    module_type: str
    port_connections: Dict[str, str] = field(default_factory=dict) # port_name -> connected_wire
    positional_connections: List[str] = field(default_factory=list) # ordered list of connected nets
    parameters: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ModuleInfo:
    name: str
    file_path: Path
    design_id: str = ""
    ports: Dict[str, PortSpec] = field(default_factory=dict)
    port_order: List[str] = field(default_factory=list) # preserves ANSI/non-ANSI port declaration order
    parameters: Dict[str, Any] = field(default_factory=dict)
    instantiations: List[InstanceInfo] = field(default_factory=list)
    internal_signals: Dict[str, PortSpec] = field(default_factory=dict) # net/reg name -> PortSpec
    tb_driven_signals: Set[str] = field(default_factory=set) # signals assigned/driven by testbench
    tb_observed_signals: Set[str] = field(default_factory=set) # signals sampled/read by testbench
    has_initial_block: bool = False
    system_calls: Set[str] = field(default_factory=set) # e.g. "$readmemh", "$display", "$finish"
    includes: List[str] = field(default_factory=list)
    is_testbench: bool = False
    is_ansi: bool = True
    has_clock: bool = False
    has_reset: bool = False
    is_sequential: bool = False
    parser_warnings: List[str] = field(default_factory=list)
    parser_name: str = "Tree-Sitter"

    def __post_init__(self):
        if not self.design_id:
            self.design_id = f"{self.file_path.stem}:{self.name}"
        if not self.port_order and self.ports:
            self.port_order = list(self.ports.keys())

@dataclass
class VectorMismatch:
    index: int
    inputs: Dict[str, Any]
    actual_outputs: Dict[str, Any]
    expected_outputs: Dict[str, Any]
    raw_message: str = ""

@dataclass
class CompatibilityEvidence:
    matched: bool
    reason: str
    match_type: str # "EXACT_NAME", "WRAPPER_COMPATIBLE", "INCOMPATIBLE"
    expected_module_name: str
    actual_module_name: str
    confidence: str = "CONFIRMED" # "CONFIRMED" (exact module contract), "HEURISTIC" (inferred)
    port_mapping: Dict[str, str] = field(default_factory=dict) # tb_port -> dut_port
    mismatches: List[str] = field(default_factory=list)
    wrapper_needed: bool = False
    is_ambiguous: bool = False
    ambiguity_reason: str = ""

@dataclass
class StaticAnalysisReport:
    module_name: str
    tool_used: str # e.g. "Yosys", "Built-in AST Static Lint"
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    inferred_latches: List[str] = field(default_factory=list)
    multi_driven_nets: List[str] = field(default_factory=list)
    unused_ports: List[str] = field(default_factory=list)

@dataclass
class DependencyResolutionResult:
    target_module: str
    required_source_files: List[Path] = field(default_factory=list)
    include_files: List[Path] = field(default_factory=list)
    missing_dependencies: List[str] = field(default_factory=list)
    circular_dependencies: List[List[str]] = field(default_factory=list)

    def __iter__(self):
        return iter(self.required_source_files)

    def __len__(self):
        return len(self.required_source_files)

    def __getitem__(self, item):
        return self.required_source_files[item]

@dataclass
class VerificationPlan:
    plan_id: str
    dut_name: str
    dut_module: str
    dut_file: Path
    tb_name: str
    tb_module: str
    tb_file: Path
    compatibility: CompatibilityEvidence
    required_sources: List[Path] # DUT + resolved dependencies + TB + wrapper if any
    data_files: List[Path] = field(default_factory=list) # Relevant LUT or memory files referenced by this TB
    missing_reference_files: List[str] = field(default_factory=list)
    unused_reference_files: List[str] = field(default_factory=list)
    include_files: List[Path] = field(default_factory=list)
    include_dirs: List[Path] = field(default_factory=list)
    build_dir: Path = field(default_factory=lambda: Path("build"))
    timeout_seconds: float = 5.0
    iverilog_flags: List[str] = field(default_factory=lambda: ["-g2012", "-Wall"])
    questa_flags: List[str] = field(default_factory=lambda: ["-sv", "-timescale", "1ns/1ps"])
    vsim_flags: List[str] = field(default_factory=list)
    simulator_name: str = "questa"
    verification_path: str = "PATH_A" # "PATH_A" (Existing TB) or "PATH_B" (Golden Reference Harness)
    wrapper_path: Optional[Path] = None

@dataclass
class TestResult:
    plan_id: str
    dut_name: str
    tb_name: str
    status: str
    passed_vectors: int = 0
    total_vectors: int = 0
    failed_vectors: int = 0
    elapsed_seconds: float = 0.0
    cached: bool = False
    content_hash: str = ""
    diagnostic_summary: str = ""
    failing_vectors: List[Dict[str, Any]] = field(default_factory=list)
    wrapper_used: bool = False
    confidence: str = "CONFIRMED"
    execution_status: str = "EXEC_SUCCESS"
    functional_status: str = "VERIF_PASS"
    audit_status: str = "AUDIT_MATCH"
    log_file: str = ""
    timestamp: str = ""
    static_analysis: Optional[Dict[str, Any]] = None
    simulator_name: str = "Icarus Verilog"
    reference_provenance: Optional[Dict[str, Any]] = None
