import os
import random
import signal
import unittest
import warnings
import datetime as dt

from time import sleep
from threading import Thread
from contextlib import contextmanager
from functools import partial
from typing import Iterator
from unittest import TestCase
from unittest.mock import patch, PropertyMock
from paramiko import AuthenticationException
from string import ascii_letters, digits

from raspinel import Connection, SSHError, Client, Screen
from raspinel.util import temp_file, rel_path


CMD_CREATE_SCREEN = "python3 -c '__import__(\"time\").sleep({})'"
ASYNC_LOOP = 1
ALPHABET = digits + ascii_letters
INVALID_URL = "invalid-" + "".join(random.choice(ALPHABET) for i in range(55))

ppatch = partial(patch, new_callable=PropertyMock)


@contextmanager
def assert_waring() -> Iterator[None]:
    with warnings.catch_warnings(record=True) as warns:
        warnings.simplefilter("always")
        yield
        if warns:
            msg = "Warning occur : \n"
            msg += "\n".join(f"{w.message}\n{w.source}" for w in warns)
            raise AssertionError(msg)


class TestConnection(TestCase):
    def test_connect_valid_credentials(self) -> None:
        conn = Connection.resolve()
        self.assertTrue(conn.connected(), "Not Connected")
        conn.close()

    def test_upload_download(self) -> None:
        conn = Connection.resolve()
        random_content = random.randbytes(random.randint(10 ** 5, 10 ** 6))
        name = "test_raspinel.bin"
        test_path = rel_path("../tests/" + name)
        with temp_file(random_content) as local_path:
            conn.upload(local_path, name)

        try:
            conn.download(name, test_path)
            with open(test_path, "rb") as file:
                content = file.read()
            self.assertEqual(random_content, content)
        finally:
            os.remove(test_path)

    def test_connect_wrong_hostname(self) -> None:
        conn = Connection.resolve()
        self.assertTrue(conn.connected(), "Login with valid hostname")
        # FIXME : raise ResourceWarning but can't do nothing
        # see: https://github.com/paramiko/paramiko/issues/1126
        with self.assertRaises(TimeoutError):
            config = conn.default_config()
            config = {"hostname": INVALID_URL, "port": config["port"]}
            conn.connect(**config)
        self.assertFalse(conn.connected(), "Login with invalid hostname")
        conn.close()

    def test_connect_wrong_password(self) -> None:
        config = Connection.default_config()
        conn = Connection(**config)
        config["password"] = "falsepasssword"
        self.assertTrue(conn.connected(), "Login with valid hostname")
        with self.assertRaises(AuthenticationException):
            conn.connect(**config)
        self.assertFalse(conn.connected(), "Login with invalid password")
        conn.close()

    def test_sync_connect(self) -> None:
        conn = Connection.resolve()
        self.assertTrue(conn.connected(), "Not Connected")
        conn.reconnect()
        self.assertTrue(conn.connected(), "Not Connected after reconnect")
        conn.close()

    def test_async_reconnect(self) -> None:
        for i in range(ASYNC_LOOP):
            print(f"Starting tests {i} ...")
            errors_collector = []
            testing = True
            conn = Connection.resolve()
            self.assertTrue(conn.connected(), "Not Connected")

            def simple_echo() -> None:
                nonlocal conn, testing
                while testing:
                    try:
                        conn.cmd("echo hello")
                    except Exception as e:
                        errors_collector.append(e)

            th = Thread(target=simple_echo)
            th.start()
            conn.reconnect()

            try:
                testing = False
                self.assertTrue(conn.connected(),
                                "Not Connected after reconnect")
                sleep(3)
                th.join()
                for err in errors_collector:
                    self.assertIsInstance(err, SSHError)
                self.assertNotEqual(errors_collector, [])
            finally:
                conn.close()
                del conn

    def test_version(self) -> None:
        conn = Connection.resolve()
        self.assertEqual(conn.version, 1, "Wrong version after connect")
        conn.reconnect()
        self.assertEqual(conn.version, 2, "Wrong version after connect")
        conn.close()
        self.assertEqual(conn.version, 2, "Version change after close")

    def test_check_connection(self) -> None:
        conn = Connection.resolve()
        try:
            conn.check_connection()
        except SSHError:
            self.fail("raise exception but connected")
        conn.close()
        with self.assertRaises(SSHError):
            conn.check_connection()

    def test_cmd(self) -> None:
        conn = Connection.resolve()
        resp = conn.cmd("echo hello  world")
        self.assertEqual(resp.out, "hello world")
        self.assertEqual(resp.err, "")
        self.assertEqual(resp.cmd, "echo hello  world")
        self.assertEqual(resp.exit, 0)

        resp = conn.cmd("echo {}", "hello  world")
        self.assertEqual(resp.out, "hello  world")
        self.assertEqual(resp.cmd, "echo 'hello  world'")

        resp = conn.cmd("echo {text}", text="hello  world")
        self.assertEqual(resp.out, "hello  world")
        self.assertEqual(resp.cmd, "echo 'hello  world'")

        resp = conn.cmd("echo {}", "hello")
        self.assertEqual(resp.out, "hello")
        self.assertEqual(resp.cmd, "echo hello")

        resp = conn.cmd("echo {}", "$?")
        self.assertEqual(resp.out, "$?")
        self.assertEqual(resp.cmd, "echo '$?'")

        resp = conn.cmd("echo {}", "hel'lo")
        self.assertEqual(resp.out, "hel'lo")
        self.assertEqual(resp.cmd, "echo 'hel'\"'\"'lo'")


class TestClient(TestCase):
    _cpt = 1

    @classmethod
    def setUpClass(cls) -> None:
        sleep(5)

    def setUp(self) -> None:
        self.client = Client.resolve()

    def tearDown(self) -> None:
        self.client.close()

    def temp_screen(self, timeout: float = 5.0) -> Screen:
        name = f"temp_unittest_{self._cpt}"
        print(f"Create Screen {name!r}")
        self.__class__._cpt += 1
        self.client.create_screen(CMD_CREATE_SCREEN.format(timeout), name)
        screen = self.client.get_screen(name)
        return screen

    def assertBetween(self, value: int | float,
                      min_: int | float, max_: int | float) -> None:
        self.assertGreaterEqual(value, min_)
        self.assertLessEqual(value, max_)

    def test_temperature(self) -> None:
        temp = self.client.temperature
        self.assertBetween(temp, -20, 85)

    def test_fmt_temperature(self) -> None:
        tests = [
            (1, "1.0°C"),
            (1.00001, "1.0°C"),
            (-500, "-500.0°C"),
            (1.04, "1.0°C"),
            (1.06, "1.1°C")
        ]
        for val, attempt in tests:
            with ppatch("raspinel.Client.temperature", return_value=val):
                self.assertEqual(self.client.fmt_temperature(), attempt)

    def test_cpu(self) -> None:
        cpus = self.client.cpu
        self.assertNotEqual(cpus, [])
        for cpu in cpus:
            self.assertBetween(cpu, 0, 1)

    def test_fmt_cpu(self) -> None:
        tests = [
            ([], "0%"),
            ([1, 1], "100.00%  100.00%  (100.00%)"),
            ([0.758, 0.7145, 0.4487], "75.80%  71.45%  44.87%  (64.04%)")
        ]
        for val, attempt in tests:
            with ppatch("raspinel.Client.cpu", return_value=val):
                self.assertEqual(self.client.fmt_cpu(), attempt)

    def test_memory(self) -> None:
        used, total = self.client.memory
        self.assertGreaterEqual(used, 0)
        self.assertGreaterEqual(total, used)

    def test_fmt_memory(self) -> None:
        tests = [
            ([7_400_000, 12_800_000], "7227MB / 12500MB (57.81%)"),
            ([7_000, 12_000], "7MB / 12MB (58.33%)")
        ]
        for val, attempt in tests:
            with ppatch("raspinel.Client.memory", return_value=val):
                self.assertEqual(self.client.fmt_memory(), attempt)

    def test_uptime(self) -> None:
        up = self.client.uptime
        self.assertGreaterEqual(up, dt.datetime(2010, 1, 1))
        self.assertLessEqual(up, dt.datetime.now() + dt.timedelta(days=1))

    def test_fmt_uptime(self) -> None:
        tests = [
            (dt.datetime(2021, 1, 15), "0d 00:00:00"),
            (dt.datetime(2021, 1, 13), "2d 00:00:00"),
            (dt.datetime(2021, 1, 14, 19), "0d 05:00:00"),
            (dt.datetime(2021, 1, 14, 23, 55), "0d 00:05:00"),
            (dt.datetime(2021, 1, 14, 23, 59, 55), "0d 00:00:05"),
            (dt.datetime(2021, 1, 16), "0d 00:00:00"),
            (dt.datetime(2015, 1, 15), "2192d 00:00:00"),
        ]
        with patch("raspinel.core.datetime") as mock_datetime:
            mock_datetime.now.return_value = dt.datetime(2021, 1, 15)
            for val, attempt in tests:
                with ppatch("raspinel.Client.uptime", return_value=val):
                    self.assertEqual(self.client.fmt_uptime(), attempt)

    def test_storage(self) -> None:
        used, total = self.client.storage
        self.assertGreaterEqual(used, 0)
        self.assertGreaterEqual(total, used)

    def test_fmt_storage(self) -> None:
        g1 = 1024 ** 2
        tests = [
            ([0, 0], "0.00GB / 0.00GB (0.00%)"),
            ([0, g1], "0.00GB / 1.05GB (0.00%)"),
            ([g1, 0], "1.05GB / 1.05GB (100.00%)"),
            ([g1, g1], "1.05GB / 1.05GB (100.00%)"),
            ([g1, g1 * 2], "1.05GB / 2.10GB (50.00%)")
        ]
        for val, attempt in tests:
            with ppatch("raspinel.Client.storage", return_value=val):
                self.assertEqual(self.client.fmt_storage(), attempt)

    def test_ps(self) -> None:
        process = self.client.ps()
        self.assertTrue("ps" in (p.cmd for p in process))

    def test_pid(self) -> None:
        pid = self.client.pid("pidof")
        self.assertIsNotNone(pid)
        self.assertGreaterEqual(pid, 0)

    def test_kill_by_pid(self) -> None:
        screen = self.temp_screen()
        self.assertTrue(self.client.kill_by_pid(screen.pid))

    def test_screens(self) -> None:
        temp_screens = [self.temp_screen() for _ in range(2)]
        screens = self.client.screens()
        for screen in temp_screens:
            self.assertIn(screen, screens)

    def test_get_screen(self) -> None:
        screen = self.temp_screen()
        self.client.get_screen(screen.name)
        with self.assertRaises(KeyError):
            self.client.get_screen("notascreen_0123456789")

    def test_create_screen(self) -> None:
        screen = self.temp_screen()
        with self.assertRaises(KeyError):
            self.client.create_screen(CMD_CREATE_SCREEN.format(3),
                                      screen.name)

    def test_kill_screen(self) -> None:
        screen1 = self.temp_screen()
        self.client.kill_screen(screen1)
        with self.assertRaises(KeyError):
            self.client.get_screen(screen1)
        screen2 = self.temp_screen(0.1)
        sleep(1)
        with self.assertRaises(KeyError):
            self.client.kill_screen(screen2)

    def test_rename_screen(self) -> None:
        screen = self.temp_screen()
        new_name = screen.name + "_renamed"
        self.client.rename_screen(screen, new_name)
        self.client.get_screen(new_name)

    def test_putty(self) -> None:
        popen_killed = self.client.putty()
        sleep(2)
        if popen_killed.poll() is None:
            popen_killed.kill()
            popen_killed.wait()
        else:
            self.fail("putty can't be run")
        with assert_waring():
            del popen_killed

        popen_alive = self.client.putty()
        pid = popen_alive.pid
        sleep(2)
        if popen_alive.poll() is not None:
            self.fail("putty can't be run")
        try:
            with assert_waring():
                del popen_alive
        finally:
            os.kill(pid, signal.SIGTERM)

    def test_winscp(self) -> None:
        popen_killed = self.client.winscp()
        sleep(4)
        if popen_killed.poll() is None:
            popen_killed.kill()
            popen_killed.wait()
        else:
            self.fail("winscp can't be run")
        with assert_waring():
            del popen_killed

        popen_alive = self.client.winscp()
        pid = popen_alive.pid
        sleep(4)
        if popen_alive.poll() is not None:
            self.fail("winscp can't be run")
        try:
            with assert_waring():
                del popen_alive
        finally:
            os.kill(pid, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
