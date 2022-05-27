# ESP32 DFU Tool

A standalone GUI application for ESP32 firmware flashing compatible with Windows and macOS.
**Note:** Currently using esptool v2.6

![gui](/wgui.png "Gui appearance on Windows 10")

## Windows exe

To build a windows exe go to the folder with the .py files and run

    pyinstaller --onefile espdfu.py

The exe file will be created in a folder "/dist"

Based on  [doayee-esp32](https://github.com/doayee/esptool-esp32-gui)

