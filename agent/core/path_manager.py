import os


class PathManager:
    """
    PathManager to manage paths relative to a root directory.
    Any incoming path is automatically treated as relative to the root unless explicitly absolute.
    """

    def __init__(self, root_path=None):
        """
        Initialize the PathManager and set the root directory.

        Args:
            root_path (str): Optional. The root path for the manager.
                             Defaults to two levels up from this file.
        """

        # Compute the root as two levels above the current file if not provided
        self.root_path = root_path or os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
        self.paths = {"root": self.root_path}  # Add the 'root' key by default

    def _ensure_root(self, path):
        """
        Ensure the given path is relative to the root, unless it's absolute.

        Args:
            path (str): Path to normalize.

        Returns:
            str: Path that is relative to the root if it is not already absolute.
        """
        return path if os.path.isabs(path) else os.path.abspath(os.path.join(self.root_path, path))

    def add_path(self, key, path):
        """
        Add a path associated with a key, treating relative paths as relative to root.

        Args:
            key (str): The identifier for the path.
            path (str): The absolute or relative path to store.
        """
        self.paths[key] = self._ensure_root(path)

    def add_paths(self, paths):
        """
        Add multiple paths from a dictionary where keys are identifiers and values are paths.

        Args:
            paths (dict): A dictionary of key-path mappings.

        Raises:
            ValueError: If the dictionary contains invalid keys or values.
        """
        if not isinstance(paths, dict):
            raise ValueError("Expected a dictionary for paths.")

        for key, path in paths.items():
            if not isinstance(key, str) or not isinstance(path, str):
                raise ValueError("Keys and values in the paths dictionary must be strings.")
            self.add_path(key, path)

    def get_path(self, key, trailing_slash=True):
        """
        Retrieve the path associated with the key.

        Args:
            key (str): The identifier for the path.
            trailing_slash (bool): Whether to ensure an OS-neutral trailing slash.

        Returns:
            str: The path with an optional trailing slash, or None if the key does not exist.
        """
        path = self.paths.get(key)
        if path and trailing_slash and not path.endswith(os.sep):
            path += os.sep
        return path

    def construct_path(self, *segments, trailing_slash=True):
        """
        Construct a path relative to the root by combining variable-length path segments.

        Args:
            *segments (str): Variable-length path components to construct the full path.
            trailing_slash (bool): Whether to ensure an OS-neutral trailing slash at the end.

        Returns:
            str: The constructed absolute path.
        """
        if not all(isinstance(segment, str) for segment in segments):
            raise ValueError("All path segments must be strings.")

        # Create the full path by joining root_path with the given segments
        full_path = os.path.join(self.root_path, *segments)

        # Optionally add a trailing slash
        if trailing_slash and not full_path.endswith(os.sep):
            full_path += os.sep

        return full_path

    def list_paths(self):
        """
        List all keys and their corresponding paths.

        Returns:
            dict: Dictionary of key-path mappings.
        """
        return self.paths
