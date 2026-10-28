# MCHOSE L7 PRO monitor batery

Small Windows system tray app for the MCHOSE L7 Pro mouse. The battery icon fills and changes color as the charge level drops. Hover over the icon or open its menu to see the exact percentage.

## Features

- Reads the L7 Pro battery over its 2.4 GHz receiver or USB cable.
- Shows five charge bands: red, orange, yellow, light green, and green.
- Keeps the last reading visible while the mouse sleeps.
- Can start with Windows; the setting is available in the tray menu.
- Reads the battery locally and does not change mouse settings.

Bluetooth mode is not supported by this version.

## Download for Windows

Download [MCHOSE.L7.PRO.monitor.batery.exe](https://github.com/Gambarraca/mchose-l7-pro-monitor-batery/releases/latest/download/MCHOSE.L7.PRO.monitor.batery.exe) from the latest release. No Python installation is needed. On its first run, the app adds itself to the current Windows user's startup list. Right-click the tray icon to see the percentage, refresh, change the startup option, or exit.

If the icon is hidden, open the hidden-icons menu by the Windows clock and drag the battery icon into the visible tray area.

## Run from source

Requires Python 3.12 or later on Windows.

```powershell
python -m pip install -r requirements.txt
python l7_battery_tray.py
```

The tray icon appears near the clock. Move the mouse to wake it for an initial reading. If no reading appears, use 2.4 GHz mode with the receiver connected, or connect the mouse with its USB cable.

## Build the executable

```powershell
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "MCHOSE L7 PRO monitor batery" --hidden-import pystray._win32 l7_battery_tray.py
```

The executable is written to `dist/`.

## Protocol reference and trademarks

The application code (tray interface, polling loop, battery icon, and Windows startup) was written separately for this project. Its MCHOSE L7 Pro HID protocol implementation is based on publicly documented details in [Mouse Tray Charge](https://github.com/Fan4Metal/mouse_tray); the protocol was not independently reverse-engineered here. This project is an independent implementation and is not affiliated with or endorsed by MCHOSE or the reference project. MCHOSE and L7 are trademarks of their respective owners.

## License

No license is granted for reuse or redistribution. All rights are reserved by the project owner.
