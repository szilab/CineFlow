"""Directory handler"""

import os
import shutil
from system.logger import log


class DirectoryHandler:
    """Directory handler class."""

    def __init__(self, path: str) -> None:
        """Initialize the directory handler."""
        self.path = path
        if path:
            try:
                os.makedirs(self.path, exist_ok=True)
                if self.usable():
                    log(f"Directory '{self.path}' initialized successfully.", level='DEBUG')
            except OSError as e:
                log(f"Error creating directory '{self.path}': {e}", level='WARNING')

    def usable(self) -> bool:
        """Check if the directory is usable."""
        if not self.path:
            log("Directory path is empty.", level='WARNING')
            return False
        if os.path.isdir(self.path) and os.access(self.path, os.W_OK):
            return True
        log(f"Directory '{self.path}' is not usable.", level='WARNING')
        return False

    def all(self) -> list:
        """Get the list of all directories in library."""
        if not self.usable():
            return []
        try:
            directories = []
            for d in os.listdir(self.path):
                if os.path.isdir(os.path.join(self.path, d)):
                    directories.append(os.path.join(self.path, d))
            log(f"Directories in library: '{len(directories)}'", level='DEBUG')
            return directories
        except OSError as e:
            log(f"Error listing directories: {e}", level='WARNING')
            return []

    def fix(self, name: str, strict: bool = False) -> tuple[str, str]:
        """Fix the paths in the library."""
        name = name.replace(':', '').replace('?', '').replace('/', '').replace(':', '')
        name = name.replace('*', '')
        if strict:
            name = name.lower().replace(' ', '_')
        return name

    def dir_path(self, directory: str) -> str:
        """Get the directory path."""
        if directory.startswith(self.path):
            return directory
        return os.path.join(self.path, self.fix(directory))

    def file_path(self, directory: str, file: str) -> str:
        """Get the file path."""
        directory_path = self.dir_path(directory)
        if file.startswith(self.path):
            return file
        return os.path.join(directory_path, self.fix(file, strict=True))

    def make(self, directory: str, file: str = None) -> bool:
        """Make a directory and file."""
        if not self.usable():
            return False
        try:
            directory_path = self.dir_path(directory)
            if not os.path.exists(directory_path):
                os.makedirs(directory_path, exist_ok=True)
                log(f"Directory '{directory}' created successfully.", level='DEBUG')
            if file:
                file_path = self.file_path(directory, file)
                if not os.path.exists(file_path):
                    with open(file=file_path, mode='w', encoding='UTF-8') as f:
                        f.write('')
                    log(f"File '{file}' created successfully.", level='DEBUG')
            return True
        except OSError as e:
            log(f"Error creating: {e}", level='WARNING')
            return False

    def remove(self, directory: str) -> bool:
        """Remove a directory."""
        if not self.usable():
            return False
        try:
            if directory.startswith(self.path):
                directory = self.fix(directory)
            else:
                directory = os.path.join(self.path, self.fix(directory))
            shutil.rmtree(directory, ignore_errors=True)
            log(f"Directory '{directory}' removed successfully.", level='DEBUG')
            return True
        except OSError as e:
            log(f"Error removing: {e}", level='WARNING')
            return False
