# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Collects validation issues before deploy

def validate_workspace(scene_items):
    errors = []
    has_matrix = False

    for item in scene_items:
        if item.node["name"].lower() == "matrix":
            has_matrix = True

        # Parent
        if item.node["name"].lower() != "matrix" and not item.node["parent"]:
            errors.append(f"{item.node['name']}: missing parent")

        # Connections
        if not item.node.get("connections"):
            errors.append(f"{item.node['name']}: missing connections")

        # Meta-based validation
        meta = item.node["meta"]
        params = item.node["params"]

        for fname, spec in meta.get("fields", {}).items():
            if spec.get("required") and not params.get(fname):
                errors.append(f"{item.node['name']}: missing required field {fname}")

    if not has_matrix:
        errors.append("Matrix agent required.")

    return errors
