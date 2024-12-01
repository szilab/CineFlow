from typing import Any
from shutil import rmtree
from pathlib import Path
from system.logger import log
from system.misc import write_json, read_json


class FileHandler:
    def __init__(self, base_path: str) -> None:
        self._path = Path(base_path)

    def create_directory(self, item: str) -> None:
        """
        Create a directory if it does not exist.
        :param item: The name of the directory to create.
        """
        dir_path = self._path / item
        if not dir_path.exists():
            log(f"Creating directory: {dir_path}", level='DEBUG')
            dir_path.mkdir(parents=True)

    def remove_directory(self, item: str) -> None:
        """
        Remove a directory if it exists.
        :param item: The name of the directory to remove.
        """
        dir_path = self._path / item
        if dir_path.exists():
            log(f"Removing directory: {dir_path}", level='DEBUG')
            rmtree(dir_path)

    def add_file(self, item: str, file_name: str, content: Any = None) -> None:
        """
        Add a file to a directory.
        :param item: The name of the directory to add the file to.
        :param file_name: The name of the file to add.
        :param content: The content to write to the file
        """
        self.create_directory(item)
        file_path = self._path / item / file_name
        if content:
            if isinstance(content, dict) or isinstance(content, list):
                write_json(path=file_path, data=content)
                # log(f"Writing json data to file: {file_path}", level='DEBUG')
            elif isinstance(content, str):
                file_path.write_text(content)
                # log(f"Writing text data to file: {file_path}", level='DEBUG')
            elif isinstance(content, bytes):
                file_path.write_bytes(content)
                # log(f"Writing bytes data to file: {file_path}", level='DEBUG')
        else:
            log(f"Creating empty file: {file_path}", level='DEBUG')
            file_path.touch()

    def get_file(self, item: str, file_name: str, typeof: str) -> Any:
        """
        Get the content of a file.
        :param item: The name of the directory to get the file from.
        :param file_name: The name of the file to get.
        :param typeof: The type of the file content to return.
        """
        file_path = self._path / item / file_name
        if file_path.exists():
            if typeof == "json":
                # log(f"Reading json data from file: {file_path}", level='DEBUG')
                return read_json(file_path)
            elif typeof == "bytes":
                # log(f"Reading bytes data from file: {file_path}", level='DEBUG')
                return file_path.read_bytes()
            elif typeof == "text":
                # log(f"Reading text data from file: {file_path}", level='DEBUG')
                return file_path.read_text()
        return None

    def file_exists(self, item: str, file_name: str) -> bool:
        """
        Check if a file exists.
        :param item: The name of the directory to check for the file.
        :param file_name: The name of the file to check.
        """
        file_path = self._path / item / file_name
        return file_path.exists()
