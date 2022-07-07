"""
Utility module.
"""
import os
import secrets
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Iterator, Optional

COMMAND_NOT_FOUND = 127


def rel_path(relative_path: str) -> str:
    """Get path as relative path, pyinstaller compatible."""
    meipass: Optional[str] = getattr(sys, "_MEIPASS", None)
    frozen: bool = getattr(sys, "frozen", False)
    if meipass is not None:
        dir_path = os.path.join(meipass, "mandelia")
    elif frozen:
        dir_path = os.path.dirname(sys.executable)
    else:
        dir_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(dir_path, relative_path)


@contextmanager
def temp_file(
        content: Optional[bytes] = None, timeout: float = 3000.0
) -> Iterator[str]:
    """Create temporary file, return the path and remove it after timeout."""
    if content is None:
        content = b""
    while True:
        path = os.path.join(
            tempfile.gettempdir(), f"file_{secrets.token_hex(16)}")
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
