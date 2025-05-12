import json
from pprint import pformat
def inject_spawn_landing_zone(source_code: str, path_resolution: dict, command_line_args: dict, tree_node: dict) -> str:
    """
    Replace the LANDING ZONE block inside an agent source file with path injection values,
    and include minimal sys.path bootstrapping for core/agent resolution.
    Also replaces boot block with standardized: agent = Agent(...)
    """

    landing_start = "# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
    landing_end = "# ======== 🛬 LANDING ZONE END 🛬 ========"

    bootstrap = (
                f"import sys\n"
                f"import os\n"
                f"site_root = \"" + path_resolution["site_root_path"] + "\"\n"
                f"if site_root not in sys.path:\n"
                f"    sys.path.insert(0, site_root)\n"
                f"agent_path = \"" + path_resolution["agent_path"] + "\"\n"
                f"if agent_path not in sys.path:\n"
                f"    sys.path.insert(0, agent_path)\n"
                f"import agent\n"
            )

    injected = (
        f"{landing_start}\n"
        f"{bootstrap}\n"
        f"path_resolution = {json.dumps(path_resolution, indent=4)}\n"
        f"command_line_args = {json.dumps(command_line_args, indent=4)}\n"
        f"tree_node = {pformat(tree_node or {}, indent=4)}\n"
        f"path_resolution[\"pod_path_resolved\"]=os.path.dirname(os.path.abspath(__file__)) \n"
        f"{landing_end}"
    )

    if landing_start in source_code and landing_end in source_code:
        pre = source_code.split(landing_start)[0]
        post = source_code.split(landing_end)[1]
        return pre + injected + post
    else:
        return injected + "\n" + source_code
