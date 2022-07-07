"""
Graphical client for raspberry pi.
"""
import logging
import os
import tkinter as tk
from abc import ABC
from datetime import datetime
from functools import partial, wraps
from threading import Lock, Thread
from time import sleep
from tkinter import TclError, messagebox, ttk
from tkinter.constants import BOTH, END, LEFT, NW, RIGHT, TRUE, W, X
from traceback import print_exc
from typing import Any, Callable, Dict, List, Optional, Set, TypeVar, Union

from paramiko import AuthenticationException
from typing_extensions import ParamSpec

from .core import Client, Screen
from .exception import ExitCodeError, SSHError
from .util import rel_path

ASSETS_PATH = rel_path("assets")
ICON_PATH = os.path.join(ASSETS_PATH, "raspinel.ico")
R = TypeVar("R")
P = ParamSpec("P")
_Runnable = Callable[[], Any]
_EntryIndex = Union[str, int]

loaded: Dict[str, tk.PhotoImage] = {}


def img(name: str) -> tk.PhotoImage:
    """Load image by name and put in cache."""
    if name not in loaded:
        loaded[name] = tk.PhotoImage(file=os.path.join(ASSETS_PATH, name))
    return loaded[name]


def show_errors_raised(func: Callable[P, None]) -> Callable[P, None]:
    """Show error messagebox if an error is raised."""
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            func(*args, **kwargs)
        except Exception as e:  # pylint: disable=broad-except
            show_error(e)
    return wrapper


def show_error(error: Exception) -> None:
    """Show an error in a popup."""
    print_exc()
    name = error.__class__.__qualname__
    messagebox.showerror(f"{name} occurred", str(error))


class SquareButton(tk.Button):
    """Square Button with an image."""
    def __init__(self, master: tk.Misc, name: str,
                 command: _Runnable) -> None:
        """Instantiate SquareButton."""
        super().__init__(
            master, command=command, image=img(name), width=20, height=20)


class Entry(tk.Entry):
    """Entry that supports transparent message before writing."""
    def __init__(
        self,
        master: tk.Misc,
        default: Optional[str] = None,
        fg: Optional[str] = None,
        action: Optional[_Runnable] = None,
        **kwargs: Any
    ) -> None:
        """Instantiate Entry."""
        super().__init__(
            master, fg="gray" if fg is None else fg, **kwargs)  # type: ignore
        self.default = "" if default is None else default
        self.action = action
        text: str = super().get()
        self._default_activated = not text
        if not text:
            self.insert(0, self.default)
        self.bind(
            "<FocusIn>", lambda _: self.handle_focus_in())  # type: ignore
        self.bind(
            "<FocusOut>", lambda _: self.handle_focus_out())  # type: ignore
        self.bind(
            "<Return>", lambda _: self._call_action())  # type: ignore

    def _call_action(self) -> None:
        """Call action if exists."""
        if self.action is not None:
            self.action()

    def focused(self) -> bool:
        """Return if this widget is currently focused."""
        return self.focus_get() == self

    def get(self) -> str:
        """Return the text."""
        if self._default_activated:
            return ""
        return super().get()

    def delete(
        self, first: _EntryIndex, last: Optional[_EntryIndex] = None
    ) -> None:
        """Delete text from FIRST to LAST (not included)."""
        super().delete(first, last)
        self.handle_focus_out()

    def handle_focus_in(self) -> None:
        """Handle focus in and remove default text if needed."""
        if self._default_activated and self.focused():
            super().delete(0, tk.END)
            self.config(fg="black")
            self._default_activated = False

    def handle_focus_out(self) -> None:
        """Handle focus out and show default text if needed."""
        text = self.get()
        if not text and not self.focused():
            super().delete(0, tk.END)
            self.config(fg="grey")
            super().insert(0, self.default)
            self._default_activated = True


class DataOutput(tk.Frame, ABC):
    """Frame for the repetitive slow function call."""
    id_last_thread = 0
    class_lock = Lock()

    def __init__(self, master: tk.Misc, func: Callable[[], str],
                 title: str, refresh: float = 1.0) -> None:
        """Instantiate DataOutput."""
        super().__init__(master)
        self.title = title
        self.label = tk.Label(self, text=title, width=12, anchor=W)
        self.refresh = refresh
        self.var = tk.StringVar()
        self.value = tk.Label(self, textvariable=self.var,
                              width=35, anchor=W)
        self.func = func
        self.label.pack(side=LEFT)
        self.value.pack(side=RIGHT)

        self.__threads: Dict[str, Thread] = {}
        self.__stop = False
        self._update_loop()

    def _update_loop(self) -> None:
        """Call the display update in a non-blocking way."""
        if self.__stop:
            return
        self._cleanup_threads()
        name = f"{self.title}-Thread-{self.id_last_thread}"
        with self.class_lock:
            self.id_last_thread += 1
        self.__threads[name] = thread = Thread(target=self._call_callback,
                                               name=name)
        thread.start()
        ms = int(self.refresh * 1000)
        self.after(ms, self._update_loop)

    def _call_callback(self) -> None:
        """Wrap function call."""
        try:
            result = str(self.func())
        except SSHError:
            result = "Not Connected ..."
        self.set(result)

    def set(self, value: str) -> None:
        """Set the variable to VALUE."""
        try:
            self.var.set(value if not self.__stop else "Closing ...")
            self.update()
        except RuntimeError:
            # Closed Window
            pass

    def _cleanup_threads(self) -> None:
        """Join threads that have finished their work."""
        for thread in tuple(self.__threads.values()):
            if not thread.is_alive():
                thread.join(0)
                if not thread.is_alive():
                    self.__threads.pop(thread.name)

    def destroy(self) -> None:
        """Destroy this and all descendants widgets."""
        self.__stop = True
        self.set("")  # update widget
        for thread in self.__threads.values():
            thread.join()
        super().destroy()


class Info(tk.LabelFrame):
    """Frame that shows the main information about remote."""
    def __init__(self, master: tk.Misc, client: Client) -> None:
        """Instantiate Info."""
        super().__init__(master, text="Info", labelanchor=NW)
        data_out = partial(DataOutput, self)

        self.temperature = data_out(client.fmt_temperature, "Temperature", 1)
        self.memory = data_out(client.fmt_memory, "Memory", 0.5)
        self.cpu = data_out(client.fmt_cpu, "CPU", 0.5)
        self.uptime = data_out(client.fmt_uptime, "Uptime", 0.1)
        self.storage = data_out(client.fmt_storage, "Storage", 2)

        for out in self.outs():
            out.pack(anchor=W, padx=1)

    def outs(self) -> List[DataOutput]:
        """Get all DataOutput."""
        return [self.temperature, self.memory, self.cpu,
                self.uptime, self.storage]


class Interaction(tk.LabelFrame):
    """Frame for buttons."""
    def __init__(self, master: tk.Misc, client: Client) -> None:
        """Instantiate Interaction."""
        super().__init__(master, text="Interaction", labelanchor=NW)
        self.client = client
        self._manager: Optional[ScreenManager] = None
        buttons: Dict[str, Callable[[], None]] = {
            "Putty": self.pressed_putty,
            "WinSCP": self.pressed_winscp,
            "Manager": self.pressed_manager,
            "Reboot": self.pressed_reboot
        }

        self.buttons = {}
        for text, command in buttons.items():
            button = tk.Button(self, text=text, command=command, width=12)
            button.pack(side=LEFT, pady=5, padx=5)
            self.buttons[text] = button

    @show_errors_raised
    def pressed_manager(self) -> None:
        """Open ScreenManager."""
        self._manager = ScreenManager(self, self.client)

    @show_errors_raised
    def pressed_putty(self) -> None:
        """Open Putty window."""
        self.client.putty()

    @show_errors_raised
    def pressed_winscp(self) -> None:
        """Open winscp window."""
        self.client.winscp()

    def pressed_reboot(self) -> None:
        """Reboot remote in other thread."""
        target = show_errors_raised(self.client.reboot)
        thread = Thread(target=target)
        thread.start()
        self.after(2000, thread.join)


class App(tk.Tk):
    """Main Application."""
    def __init__(self) -> None:
        """Instantiate App."""
        super().__init__()
        self.iconbitmap(ICON_PATH)
        self.title("Raspinel")
        self.resizable(width=False, height=False)
        self.raspberry = Client()
        self.info = Info(self, self.raspberry)
        self.inter = Interaction(self, self.raspberry)
        self.info.pack(fill=X, pady=5, padx=5)
        self.inter.pack(fill=X, pady=5, padx=5)
        self.closed = False
        self.__th = Thread(target=self.handle_starting)
        self.__th.start()
        self.protocol("WM_DELETE_WINDOW", self.handle_closing)

    def handle_closing(self) -> None:
        """Called when the app is closed."""
        self.closed = True
        self.raspberry.close()
        self.__th.join()
        # run action from the main thread
        self.after(0, self.destroy)

    def handle_starting(self) -> None:
        """Called when the app is starting."""
        while not self.closed:
            if self.raspberry.connected():
                sleep(1)
            else:
                logging.info("Try reconnect")
                try:
                    config = self.raspberry.default_config()
                    self.raspberry.connect(**config)
                    logging.info("Try reconnect")
                except FileNotFoundError as e:
                    self.withdraw()
                    show_error(e)
                    self.after(0, self.destroy)
                    return
                except TimeoutError:
                    logging.error("Timeout")
                except AuthenticationException:
                    self.raspberry.close()
                    logging.critical("Wrong auth")
                    ok = messagebox.askokcancel(
                        "Authentication failed",
                        "Authentication failed, Please check credential and "
                        "be sure they are valid,"
                        "press ok when it's done or close for exit raspinel",
                        icon="error"
                    )
                    if not ok:
                        self.handle_closing()
                        break


class ScreenManager(tk.Toplevel):
    """Window to manage screens."""
    def __init__(self, app: tk.Misc, client: Client) -> None:
        """Instantiate ScreenManager."""
        super().__init__(app)
        self.iconbitmap(ICON_PATH)
        self.title("Raspinel - Manager")
        self.geometry("500x600")
        self.resizable(width=False, height=False)

        self.raspberry = client
        self.table = ttk.Treeview(self)

        # Define columns
        col0, col1, col2, col3 = "#0", "#1", "#2", "#3"
        self.table["columns"] = (col1, col2, col3)

        def _column(col: str, width: int, text: str) -> None:
            self.table.column(col, anchor=W, stretch=False,
                              width=width, minwidth=width)
            self.table.heading(col, text=text, anchor=W)

        # Format columns
        _column(col0, 60, "Id")
        _column(col1, 150, "Name")
        _column(col2, 120, "Start")
        _column(col3, 80, "State")

        def _heading(col: str, text: str) -> None:
            self.table.heading(col, text=text, anchor=W)

        # Create bottom bar
        self.interaction_bar = tk.Frame(self)
        self.cmd = Entry(self.interaction_bar, default="Command",
                         action=self.pressed_create_screen)
        self.name = Entry(self.interaction_bar, width=14, default="Name",
                          action=self.cmd.focus)

        # Create buttons
        button = partial(SquareButton, self.interaction_bar)
        self.kill = button("kill.png", self.pressed_kill_screen)
        self.connect = button("connect.png", self.pressed_attach_screen)
        self.start = button("run.png", self.pressed_create_screen)

        # Packing buttons
        self.name.pack(side=LEFT, padx=5, ipady=3, ipadx=3)
        self.cmd.pack(side=LEFT, ipady=3, ipadx=3, fill=X, expand=TRUE)
        self.start.pack(side=LEFT, padx=5)
        self.connect.pack(side=LEFT)
        self.kill.pack(side=LEFT, padx=5)

        # Packing table and buttons
        self.table.pack(padx=5, pady=5, expand=TRUE, fill=BOTH)
        self.interaction_bar.pack(fill=X, side=LEFT, pady=5, expand=TRUE)

        # Binding events
        self.table.bind("<Double-1>", self.handle_double_left_click)

        # Run Update loop in another thread
        thread = Thread(target=self._update_loop, name="Update-Thread")
        thread.start()
        # self.__update_th = th

    @show_errors_raised
    def handle_double_left_click(self, event):
        # type: (tk.Event[ttk.Treeview]) -> None
        """Triggered by double click for attach screen."""
        screen = self.focus_at(event.y)
        if screen is not None:
            self.raspberry.putty(screen=screen)

    def focus_at(self, y: int) -> Optional[Screen]:
        """Get screen at y pos and select it."""
        iid = self.table.identify_row(y)
        if not iid:
            self.table.selection_set([])
            return None
        self.table.selection_set(iid)
        return self.selection[0]

    @property
    def selection(self) -> List[Screen]:
        """Get selected screens, if no one is selected return the first."""
        selection = self.table.selection()
        children = self.table.get_children()
        # Default case
        if not selection and children:
            selection = (children[0], )
        # Convert selection data to screens instances
        items = [self.table.item(id_) for id_ in selection]  # type: ignore
        screens = []
        for item in items:  # type: ignore
            pid = int(item["text"])  # type: ignore
            values: List[str] = item["values"]  # type: ignore
            name, start, state = values
            screen = Screen(
                pid=pid,
                name=name,
                start=datetime.strptime(start, "%d/%m/%Y %H:%M"),
                state=state
            )
            screens.append(screen)
        return screens

    @show_errors_raised
    def pressed_kill_screen(self) -> None:
        """Kill the selected screens."""
        for screen in self.selection:
            try:
                self.raspberry.kill_screen(screen.pid)
            except ValueError:
                # Screen already dead
                pass

    @show_errors_raised
    def pressed_attach_screen(self) -> None:
        """Open putty session with connecting to the selected screens."""
        for screen in self.selection:
            self.raspberry.putty(screen=screen)

    @show_errors_raised
    def pressed_create_screen(self) -> None:
        """Create screen."""
        cmd = self.cmd.get()
        name = self.name.get()
        if not name:
            raise SSHError("No name provided")
        if not cmd:
            raise SSHError("No command provided")
        self.raspberry.create_screen(cmd, name)
        self.cmd.delete(0, END)
        self.name.delete(0, END)

    def _update_loop(self) -> None:
        """Launches the screens update loop."""
        i = 0
        last: Set[Screen] = set()
        while True:
            try:
                actual = set(self.raspberry.screens())
                for screen in actual - last:
                    values = [screen.name,
                              f"{screen.start:%d/%m/%Y %H:%M}",
                              screen.state]
                    self.table.insert(parent="", index=END,
                                      text=str(screen.pid), iid=str(i),
                                      tags=("row",), values=values)
                    i += 1
                ids = {int(self.table.item(index, "text")): index
                       for index in self.table.get_children()}
                deleted_ids = [ids[screen.pid] for screen in last - actual]
                self.table.delete(*deleted_ids)
                last = actual
            except (TclError, RuntimeError):  # Window closed
                logging.info("Window closed")
                return
            except ExitCodeError:
                logging.error("Wrong exit code")
            except SSHError:  # Connection closed
                logging.info("Connection closed")
                try:
                    last = set()
                    children = self.table.get_children()
                    self.table.delete(*children)
                except (TclError, RuntimeError):
                    # Connection and window closed
                    return
            sleep(1)
