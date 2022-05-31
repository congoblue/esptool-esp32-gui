# ESP32 DFU Tool

A standalone GUI application for ESP32 firmware flashing compatible with Windows and macOS.
**Note:** Currently using esptool v2.6

![gui](/wgui.png "Gui appearance on Windows 10")

## Windows exe

You will need to have Python 3 installed to run the app, also the wxpython library. To make a standalone exe:

Install pyinstaller if you don't already have it

    pip install pyinstaller

To build exe go to the folder with the .py files and run

    pyinstaller --onefile espdfu.py

The exe file will be created in a folder "/dist"

Based on  [doayee-esp32](https://github.com/doayee/esptool-esp32-gui)

