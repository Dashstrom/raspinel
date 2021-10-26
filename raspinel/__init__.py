"""
Package to simplify the connection to a raspberry pi.
"""
__all__ = [
    'DetachedProcess',
    'Client',
    'Response',
    'EntryPS',
    'Screen',
    'Connection',
    'ExitCodeError',
    'FormatError',
    'SSHError',
    'NoConnectionError',
    'rel_path',
    'temp_file',
    '__version__',
    '__author__'
]

__version__ = "1.0.0"
__author__ = "***REMOVED*** ***REMOVED*** <***REMOVED***>"

from .core import (
    DetachedProcess,
    Client,
    Response,
    EntryPS,
    Screen,
    Connection
)
from .exception import (
    ExitCodeError,
    FormatError,
    SSHError,
    NoConnectionError
)
from .util import rel_path, temp_file
