from __future__ import annotations
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from models import (
    VerificationPlan,
    TestResult,
    STATUS_PASS,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR,
    STATUS_SIMULATION_ERROR,
    EXEC_SUCCESS,
)


@dataclass
class Mutant:
    mutant_id: str
    mutation_type: str  # AOR, BOR, OI, CS, BS, COA, ROR, SOR
    line_number: int
    original_line: str
    mutated_line: str
    mutated_content: str
    source_file: str = ""
    compile_result: str = "UNTESTED"  # PASS, COMPILE_ERROR
    sim_result: str = "UNTESTED"      # PASS, FAIL, TIMEOUT
    path_a_detected: str = "UNTESTED" # KILLED, SURVIVED
    path_b_detected: str = "UNTESTED" # KILLED, SURVIVED
    is_equivalent: bool = False
    status: str = "UNTESTED"          # KILLED, SURVIVED, STILLBORN


@dataclass
class MutationReport:
    dut_name: str
    tb_name: str
    total_mutants: int
    killed_mutants: int
    survived_mutants: int
    stillborn_mutants: int
    mutation_score: float  # (killed / (total - stillborn)) * 100%
    mutant_details: List[Mutant] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Mutation Analysis for {self.dut_name} with {self.tb_name}:\n"
            f"  Total Mutants:     {self.total_mutants}\n"
            f"  Killed Mutants:    {self.killed_mutants}\n"
            f"  Survived Mutants:  {self.survived_mutants}\n"
            f"  Stillborn:         {self.stillborn_mutants}\n"
            f"  Mutation Score:    {self.mutation_score:.1f}%\n"
        )


class RTLMutator:
    """
    Syntactic RTL Fault Injection Engine compliant with MANTRA2 principles.
    Injects single first-order faults into synthesizable Verilog modules.
    """

    OPERATOR_MAPS = {
        # Arithmetic Operator Replacement (AOR)
        "AOR": [
            (r"(?<=[a-zA-Z0-9_\)\]])\s*\+\s*(?=[a-zA-Z0-9_\(\[])", " - "),
            (r"(?<=[a-zA-Z0-9_\)\]])\s*\-\s*(?=[a-zA-Z0-9_\(\[])", " + "),
            (r"(?<=[a-zA-Z0-9_\)\]])\s*\*\s*(?=[a-zA-Z0-9_\(\[])", " + "),
        ],
        # Bitwise Operator Replacement (BOR)
        "BOR": [
            (r"(?<=[a-zA-Z0-9_\)\]])\s*&\s*(?=[a-zA-Z0-9_\(\[])", " | "),
            (r"(?<=[a-zA-Z0-9_\)\]])\s*\|\s*(?=[a-zA-Z0-9_\(\[])", " & "),
            (r"(?<=[a-zA-Z0-9_\)\]])\s*\^\s*(?=[a-zA-Z0-9_\(\[])", " & "),
        ],
        # Operand Inversion (OI)
        "OI": [
            (r"([=+\-*/&|^]\s*)([a-zA-Z_][a-zA-Z0-9_]*)", r"\g<1>~\g<2>"),
        ],
        # Constant Substitution (CS)
        "CS": [
            (r"\b1'b0\b", "1'b1"),
            (r"\b1'b1\b", "1'b0"),
            (r"\b4'b0000\b", "4'b0001"),
            (r"([=+\-*/&|^,]\s*)0([\s;,\)])", r"\g<1>1\g<2>"),
            (r"([=+\-*/&|^,]\s*)1([\s;,\)])", r"\g<1>0\g<2>"),
        ],
        # Condition Alteration (COA) / Logical Operators
        "COA": [
            (r"&&", "||"),
            (r"\|\|", "&&"),
        ],
        # Relational Operator Replacement (ROR)
        "ROR": [
            (r"==", "!="),
            (r"!=", "=="),
            (r">=", "<"),
            (r"<=", ">"),
        ],
        # Shift Operator Replacement (SOR)
        "SOR": [
            (r"<<", ">>"),
            (r">>", "<<"),
        ]
    }

    @classmethod
    def generate_mutants(cls, dut_path: Path, max_mutants: int = 20) -> List[Mutant]:
        if not dut_path.exists():
            return []

        lines = dut_path.read_text(encoding="utf-8").splitlines()
        mutants: List[Mutant] = []
        mut_idx = 1

        for line_idx, line in enumerate(lines):
            stripped = line.strip()
            # Skip comments, module declarations, pragmas
            if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("module") or stripped.startswith("endmodule") or stripped.startswith("`"):
                continue

            # Check each mutation type
            for op_type, replacements in cls.OPERATOR_MAPS.items():
                for pat, rep in replacements:
                    if re.search(pat, line):
                        # Generate single replacement
                        mutated_line = re.sub(pat, rep, line, count=1)
                        if mutated_line != line:
                            # Construct full mutated file content
                            mut_lines = list(lines)
                            mut_lines[line_idx] = mutated_line
                            mut_content = "\n".join(mut_lines) + "\n"

                            mutant = Mutant(
                                mutant_id=f"MUT_{op_type}_{mut_idx:03d}",
                                mutation_type=op_type,
                                line_number=line_idx + 1,
                                original_line=line.strip(),
                                mutated_line=mutated_line.strip(),
                                mutated_content=mut_content
                            )
                            mutants.append(mutant)
                            mut_idx += 1
                            if len(mutants) >= max_mutants:
                                return mutants
        return mutants


class MutationQualifier:
    """
    Evaluates testbench defect detection efficacy by running verification against RTL mutants.
    """

    @classmethod
    def qualify_testbench(
        cls,
        plan: VerificationPlan,
        mutants: List[Mutant],
        engine_runner: Any,
        build_base_dir: Path
    ) -> MutationReport:
        killed = 0
        survived = 0
        stillborn = 0

        build_base_dir.mkdir(parents=True, exist_ok=True)

        for mutant in mutants:
            mut_dir = build_base_dir / mutant.mutant_id
            mut_dir.mkdir(parents=True, exist_ok=True)

            # Write mutated DUT
            mut_dut_file = mut_dir / plan.dut_file.name
            mut_dut_file.write_text(mutant.mutated_content, encoding="utf-8")

            # Create an isolated plan copy with mutated DUT
            mut_sources = [
                mut_dut_file if p.resolve() == plan.dut_file.resolve() else p
                for p in plan.required_sources
            ]

            # Run execution via provided runner
            try:
                res = engine_runner(mut_dut_file, mut_sources, mut_dir)
                if res.status == STATUS_COMPILE_ERROR:
                    mutant.status = "STILLBORN"
                    stillborn += 1
                elif res.status in (STATUS_PASS, STATUS_PASS_REFERENCE_VERIFIED, STATUS_PASS_TESTBENCH_ONLY):
                    # Testbench failed to detect the injected bug!
                    mutant.status = "SURVIVED"
                    survived += 1
                else:
                    # Testbench caught the bug (FUNCTIONAL_FAIL, SIMULATION_ERROR, INVALID_RESULTS)
                    mutant.status = "KILLED"
                    killed += 1
            except Exception:
                mutant.status = "KILLED"
                killed += 1

        valid_mutants = killed + survived
        ms = (killed / valid_mutants * 100.0) if valid_mutants > 0 else 0.0

        return MutationReport(
            dut_name=plan.dut_name,
            tb_name=plan.tb_name,
            total_mutants=len(mutants),
            killed_mutants=killed,
            survived_mutants=survived,
            stillborn_mutants=stillborn,
            mutation_score=ms,
            mutant_details=mutants
        )
