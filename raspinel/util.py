"""
Utility module.
"""
import os
import random
import sys
import time

from contextlib import contextmanager
from typing import Iterator, Union


COMMAND_NOT_FOUND = 127


def rel_path(relative_path: str) -> str:
    """Get path as relative path, pyinstaller compatible."""
    if hasattr(sys, '_MEIPASS'):
        dir_path = getattr(sys, "_MEIPASS")
    elif getattr(sys, 'frozen', False):
        dir_path = os.path.dirname(sys.executable)
    else:
        dir_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(dir_path, relative_path)


@contextmanager
def temp_file(
        content: Union[str, bytes], timeout: float = 3000.0
) -> Iterator[str]:
    """ Create temporary file, return the path and remove it after timeout."""
    while True:
        path = rel_path(f"tmp/file_{random.randbytes(8).hex()}")
        if not os.path.exists(path):
            break
    if isinstance(content, str):
        content = content.encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as file:
        file.write(content)
    try:
        yield path
    finally:
        # prevent from closing during timeout
        try:
            time.sleep(timeout / 1000)
        finally:
            os.remove(path)
