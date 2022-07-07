"""
Module for exception handling.
"""
from typing import Any


class SSHError(Exception):
    """Raised if there is any error during communication."""


class FormatError(SSHError):
    """Raised when response have wrong format."""
    def __init__(self, name: str, got: Any) -> None:
        super().__init__(
            f"Invalid format for {name} got {got}")  # type: ignore


class ExitCodeError(SSHError):
    """Raised when response get a wrong exit code"""
    def __init__(self, code: int):
        self.code = code
        super().__init__(f"Invalid code got {code}")


class NoConnectionError(SSHError):
    """Raised when trying to use connection without be connected."""
    def __init__(self) -> None:
        super().__init__("Not Connected")
