"""
RTL Regression and Verification Framework (rtl_framework)
A publication-ready, independently reusable framework for automated RTL regression and verification.
"""

from .models import (
    ModuleInfo,
    PortSpec,
    InstanceInfo,
    CompatibilityEvidence,
    VerificationPlan,
    TestResult,
    VectorMismatch,
    STATUS_PASS,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
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
    STATUS_REFERENCE_DISPUTED,
    STATUS_REFERENCE_UNAVAILABLE,
    STATUS_LICENSE_ERROR,
    EXEC_SUCCESS,
    EXEC_COMPILE_ERROR,
    EXEC_SIMULATION_ERROR,
    EXEC_TIMEOUT,
    EXEC_SKIPPED,
    EXEC_LICENSE_ERROR,
    VERIF_PASS,
    VERIF_FAIL,
    VERIF_INVALID,
    VERIF_INCOMPLETE,
    VERIF_NOT_VERIFIED,
    VERIF_UNCHECKED,
    AUDIT_MATCH,
    AUDIT_MISMATCH,
    AUDIT_MISSING_REF,
    AUDIT_SKIPPED,
    AUDIT_INVALID,
)
from .parser import VerilogASTParser
from .scanner import ProjectScanner
from .dependency_resolver import DependencyResolver
from .matcher import DUTTestbenchMatcher, DUTTestbenchMatch
from .planner import VerificationPlanner
from .executor import (
    BaseSimulatorAdapter,
    IsolatedSimulatorExecutor,
    IcarusSimulatorAdapter,
    QuestaSimulatorAdapter,
    EdalizeSimulatorAdapter,
    VerilatorSimulatorAdapter,
    ExecutionResult,
)
from .auditor import VerificationAuditor
from .reference_verifier import (
    ParsedVector,
    ReferenceConfig,
    ReferenceTiming,
    ReferenceDataLoader,
    ReferenceVerificationEngine,
)
from .reference_manager import (
    ReferenceCategory,
    ReferenceSource,
    ReferenceResolver,
    ReferenceResolutionResult,
    ReferenceClassificationEngine,
)
from .static_analyzer import StaticRTLAnalyzer
from .wrapper_generator import generate_dut_wrapper
from .cache_manager import CacheManager
from .mutator import RTLMutator, Mutant, MutationReport
from .report_generator import ReportGenerator
from .engine import RegressionEngine
from .provider import ReferenceProvider, ExtensionRegistry
from .cli import main

__version__ = "1.0.0"

__all__ = [
    "RegressionEngine",
    "TestResult",
    "VerificationPlan",
    "ModuleInfo",
    "PortSpec",
    "InstanceInfo",
    "CompatibilityEvidence",
    "ParsedVector",
    "VectorMismatch",
    "VerilogASTParser",
    "ProjectScanner",
    "DependencyResolver",
    "DUTTestbenchMatcher",
    "DUTTestbenchMatch",
    "VerificationPlanner",
    "BaseSimulatorAdapter",
    "IsolatedSimulatorExecutor",
    "IcarusSimulatorAdapter",
    "QuestaSimulatorAdapter",
    "EdalizeSimulatorAdapter",
    "VerilatorSimulatorAdapter",
    "ExecutionResult",
    "VerificationAuditor",
    "ParsedVector",
    "ReferenceConfig",
    "ReferenceTiming",
    "ReferenceDataLoader",
    "ReferenceVerificationEngine",
    "ReferenceCategory",
    "ReferenceSource",
    "ReferenceResolver",
    "ReferenceResolutionResult",
    "ReferenceClassificationEngine",
    "StaticRTLAnalyzer",
    "generate_dut_wrapper",
    "CacheManager",
    "RTLMutator",
    "Mutant",
    "MutationReport",
    "ReportGenerator",
    "ReferenceProvider",
    "ExtensionRegistry",
    "main",
    "__version__",
]
