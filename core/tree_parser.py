#Authored by Daniel F MacDonald and ChatGPT
import json
import os
import time
import tempfile

class TreeParser:
    CHILDREN_KEY = "children"
    UNIVERSAL_ID_KEY = "universal_id"

    def __init__(self, root, tree_path=None):
        """
        Initialize the TreeParser with a root node.
        """
        self.root = root  # Root of the JSON tree
        self.nodes = {}  # Dictionary to store all parsed nodes
        self.duplicates = []  # To track any duplicate permanent IDs
        self.delegated = {}  # Any delegated data (not relevant here)
        self.tree_path = tree_path
        self.rejected_subtrees = []  # Track rejected universal_ids

    def _initialize_data(self, data):
        """
        Ensures the input data is a dictionary. If string, attempts to parse as JSON.
        """
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {}
        return data if isinstance(data, dict) else {}

    def _parse_nodes(self, node):
        """
        Recursively parse nodes and store them into self.nodes.
        Rejects entire subtrees if a duplicate universal_id is found.
        """
        if not node or not isinstance(node, dict):
            return

        universal_id = node.get(self.UNIVERSAL_ID_KEY)
        if not universal_id:
            return

        if universal_id in self.nodes:
            print(f"[TREE-REJECT] ❌ Duplicate universal_id '{universal_id}' — rejecting this subtree and all children.")
            self.duplicates.append(universal_id)
            self.rejected_subtrees.append(universal_id)
            return  # Skip entire subtree

        self._validate_and_store_node(node)

        for child in node.get(self.CHILDREN_KEY, []):
            self._parse_nodes(child)

    def _validate_and_store_node(self, node):
        """
        Validates and stores a node, ensuring unique `universal_id`.
        """
        universal_id = node.get(self.UNIVERSAL_ID_KEY)
        if not universal_id:
           return

        # Clean up malformed children
        valid_children = []
        for child in node.get(self.CHILDREN_KEY, []):
           if isinstance(child, dict) and child.get("universal_id"):
               valid_children.append(child)
           else:
               print(f"[TREE] ⚠️ Malformed child skipped: {child}")

        node[self.CHILDREN_KEY] = valid_children
        node.setdefault(self.CHILDREN_KEY, [])

        # Add the node if it's not a duplicate
        if universal_id not in self.nodes:
            self.nodes[universal_id] = node
        else:
            self.duplicates.append(universal_id)
            return

        # Ensure children is properly initialized
        node.setdefault(self.CHILDREN_KEY, [])

    def get_first_level_child_ids(self, universal_id):
        """
        Get a list of universal_ids for all direct children of a node.
        """
        node = self._find_node(self.root, universal_id)
        if not node:
            return []
        return [child["universal_id"] for child in node.get(self.CHILDREN_KEY, []) if "universal_id" in child]

    def get_first_level_children(self, universal_id):
        """
        Retrieve all first-level children of the node with the given `universal_id`.
        Only direct (one-level) children are included.
        """
        # Find the node in the tree using `_find_node`
        node = self._find_node(self.root, universal_id)

        # If the node is not found, return an empty list
        if not node:
            return []

        # Get the immediate children
        first_level_children = node.get(self.CHILDREN_KEY, [])

        # Return the full children list (only one level down)
        return first_level_children

    def _find_node(self, node, universal_id):
        """
        Recursively searches for a node by `universal_id`.

        Args:
            node (dict): The current node being searched.
            universal_id (str): The permanent ID of the target node.

        Returns:
            dict: The node with the matching `universal_id`, or None if not found.
        """
        if not node:
            return None  # Base case: no node to search

        if node.get(self.UNIVERSAL_ID_KEY) == universal_id:
            return node  # Found the target node

        # Recursively search children
        for child in node.get(self.CHILDREN_KEY, []):
            found = self._find_node(child, universal_id)
            if found:  # Return as soon as the node is found
                return found

        return None  # Return None if the node is not found in the current branch

    def insert_node(self, new_node, parent_universal_id=None):
        """
        Insert a new node under the specified parent node.
        """
        new_universal_id = new_node.get(self.UNIVERSAL_ID_KEY)
        if not new_universal_id:
            raise ValueError("New node must have a `universal_id`.")

        new_node = TreeParser.strip_invalid_nodes(new_node)
        if not new_node:
            raise ValueError("New node rejected due to missing name or universal_id.")

        self._validate_and_store_node(new_node)

        parent_node = self.root if parent_universal_id is None else self._find_node(self.root, parent_universal_id)
        if not parent_node:
            raise ValueError(f"Parent with `universal_id` {parent_universal_id} not found.")

        parent_node[self.CHILDREN_KEY].append(new_node)

        return True

    @staticmethod
    def strip_invalid_nodes(tree):
        """
        Recursively remove nodes (and all subtrees) where 'name' or 'universal_id' is missing or blank.
        """
        if not isinstance(tree, dict):
            return None

        name = tree.get("name", "").strip()
        uid = tree.get("universal_id", "").strip()

        if not name or not uid:
            print(f"[TREE-CLEAN] 🧹 Removed invalid node: name='{name}', universal_id='{uid}'")
            return None

        cleaned_children = []
        for child in tree.get("children", []):
            cleaned = TreeParser.strip_invalid_nodes(child)
            if cleaned:
                cleaned_children.append(cleaned)

        tree["children"] = cleaned_children
        return tree

    def mark_confirmed(self, universal_id):
        """
        Marks a node as confirmed by setting a timestamp.
        """
        node = self.nodes.get(universal_id)
        if node:
            node["confirmed"] = time.time()
            return True
        return False

    def get_unconfirmed(self):
        """
        Returns a list of universal_ids for nodes that are not confirmed.
        """
        return [p for p, node in self.nodes.items() if "confirmed" not in node]

    def dump_tree(self, output_path):
        """
        Saves the current tree structure to a file.
        """
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(output_path)) as temp_file:
                json.dump(self.root, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = temp_file.name
            os.replace(temp_path, output_path)
            return True
        except Exception as e:
            # print(f"[TREE-DUMP-ERROR] Failed to save tree: {e}")
            return False

    def save_tree(self, output_path=None):
        """
        Save the current tree to disk. Uses the original path if output_path is not provided.
        """
        if not output_path and hasattr(self, 'tree_path'):
            output_path = self.tree_path

        if not output_path:
            self.log("[TREE] No output path specified for save().")
            return False

        try:
            with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(output_path)) as temp_file:
                json.dump(self.root, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = temp_file.name
            os.replace(temp_path, output_path)
            return True
        except Exception as e:
            self.log(f"[TREE] Failed to save tree: {e}")
            return False

    def is_valid_tree(self):
        """
        Validates the tree by checking for duplicate universal_ids.
        """
        return len(self.duplicates) == 0

    def get_duplicates(self):
        """
        Retrieves a list of duplicate nodes.
        """
        return self.duplicates

    def get_child_count_by_id(self, universal_id):
        """
        Returns the count of direct children for a node by `universal_id`.
        """
        return len(self.query_children_by_id(universal_id))

    def dump_all_nodes(self):
        """
        Prints all stored nodes in the tree.
        """
        print("Dumping all nodes in the tree:")

        if not self.nodes:
            print("(self.nodes is empty!)")
            return None  # No nodes to dump

        for universal_id, node in self.nodes.items():
            print(f"Permanent ID: {universal_id}, Node: {node}")

        return self.nodes  # Optionally return the `self.nodes` dictionary

    def extract_subtree_by_id(self, universal_id):
        """
        Extract a full subtree rooted at the given `universal_id`, including all children.
        Returns a deep copy of the node structure.
        """
        import copy
        root_node = self._find_node(self.root, universal_id)
        if not root_node:
            return None

        return copy.deepcopy(root_node)

    def save(self, output_path=None):
        """
        Save the current tree to disk. Uses the original path if output_path is not provided.
        """
        if not output_path and hasattr(self, 'tree_path'):
            output_path = self.tree_path

        if not output_path:
            #self.log("[TREE] No output path specified for save().")
            return False

        try:
            with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(output_path)) as temp_file:
                json.dump(self.root, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = temp_file.name
            os.replace(temp_path, output_path)
            return True
        except Exception as e:
            #self.log(f"[TREE] Failed to save tree: {e}")
            return False

    def remove_exact_node(self, target_node):
        """
        Recursively remove the exact instance of a node from the tree by identity.
        """

        def recurse(node):
            if not isinstance(node, dict):
                return False

            children = node.get(self.CHILDREN_KEY, [])
            for i, child in enumerate(children):
                if child is target_node:
                    del children[i]
                    print(f"[TREE-PRECISION] 🎯 Removed node '{target_node.get(self.UNIVERSAL_ID_KEY)}'")
                    return True
                if recurse(child):  # Dive deeper
                    return True
            return False

        # Start at root
        return recurse(self.root)

    def pre_scan_for_duplicates(self, node):
        """
        Pre-scan the tree to detect duplicates and remove all but the first instance.
        """
        from collections import defaultdict

        seen = defaultdict(list)

        def recurse(n, path="root"):
            if not isinstance(n, dict):
                return
            uid = n.get(self.UNIVERSAL_ID_KEY)
            if uid:
                seen[uid].append(n)
            for child in n.get(self.CHILDREN_KEY, []):
                recurse(child, path + f" > {uid}")

        recurse(node)

        # Keep the first instance, remove all subsequent ones
        for uid, instances in seen.items():
            if len(instances) > 1:
                print(f"[TREE-SCAN] ⚠️ Found {len(instances)} clones of '{uid}' — purging {len(instances) - 1}")
                self.rejected_subtrees.append(uid)
                # Remove by ID, not direct node, so cleanup will strike even deep ghosts
                for dup_node in instances[1:]:
                    self.remove_exact_node(dup_node)
                    self.rejected_subtrees.append(uid)

    @classmethod
    def load_tree(cls, input_path):
        try:
            # Load JSON data
            with open(input_path, "r") as f:
                data = json.load(f)

            #    print("Successfully loaded JSON data:", data)

            # Create TreeParser instance and parse root node
            instance = cls(data)  # Root node initialized
            #   print("Calling _parse_nodes once...")
            instance._parse_nodes(instance.root)  # Parse the tree
            return instance  # Correctly return the instance

        except Exception as e:  # Catch exceptions like FileNotFoundError or JSONDecodeError
            #  print(f"Error occurred while loading tree: {e}")
            return None  # Handle failure to load data gracefully

    @classmethod
    def load_tree_direct(cls, data):

        """
        Load tree from raw directive dict with agent_tree and services.
        """


        if isinstance(data, dict) and "agent_tree" in data:
            root_tree = data["agent_tree"]
            services = data.get("services", [])
        else:
            root_tree = data
            services = []


        instance = cls(root_tree)
        instance._service_manager_services = services  # inject globally scoped services
        instance.cleanse()
        instance.pre_scan_for_duplicates(instance.root)
        instance._parse_nodes(instance.root)
        return instance


    def _remove_node_and_children(self, target_uid):
        """
        Removes the node and its entire subtree from the tree.
        """
        parent = self.find_parent_of(target_uid)

        if parent:
            children = parent.get(self.CHILDREN_KEY, [])
            parent[self.CHILDREN_KEY] = [
                c for c in children if c.get(self.UNIVERSAL_ID_KEY) != target_uid
            ]
            print(f"[TREE-REMOVE] 🌪 Removed duplicate subtree '{target_uid}' from parent '{parent.get(self.UNIVERSAL_ID_KEY)}'")
        elif self.root.get(self.UNIVERSAL_ID_KEY) == target_uid:
            print(f"[TREE-REMOVE] 🌪 Root node is duplicate '{target_uid}', clearing root.")
            self.root = {self.UNIVERSAL_ID_KEY: "root", self.CHILDREN_KEY: []}


    @staticmethod
    def flatten_tree(subtree):
        nodes = []

        def recurse(node):
            if not isinstance(node, dict):
                return
            if "agent_name" in node and "name" not in node:
                node["name"] = node["agent_name"]
            nodes.append(node)
            for child in node.get("children", []):
                recurse(child)

        recurse(subtree)
        return nodes

    def merge_subtree(self, subtree):
        """
        Attempt to merge a subtree into the tree. Rejects if any duplicate universal_ids exist.
        """
        if not isinstance(subtree, dict):
            return False

        # 🧹 Clean out nameless nodes
        subtree = TreeParser.strip_invalid_nodes(subtree)
        if not subtree:
            print("[MERGE-REJECT] Entire subtree rejected due to invalid root node.")
            return False

        # Pre-scan for duplicate universal_ids
        new_ids = {node["universal_id"] for node in self.flatten_tree(subtree) if "universal_id" in node}
        collision = new_ids.intersection(set(self.nodes.keys()))
        if collision:
            print(f"[MERGE-REJECT] ❌ Subtree rejected due to duplicate IDs: {list(collision)}")
            self.duplicates.extend(collision)
            self.rejected_subtrees.extend(collision)
            return False

        new_root_id = subtree.get("universal_id")
        if not new_root_id:
            return False

        self._parse_nodes(subtree)
        self.root[self.CHILDREN_KEY].append(subtree)
        return True

    def get_all_nodes_flat(self):
        flat = {}

        def recurse(node):
            if isinstance(node, dict) and 'universal_id' in node:
                flat[node['universal_id']] = node
            for child in node.get('children', []):
                recurse(child)

        recurse(self.root)
        return flat

    def load_dict(self, data):
        """
        Load a tree from a raw Python dictionary and return the cleansed version.
        """
        self.root = self._initialize_data(data)
        self.cleanse()
        return self.root

    def cleanse(self):
        """
        Fully cleanse the entire root tree including children.
        """

        def recursive_purge(node):
            if not isinstance(node, dict) or not node.get(self.UNIVERSAL_ID_KEY):
                return None

            clean_children = []
            for child in node.get(self.CHILDREN_KEY, []):
                clean = recursive_purge(child)
                if clean:
                    clean_children.append(clean)
                else:
                    print(f"[TREE] ⚠️ Removed malformed node during cleanse: {child}")

            node[self.CHILDREN_KEY] = clean_children
            return node

        self.root = recursive_purge(self.root)
        return self.root

    def find_parent_of(self, child_universal_id):
        """
        Recursively find the parent node that has a child with the given universal_id.
        """

        def recurse(node):
            if not node or not isinstance(node, dict):
                print(f"[RECURSE] Skipping bad node: {node}")
                return None

            children = node.get(self.CHILDREN_KEY, [])
            if not isinstance(children, list):
                print(f"[RECURSE] Children field is not a list for node: {node}")
                return None

            for child in children:
                if not isinstance(child, dict):
                    print(f"[RECURSE] Skipping bad child: {child}")
                    continue  # skip non-dict children

                child_perm = child.get(self.UNIVERSAL_ID_KEY, None)
                if child_perm == child_universal_id:
                    print(f"[RECURSE] FOUND parent of {child_universal_id} under node {node.get(self.UNIVERSAL_ID_KEY)}")
                    return node

                result = recurse(child)
                if result:
                    return result

            return None

        print(f"[FIND_PARENT] Starting parent search for {child_universal_id}")
        return recurse(self.root)

    def get_subtree_nodes(self, universal_id):
        """
        Get all nodes under and including the given universal_id.
        """
        if universal_id not in self.nodes:
            return []

        result = []

        def collect(node):
            result.append(node[self.UNIVERSAL_ID_KEY])
            for child in node.get(self.CHILDREN_KEY, []):
                collect(child)

        collect(self.nodes[universal_id])
        return result

    def walk_tree(self, node):
        nodes = [node]
        for child in node.get("children", []):
            nodes.extend(self.walk_tree(child))
        return nodes

    def all_universal_ids(self):
        return [n["universal_id"] for n in self.walk_tree(self.root)]

    def get_node(self, universal_id):
        for node in self.walk_tree(self.root):
            if node.get("universal_id") == universal_id:
                return node
        return None

    def has_node(self, universal_id):
        return self.get_node(universal_id) is not None

    def get_service_managers(self, caller_universal_id=None):
        """
        Returns a flat list of all nodes that have a non-empty 'service-manager' field
        under their config.
        If caller_universal_id is provided, it annotates each service with:
            - _is_child: True if the caller is an ancestor of the service node
            - _level: depth from caller to service node (0 if same, 1 if direct child, etc)
        """
        service_nodes = []

        def recurse(node, path_stack):
            if not isinstance(node, dict):
                return

            config = node.get("config", {})
            universal_id = node.get("universal_id")
            full_path = path_stack + [universal_id] if universal_id else path_stack

            if config.get("service-manager") and (universal_id != caller_universal_id):
                annotated_node = dict(node)  # shallow copy

                if caller_universal_id and caller_universal_id in full_path:
                    idx = full_path.index(caller_universal_id)
                    annotated_node["_is_child"] = True
                    annotated_node["_level"] = len(full_path) - idx - 1
                else:
                    annotated_node["_is_child"] = False
                    annotated_node["_level"] = None

                service_nodes.append(annotated_node)

            for child in node.get("children", []):
                recurse(child, full_path)

        recurse(self.root, [])
        return service_nodes

