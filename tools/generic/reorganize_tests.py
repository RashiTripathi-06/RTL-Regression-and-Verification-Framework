#!/usr/bin/env python3
"""
scripts/reorganize_tests.py

Moves and categorizes test files from tests/ into:
- tests/unit/
- tests/integration/
- tests/regression/

Updates sys.path and root directory references to Path(__file__).resolve().parents[2].
"""

import os
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent

unit_files = [
    'test_auditor.py', 'test_cache.py', 'test_dependency.py', 'test_matcher.py',
    'test_mutator.py', 'test_parser.py', 'test_posit_model.py', 'test_questa_adapter.py',
    'test_reference_manager.py', 'test_wrapper_validation.py'
]

integration_files = [
    'test_advanced_features.py', 'test_adversarial.py', 'test_cache_invalidation_comprehensive.py',
    'test_deep_dependencies.py', 'test_filename_invariance.py', 'test_generic_family.py',
    'test_interface_verification.py', 'test_lut_association.py', 'test_reference_verifier.py'
]

regression_files = [
    'test_end_to_end.py', 'test_reproducibility.py'
]

# Create __init__.py files
for p in ['tests', 'tests/unit', 'tests/integration', 'tests/regression']:
    init_f = root / p / '__init__.py'
    if not init_f.exists():
        init_f.write_text('# Package initialization\n', encoding='utf-8')

def transform_and_move(filename, target_dir):
    src_path = root / 'tests' / filename
    dst_path = root / 'tests' / target_dir / filename
    if not src_path.exists():
        if dst_path.exists():
            print(f"Already in {target_dir}: {filename}")
        else:
            print(f"Skipping {src_path}, not found.")
        return

    content = src_path.read_text(encoding='utf-8')

    # 1. Update ROOT / WORKSPACE_ROOT / ROOT_DIR definitions
    content = content.replace('Path(__file__).resolve().parents[1]', 'Path(__file__).resolve().parents[2]')
    content = content.replace('Path(__file__).resolve().parent.parent', 'Path(__file__).resolve().parents[2]')
    content = content.replace('Path(__file__).parent.parent / "src"', 'Path(__file__).resolve().parents[2] / "src"')

    # 2. Specific fixes for individual tests
    if filename == 'test_generic_family.py':
        if 'ROOT = Path(__file__).resolve().parents[2]' not in content:
            content = content.replace('from pathlib import Path\n', 'from pathlib import Path\nROOT = Path(__file__).resolve().parents[2]\n')
        content = content.replace('RegressionEngine(root_dir=Path("."))', 'RegressionEngine(root_dir=ROOT)')

    if filename == 'test_lut_association.py':
        if 'ROOT = Path(__file__).resolve().parents[2]' not in content:
            content = content.replace('from pathlib import Path\n', 'from pathlib import Path\nROOT = Path(__file__).resolve().parents[2]\n')
        content = content.replace('self.parser.parse_file(Path("tb/tb_counter.v"))', 'self.parser.parse_file(ROOT / "tb/tb_counter.v")')
        content = content.replace('self.parser.parse_file(Path("designs/counter_updown_4bit.v"))', 'self.parser.parse_file(ROOT / "designs/counter_updown_4bit.v")')

    if filename == 'test_reference_verifier.py':
        content = content.replace(
            'self.csv_ref = WORKSPACE_ROOT / "tb" / "golden_adder.csv"',
            'self.csv_ref = WORKSPACE_ROOT / "references" / "golden" / "golden_adder.csv"\n        if not self.csv_ref.exists():\n            self.csv_ref = WORKSPACE_ROOT / "tb" / "golden_adder.csv"'
        )
        content = content.replace(
            'self.json_ref = WORKSPACE_ROOT / "tb" / "golden_adder.json"',
            'self.json_ref = WORKSPACE_ROOT / "references" / "golden" / "golden_adder.json"\n        if not self.json_ref.exists():\n            self.json_ref = WORKSPACE_ROOT / "tb" / "golden_adder.json"'
        )

    dst_path.write_text(content, encoding='utf-8')
    src_path.unlink()
    print(f"Moved and updated: {filename} -> {target_dir}/{filename}")

def main():
    for f in unit_files:
        transform_and_move(f, 'unit')

    for f in integration_files:
        transform_and_move(f, 'integration')

    for f in regression_files:
        transform_and_move(f, 'regression')

    print("All test moves completed successfully.")

if __name__ == "__main__":
    main()
