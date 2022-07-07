"""
Core to connect to a raspberry.
"""
import logging
import os
import re
import socket
import subprocess
import sys
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from os import PathLike
from shlex import quote
from threading import Lock
from types import TracebackType
from typing import (TYPE_CHECKING, Dict, Iterator, List, Optional, Sequence,
                    Tuple, Type, Union)

import yaml
from paramiko import (AuthenticationException, AutoAddPolicy, SSHClient,
                      SSHException)
from paramiko.channel import ChannelFile
from paramiko.config import SSH_PORT
from paramiko.sftp_client import SFTPClient
from typing_extensions import Literal, NotRequired, Protocol, TypedDict

from .exception import ExitCodeError, FormatError, NoConnectionError, SSHError
from .util import rel_path, temp_file


class Stringable(Protocol):
    """Represent an object who can be printed."""
    def __str__(self) -> str:
        ...


if TYPE_CHECKING:
    PopenBytes = subprocess.Popen[bytes]  # type: ignore
    PathLikeBytes = PathLike[bytes]
    PathLikeStr = PathLike[str]
else:
    PopenBytes = subprocess.Popen
    PathLikeBytes = PathLike
    PathLikeStr = PathLike


StrOrBytesPath = Union[str, bytes, PathLikeBytes, PathLikeStr]
_CMD = Union[StrOrBytesPath, Sequence[StrOrBytesPath]]

GB = 10 ** 6

auth_lock = Lock()

# Regex definitions
TEMPERATURE_RE = re.compile(r"temp=(\d+(?:\.\d+)?)'C")
CPU_RE = re.compile("cpu[^ ]")
COLOR_RE = re.compile(r"\x1b\[[0-9]{1,2}(?:;[0-9]{1,2})?m")
SCREEN_RE = re.compile(
    r"\t(?P<pid>\d{1,8})\.(?P<name>.+)\t"
    r"\((?P<start>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\)\t\((?P<state>.+)\)"
)
CONFIG_MAPPER = {
    "hostname": "RASPINEL_HOSTNAME",
    "port": "RASPINEL_PORT",
    "password": "RASPINEL_PASSWORD",
    "username": "RASPINEL_USERNAME",
    "timeout": "RASPINEL_TIMEOUT"
}

# Paths for child programs
WINSCP = "C:\\Program Files (x86)\\WinSCP\\WinSCP.exe"
PUTTY = "C:\\Program Files\\PuTTY\\putty.exe"

# Flag for DetachedProcess
DETACHED: int = 0
if sys.platform == "win32":
    if sys.version_info >= (3, 7):
        DETACHED |= subprocess.DETACHED_PROCESS
        DETACHED |= subprocess.CREATE_BREAKAWAY_FROM_JOB
    DETACHED |= subprocess.CREATE_NEW_PROCESS_GROUP


class Config(TypedDict):
    """Represent a confuguration."""
    hostname: str
    port: int
    password: NotRequired[str]
    username: NotRequired[str]
    timeout: NotRequired[int]


ConfigKey = Literal["hostname", "port", "password", "username", "timeout"]


class DetachedProcess(PopenBytes):
    """Same as Popen but can be left open at the end of the program."""
    def __init__(self, args: _CMD) -> None:
        """Instantiate DetachedProcess."""
        super().__init__(args, creationflags=DETACHED)  # type: ignore
        # hide args just to prevent display mistake
        self.args = []

    def __del__(self) -> None:
        # remove warning for zombie process
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ResourceWarning)
            super().__del__()  # type: ignore

    def __repr__(self) -> str:
        name = self.__class__.__name__
        return name + f"<id=0x{id(self):016x} *args=SECRET>"

    __str__ = __repr__


@dataclass(eq=False, frozen=True)
class Response:
    """Represent a response from remote."""
    cmd: str
    out: str
    err: str
    exit: int = 0

    def check(self, *exits: int) -> "Response":
        """Check if the exit code is correct, otherwise raise ExitCodeError."""
        if self.exit not in exits:
            raise ExitCodeError(self.exit)
        return self


@dataclass(eq=False, frozen=True)
class EntryPS:
    """Represent an entry in ps command."""
    s: str
    uid: int
    pid: int
    ppid: int
    c: str
    pri: str
    ni: str
    rss: int
    sz: int
    wchan: str
    tty: str
    time: str
    cmd: str

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EntryPS):
            return self.pid == other.pid
        return NotImplemented

    def __hash__(self) -> int:
        return self.pid

    @staticmethod
    def from_line(line: str) -> "EntryPS":
        """Convert a line from ps command into EntryPS instance."""
        args = line.strip().split(maxsplit=12)
        if len(args) != 13:
            raise FormatError("EntryPS format", line)
        s, uid, pid, ppid, c, pri, ni, rss, sz, wchan, tty, tim, cmd = args
        return EntryPS(s, int(uid), int(pid), int(ppid), c, pri, ni,
                       int(rss), int(sz), wchan, tty, tim, cmd)


@dataclass(eq=False, frozen=True)
class Screen:
    """Represent a screen."""
    pid: int
    name: str
    start: datetime
    state: str

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Screen):
            return self.pid == other.pid
        return NotImplemented

    def __hash__(self) -> int:
        return self.pid

    def __str__(self) -> str:
        return f"{self.pid}.{self.name}"


ScreenIdentifier = Union[str, int, Screen]


class Connection:
    """Represent a connection to the remote with basic interaction."""
    def __init__(
        self,
        hostname: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> None:
        """Instantiate Connection, no hostname for no implicit connection."""
        self.__ssh: Optional[SSHClient] = None
        self.__password = password
        self.__username = username
        self.__hostname = hostname
        self.__port: int = port if port is not None else SSH_PORT
        self.__version = 0
        self.timeout = 3 if timeout is None else timeout
        logging.info("Create Connection")
        if hostname is not None:
            self.reconnect()

    def __repr__(self) -> str:
        """Represent the Connection."""
        name = self.__class__.__name__
        return f"{name}(host={self.hostname!r}, port={self.port})"

    @property
    def ssh(self) -> SSHClient:
        """Get ssh, raise NoConnectionError if not connected."""
        if self.connected():
            return self.__ssh  # type: ignore
        else:
            raise NoConnectionError()

    @contextmanager
    def _sftp(self) -> Iterator[SFTPClient]:
        """Open an SFTP session and close if after."""
        sftp = self.ssh.open_sftp()
        try:
            yield sftp
        finally:
            sftp.close()

    def upload(self, local_path: str, remote_path: str) -> None:
        """Upload a file."""
        with self._sftp() as sftp:
            sftp.put(local_path, remote_path)

    def download(self, remote_path: str, local_path: str) -> None:
        """Download a file."""
        with self._sftp() as sftp:
            sftp.get(remote_path, local_path)

    @staticmethod
    def config_env() -> Config:
        """Load config from default path."""
        config: Config = {}  # type: ignore
        for k, e in CONFIG_MAPPER.items():
            v = os.getenv(e)
            if v is not None:
                config[k] = v  # type: ignore
        if not config:
            raise OSError("No env config")
        if "hostname" not in config:
            raise KeyError("\"RASPINEL_HOSTNAME\" missing from env")

        def _int(key: ConfigKey, export: str) -> None:
            if key in config:
                try:
                    config[key] = int(config[key])
                except ValueError:
                    raise ValueError(f"{export!r} must be a number") from None

        _int("port", "RASPINEL_PORT")
        _int("timeout", "RASPINEL_TIMEOUT")
        return config

    @staticmethod
    def config_yml(path: str) -> Config:
        """Load config from default path."""
        with open(path, "r", encoding="utf8") as file:
            config: Config = yaml.safe_load(file)

        if not isinstance(config, dict):
            raise TypeError("Config must be key-value")

        def check(key: ConfigKey, klass: type, required: bool = False) -> None:
            if key in config:
                if not isinstance(config.get(key), klass):
                    raise TypeError(f"{key!r} must be a {klass.__name__}")
            elif required:
                raise KeyError(f"Missing {key!r} in config")

        check("hostname", str, required=True)
        check("port", int)
        check("timeout", int)
        check("password", str)
        check("username", str)

        keys = set(config.keys())
        extras = keys - {"hostname", "username", "port", "password", "timeout"}
        if extras:
            extra = next(iter(extras))
            raise KeyError(f"{extra!r} should not be present")

        return config

    @staticmethod
    def default_config() -> Config:
        """Get config from env or yml."""
        try:
            return Connection.config_env()
        except OSError:  # no config config
            pass
        name = ".raspinel.yml"

        paths = [os.path.abspath(os.path.join("./", name)),
                 os.path.join(os.path.expanduser("~"), name),
                 rel_path(name)]

        for path in paths:
            try:
                return Connection.config_yml(path)
            except FileNotFoundError:
                pass

        msg = "No environment variables set and no config file found at :"
        msg += "".join("\n - " + p for p in paths)
        msg += "\nSee README.md for more explanation."
        raise FileNotFoundError(msg)

    @staticmethod
    def resolve() -> "Connection":
        """Load default configuration, from raspinel.conf."""
        return Connection(**Connection.default_config())

    def connect(
        self,
        hostname: str,
        port: int = SSH_PORT,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> None:
        """Connect with ssh."""
        self.__hostname = hostname
        self.__port = port
        self.__username = username
        self.__password = password
        self.timeout = 3 if timeout is None else timeout
        self.reconnect()

    def reconnect(self) -> None:
        """Reopen ssh connection."""
        with auth_lock:
            self._unsafe_close()
            if self.hostname is None:
                raise AuthenticationException("Missing hostname")
            # self.__authenticated = None
            self.__ssh = SSHClient()
            self.__ssh.load_system_host_keys()
            self.__ssh.set_missing_host_key_policy(AutoAddPolicy())
            self.__version += 1
            try:
                self.__ssh.connect(
                    hostname=self.hostname,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=self.timeout
                )
            except socket.timeout:  # can't resolve hostname or port
                self._unsafe_close()
                raise TimeoutError(
                    "Socket has timeout, maybe wrong port or hostname"
                ) from None
            except Exception:
                self._unsafe_close()
                raise

    @property
    def version(self) -> int:
        """Get version, incremented for each reconnect."""
        return self.__version

    @property
    def username(self) -> Optional[str]:
        """username for ssh connection and sftp."""
        return self.__username

    @property
    def password(self) -> Optional[str]:
        """password for ssh connection and sftp."""
        return self.__password

    @property
    def port(self) -> int:
        """port for ssh connection and sftp."""
        return self.__port

    @property
    def hostname(self) -> Optional[str]:
        """hostname for ssh connection and sftp."""
        return self.__hostname

    def connected(self) -> bool:
        """Return True if ssh is usable else False."""
        ssh = self.__ssh
        if not ssh:
            return False
        transport = ssh.get_transport()
        connected = bool(transport is not None and
                         transport.is_active() and
                         transport.is_alive())
        return connected

    def check_connection(self) -> None:
        """Raise error if not connected."""
        if not self.connected():
            raise SSHError("Can't use not available connection")

    def cmd(self, fmt: str, *args: Stringable, **kw: Stringable) -> Response:
        """Run command with auto escape of args."""
        # format command by escaping
        def read(channel: ChannelFile) -> str:
            return channel.read().decode("utf8").strip("\n")

        cmd = fmt.format(*[quote(str(arg)) for arg in args],
                         **{k: quote(str(v)) for k, v in kw.items()})
        # let NoConnectionError propagnate
        try:
            channels = self.ssh.exec_command(cmd, timeout=self.timeout)
        except (SSHException, EOFError, ConnectionResetError) as e:
            if isinstance(e, (ConnectionResetError, EOFError)):
                self.close()
            else:
                # check if closed
                try:
                    self.ssh.exec_command("", timeout=self.timeout)
                except (SSHException, EOFError):
                    logging.critical("Connexion closed")
                    if not auth_lock.locked():
                        self.close()
            logging.error("Error %s for %s", repr(e), cmd)
            raise SSHError(f"Error occurred during command {cmd}") from e

        _, stdout, stderr = channels
        code = stdout.channel.recv_exit_status()
        if code == -1:
            raise ExitCodeError(-1)
        logging.info("Exit %d for %s", code, repr(cmd))
        err = read(stderr)
        out = read(stdout)
        return Response(cmd, out, err, code)

    def _check_lock(self) -> None:
        """Raise an error if auth_lock is locked."""
        if not auth_lock.locked():
            raise RuntimeError(
                "unsafe method must be only used in locked method")

    def _unsafe_close(self) -> None:
        """Close connection but raise and error if auth_lock is active."""
        self._check_lock()
        if self.connected():
            if self.__ssh:
                self.__ssh.close()
        self.__ssh = None

    def close(self) -> None:
        """Close connection."""
        # we need to do that for avoiding memory leak
        with auth_lock:
            self._unsafe_close()


class Client(Connection):
    """Represent a Client for connection."""
    __cache_uptime: Optional[datetime]

    def __init__(
        self,
        hostname: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> None:
        """Instantiate Client."""
        self.__cache_uptime = None
        super().__init__(hostname, port, username, password, timeout)

    def reconnect(self) -> None:
        """Reopen ssh connection."""
        self.__cache_uptime = None
        super().reconnect()

    @staticmethod
    def resolve() -> "Client":
        """Load default configuration, from raspinel.conf."""
        return Client(**Client.default_config())

    @property
    def temperature(self) -> float:
        """Get temperature."""
        resp = self.cmd("vcgencmd measure_temp")
        resp.check(0)
        match = TEMPERATURE_RE.fullmatch(resp.out)
        if match is not None:
            return float(match[1])  # type: ignore
        raise FormatError("temperature", resp)

    def fmt_temperature(self) -> str:
        """Get formatted temperature."""
        return f"{self.temperature:.1f}°C"

    @property
    def cpu(self) -> List[float]:
        """Get CPU's usage between 0 and 1, if no cpu return empty list."""
        resp = self.cmd("mpstat -P ALL 1 1")
        resp.check(0)
        lines = COLOR_RE.sub("", resp.out).split("\n")[11:]
        if not lines:
            return []
        percents = []
        for line in lines:
            *_, idle = line.split()
            percents.append(1 - float(idle.replace(",", ".")) / 100)
        return percents

    def fmt_cpu(self) -> str:
        """Get formatted CUP's usage."""
        cpus = self.cpu
        if cpus:
            cpu = "  ".join(f"{perc * 100:.2f}%" for perc in cpus)
            cpu += f"  ({sum(cpus) * 100 / len(cpus):.2f}%)"
            return cpu
        return "0%"

    @property
    def memory(self) -> Tuple[int, int]:
        """Get usage of memory with 2 int: (used, total)."""
        resp = self.cmd("free | grep 'Mem:'")
        resp.check(0)
        _, total, _, free, *_ = resp.out.split()
        return int(total) - int(free), int(total)

    def fmt_memory(self) -> str:
        """Get formatted memory."""
        use, total = self.memory
        return (f"{use / 1024:.0f}MB / {total / 1024:.0f}MB "
                f"({use * 100 / total:.2f}%)")

    @property
    def uptime(self) -> datetime:
        """Get turned-on date."""
        self.check_connection()
        if self.__cache_uptime is None:
            resp = self.cmd("uptime -s")
            resp.check(0)
            self.__cache_uptime = datetime.strptime(
                resp.out, "%Y-%m-%d %H:%M:%S")
        return self.__cache_uptime

    def fmt_uptime(self) -> str:
        """Get formatted uptime."""
        uptime = datetime.now() - self.uptime
        if uptime < timedelta(0):
            return "0d 00:00:00"
        minutes, seconds = divmod(int(uptime.total_seconds()), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"

    @property
    def storage(self) -> Tuple[int, int]:
        """Get disk space with 2 int: (used, total)."""
        resp = self.cmd("df")
        resp.check(0)
        lines = resp.out.split("\n")
        used = 0
        total = 0
        for line in lines[1:]:
            name, size, use, *_ = line.split()
            if name.startswith("/"):
                used += int(use)
                total += int(size)
        return used, total

    def fmt_storage(self) -> str:
        """Get formatted storage."""
        used, total = self.storage
        if not (used or total):
            return "0.00GB / 0.00GB (0.00%)"
        total = max(total, used)
        return (f"{used / GB:.2f}GB / {total / GB:.2f}GB "
                f"({used * 100 / total:.2f}%)")

    @property
    def info(self) -> str:
        """Get info on remote."""
        return (
            f"hostname    : {self.hostname}\n"
            f"port        : {self.port}\n"
            f"temperature : {self.fmt_temperature()}\n"
            f"cpu         : {self.fmt_cpu()}\n"
            f"memory      : {self.fmt_memory()}\n"
            f"uptime      : {self.fmt_uptime()}\n"
            f"storage     : {self.fmt_storage()}"
        )

    def ps(self) -> List[EntryPS]:
        """Get all running process."""
        resp = self.cmd("ps -ely")
        resp.check(0)
        lines = resp.out.split("\n")[1:]
        return [EntryPS.from_line(line) for line in lines]

    def pid(self, name: str) -> Optional[int]:
        """Get process pid by name."""
        try:
            resp = self.cmd("pidof {}", name)
            resp.check(0, 1)
            return int(resp.out)
        except ExitCodeError:
            return None

    def kill_by_name(self, name: str) -> bool:
        """Kill a process by name, return True if killed."""
        pid = self.pid(name)
        if pid is None:
            raise ValueError(f"Can't find pid of {name}")
        return self.kill_by_pid(pid)

    def kill_by_pid(self, pid: int) -> bool:
        """Kill a process by pid, return True if killed."""
        try:
            # check if it's a screen
            screen = self.get_screen(pid)
        except ValueError:
            # other process
            self.cmd("kill -9 {}", pid).check(0)
            killed = all(entry.pid != pid for entry in self.ps())
            return killed
        else:
            # it's a screen
            try:
                self.kill_screen(screen)
                return True
            except ExitCodeError:
                return False

    def reboot(self) -> None:
        """Restart remote."""
        try:
            resp = self.cmd("sudo reboot")
        except ExitCodeError:
            pass  # can't reply because remote is down
        else:
            resp.check(0)

    def screens(self) -> List[Screen]:
        """Get all screens"""
        resp = self.cmd("screen -ls")
        resp.check(0, 1)
        screens = []
        for line in resp.out.split("\n")[1:-1]:
            match = SCREEN_RE.fullmatch(line)
            if match is not None:
                kwargs: Dict[str, str] = match.groupdict()
                start = datetime.strptime(kwargs["start"], "%d/%m/%Y %H:%M:%S")
                start = start.replace(second=0)
                screens.append(Screen(
                    pid=int(kwargs["pid"]),
                    name=kwargs["name"],
                    start=start,
                    state=kwargs["state"]
                ))
        return screens

    def get_screen(self, identifier: ScreenIdentifier) -> Screen:
        """Get screen session on remote or raise KeyError."""
        if isinstance(identifier, int):
            for screen in self.screens():
                if screen.pid == identifier:
                    return screen
        elif isinstance(identifier, str):
            for screen in self.screens():
                if identifier in (str(screen), screen.name):
                    return screen
        elif isinstance(identifier, Screen) and identifier in self.screens():
            return identifier
        raise KeyError(f"Unresolvable Screen : {identifier!r}")

    def create_screen(self, cmd: str, name: str) -> None:
        """Create screen session on remote."""
        for screen in self.screens():
            if screen.name == name:
                raise KeyError("Screen already exist with this name")
        self.cmd("screen -dmS {} bash -c {}", name, cmd).check(0)

    def kill_screen(self, screen: ScreenIdentifier) -> bool:
        """Kill screen session on remote raise ValueError if no screen."""
        screen = self.get_screen(screen)
        try:
            self.cmd("screen -X -S {} quit", screen).check(0)
        except ExitCodeError:
            return False
        return True

    def rename_screen(self, screen: ScreenIdentifier, name: str) -> None:
        """Rename a screen."""
        screen = self.get_screen(screen)
        self.cmd("screen -S {} -X sessionname {}", screen, name).check(0)

    def putty(
        self,
        command: Optional[str] = None,
        screen: Optional[ScreenIdentifier] = None
    ) -> DetachedProcess:
        """Open putty with command or screen."""
        self.check_connection()
        args = [PUTTY, "-ssh", f"{self.username}@{self.hostname}"]
        if self.password:
            args += ["-pw", self.password]
        script = ""
        if screen:
            screen = self.get_screen(screen)
            script += f"screen -dRR {quote(str(screen))}\n"
        if command:
            script += command
        if script:
            with temp_file(script.encode("utf8")) as path:
                args += ["-m", path, "-t"]
                return DetachedProcess(args)
        else:
            return DetachedProcess(args)

    @property
    def sftp_url(self) -> str:
        """Get sftp url."""
        url = "sftp://"
        if self.username or self.password:
            if self.username is not None:
                url += self.username
            if self.password is not None:
                url += ":" + self.password
            url += "@"
        url += "localhost" if self.hostname is None else self.hostname
        if self.port is not None:
            url += f":{self.port}"
        return url

    def winscp(self) -> DetachedProcess:
        """Open Winscp."""
        self.check_connection()
        return DetachedProcess([WINSCP, self.sftp_url])

    def __enter__(self) -> "Connection":
        """Support for contextmanager."""
        return self

    def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType]
    ) -> None:
        """Close raspberry anyway."""
        self.close()
