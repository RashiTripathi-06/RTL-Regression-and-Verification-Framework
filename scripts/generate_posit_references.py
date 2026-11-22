import csv
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "plugins" / "posit"))
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from posit_model import PositModel

def generate_datasets():
    tb_dir = WORKSPACE_ROOT / "tb"
    tb_dir.mkdir(parents=True, exist_ok=True)

    pm = PositModel(n=16, es=2)

    # 1. Corner cases dataset
    corners = [
        0x0000, 0x8000, 0x4000, 0xC000, 0x4800, 0x3800,
        0x0001, 0x7FFF, 0x8001, 0xFFFF, 0x2000, 0x6000
    ]
    corner_vecs = []
    for a in corners:
        for b in corners:
            prod = pm.multiply(a, b)
            corner_vecs.append({
                "opd_a": f"{a:04x}",
                "opd_b": f"{b:04x}",
                "expected_product": f"{prod:04x}"
            })

    corner_file = tb_dir / "posit_mult_corners.csv"
    with open(corner_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["opd_a", "opd_b", "expected_product"])
        writer.writeheader()
        writer.writerows(corner_vecs)
    print(f"Generated {len(corner_vecs)} corner vectors in {corner_file}")

    # 2. Sample fixed_a = 0x4800 (as in tb_multiplier (2).v)
    sample_vecs = []
    fixed_a = 0x4800
    for b in range(0, 256):  # 256 representative sweep points
        prod = pm.multiply(fixed_a, b)
        sample_vecs.append({
            "opd_a": f"{fixed_a:04x}",
            "opd_b": f"{b:04x}",
            "expected_product": f"{prod:04x}"
        })

    sample_file = tb_dir / "posit_mult_sample.csv"
    with open(sample_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["opd_a", "opd_b", "expected_product"])
        writer.writeheader()
        writer.writerows(sample_vecs)
    print(f"Generated {len(sample_vecs)} sample sweep vectors in {sample_file}")

if __name__ == "__main__":
    generate_datasets()
