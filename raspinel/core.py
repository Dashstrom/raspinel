"""
Core to connect to a raspberry.
"""
import logging
import sys
import os
import re
import socket
import subprocess
import warnings

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from shlex import quote
from os import PathLike
from typing import Any, Iterator, Optional, Sequence, Union, Type
from types import TracebackType
from threading import Lock
from pathlib import Path

import yaml

from paramiko import AuthenticationException, SSHClient, SSHException
from paramiko.channel import ChannelFile
from paramiko.config import SSH_PORT
from paramiko.sftp_client import SFTPClient

from .exception import ExitCodeError, FormatError, SSHError, NoConnectionError
from .util import temp_file, rel_path


StrOrBytesPath = Union[str, bytes, PathLike[str], PathLike[bytes]]
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

# Paths for child programs
# TODO Auto Resolve
WINSCP = "C:\\Program Files (x86)\\WinSCP\\WinSCP.exe"
PUTTY = "putty"

# Flag for DetachedProcess
# TODO use deamon = True and os.fork() on linux
DETACHED = 0
if sys.platform == "win32":
    DETACHED |= subprocess.DETACHED_PROCESS
    DETACHED |= subprocess.CREATE_NEW_PROCESS_GROUP
    DETACHED |= subprocess.CREATE_BREAKAWAY_FROM_JOB


class DetachedProcess(subprocess.Popen[bytes]):
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
        return self.__class__.__name__ + f"<id=0x{id(self):016x} *args=SECRET>"

    __str__ = __repr__


@dataclass(eq=False, frozen=True)
class Response:
    """Represent a response from remote."""
    cmd: str
    out: str
    err: str
    exit: int = 0

    def check(self, *exits: int) -> 'Response':
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
    def from_line(line: str) -> 'EntryPS':
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
        hostname: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float | None = None
    ) -> None:
        """Instantiate Connection, no hostname for no implicit connection."""
        self.__ssh: Optional[SSHClient] = None
        self.__password: Optional[str] = password
        self.__username: Optional[str] = username
        self.__hostname: Optional[str] = hostname
        self.__port: int = port if port is not None else SSH_PORT
        self.__version = 0
        self.timeout = 1.5 if timeout is None else timeout
        logging.info("Create Connection")
        if hostname is not None:
            self.reconnect()

    def __repr__(self) -> str:
        """Represent the Connection."""
        return (f"{self.__class__.__name__}"
                f"(host='{self.hostname}', port={self.port})")

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
    def config_env() -> dict[str, Any]:
        """Load config from default path."""
        config: dict[str, Any] = {
            "hostname": "RASPINEL_HOSTNAME",
            "port": "RASPINEL_PORT",
            "password": "RASPINEL_PASSWORD",
            "username": "RASPINEL_USERNAME",
            "timeout": "RASPINEL_TIMEOUT"
        }
        config = {k: v for k, e in config.items()
                  if (v := os.getenv(e)) is not None}
        if not config:
            raise OSError("No env config")
        if "hostname" not in config:
            raise KeyError("'RASPINEL_HOSTNAME' missing from env")
        if "port" in config:
            try:
                config["port"] = int(config["port"])
            except ValueError:
                raise ValueError("'RASPINEL_PORT' must be a number") from None
        return config

    @staticmethod
    def config_yml(path: str) -> dict[str, Any]:
        """Load config from default path."""
        with open(path, "r", encoding="utf8") as file:
            config = yaml.safe_load(file)

        if not isinstance(config, dict):
            raise TypeError("Config must be key-value")

        def check(key: Any, klass: type, required: bool = False) -> None:
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
            raise KeyError(f"'{extra}' should not be present")

        return config

    @staticmethod
    def default_config() -> dict[str, Any]:
        try:
            return Connection.config_env()
        except OSError:  # no config config
            pass
        name = ".raspinel.yml"

        paths = [os.path.abspath(os.path.join("./", name)),
                 os.path.join(Path.home(), name),
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
    def resolve() -> 'Connection':
        """Load default configuration, from raspinel.conf."""
        return Connection(**Connection.default_config())

    def connect(
        self,
        hostname: str,
        port: int = SSH_PORT,
        username: str | None = None,
        password: str | None = None
    ) -> None:
        """Connect with ssh."""
        self.__hostname = hostname
        self.__port = port
        self.__username = username
        self.__password = password
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
                    "Sockat has timeout, maybe wrong port or hostname"
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

    def cmd(self, fmt: str, *args: Any, **kw: Any) -> Response:
        """Run command with auto escape of args."""
        # format command by escaping
        def read(channel: ChannelFile) -> str:
            return channel.read().decode("utf8").strip('\n')

        cmd = fmt.format(*[quote(str(arg)) for arg in args],
                         **{k: quote(str(v)) for k, v in kw.items()})
        try:
            channels = self.ssh.exec_command(cmd, timeout=self.timeout)
        except NoConnectionError:
            raise
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

        stdin, stdout, stderr = channels
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

    def __enter__(self) -> "Connection":
        """Support for contextmanager."""
        return self

    def __exit__(
            self,
            exc_type: Type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None
    ) -> None:
        """Close raspberry anyway."""
        self.close()


class Client(Connection):
    """Represent a Client for connection."""
    __cache_uptime: datetime | None

    def __init__(
        self,
        hostname: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float | None = None
    ) -> None:
        """Instantiate Client."""
        self.__cache_uptime = None
        super().__init__(hostname, port, username, password, timeout)

    def reconnect(self) -> None:
        """Reopen ssh connection."""
        self.__cache_uptime = None
        super().reconnect()

    @staticmethod
    def resolve() -> 'Client':
        """Load default configuration, from raspinel.conf."""
        return Client(**Client.default_config())

    @property
    def temperature(self) -> float:
        """Get temperature."""
        resp = self.cmd("vcgencmd measure_temp")
        resp.check(0)
        if match := TEMPERATURE_RE.fullmatch(resp.out):
            return float(match[1])

        raise FormatError("temperature", resp)

    def fmt_temperature(self) -> str:
        """Get formatted temperature."""
        return f"{self.temperature:.1f}°C"

    @property
    def cpu(self) -> list[float]:
        """ Get CPU's usage between 0 and 1, if no cpu return empty list."""
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
        # FIXME : missing value in __main__
        cpus = self.cpu
        if cpus:
            cpu = "  ".join(f"{perc * 100:.2f}%" for perc in cpus)
            cpu += f"  ({sum(cpus) * 100 / len(cpus):.2f}%)"
            return cpu
        else:
            return "0%"

    @property
    def memory(self) -> tuple[int, int]:
        """Get usage of memory with 2 int: (used, total)."""
        resp = self.cmd("free | grep 'Mem:'")
        resp.check(0)
        name, total, used, free, *others = resp.out.split()
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
            self.__cache_uptime = datetime.fromisoformat(resp.out)
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
    def storage(self) -> tuple[int, int]:
        """Get disk space with 2 int: (used, total)."""
        resp = self.cmd("df")
        resp.check(0)
        lines = resp.out.split("\n")
        used = 0
        total = 0
        for line in lines[1:]:
            name, size, use, free, perc, mount = line.split()
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
        return f"{used/GB:.2f}GB / {total/GB:.2f}GB ({used * 100/total:.2f}%)"

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

    def ps(self) -> list[EntryPS]:
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

    def screens(self) -> list[Screen]:
        """Get all screens"""
        resp = self.cmd("screen -ls")
        resp.check(0, 1)
        screens = []
        for line in resp.out.split("\n")[1:-1]:
            if match := SCREEN_RE.fullmatch(line):
                kwargs: dict[str, Any] = match.groupdict()
                kwargs["pid"] = int(kwargs["pid"])
                start = datetime.strptime(kwargs["start"], "%d/%m/%Y %H:%M:%S")
                kwargs["start"] = start.replace(second=0)
                screen = Screen(**kwargs)
                screens.append(screen)
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
        command: str | None = None,
        screen: ScreenIdentifier | None = None
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
            with temp_file(script) as path:
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
