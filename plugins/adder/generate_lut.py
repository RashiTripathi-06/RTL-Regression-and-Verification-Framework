from pathlib import Path

def generate_lut(path: Path) -> None:
    """Write 512 14-bit words: {a[3:0], b[3:0], cin, cout, sum[3:0]}."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "// Demo golden LUT for unsigned 4-bit addition",
        "// word = {a[3:0], b[3:0], cin, expected_cout, expected_sum[3:0]}"
    ]
    for idx in range(512):
        a = (idx >> 5) & 0xF
        b = (idx >> 1) & 0xF
        cin = idx & 1
        total = a + b + cin
        cout, summation = (total >> 4) & 1, total & 0xF
        word = (a << 10) | (b << 6) | (cin << 5) | (cout << 4) | summation
        lines.append(f"{word:04x}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

generate_golden_lut = generate_lut

if __name__ == "__main__":
    import sys
    ROOT = Path(__file__).resolve().parents[2]
    out = ROOT / "tb" / "adder_lut.mem"
    generate_lut(out)
    print(f"Generated {out}")
