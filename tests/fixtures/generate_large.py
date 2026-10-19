#!/usr/bin/env python3
"""Generate a large synthetic CSV (not committed). Streaming, constant memory, seeded.

Default: 1,000,000 rows x 10 columns (~100 MB), the REQ-61 performance target.
Usage: python3 tests/fixtures/generate_large.py [--rows N] [--out PATH] [--seed S]
Default output: data/fixtures/large_orders.csv (git-ignored).
Columns: id,email,country,status,amount,order_date,is_gift,quantity,sku,note
Every row is valid for a pipeline that casts the obvious types.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

HEADER = "id,email,country,status,amount,order_date,is_gift,quantity,sku,note\n"
COUNTRIES = ("US", "DE", "FR", "MX", "CA", "GB")
STATUSES = ("pending", "completed", "cancelled")


def generate(path: Path, rows: int, seed: int) -> int:
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(HEADER)
        buf: list[str] = []
        for i in range(1, rows + 1):
            buf.append(
                f"{i},user{i}@example.com,{rng.choice(COUNTRIES)},{rng.choice(STATUSES)},"
                f"{rng.uniform(0, 1000):.2f},20{rng.randint(10, 29)}-{rng.randint(1, 12):02d}-"
                f"{rng.randint(1, 28):02d},{rng.choice(('true', 'false'))},{rng.randint(1, 20)},"
                f"SKU-{rng.randint(0, 99999):05d},synthetic row {i} lorem ipsum dolor\n"
            )
            if len(buf) >= 10_000:
                fh.write("".join(buf))
                buf.clear()
        fh.write("".join(buf))
    return path.stat().st_size


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rows", type=int, default=1_000_000)
    ap.add_argument("--out", type=Path, default=Path("data/fixtures/large_orders.csv"))
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    size = generate(a.out, a.rows, a.seed)
    print(f"wrote {a.rows} rows, {size / 1e6:.1f} MB -> {a.out}")


if __name__ == "__main__":
    main()
