import json
import os
import time
import tempfile


class TreeParser:
    CHILDREN_KEY = "children"
    PERMANENT_ID_KEY = "permanent_id"

    def __init__(self, root, tree_path=None):
        """
        Initialize the TreeParser with a root node.
        """
        self.root = root  # Root of the JSON tree
        self.nodes = {}  # Dictionary to store all parsed nodes
        self.duplicates = []  # To track any duplicate permanent IDs
        self.delegated = {}  # Any delegated data (not relevant here)
        self.tree_path = tree_path

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
        """
        # Handle empty or invalid nodes
        if not node:
            return

        # Extract the permanent ID of the node
        permanent_id = node.get(self.PERMANENT_ID_KEY)
        if not permanent_id:
            return

        # Check and process duplicates
        if permanent_id in self.nodes:
            self.duplicates.append(permanent_id)
            return

        # Add the node to self.nodes
        self._validate_and_store_node(node)

        # Debugging the state of self.nodes after adding
        print("Current state of self.nodes:")
        for key, value in self.nodes.items():
            print(f"")

        # Recursively process the children
        for child in node.get(self.CHILDREN_KEY, []):
            self._parse_nodes(child)

    def _validate_and_store_node(self, node):
        """
        Validates and stores a node, ensuring unique `permanent_id`.
        """
        permanent_id = node.get(self.PERMANENT_ID_KEY)
        if not permanent_id:
           return

        # Add the node if it's not a duplicate
        if permanent_id not in self.nodes:
            self.nodes[permanent_id] = node
        else:
            self.duplicates.append(permanent_id)
            return

        # Ensure children is properly initialized
        node.setdefault(self.CHILDREN_KEY, [])

    def get_first_level_child_ids(self, permanent_id):
        """
        Get a list of permanent_ids for all direct children of a node.
        """
        node = self._find_node(self.root, permanent_id)
        if not node:
            return []
        return [child["permanent_id"] for child in node.get(self.CHILDREN_KEY, []) if "permanent_id" in child]

    def get_first_level_children(self, permanent_id):
        """
        Retrieve all first-level children of the node with the given `permanent_id`.
        Only direct (one-level) children are included.
        """
        # Find the node in the tree using `_find_node`
        node = self._find_node(self.root, permanent_id)

        # If the node is not found, return an empty list
        if not node:
            return []

        # Get the immediate children
        first_level_children = node.get(self.CHILDREN_KEY, [])

        # Return the full children list (only one level down)
        return first_level_children

    def _find_node(self, node, permanent_id):
        """
        Recursively searches for a node by `permanent_id`.

        Args:
            node (dict): The current node being searched.
            permanent_id (str): The permanent ID of the target node.

        Returns:
            dict: The node with the matching `permanent_id`, or None if not found.
        """
        if not node:
            return None  # Base case: no node to search

        if node.get(self.PERMANENT_ID_KEY) == permanent_id:
            return node  # Found the target node

        # Recursively search children
        for child in node.get(self.CHILDREN_KEY, []):
            found = self._find_node(child, permanent_id)
            if found:  # Return as soon as the node is found
                return found

        return None  # Return None if the node is not found in the current branch

    def has_node(self, permanent_id):
        return permanent_id in self.nodes

    def insert_node(self, new_node, parent_permanent_id=None):
        """
        Insert a new node under the specified parent node.
        """
        new_permanent_id = new_node.get(self.PERMANENT_ID_KEY)
        if not new_permanent_id:
            raise ValueError("New node must have a `permanent_id`.")

        self._validate_and_store_node(new_node)

        parent_node = self.root if parent_permanent_id is None else self._find_node(self.root, parent_permanent_id)
        if not parent_node:
            raise ValueError(f"Parent with `permanent_id` {parent_permanent_id} not found.")

        parent_node[self.CHILDREN_KEY].append(new_node)

    def mark_confirmed(self, permanent_id):
        """
        Marks a node as confirmed by setting a timestamp.
        """
        node = self.nodes.get(permanent_id)
        if node:
            node["confirmed"] = time.time()
            return True
        return False

    def get_unconfirmed(self):
        """
        Returns a list of permanent_ids for nodes that are not confirmed.
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
        Validates the tree by checking for duplicate permanent_ids.
        """
        return len(self.duplicates) == 0

    def get_duplicates(self):
        """
        Retrieves a list of duplicate nodes.
        """
        return self.duplicates

    def get_child_count_by_id(self, permanent_id):
        """
        Returns the count of direct children for a node by `permanent_id`.
        """
        return len(self.query_children_by_id(permanent_id))

    def dump_all_nodes(self):
        """
        Prints all stored nodes in the tree.
        """
        print("Dumping all nodes in the tree:")

        if not self.nodes:
            print("(self.nodes is empty!)")
            return None  # No nodes to dump

        for permanent_id, node in self.nodes.items():
            print(f"Permanent ID: {permanent_id}, Node: {node}")

        return self.nodes  # Optionally return the `self.nodes` dictionary

    def extract_subtree_by_id(self, permanent_id):
        """
        Extract a full subtree rooted at the given `permanent_id`, including all children.
        Returns a deep copy of the node structure.
        """
        import copy
        root_node = self._find_node(self.root, permanent_id)
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

        if not isinstance(subtree, dict):
            return False

        new_root_id = subtree.get("permanent_id")
        if not new_root_id:
            return False

        if self.has_node(new_root_id):
            self.log(f"[MERGE] Root node {new_root_id} already exists. Merge aborted.")
            return False

        # Merge by attaching to root if not already present
        self.tree["children"].append(subtree)
        return True

    def get_all_nodes_flat(self):
        flat = {}

        def recurse(node):
            if isinstance(node, dict) and 'permanent_id' in node:
                flat[node['permanent_id']] = node
            for child in node.get('children', []):
                recurse(child)

        recurse(self.root)
        return flat
