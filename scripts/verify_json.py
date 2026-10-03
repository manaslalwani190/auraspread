import json
import math
from pathlib import Path

def main():
    p = Path("web/data/auraspread_data.json")
    if not p.exists():
        print("ERROR: File does not exist")
        return
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("=== TOP-LEVEL STRUCTURE ===")
    for k, v in data.items():
        if isinstance(v, (list, dict)):
            print(f"  {k}: {type(v).__name__} with length {len(v)}")
        else:
            print(f"  {k}: {v}")

    # Check for NaN / Inf
    nan_count = 0
    null_count = 0
    total_values = 0

    def inspect(val, path):
        nonlocal nan_count, null_count, total_values
        total_values += 1
        if val is None:
            null_count += 1
        elif isinstance(val, float):
            if math.isnan(val) or math.isinf(val):
                nan_count += 1
                print(f"NaN/Inf at {path}: {val}")
        elif isinstance(val, str) and val.lower() in ("nan", "inf", "-inf"):
            nan_count += 1
            print(f"String NaN/Inf at {path}: {val}")
        elif isinstance(val, dict):
            for k, sub_v in val.items():
                inspect(sub_v, f"{path}.{k}")
        elif isinstance(val, list):
            for i, sub_v in enumerate(val):
                inspect(sub_v, f"{path}[{i}]")

    inspect(data, "root")
    print("\n=== DATA INTEGRITY SCAN ===")
    print(f"Total values checked: {total_values}")
    print(f"NaN / Inf count: {nan_count}")
    print(f"Null count: {null_count}")

if __name__ == "__main__":
    main()
