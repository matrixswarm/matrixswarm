import os

PACKAGE_DIR = "matrixswarm"

for root, dirs, files in os.walk(PACKAGE_DIR):
    # Skip hidden folders
    if any(part.startswith('.') for part in root.split(os.sep)):
        continue
    # Add __init__.py if missing
    init_path = os.path.join(root, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w", encoding="utf-8") as f:
            f.write("# MatrixSwarm package marker\n")
        print(f"Added: {init_path}")
    else:
        print(f"Exists: {init_path}")
print("✅ All done! Every package folder now has __init__.py.")