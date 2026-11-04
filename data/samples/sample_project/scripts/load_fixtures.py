# Script-style module with no functions: scored as a single <module> unit.
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "fixtures.json"
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

count = 0
for item in data.get("products", []):
    if item.get("stock", 0) > 0:
        count += 1
print(f"{count} products in stock")
