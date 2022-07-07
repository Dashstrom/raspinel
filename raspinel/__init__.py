"""
Package to simplify the connection to a raspberry pi.
"""
__all__ = [
    "DetachedProcess",
    "Client",
    "Response",
    "EntryPS",
    "Screen",
    "Connection",
    "ExitCodeError",
    "FormatError",
    "SSHError",
    "NoConnectionError",
    "rel_path",
    "temp_file",
    "__version__",
    "__author__"
]

__version__ = "1.0.2"
__author__ = "Dashstrom"

from .core import (Client, Connection, DetachedProcess, EntryPS, Response,
                   Screen)
from .exception import ExitCodeError, FormatError, NoConnectionError, SSHError
from .util import rel_path, temp_file
