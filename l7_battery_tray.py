"""Small Windows tray app for the MCHOSE L7 Pro battery level.

Reads the percentage pushed by the L7 Pro's HID interface. The tray icon is
local-only and the app does not change mouse settings or send data anywhere.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
import winreg

import hid
import pystray
from PIL import Image, ImageDraw, ImageFont


APP_NAME = "L7 Battery"
VENDOR_ID = 0x5253
WIRELESS_PRODUCT_ID = 0x1020
WIRED_PRODUCT_ID = 0x00B0
USAGE_PAGE = 0xFF01
USAGE = 0x0001
REPORT_ID = 0x13
REPORT_TYPE = 0x1D
BATTERY_OFFSET = 5
WIRED_OFFSET = 4
NUDGE_REPORT = [0x11, 0xF9] + [0xFF] * 19
LOW_BATTERY_THRESHOLD = 20
SCAN_INTERVAL_SECONDS = 5
NUDGE_INTERVAL_SECONDS = 8
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "L7BatteryTray"
AUTOSTART_CHOICE_VALUE = "L7BatteryTrayAutostartChoice"


def _log_path() -> Path:
    base = Path.home() / "AppData" / "Local" / "L7BatteryTray"
    base.mkdir(parents=True, exist_ok=True)
    return base / "app.log"


logging.basicConfig(
    filename=_log_path(),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


class L7BatteryTray:
    def __init__(self) -> None:
        self.icon: pystray.Icon | None = None
        self.stop_event = threading.Event()
        self.refresh_event = threading.Event()
        self._lock = threading.Lock()
        self.percent: int | None = None
        self.charging = False
        self.connected = False
        self.last_update: float | None = None
        self._was_fresh = False
        self.low_notice_sent = False
        self._last_error: str | None = None

    def run(self) -> None:
        self._ensure_autostart()
        self.icon = pystray.Icon(
            APP_NAME,
            self._make_icon(None),
            title="MCHOSE L7 Pro: buscando ratón…",
            menu=pystray.Menu(
                pystray.MenuItem(self._menu_status_text, self._noop_menu_action, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Actualizar ahora", self._request_refresh),
                pystray.MenuItem(
                    "Iniciar con Windows",
                    self._toggle_autostart,
                    checked=self._is_autostart_enabled,
                ),
                pystray.MenuItem("Acerca de L7 Battery", self._show_about),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", self._quit),
            ),
        )
        threading.Thread(target=self._reader_loop, name="l7-hid-reader", daemon=True).start()
        self.icon.run()

    @staticmethod
    def _noop_menu_action(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        return

    def _menu_status_text(self, _item: pystray.MenuItem) -> str:
        with self._lock:
            percent = self.percent
            connected = self.connected
            charging = self.charging
            last_update = self.last_update
        if percent is None:
            return "MCHOSE L7 Pro: buscando ratón…" if not connected else "MCHOSE L7 Pro: esperando lectura"
        if not connected:
            return f"MCHOSE L7 Pro: {percent}% (última lectura)"
        if last_update is not None and time.monotonic() - last_update >= 15:
            return f"MCHOSE L7 Pro: {percent}% (en reposo)"
        return f"MCHOSE L7 Pro: {percent}% · cargando" if charging else f"MCHOSE L7 Pro: {percent}%"

    @staticmethod
    def _autostart_command() -> str:
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"'
        executable = Path(sys.executable)
        if executable.name.lower() == "python.exe":
            windowed = executable.with_name("pythonw.exe")
            if windowed.exists():
                executable = windowed
        script = Path(__file__).resolve()
        return f'"{executable}" "{script}"'

    @classmethod
    def _ensure_autostart(cls) -> None:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                try:
                    choice, _ = winreg.QueryValueEx(key, AUTOSTART_CHOICE_VALUE)
                except FileNotFoundError:
                    choice = ""
                if choice == "disabled":
                    return
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, cls._autostart_command())
                winreg.SetValueEx(key, AUTOSTART_CHOICE_VALUE, 0, winreg.REG_SZ, "enabled")
        except OSError as exc:
            logging.warning("Could not configure Windows startup: %s", exc)

    @staticmethod
    def _is_autostart_enabled(_item: pystray.MenuItem | None = None) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                command, _ = winreg.QueryValueEx(key, RUN_VALUE)
            return command.strip().lower() == L7BatteryTray._autostart_command().lower()
        except OSError:
            return False

    def _toggle_autostart(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        try:
            if self._is_autostart_enabled():
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, RUN_VALUE)
                    winreg.SetValueEx(key, AUTOSTART_CHOICE_VALUE, 0, winreg.REG_SZ, "disabled")
                message = "La aplicación ya no se abrirá al iniciar Windows."
            else:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                    winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, self._autostart_command())
                    winreg.SetValueEx(key, AUTOSTART_CHOICE_VALUE, 0, winreg.REG_SZ, "enabled")
                message = "La aplicación se abrirá al iniciar Windows."
            if self.icon:
                self.icon.update_menu()
                self.icon.notify(message, APP_NAME)
        except OSError as exc:
            logging.warning("Could not update Windows startup: %s", exc)
            if self.icon:
                self.icon.notify("No se pudo cambiar el inicio automático.", APP_NAME)

    def _request_refresh(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.refresh_event.set()

    def _show_about(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        if self.icon:
            self.icon.notify(
                "Indicador de batería para MCHOSE L7 Pro. "
                "Lee el estado del ratón localmente por USB HID.",
                APP_NAME,
            )

    def _quit(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.stop_event.set()
        if self.icon:
            self.icon.stop()

    def _reader_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                device_path = self._find_device()
                if device_path is None:
                    self._set_disconnected()
                    self.stop_event.wait(SCAN_INTERVAL_SECONDS)
                    continue

                device = hid.device()
                try:
                    device.open_path(device_path)
                    device.set_nonblocking(0)
                    self._set_connected()
                    logging.info("Opened MCHOSE L7 Pro HID interface")
                    last_nudge = 0.0
                    last_scan = time.monotonic()

                    while not self.stop_event.is_set():
                        now = time.monotonic()
                        if now - last_scan >= SCAN_INTERVAL_SECONDS:
                            if self._find_device() is None:
                                self._set_disconnected()
                                break
                            last_scan = now
                        if self.refresh_event.is_set() or now - last_nudge >= NUDGE_INTERVAL_SECONDS:
                            self.refresh_event.clear()
                            try:
                                device.send_feature_report(NUDGE_REPORT)
                            except OSError as exc:
                                logging.debug("Status nudge was unavailable: %s", exc)
                            last_nudge = now

                        report = device.read(64, 500)
                        if report:
                            status = self._parse_report(report)
                            if status is not None:
                                percent, charging = status
                                self._set_status(percent, charging)
                        elif self._was_fresh and self.last_update is not None:
                            if time.monotonic() - self.last_update >= 15:
                                self._was_fresh = False
                                self._refresh_icon()
                finally:
                    try:
                        device.close()
                    except Exception:
                        pass
            except Exception as exc:
                message = f"HID read error: {exc}"
                if message != self._last_error:
                    logging.warning(message)
                    self._last_error = message
                self._set_connected(stale=True)
                self.stop_event.wait(SCAN_INTERVAL_SECONDS)

    @staticmethod
    def _find_device() -> bytes | str | None:
        for product_id in (WIRELESS_PRODUCT_ID, WIRED_PRODUCT_ID):
            try:
                devices = hid.enumerate(VENDOR_ID, product_id)
            except OSError:
                continue
            for device in devices:
                if device.get("usage_page") == USAGE_PAGE and device.get("usage") == USAGE:
                    return device.get("path")
        return None

    @staticmethod
    def _parse_report(report: list[int]) -> tuple[int, bool] | None:
        if len(report) <= BATTERY_OFFSET or report[0] != REPORT_ID or report[1] != REPORT_TYPE:
            return None
        percent = report[BATTERY_OFFSET] ^ 0xFF
        if not 0 <= percent <= 100:
            return None
        wired = bool(report[WIRED_OFFSET] ^ 0xFF) if len(report) > WIRED_OFFSET else False
        return percent, wired and percent < 100

    def _set_status(self, percent: int, charging: bool) -> None:
        with self._lock:
            previous = self.percent
            self.percent = percent
            self.charging = charging
            self.connected = True
            self.last_update = time.monotonic()
            self._was_fresh = True
            self._last_error = None
            if percent > LOW_BATTERY_THRESHOLD:
                self.low_notice_sent = False

        if percent <= LOW_BATTERY_THRESHOLD and not charging and not self.low_notice_sent:
            self.low_notice_sent = True
            if self.icon:
                self.icon.notify(f"Queda un {percent}% de batería. Conviene cargar el ratón.", APP_NAME)
        if previous != percent or charging:
            logging.info("Battery: %s%%, charging=%s", percent, charging)
        self._refresh_icon()

    def _set_connected(self, stale: bool = False) -> None:
        with self._lock:
            self.connected = True
        if stale and self.icon:
            self._refresh_icon()

    def _set_disconnected(self) -> None:
        with self._lock:
            self.connected = False
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        if not self.icon:
            return
        with self._lock:
            percent = self.percent
            connected = self.connected
            charging = self.charging
            last_update = self.last_update
        fresh = last_update is not None and (time.monotonic() - last_update) < 15
        self.icon.icon = self._make_icon(percent, fresh=fresh)
        if percent is None:
            title = "MCHOSE L7 Pro: buscando ratón…" if not connected else "MCHOSE L7 Pro: esperando lectura"
        elif not connected:
            title = f"MCHOSE L7 Pro: {percent}% (última lectura)"
        elif not fresh:
            title = f"MCHOSE L7 Pro: {percent}% (en reposo; mueve el ratón)"
        elif charging:
            title = f"MCHOSE L7 Pro: {percent}% · cargando"
        else:
            title = f"MCHOSE L7 Pro: {percent}%"
        self.icon.title = title
        self.icon.update_menu()

    @staticmethod
    def _make_icon(
        percent: int | None,
        *,
        fresh: bool = True,
    ) -> Image.Image:
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if percent is None:
            color = (105, 110, 118, 255)
        else:
            if percent <= 20:
                color = (235, 70, 70, 255)
            elif percent <= 40:
                color = (244, 135, 55, 255)
            elif percent <= 60:
                color = (240, 195, 55, 255)
            elif percent <= 80:
                color = (165, 215, 75, 255)
            else:
                color = (75, 205, 130, 255)

        # Battery silhouette, terminal, and a level fill that rises from the bottom.
        outline = (225, 231, 238, 255) if fresh else (150, 150, 150, 255)
        draw.rounded_rectangle((8, 12, 56, 60), radius=6, fill=(28, 32, 38, 255), outline=outline, width=3)
        draw.rounded_rectangle((23, 5, 41, 13), radius=3, fill=outline)
        draw.rounded_rectangle((13, 17, 51, 55), radius=3, fill=(15, 18, 22, 255))
        if percent is not None:
            fill_height = round(34 * percent / 100)
            if fill_height:
                draw.rectangle((16, 52 - fill_height, 48, 52), fill=color)

        return image


if __name__ == "__main__":
    L7BatteryTray().run()
