#!/usr/bin/env python3
"""AAG Canon EOS 4000D Manager v1.1.

A small, conservative tethering GUI for the Canon EOS 4000D based on the
working libgphoto2 baseline that was validated on this machine.  All camera
I/O is serialized through one worker thread and one persistent PTP session.
"""

from __future__ import annotations

import argparse
import io
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import fcntl
import gphoto2 as gp
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import messagebox, ttk

APP_NAME = "AAG Canon EOS 4000D Linux Manager"
APP_VERSION = "1.1"
TARGET_MODEL = "Canon EOS 4000D"
TARGET_USB_ID = "04a9:32d9"
TARGET_GVFS_URI = "gphoto2://Canon_Inc._Canon_Digital_Camera/"
DEFAULT_BASE_DIR = Path.home() / "Pictures" / "Canon-4000D"
DEFAULT_LOG_DIR = Path(
    os.environ.get(
        "AAG_CANON_LOG_DIR",
        str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "aag-canon-4000d"),
    )
) / "logs"
DEFAULT_LOCK_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "aag-canon-4000d.lock"

EOS_CAPTURETARGET_PATH = "/main/settings/capturetarget"
EOS_EVFOUTPUTDEVICE_PATH = "/main/actions/viewfinder"
EOS_AFDRIVE_PATH = "/main/actions/autofocusdrive"
EOS_CANCELAF_PATH = "/main/actions/cancelautofocus"
EOS_AF_METHOD_PATH = "/main/capturesettings/eosviewtype"
EOS_REMOTE_RELEASE_PATH = "/main/actions/eosremoterelease"
EOS_SHUTTERSPEED_PATH = "/main/capturesettings/shutterspeed"
EOS_APERTURE_PATH = "/main/capturesettings/aperture"
EOS_ISO_PATH = "/main/imgsettings/iso"
EOS_IMAGEFORMAT_PATH = "/main/imgsettings/imageformat"

CAPTURE_TARGET_CHOICES = ("Internal RAM", "Memory card")
AF_METHOD_LABELS = {"0": "Live", "1": "LiveFace", "2": "Quick"}
REMOTE_PRESS_FULL = "Press Full"
REMOTE_RELEASE_FULL = "Release Full"
PREVIEW_UI_POLL_MS = 30
PREVIEW_WORKER_QUEUE_WAIT_S = 0.008
PREVIEW_JOIN_TIMEOUT_S = 1.5
EVENT_POLL_SECONDS = 0.25
EVENT_SCAN_TIMEOUT_SECONDS = 12.0
EVENT_SETTLE_SECONDS = 0.75
RECONNECT_ATTEMPTS = 6
RECONNECT_INTERVAL_SECONDS = 1.25
USB_DEBOUNCE_SECONDS = 0.75


class AppLogger:
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"aag-canon-{datetime.now():%Y%m%d}.log"
        self._lock = threading.Lock()

    def write(self, message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S.%f} {message.rstrip()}\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)


@dataclass
class CameraFileRef:
    folder: str
    name: str

    @property
    def key(self) -> tuple[str, str]:
        return self.folder, self.name


@dataclass
class PreviewFrame:
    jpeg: bytes
    acquired_at: float
    acquire_ms: float


class CanonSession:
    """Owns one persistent libgphoto2 session and all camera operations."""

    def __init__(self, logger: AppLogger):
        self.log = logger
        self.camera: Optional[gp.Camera] = None
        self.model: Optional[str] = None
        self.port: Optional[str] = None
        self.initialized = False
        self._known_files: set[tuple[str, str]] = set()

    @staticmethod
    def usb_present() -> bool:
        try:
            proc = subprocess.run(
                ["lsusb", "-d", TARGET_USB_ID],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2.0,
            )
            return bool(proc.stdout.strip())
        except Exception:
            return False

    def targeted_release(self) -> None:
        """Unmount only the Canon GVFS PTP mount if GNOME currently owns it."""
        try:
            subprocess.run(
                ["gio", "mount", "-u", TARGET_GVFS_URI],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
            )
            time.sleep(0.15)
        except Exception as exc:
            self.log.write(f"GVFS targeted release warning: {exc!r}")

    def _detect(self) -> tuple[str, str]:
        detected = gp.Camera.autodetect()
        for model, port in detected:
            if model == TARGET_MODEL:
                return model, port
        raise RuntimeError(
            f"{TARGET_MODEL} is not available to libgphoto2. "
            "Check the USB connection and camera power."
        )

    def connect(self) -> None:
        if self.camera is not None:
            self.disconnect()
        if not self.usb_present():
            raise RuntimeError(
                f"{TARGET_MODEL} is not present on USB ({TARGET_USB_ID})."
            )
        self.targeted_release()
        model, port = self._detect()
        camera = gp.Camera()
        abilities_list = gp.CameraAbilitiesList()
        abilities_list.load()
        index = abilities_list.lookup_model(model)
        camera.set_abilities(abilities_list[index])
        port_info_list = gp.PortInfoList()
        port_info_list.load()
        port_index = port_info_list.lookup_path(port)
        camera.set_port_info(port_info_list[port_index])
        camera.init()
        self.camera = camera
        self.model = model
        self.port = port
        self.initialized = True
        self.log.write(f"Camera connected: model={model!r} port={port!r}")
        try:
            self._known_files = self.list_files()
        except Exception as exc:
            self.log.write(f"Initial file inventory warning: {exc!r}")
            self._known_files = set()

    def disconnect(self) -> None:
        camera = self.camera
        self.camera = None
        self.initialized = False
        self.model = None
        self.port = None
        if camera is not None:
            try:
                camera.exit()
            except Exception as exc:
                self.log.write(f"Camera exit warning: {exc!r}")
        self.log.write("Camera session closed")

    def _require(self) -> gp.Camera:
        if self.camera is None:
            raise RuntimeError("Camera is not connected.")
        return self.camera

    def get_summary(self) -> str:
        return self._require().get_summary()

    def get_config(self) -> gp.CameraWidget:
        return self._require().get_config()

    @staticmethod
    def _widget_by_path(root: gp.CameraWidget, path: str) -> gp.CameraWidget:
        node = root
        for component in [part for part in path.split("/") if part]:
            node = node.get_child_by_name(component)
        return node

    def get_widget(self, path: str) -> gp.CameraWidget:
        return self._widget_by_path(self.get_config(), path)

    def get_config_value(self, path: str) -> Any:
        return self.get_widget(path).get_value()

    def get_config_choices(self, path: str) -> list[Any]:
        return list(self.get_widget(path).get_choices())

    def set_config_value(self, path: str, value: Any) -> None:
        camera = self._require()
        root = camera.get_config()
        widget = self._widget_by_path(root, path)
        if hasattr(widget, "get_readonly") and widget.get_readonly():
            raise RuntimeError(f"Camera setting is read-only: {path}")
        widget.set_value(value)
        camera.set_config(root)

    def load_controls(self) -> dict[str, Any]:
        controls: dict[str, Any] = {}
        specs = {
            "shutter": EOS_SHUTTERSPEED_PATH,
            "aperture": EOS_APERTURE_PATH,
            "iso": EOS_ISO_PATH,
            "imageformat": EOS_IMAGEFORMAT_PATH,
            "af_method": EOS_AF_METHOD_PATH,
        }
        for name, path in specs.items():
            try:
                controls[name] = {
                    "value": self.get_config_value(path),
                    "choices": self.get_config_choices(path),
                    "error": None,
                }
            except Exception as exc:
                controls[name] = {"value": None, "choices": [], "error": str(exc)}
        return controls

    def set_live_view(self, enabled: bool) -> None:
        self.set_config_value(EOS_EVFOUTPUTDEVICE_PATH, 1 if enabled else 0)

    def capture_preview(self) -> bytes:
        camera_file = self._require().capture_preview()
        data = camera_file.get_data_and_size()
        if not data:
            raise RuntimeError("The camera returned an empty Live View frame.")
        return bytes(data)

    def autofocus_once(self, method_value: Optional[Any] = None) -> None:
        if method_value is not None:
            self.set_config_value(EOS_AF_METHOD_PATH, method_value)
        try:
            self.set_config_value(EOS_AFDRIVE_PATH, 1)
        finally:
            try:
                self.set_config_value(EOS_CANCELAF_PATH, 1)
            except Exception as exc:
                self.log.write(f"cancelautofocus cleanup warning: {exc!r}")

    def _camera_folders(self, folder: str = "/") -> Iterable[str]:
        camera = self._require()
        try:
            for child in camera.folder_list_folders(folder):
                name = child[0] if isinstance(child, tuple) else child
                child_path = (folder.rstrip("/") + "/" + name).replace("//", "/")
                yield child_path
                yield from self._camera_folders(child_path)
        except gp.GPhoto2Error:
            return

    def list_files(self) -> set[tuple[str, str]]:
        camera = self._require()
        found: set[tuple[str, str]] = set()
        folders = ["/"] + list(self._camera_folders("/"))
        for folder in folders:
            try:
                for item in camera.folder_list_files(folder):
                    name = item[0] if isinstance(item, tuple) else item
                    found.add((folder, name))
            except gp.GPhoto2Error:
                continue
        return found

    def _drain_events(self, seconds: float = 0.35) -> None:
        camera = self._require()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            event_type, _event_data = camera.wait_for_event(50)
            if event_type == gp.GP_EVENT_TIMEOUT:
                continue

    @staticmethod
    def _event_file_ref(event_data: Any) -> Optional[CameraFileRef]:
        if event_data is None:
            return None
        folder = getattr(event_data, "folder", None)
        name = getattr(event_data, "name", None)
        if folder and name:
            return CameraFileRef(str(folder), str(name))
        if isinstance(event_data, tuple) and len(event_data) >= 2:
            return CameraFileRef(str(event_data[0]), str(event_data[1]))
        return None

    def _wait_for_new_file(
        self,
        before: set[tuple[str, str]],
        timeout: float = EVENT_SCAN_TIMEOUT_SECONDS,
    ) -> CameraFileRef:
        camera = self._require()
        deadline = time.monotonic() + timeout
        event_candidate: Optional[CameraFileRef] = None
        while time.monotonic() < deadline:
            event_type, event_data = camera.wait_for_event(int(EVENT_POLL_SECONDS * 1000))
            if event_type == gp.GP_EVENT_FILE_ADDED:
                ref = self._event_file_ref(event_data)
                if ref is not None:
                    event_candidate = ref
                    self.log.write(f"FILE_ADDED event: {ref.folder}/{ref.name}")
                    return ref
            if event_type == gp.GP_EVENT_TIMEOUT:
                try:
                    after = self.list_files()
                    diff = after - before
                    if diff:
                        folder, name = sorted(diff)[-1]
                        self.log.write(f"New file found by bounded scan: {folder}/{name}")
                        return CameraFileRef(folder, name)
                except Exception:
                    pass
        if event_candidate is not None:
            return event_candidate
        raise TimeoutError("Timed out waiting for the camera to report the captured file.")

    def trigger_capture(self) -> CameraFileRef:
        before = self.list_files()
        self._drain_events()
        self.set_config_value(EOS_REMOTE_RELEASE_PATH, REMOTE_PRESS_FULL)
        time.sleep(0.08)
        self.set_config_value(EOS_REMOTE_RELEASE_PATH, REMOTE_RELEASE_FULL)
        ref = self._wait_for_new_file(before)
        time.sleep(EVENT_SETTLE_SECONDS)
        return ref

    def download_file(self, ref: CameraFileRef, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        camera_file = self._require().file_get(ref.folder, ref.name, gp.GP_FILE_TYPE_NORMAL)
        camera_file.save(str(temporary))
        if not temporary.exists() or temporary.stat().st_size <= 0:
            raise RuntimeError(f"Downloaded camera file is empty: {temporary}")
        with temporary.open("rb") as fh:
            os.fsync(fh.fileno())
        os.replace(temporary, destination)
        self.log.write(
            f"Downloaded {ref.folder}/{ref.name} -> {destination} ({destination.stat().st_size} bytes)"
        )
        self._known_files.add(ref.key)
        return destination

    def capture_and_download(self, base_dir: Path) -> Path:
        ref = self.trigger_capture()
        day_dir = Path(base_dir) / datetime.now().strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        target = day_dir / ref.name
        if target.exists():
            stem, suffix = target.stem, target.suffix
            target = day_dir / f"{stem}-{datetime.now():%H%M%S}{suffix}"
        return self.download_file(ref, target)


class CameraWorker(threading.Thread):
    def __init__(self, logger: AppLogger):
        super().__init__(name="aag-canon-camera", daemon=True)
        self.log = logger
        self.session = CanonSession(logger)
        self.commands: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any], Optional[Callable[[Any, Optional[BaseException]], None]]]] = queue.Queue()
        self.stop_event = threading.Event()

    def submit(
        self,
        func: Callable[..., Any],
        *args: Any,
        callback: Optional[Callable[[Any, Optional[BaseException]], None]] = None,
        **kwargs: Any,
    ) -> None:
        self.commands.put((func, args, kwargs, callback))

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                func, args, kwargs, callback = self.commands.get(timeout=0.1)
            except queue.Empty:
                continue
            result: Any = None
            error: Optional[BaseException] = None
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:  # keep worker alive after camera errors
                error = exc
                self.log.write(f"Worker error in {getattr(func, '__name__', func)!r}: {exc!r}")
                self.log.write(traceback.format_exc())
            finally:
                self.commands.task_done()
            if callback is not None:
                try:
                    callback(result, error)
                except Exception as exc:
                    self.log.write(f"Worker callback error: {exc!r}")

    def stop(self) -> None:
        self.stop_event.set()


class CanonApp:
    def __init__(self, root: tk.Tk, logger: AppLogger, lock_handle: Any):
        self.root = root
        self.log = logger
        self.lock_handle = lock_handle
        self.worker = CameraWorker(logger)
        self.worker.start()
        self.base_dir = DEFAULT_BASE_DIR
        self.connected = False
        self.live_requested = False
        self.preview_running = False
        self.preview_generation = 0
        self.latest_preview: Optional[PreviewFrame] = None
        self.latest_preview_lock = threading.Lock()
        self.preview_stop_event = threading.Event()
        self.preview_thread: Optional[threading.Thread] = None
        self.last_display_at: Optional[float] = None
        self.display_intervals: deque[float] = deque(maxlen=30)
        self.usb_last_state = CanonSession.usb_present()
        self.usb_state_since = time.monotonic()
        self.reconnect_in_progress = False
        self.closing = False

        self.status_var = tk.StringVar(value="Starting...")
        self.detail_var = tk.StringVar(value="")
        self.fps_var = tk.StringVar(value="Live View: stopped")
        self.output_var = tk.StringVar(value=str(self.base_dir))
        self.shutter_var = tk.StringVar(value="")
        self.aperture_var = tk.StringVar(value="")
        self.iso_var = tk.StringVar(value="")
        self.format_var = tk.StringVar(value="")
        self.af_method_var = tk.StringVar(value="Live")
        self.af_method_values: dict[str, Any] = {}

        root.title(APP_NAME)
        root.geometry("1100x780")
        root.minsize(920, 650)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build_ui()
        self.root.after(PREVIEW_UI_POLL_MS, self._poll_preview_ui)
        self.root.after(350, self._usb_watchdog)
        self._set_status("Connecting to Canon EOS 4000D...")
        self._connect_async(initial=True)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text=APP_NAME, font=("Sans", 16, "bold")).pack(side="left")
        ttk.Label(top, text=f"v{APP_VERSION}").pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Reconnect", command=self.reconnect_clicked).pack(side="right")

        status = ttk.LabelFrame(outer, text="Camera status", padding=8)
        status.pack(fill="x", pady=(0, 8))
        ttk.Label(status, textvariable=self.status_var, font=("Sans", 11, "bold")).pack(anchor="w")
        ttk.Label(status, textvariable=self.detail_var).pack(anchor="w", pady=(3, 0))

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True)

        preview_box = ttk.LabelFrame(body, text="Live View", padding=6)
        controls = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(preview_box, weight=4)
        body.add(controls, weight=2)

        self.preview_label = ttk.Label(preview_box, anchor="center")
        self.preview_label.pack(fill="both", expand=True)
        ttk.Label(preview_box, textvariable=self.fps_var).pack(anchor="w", pady=(5, 0))

        live_row = ttk.Frame(controls)
        live_row.pack(fill="x", pady=(0, 8))
        self.live_button = ttk.Button(live_row, text="Start Live View", command=self.toggle_live_view)
        self.live_button.pack(side="left", fill="x", expand=True)

        af_box = ttk.LabelFrame(controls, text="Autofocus", padding=8)
        af_box.pack(fill="x", pady=(0, 8))
        ttk.Label(af_box, text="AF Method").grid(row=0, column=0, sticky="w")
        self.af_combo = ttk.Combobox(af_box, textvariable=self.af_method_var, state="readonly", width=14)
        self.af_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.af_button = ttk.Button(af_box, text="AF Once", command=self.af_once_clicked)
        self.af_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        af_box.columnconfigure(1, weight=1)

        camera_box = ttk.LabelFrame(controls, text="Camera controls", padding=8)
        camera_box.pack(fill="x", pady=(0, 8))
        self.shutter_combo = self._control_row(camera_box, 0, "Shutter", self.shutter_var)
        self.aperture_combo = self._control_row(camera_box, 1, "Aperture", self.aperture_var)
        self.iso_combo = self._control_row(camera_box, 2, "ISO", self.iso_var)
        self.format_combo = self._control_row(camera_box, 3, "Image format", self.format_var)
        self.shutter_combo.bind("<<ComboboxSelected>>", lambda _e: self._set_control(EOS_SHUTTERSPEED_PATH, self.shutter_var.get()))
        self.aperture_combo.bind("<<ComboboxSelected>>", lambda _e: self._set_control(EOS_APERTURE_PATH, self.aperture_var.get()))
        self.iso_combo.bind("<<ComboboxSelected>>", lambda _e: self._set_control(EOS_ISO_PATH, self.iso_var.get()))
        self.format_combo.bind("<<ComboboxSelected>>", lambda _e: self._set_control(EOS_IMAGEFORMAT_PATH, self.format_var.get()))

        capture_box = ttk.LabelFrame(controls, text="Capture", padding=8)
        capture_box.pack(fill="x", pady=(0, 8))
        ttk.Label(capture_box, text="Download folder").pack(anchor="w")
        ttk.Label(capture_box, textvariable=self.output_var, wraplength=300).pack(anchor="w", pady=(2, 8))
        self.capture_button = ttk.Button(capture_box, text="Capture & Download", command=self.capture_clicked)
        self.capture_button.pack(fill="x")

        note = ttk.LabelFrame(controls, text="Camera setup", padding=8)
        note.pack(fill="x")
        ttk.Label(
            note,
            justify="left",
            wraplength=320,
            text=(
                "Required: Auto Power Off = Disable in the camera menu.\n\n"
                "M mode is optional. Use M only when you want manual shutter, aperture and ISO controls.\n\n"
                "The lens switch must be on AF only when using AF Once. MF remains valid for normal Live View and capture."
            ),
        ).pack(anchor="w")

    @staticmethod
    def _control_row(parent: ttk.LabelFrame, row: int, label: str, variable: tk.StringVar) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        combo = ttk.Combobox(parent, textvariable=variable, state="readonly", width=18)
        combo.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
        parent.columnconfigure(1, weight=1)
        return combo

    def _ui(self, func: Callable[[], None]) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, func)
        except tk.TclError:
            pass

    def _set_status(self, status: str, detail: Optional[str] = None) -> None:
        self.status_var.set(status)
        if detail is not None:
            self.detail_var.set(detail)
        self.log.write(f"STATUS: {status}" + (f" | {detail}" if detail else ""))

    def _connect_async(self, initial: bool = False) -> None:
        if self.reconnect_in_progress or self.closing:
            return
        self.reconnect_in_progress = True
        self._set_status("Connecting...", "Releasing only the Canon GVFS mount and opening one PTP session.")

        def done(result: Any, error: Optional[BaseException]) -> None:
            def finish() -> None:
                self.reconnect_in_progress = False
                if error:
                    self.connected = False
                    self._set_status("Camera unavailable", self._friendly_error(error))
                    if initial:
                        self.log.write("Initial camera connection failed; reconnect remains available.")
                    return
                self.connected = True
                self._set_status(
                    "Ready",
                    f"{self.worker.session.model} on {self.worker.session.port}. Auto Power Off must be Disabled.",
                )
                self._refresh_controls_async()
            self._ui(finish)

        self.worker.submit(self.worker.session.connect, callback=done)

    def _disconnect_async(self, callback: Optional[Callable[[], None]] = None) -> None:
        self._stop_preview_local()

        def done(_result: Any, _error: Optional[BaseException]) -> None:
            def finish() -> None:
                self.connected = False
                if callback:
                    callback()
            self._ui(finish)

        self.worker.submit(self.worker.session.disconnect, callback=done)

    def reconnect_clicked(self) -> None:
        if self.reconnect_in_progress:
            return
        self.live_requested = False
        self.live_button.configure(text="Start Live View")
        self._stop_preview_local()

        def reconnect_after_disconnect(_result: Any, _error: Optional[BaseException]) -> None:
            self._ui(lambda: self._connect_async(initial=False))

        self.worker.submit(self.worker.session.disconnect, callback=reconnect_after_disconnect)

    def _refresh_controls_async(self) -> None:
        def done(result: Any, error: Optional[BaseException]) -> None:
            if error:
                return

            def apply() -> None:
                specs = [
                    ("shutter", self.shutter_var, self.shutter_combo),
                    ("aperture", self.aperture_var, self.aperture_combo),
                    ("iso", self.iso_var, self.iso_combo),
                    ("imageformat", self.format_var, self.format_combo),
                ]
                for name, variable, combo in specs:
                    info = result.get(name, {})
                    choices = [str(x) for x in info.get("choices", [])]
                    combo.configure(values=choices)
                    value = info.get("value")
                    if value is not None:
                        variable.set(str(value))
                    combo.configure(state="readonly" if choices else "disabled")

                af = result.get("af_method", {})
                choices = af.get("choices", [])
                labels: list[str] = []
                self.af_method_values = {}
                for choice in choices:
                    key = str(choice)
                    label = AF_METHOD_LABELS.get(key, key)
                    labels.append(label)
                    self.af_method_values[label] = choice
                self.af_combo.configure(values=labels)
                current_key = str(af.get("value")) if af.get("value") is not None else ""
                self.af_method_var.set(AF_METHOD_LABELS.get(current_key, current_key or "Live"))
                self.af_combo.configure(state="readonly" if labels else "disabled")
            self._ui(apply)

        self.worker.submit(self.worker.session.load_controls, callback=done)

    def _set_control(self, path: str, value: Any) -> None:
        if not self.connected:
            return

        def done(_result: Any, error: Optional[BaseException]) -> None:
            if error:
                self._ui(lambda: messagebox.showerror(APP_NAME, self._friendly_error(error)))
            self._refresh_controls_async()

        self.worker.submit(self.worker.session.set_config_value, path, value, callback=done)

    def toggle_live_view(self) -> None:
        if not self.connected:
            messagebox.showwarning(APP_NAME, "Connect the camera first.")
            return
        if self.live_requested:
            self.live_requested = False
            self.live_button.configure(text="Start Live View")
            self._pause_preview_for_camera_op(disable_camera_live=True)
        else:
            self.live_requested = True
            self.live_button.configure(text="Stop Live View")
            self._start_live_view_async()

    def _start_live_view_async(self) -> None:
        if not self.connected or not self.live_requested or self.preview_running:
            return

        def done(_result: Any, error: Optional[BaseException]) -> None:
            if error:
                def fail() -> None:
                    self.live_requested = False
                    self.live_button.configure(text="Start Live View")
                    self._set_status("Live View failed", self._friendly_error(error))
                self._ui(fail)
                return
            self._ui(self._start_preview_local)

        self.worker.submit(self.worker.session.set_live_view, True, callback=done)

    def _start_preview_local(self) -> None:
        if self.preview_running or not self.live_requested or not self.connected:
            return
        self.preview_generation += 1
        generation = self.preview_generation
        self.preview_stop_event = threading.Event()
        self.preview_running = True
        self.display_intervals.clear()
        self.last_display_at = None
        self.preview_thread = threading.Thread(
            target=self._preview_loop,
            args=(generation, self.preview_stop_event),
            name="aag-canon-preview",
            daemon=True,
        )
        self.preview_thread.start()
        self._set_status("Live View active", "Preview frames are read in memory; no temporary image files are created.")

    def _preview_loop(self, generation: int, stop_event: threading.Event) -> None:
        next_start = time.monotonic()
        while not stop_event.is_set() and not self.closing:
            if generation != self.preview_generation:
                break
            now = time.monotonic()
            if now < next_start:
                stop_event.wait(min(PREVIEW_WORKER_QUEUE_WAIT_S, next_start - now))
                continue
            frame_start = time.monotonic()
            completed = threading.Event()
            payload: dict[str, Any] = {}

            def done(result: Any, error: Optional[BaseException]) -> None:
                payload["result"] = result
                payload["error"] = error
                completed.set()

            self.worker.submit(self.worker.session.capture_preview, callback=done)
            while not completed.wait(PREVIEW_WORKER_QUEUE_WAIT_S):
                if stop_event.is_set() or generation != self.preview_generation or self.closing:
                    return
            error = payload.get("error")
            if error is not None:
                self.log.write(f"Live View frame error: {error!r}")
                self._ui(lambda e=error: self._handle_preview_error(e))
                return
            jpeg = payload.get("result")
            acquired = time.monotonic()
            frame = PreviewFrame(bytes(jpeg), acquired, (acquired - frame_start) * 1000.0)
            with self.latest_preview_lock:
                # Coalesce pending frames by replacing the undrawn frame with the newest one.
                self.latest_preview = frame
            # Start-to-start scheduling.  There is deliberately no completion-plus-delay sleep.
            next_start = frame_start

    def _poll_preview_ui(self) -> None:
        if self.closing:
            return
        frame: Optional[PreviewFrame] = None
        with self.latest_preview_lock:
            if self.latest_preview is not None:
                frame = self.latest_preview
                self.latest_preview = None
        if frame is not None and self.preview_running:
            render_start = time.monotonic()
            try:
                image = Image.open(io.BytesIO(frame.jpeg))
                image.load()
                width = max(self.preview_label.winfo_width(), 320)
                height = max(self.preview_label.winfo_height(), 240)
                image.thumbnail((width, height), Image.Resampling.BILINEAR)
                photo = ImageTk.PhotoImage(image)
                self.preview_label.configure(image=photo)
                self.preview_label.image = photo
                display_at = time.monotonic()
                if self.last_display_at is not None:
                    self.display_intervals.append(display_at - self.last_display_at)
                self.last_display_at = display_at
                fps = 0.0
                if self.display_intervals:
                    average = sum(self.display_intervals) / len(self.display_intervals)
                    fps = (1.0 / average) if average > 0 else 0.0
                ui_ms = (display_at - render_start) * 1000.0
                age_ms = (display_at - frame.acquired_at) * 1000.0
                self.fps_var.set(
                    f"{fps:.1f} FPS | acquire {frame.acquire_ms:.1f} ms | decode/render {ui_ms:.1f} ms | frame age {age_ms:.1f} ms"
                )
            except Exception as exc:
                self.log.write(f"Preview decode/render error: {exc!r}")
        try:
            self.root.after(PREVIEW_UI_POLL_MS, self._poll_preview_ui)
        except tk.TclError:
            pass

    def _handle_preview_error(self, error: BaseException) -> None:
        self.preview_running = False
        self.live_requested = False
        self.live_button.configure(text="Start Live View")
        self._set_status("Live View stopped", self._friendly_error(error))

    def _stop_preview_local(self) -> None:
        self.preview_generation += 1
        self.preview_stop_event.set()
        thread = self.preview_thread
        self.preview_thread = None
        self.preview_running = False
        with self.latest_preview_lock:
            self.latest_preview = None
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=PREVIEW_JOIN_TIMEOUT_S)
        self.fps_var.set("Live View: stopped")

    def _pause_preview_for_camera_op(
        self,
        continuation: Optional[Callable[[], None]] = None,
        disable_camera_live: bool = False,
    ) -> None:
        was_running = self.preview_running
        self._stop_preview_local()
        if disable_camera_live and self.connected:
            def done(_result: Any, _error: Optional[BaseException]) -> None:
                if continuation:
                    self._ui(continuation)
            self.worker.submit(self.worker.session.set_live_view, False, callback=done)
        elif continuation:
            continuation()
        if was_running and not disable_camera_live:
            self.log.write("Preview loop paused for serialized camera operation")

    def af_once_clicked(self) -> None:
        if not self.connected:
            messagebox.showwarning(APP_NAME, "Connect the camera first.")
            return
        resume_live = self.live_requested
        self.af_button.configure(state="disabled")
        self._set_status("Autofocus...", "The preview loop is paused while AF Once owns the camera session.")
        self._stop_preview_local()
        method = self.af_method_values.get(self.af_method_var.get())

        def done(_result: Any, error: Optional[BaseException]) -> None:
            def finish() -> None:
                self.af_button.configure(state="normal")
                if error:
                    friendly = self._friendly_error(error)
                    low = friendly.lower()
                    if any(token in low for token in ("not supported", "invalid", "busy", "focus")):
                        friendly = (
                            "Autofocus could not run. If the lens switch is set to MF, move it to AF and try again. "
                            "MF mode is still valid for Live View and capture.\n\n"
                            + friendly
                        )
                    self._set_status("Autofocus failed", friendly)
                else:
                    self._set_status("Autofocus complete", "AF Once finished and autofocus was released.")
                if resume_live and self.live_requested:
                    self._start_preview_local()
            self._ui(finish)

        self.worker.submit(self.worker.session.autofocus_once, method, callback=done)

    def capture_clicked(self) -> None:
        if not self.connected:
            messagebox.showwarning(APP_NAME, "Connect the camera first.")
            return
        resume_live = self.live_requested
        self.capture_button.configure(state="disabled")
        self._set_status("Capturing...", "Using the validated Canon remote-release path; existing camera files are not deleted.")
        self._stop_preview_local()

        def done(result: Any, error: Optional[BaseException]) -> None:
            def finish() -> None:
                self.capture_button.configure(state="normal")
                if error:
                    self._set_status("Capture failed", self._friendly_error(error))
                    messagebox.showerror(APP_NAME, self._friendly_error(error))
                else:
                    self._set_status("Capture complete", f"Saved to {result}")
                if resume_live and self.live_requested:
                    self._start_preview_local()
                self._refresh_controls_async()
            self._ui(finish)

        self.worker.submit(self.worker.session.capture_and_download, self.base_dir, callback=done)

    def _usb_watchdog(self) -> None:
        if self.closing:
            return
        present = CanonSession.usb_present()
        now = time.monotonic()
        if present != self.usb_last_state:
            if now - self.usb_state_since >= USB_DEBOUNCE_SECONDS:
                self.usb_last_state = present
                self.usb_state_since = now
                if not present:
                    self.live_requested = False
                    self.live_button.configure(text="Start Live View")
                    self._stop_preview_local()
                    self.connected = False
                    self._set_status("Camera disconnected", "USB connection was lost. Reconnect the camera to recover.")
                    self.worker.submit(self.worker.session.disconnect)
                else:
                    self._set_status("Camera detected", "Attempting bounded reconnect...")
                    self._bounded_reconnect(1)
            # A state transition was seen but has not been stable long enough yet.
        else:
            self.usb_state_since = now
        try:
            self.root.after(350, self._usb_watchdog)
        except tk.TclError:
            pass

    def _bounded_reconnect(self, attempt: int) -> None:
        if self.closing or not CanonSession.usb_present() or self.connected:
            return
        if attempt > RECONNECT_ATTEMPTS:
            self._set_status("Reconnect failed", "Use the Reconnect button after checking camera power and USB.")
            return
        if self.reconnect_in_progress:
            return
        self.reconnect_in_progress = True

        def done(_result: Any, error: Optional[BaseException]) -> None:
            def finish() -> None:
                self.reconnect_in_progress = False
                if error is None:
                    self.connected = True
                    self._set_status("Ready", f"{self.worker.session.model} reconnected on {self.worker.session.port}.")
                    self._refresh_controls_async()
                    return
                self.log.write(f"Reconnect attempt {attempt}/{RECONNECT_ATTEMPTS} failed: {error!r}")
                if attempt < RECONNECT_ATTEMPTS and CanonSession.usb_present():
                    self.root.after(
                        int(RECONNECT_INTERVAL_SECONDS * 1000),
                        lambda: self._bounded_reconnect(attempt + 1),
                    )
                else:
                    self._set_status("Reconnect failed", self._friendly_error(error))
            self._ui(finish)

        self.worker.submit(self.worker.session.connect, callback=done)

    @staticmethod
    def _friendly_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        lower = text.lower()
        if "could not claim interface" in lower or "resource busy" in lower:
            return (
                "The camera PTP interface is busy. GNOME/GVFS may have mounted the camera again. "
                "The manager uses only a targeted Canon GVFS release; reconnect the camera and press Reconnect."
            )
        if "no such device" in lower or "not present" in lower or "not available" in lower:
            return (
                "Canon EOS 4000D is not available on USB. Check camera power and cable. "
                "Also confirm MENU -> Setup -> Auto power off -> Disable."
            )
        return text

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.live_requested = False
        self._stop_preview_local()
        try:
            self.worker.session.disconnect()
        except Exception:
            pass
        self.worker.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def acquire_single_instance(lock_path: Path) -> Any:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError(f"{APP_NAME} is already running.")
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def status_mode(logger: AppLogger) -> int:
    present = CanonSession.usb_present()
    print(f"app={APP_NAME}")
    print(f"version={APP_VERSION}")
    print(f"usb_id={TARGET_USB_ID}")
    print(f"usb_present={'yes' if present else 'no'}")
    try:
        with DEFAULT_LOCK_PATH.open("a+") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                running = False
            except BlockingIOError:
                running = True
    except Exception:
        running = False
    print(f"manager_running={'yes' if running else 'no'}")
    print(f"log={logger.path}")
    return 0 if present else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--status", action="store_true", help="print a non-GUI status summary")
    args = parser.parse_args(argv)
    logger = AppLogger(DEFAULT_LOG_DIR)
    if args.status:
        return status_mode(logger)
    try:
        lock_handle = acquire_single_instance(DEFAULT_LOCK_PATH)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    logger.write(f"Starting {APP_NAME} v{APP_VERSION}")
    root = tk.Tk()
    app = CanonApp(root, logger, lock_handle)

    def on_signal(_signum: int, _frame: Any) -> None:
        app.close()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        root.mainloop()
    finally:
        try:
            lock_handle.close()
        except Exception:
            pass
        logger.write(f"Stopped {APP_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
