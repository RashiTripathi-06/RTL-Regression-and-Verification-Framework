# RTL Mutation Testing Analysis Report (MANTRA2 Methodology)

## Executive Summary

- **Total Mutants Generated**: 7
- **Compilable Mutants**: 7
- **Stillborn Mutants (Compile Failures)**: 0
- **Mutants Killed by Path A (Legacy TB)**: 0 (0.0%)
- **Mutants Killed by Path B (Golden Reference)**: 7 (100.0%)
- **Mutants Killed by Both**: 0
- **Mutants Surviving Both**: 0
- **Combined Mutation Score**: 100.0%

## Detailed Fault Injection Records

| Mutant ID | Operator | Target Module | File & Line | Original Code | Mutated Code | Comp | Sim | Path A | Path B | Equiv? |
|---|---|---|---|---|---|---|---|---|---|---|
| MUT_BOR_001 | BOR | full_adder | `designs\common\full_adder.v:10` | `assign sum  = a ^ b ^ cin;` | `assign sum  = a & b ^ cin;` | PASS | PASS | **SURVIVED** | **KILLED** | False |
| MUT_OI_002 | OI | full_adder | `designs\common\full_adder.v:10` | `assign sum  = a ^ b ^ cin;` | `assign sum  = ~a ^ b ^ cin;` | PASS | PASS | **SURVIVED** | **KILLED** | False |
| MUT_BOR_003 | BOR | full_adder | `designs\common\full_adder.v:11` | `assign cout = (a & b) | (b & cin) | (a & cin);` | `assign cout = (a | b) | (b & cin) | (a & cin);` | PASS | PASS | **SURVIVED** | **KILLED** | False |
| MUT_BOR_004 | BOR | full_adder | `designs\common\full_adder.v:11` | `assign cout = (a & b) | (b & cin) | (a & cin);` | `assign cout = (a & b) & (b & cin) | (a & cin);` | PASS | PASS | **SURVIVED** | **KILLED** | False |
| MUT_OI_005 | OI | full_adder | `designs\common\full_adder.v:11` | `assign cout = (a & b) | (b & cin) | (a & cin);` | `assign cout = (a & ~b) | (b & cin) | (a & cin);` | PASS | PASS | **SURVIVED** | **KILLED** | False |
| MUT_AOR_001 | AOR | adder_behavioral | `designs\adder_behavioral.v:9` | `assign {cout, sum} = a + b + cin;` | `assign {cout, sum} = a - b + cin;` | PASS | PASS | **SURVIVED** | **KILLED** | False |
| MUT_OI_002 | OI | adder_behavioral | `designs\adder_behavioral.v:9` | `assign {cout, sum} = a + b + cin;` | `assign {cout, sum} = ~a + b + cin;` | PASS | PASS | **SURVIVED** | **KILLED** | False |

## Mutation Operators Handled

1. **AOR (Arithmetic Operator Replacement)**: `+` <-> `-`, `*` -> `+`
2. **BOR (Bitwise Operator Replacement)**: `&` <-> `|`, `^` -> `&`
3. **OI (Operand Inversion)**: `sig` -> `~sig`
4. **CS (Constant Substitution)**: `1'b0` <-> `1'b1`, `0` <-> `1`
5. **COA (Condition Operator Alteration)**: `&&` <-> `||`
6. **ROR (Relational Operator Replacement)**: `==` <-> `!=`, `>=` <-> `<`, `<=` <-> `>`
7. **SOR (Shift Operator Replacement)**: `<<` <-> `>>`

## Scope, Limitations, and Threats to Validity

- **Scope**: First-order syntactic fault injection in synthesizable Verilog modules.
- **Empirical Insight on Testbench Quality**: Legacy testbenches that perform weak checks (such as `tb_alu.v` checking only that signals are not X) fail to kill arithmetic/logic mutants (`SURVIVED`). Conversely, Path B independent reference checking drives vectors systematically against golden models and kills 100% of functional mutants.
- **Equivalent Mutants**: Mutants that produce functionally identical transfer functions across the operational domain are identified when both Path A and exhaustive Path B pass.
- **Threats to Validity**: Complex multi-cycle protocol bugs and timing closure issues are outside the scope of combinatorial/pipeline single-fault syntactic mutators.
