import wx
import sys
import threading
import serial.tools.list_ports
import os
import esptool
from configparser import ConfigParser
from serial import SerialException
from esptool import FatalError
import argparse

# this class credit marcelstoer
# See discussion at http://stackoverflow.com/q/41101897/131929
class RedirectText:
    def __init__(self, text_ctrl):
        self.out = text_ctrl
        self.pending_backspaces = 0

    def write(self, string):
        new_string = ""
        number_of_backspaces = 0
        for c in string:
            if c == "\b":
                number_of_backspaces += 1
            else:
                new_string += c

        if self.pending_backspaces > 0:
            # current value minus pending backspaces plus new string
            new_value = self.out.GetValue()[:-1 * self.pending_backspaces] + new_string
            wx.CallAfter(self.out.SetValue, new_value)
        else:
            wx.CallAfter(self.out.AppendText, new_string)

        self.pending_backspaces = number_of_backspaces

    def flush(self):
        None

class dfuTool(wx.Frame):

    ################################################################
    #                         INIT TASKS                           #
    ################################################################
    def __init__(self, parent, title):
        super(dfuTool, self).__init__(parent, title=title)

        self.baudrates = ['9600', '57600', '74880', '115200', '230400', '460800', '921600']
        self.SetSize(800,750)
        self.SetMinSize(wx.Size(800,600))
        self.Centre()
        self.initFlags()
        self.initUI()
        self.ESPTOOLARG_SERIALPORT = self.serialChoice.GetString(self.serialChoice.GetSelection())
        self.ESPTOOLARG_BAUD = self.ESPTOOLARG_BAUD # this default is regrettably loaded as part of the initUI process

        print('ESP32 Firmware Flash tool')
        print('--------------------------------------------')

    def initUI(self):
        '''Runs on application start to build the GUI'''

        self.mainPanel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        ################################################################
        #                   BEGIN SERIAL OPTIONS GUI                   #
        ################################################################
        self.serialPanel = wx.Panel(self.mainPanel)
        serialhbox = wx.BoxSizer(wx.HORIZONTAL)

        self.serialtext = wx.StaticText(self.serialPanel,label = "Serial Port:", style = wx.ALIGN_CENTRE)
        serialhbox.Add(self.serialtext,1,wx.ALL|wx.ALIGN_CENTER_VERTICAL,20)

        devices = self.list_serial_devices()
        self.serialChoice = wx.Choice(self.serialPanel, choices=devices)
        self.serialChoice.Bind(wx.EVT_CHOICE, self.on_serial_list_select)
        serialhbox.Add(self.serialChoice,3,wx.ALL|wx.ALIGN_CENTER_VERTICAL,20)

        self.scanButton = wx.Button(parent=self.serialPanel, label='Rescan Ports')
        self.scanButton.Bind(wx.EVT_BUTTON, self.on_serial_scan_request)
        serialhbox.Add(self.scanButton,2,wx.ALL|wx.ALIGN_CENTER_VERTICAL,20)

        self.serialAutoCheckbox = wx.CheckBox(parent=self.serialPanel,label="Auto-detect (slow)")
        self.serialAutoCheckbox.Bind(wx.EVT_CHECKBOX,self.on_serial_autodetect_check)
        serialhbox.Add(self.serialAutoCheckbox,2,wx.ALL|wx.ALIGN_CENTER_VERTICAL,20)

        vbox.Add(self.serialPanel,1, wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        ################################################################
        #                   BEGIN BAUD RATE GUI                        #
        ################################################################
        self.baudPanel = wx.Panel(self.mainPanel)
        baudhbox = wx.BoxSizer(wx.HORIZONTAL)

        self.baudtext = wx.StaticText(self.baudPanel,label = "Baud Rate:", style = wx.ALIGN_CENTRE)
        baudhbox.Add(self.baudtext,1,wx.ALL,20)

        # create a button for each baud rate
        for index, baud in enumerate(self.baudrates):
            # use the first button to initialise the group
            style = wx.RB_GROUP if index == 0 else 0

            baudChoice = wx.RadioButton(self.baudPanel,style=style,label=baud, name=baud)
            baudChoice.Bind(wx.EVT_RADIOBUTTON, self.on_baud_selected)
            baudChoice.baudrate = baud
            baudhbox.Add(baudChoice, 1, wx.TOP | wx.BOTTOM |wx.EXPAND, 20)

            # set the default up
            if index == len(self.baudrates) - 1:
                baudChoice.SetValue(True)
                self.ESPTOOLARG_BAUD = baudChoice.baudrate

        vbox.Add(self.baudPanel,1, wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        ################################################################
        #                   BEGIN PROJECT FILE SELECT GUI                   #
        ################################################################
        self.projectPanel = wx.Panel(self.mainPanel)
        projecthbox = wx.BoxSizer(wx.HORIZONTAL)

        self.projectdesc = wx.StaticText(self.projectPanel,label = "Project file:", style = wx.ALIGN_CENTRE)
        projecthbox.Add(self.projectdesc,0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,20)

        # read project from config file. If error reading, create new file
        config = ConfigParser() 
        try:
            config.read('espdfu.ini') #read the last used filename for the project file
            projfile = config.get('files', 'projfile')
        except:
            config.add_section('files')
            config.set('files', 'projfile', '')
            with open('espdfu.ini', 'w') as configfile:
                config.write(configfile) 
            projfile = ''

        if projfile == '':
            self.projectText = wx.TextCtrl(parent=self.projectPanel, value='No file selected',style=wx.TE_READONLY)
        else:
            self.projectText = wx.TextCtrl(parent=self.projectPanel, value=projfile, style=wx.TE_READONLY)
        projecthbox.Add(self.projectText,20,wx.TOP | wx.BOTTOM |wx.EXPAND,20)
        self.projectButton = wx.Button(parent=self.projectPanel, label='Browse...')
        self.projectButton.Bind(wx.EVT_BUTTON, self.on_project_browse_button)        
        projecthbox.Add(self.projectButton,0,wx.ALL|wx.ALIGN_CENTER_VERTICAL ,20)

        self.projectSaveButton = wx.Button(parent=self.projectPanel, label='Save')
        self.projectSaveButton.Bind(wx.EVT_BUTTON, self.on_project_save_button)        
        projecthbox.Add(self.projectSaveButton,0,wx.ALL|wx.ALIGN_CENTER_VERTICAL ,20)

        vbox.Add(self.projectPanel,1, wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        ################################################################
        #                   BEGIN ERASE BUTTON GUI                     #
        ################################################################
        self.eraseButton = wx.Button(parent=self.mainPanel, label='Erase ESP')
        self.eraseButton.Bind(wx.EVT_BUTTON, self.on_erase_button)

        self.eraseWarning= wx.StaticText(self.mainPanel,label = "WARNING: Erasing is not mandatory to flash a new app, but if you do, you must reflash ALL files.", style = wx.ALIGN_LEFT)

        vbox.Add(self.eraseButton,1, wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        vbox.Add(self.eraseWarning,1,wx.BOTTOM|wx.LEFT|wx.RIGHT|wx.EXPAND, 20 )
        ################################################################
        #                   BEGIN APP DFU FILE GUI                     #
        ################################################################
        self.appDFUpanel = wx.Panel(self.mainPanel)
        self.appDFUpanel.SetBackgroundColour('white')
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        self.appDFUCheckbox = wx.CheckBox(parent=self.appDFUpanel,label="Application    ")
        self.appDFUCheckbox.SetValue(True)
        self.appDFUCheckbox.Disable()
        hbox.Add(self.appDFUCheckbox,2,wx.EXPAND|wx.ALL,10)

        self.appAddrText = wx.TextCtrl(parent=self.appDFUpanel, value='0x10000')
        hbox.Add(self.appAddrText,1,wx.EXPAND|wx.ALL,10)

        self.app_pathtext = wx.TextCtrl(parent=self.appDFUpanel,value = "No File Selected")
        hbox.Add(self.app_pathtext,20,wx.EXPAND|wx.ALL,10)

        self.browseButton = wx.Button(parent=self.appDFUpanel, label='Browse...')
        self.browseButton.Bind(wx.EVT_BUTTON, self.on_app_browse_button)
        hbox.Add(self.browseButton, 0, wx.ALL, 10)

        vbox.Add(self.appDFUpanel,1,wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        ################################################################
        #                BEGIN PARTITIONS DFU FILE GUI                 #
        ################################################################
        self.partitionDFUpanel = wx.Panel(self.mainPanel)
        self.partitionDFUpanel.SetBackgroundColour('white')
        partitionhbox = wx.BoxSizer(wx.HORIZONTAL)

        self.partitionDFUCheckbox = wx.CheckBox(parent=self.partitionDFUpanel,label="Partition Table")
        partitionhbox.Add(self.partitionDFUCheckbox,2,wx.EXPAND|wx.ALL,10)

        self.partitionAddrText = wx.TextCtrl(parent=self.partitionDFUpanel, value='0x8000')
        partitionhbox.Add(self.partitionAddrText,1,wx.EXPAND|wx.ALL,10)

        self.partition_pathtext = wx.TextCtrl(parent=self.partitionDFUpanel,value = "No File Selected")
        partitionhbox.Add(self.partition_pathtext,20,wx.EXPAND|wx.ALL,10)

        self.browseButton = wx.Button(parent=self.partitionDFUpanel, label='Browse...')
        self.browseButton.Bind(wx.EVT_BUTTON, self.on_partition_browse_button)
        partitionhbox.Add(self.browseButton, 0, wx.ALL, 10)

        vbox.Add(self.partitionDFUpanel,1,wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        ################################################################
        #                BEGIN SPIFFS DFU FILE GUI                 #
        ################################################################
        self.spiffsDFUpanel = wx.Panel(self.mainPanel)
        self.spiffsDFUpanel.SetBackgroundColour('white')
        spiffshbox = wx.BoxSizer(wx.HORIZONTAL)

        self.spiffsDFUCheckbox = wx.CheckBox(parent=self.spiffsDFUpanel,label="Spiffs data    ")
        spiffshbox.Add(self.spiffsDFUCheckbox,2,wx.EXPAND|wx.ALL,10)

        self.spiffsAddrText = wx.TextCtrl(parent=self.spiffsDFUpanel, value='0x290000')
        spiffshbox.Add(self.spiffsAddrText,1,wx.EXPAND|wx.ALL,10)

        self.spiffs_pathtext = wx.TextCtrl(parent=self.spiffsDFUpanel,value = "No File Selected")
        spiffshbox.Add(self.spiffs_pathtext,20,wx.EXPAND|wx.ALL,10)

        self.browseButton = wx.Button(parent=self.spiffsDFUpanel, label='Browse...')
        self.browseButton.Bind(wx.EVT_BUTTON, self.on_spiffs_browse_button)
        spiffshbox.Add(self.browseButton, 0, wx.ALL, 10)

        vbox.Add(self.spiffsDFUpanel,1,wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        ################################################################
        #                BEGIN BOOTLOADER DFU FILE GUI                 #
        ################################################################
        self.bootloaderDFUpanel = wx.Panel(self.mainPanel)
        self.bootloaderDFUpanel.SetBackgroundColour('white')
        bootloaderhbox = wx.BoxSizer(wx.HORIZONTAL)

        self.bootloaderDFUCheckbox = wx.CheckBox(parent=self.bootloaderDFUpanel,label="Bootloader     ")
        bootloaderhbox.Add(self.bootloaderDFUCheckbox,2,wx.EXPAND|wx.ALL,10)

        self.bootloaderAddrText = wx.TextCtrl(parent=self.bootloaderDFUpanel, value='0x1000')
        bootloaderhbox.Add(self.bootloaderAddrText,1,wx.EXPAND|wx.ALL,10)

        self.bootloader_pathtext = wx.TextCtrl(parent=self.bootloaderDFUpanel,value = "No File Selected")
        bootloaderhbox.Add(self.bootloader_pathtext,20,wx.EXPAND|wx.ALL,10)

        self.browseButton = wx.Button(parent=self.bootloaderDFUpanel, label='Browse...')
        self.browseButton.Bind(wx.EVT_BUTTON, self.on_bootloader_browse_button)
        bootloaderhbox.Add(self.browseButton, 0, wx.ALL, 10)

        vbox.Add(self.bootloaderDFUpanel,1,wx.LEFT|wx.RIGHT|wx.EXPAND, 20)        
        ################################################################
        #                   BEGIN FLASH BUTTON GUI                     #
        ################################################################
        self.flashButton = wx.Button(parent=self.mainPanel, label='Flash')
        self.flashButton.Bind(wx.EVT_BUTTON, self.on_flash_button)

        vbox.Add(self.flashButton,1, wx.LEFT|wx.RIGHT|wx.EXPAND, 20)
        ################################################################
        #                   BEGIN CONSOLE OUTPUT GUI                   #
        ################################################################
        self.consolePanel = wx.TextCtrl(self.mainPanel, style=wx.TE_MULTILINE|wx.TE_READONLY)
        sys.stdout = RedirectText(self.consolePanel)

        vbox.Add(self.consolePanel,5, wx.ALL|wx.EXPAND, 20)
        ################################################################
        #                ASSOCIATE PANELS TO SIZERS                    #
        ################################################################
        self.appDFUpanel.SetSizer(hbox)
        self.partitionDFUpanel.SetSizer(partitionhbox)
        self.spiffsDFUpanel.SetSizer(spiffshbox)
        self.bootloaderDFUpanel.SetSizer(bootloaderhbox)
        self.serialPanel.SetSizer(serialhbox)
        self.projectPanel.SetSizer(projecthbox)
        self.baudPanel.SetSizer(baudhbox)
        self.mainPanel.SetSizer(vbox)

        # if a project file was loaded, set the options from it
        if projfile != '':
            self.load_options()

    def initFlags(self):
        '''Initialises the flags used to control the program flow'''
        self.ESPTOOL_BUSY = False

        self.ESPTOOLARG_AUTOSERIAL = False

        self.APPFILE_SELECTED = False
        self.PARTITIONFILE_SELECTED = False
        self.SPIFFSFILE_SELECTED = False
        self.BOOTLOADERFILE_SELECTED = False

        self.ESPTOOLMODE_ERASE = False
        self.ESPTOOLMODE_FLASH = False

        self.ESPTOOL_ERASE_USED = False

    ################################################################
    #                      UI EVENT HANDLERS                       #
    ################################################################
    def on_serial_scan_request(self, event):
        # disallow if automatic serial port is chosen
        if self.ESPTOOLARG_AUTOSERIAL:
            print('disable automatic mode first')
            return

        # repopulate the serial port choices and update the selected port
        print('rescanning serial ports...')
        devices = self.list_serial_devices()
        self.serialChoice.Clear()
        for device in devices:
            self.serialChoice.Append(device)
        self.ESPTOOLARG_SERIALPORT = self.serialChoice.GetString(self.serialChoice.GetSelection())
        print('serial choices updated')

    def on_serial_list_select(self,event):
        port = self.serialChoice.GetString(self.serialChoice.GetSelection())
        self.ESPTOOLARG_SERIALPORT = self.serialChoice.GetString(self.serialChoice.GetSelection())
        print('you chose '+port)

    def on_serial_autodetect_check(self,event):
        self.ESPTOOLARG_AUTOSERIAL = self.serialAutoCheckbox.GetValue()

        if self.ESPTOOLARG_AUTOSERIAL:
            self.serialChoice.Clear()
            self.serialChoice.Append('Automatic')
        else:
            self.on_serial_scan_request(event)

    def on_baud_selected(self,event):
        selection = event.GetEventObject()
        self.ESPTOOLARG_BAUD = selection.baudrate
        print('baud set to '+selection.baudrate)

    def on_erase_button(self, event):
        if self.ESPTOOL_BUSY:
            print('currently busy')
            return
        self.ESPTOOLMODE_ERASE = True
        self.ESPTOOL_ERASE_USED = True
        t = threading.Thread(target=self.esptoolRunner, daemon=True)
        t.start()

    def on_project_browse_button(self, event):
        with wx.FileDialog(self, "Open", "", "","*.ini", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            self.PROJFILE_SELECTED = True

        self.projectText.SetValue(os.path.abspath(path))
        self.ESPTOOLARG_PROJPATH=os.path.abspath(path) 
        #remember selected proj file for next time
        config = ConfigParser() 
        config.add_section('files')
        config.set('files', 'projfile', os.path.abspath(path))
        with open('espdfu.ini', 'w') as configfile:
            config.write(configfile) 
        #load settings
        self.load_options()


    def on_project_save_button(self, event):
        config = ConfigParser() 
        config.add_section('files')
        config.set('files', 'binfile', self.app_pathtext.GetLabel())
        config.set('files', 'partitionfile', self.partition_pathtext.GetLabel())
        config.set('files', 'bootfile', self.bootloader_pathtext.GetLabel())
        config.set('files', 'spiffsfile', self.spiffs_pathtext.GetLabel())
        config.set('files', 'binsel', str(self.appDFUCheckbox.GetValue()))
        config.set('files', 'partitionsel', str(self.partitionDFUCheckbox.GetValue()))
        config.set('files', 'bootsel', str(self.bootloaderDFUCheckbox.GetValue()))
        config.set('files', 'spiffssel', str(self.spiffsDFUCheckbox.GetValue()))
        config.add_section('comport')
        config.set('comport', 'port', self.ESPTOOLARG_SERIALPORT)
        config.set('comport', 'baudrate', self.ESPTOOLARG_BAUD)
        with open(self.projectText.GetValue(), 'w') as configfile:
            config.write(configfile) 

    def on_app_browse_button(self, event):
        with wx.FileDialog(self, "Open", "", "","*.bin", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            self.APPFILE_SELECTED = True

        self.app_pathtext.SetValue(os.path.abspath(path))

    def on_partition_browse_button(self, event):
        with wx.FileDialog(self, "Open", "", "","*.bin", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            self.PARTITIONFILE_SELECTED = True

        self.partition_pathtext.SetValue(os.path.abspath(path))

    def on_spiffs_browse_button(self, event):
        with wx.FileDialog(self, "Open", "", "","*.bin", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            self.SPIFFSFILE_SELECTED = True

        self.spiffs_pathtext.SetValue(os.path.abspath(path))

    def on_bootloader_browse_button(self, event):
        with wx.FileDialog(self, "Open", "", "","*.bin", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:

            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            path = fileDialog.GetPath()
            self.BOOTLOADERFILE_SELECTED = True

        self.bootloader_pathtext.SetValue(os.path.abspath(path))

    def on_flash_button(self, event):
        if self.ESPTOOL_BUSY:
            print('currently busy')
            return
        # handle cases where a flash has been requested but no file provided
        elif self.appDFUCheckbox.GetValue() & ~self.APPFILE_SELECTED:
            print('no app selected for flash')
            return
        elif self.partitionDFUCheckbox.GetValue() & ~self.PARTITIONFILE_SELECTED:
            print('no partition table selected for flash')
            return
        elif self.spiffsDFUCheckbox.GetValue() & ~self.SPIFFSFILE_SELECTED:
            print('no spiffs file selected for flash')
            return        
        elif self.bootloaderDFUCheckbox.GetValue() & ~self.BOOTLOADERFILE_SELECTED:
            print('no bootloader selected for flash')
            return
        else:
            # if the erase_flash has been used but we have not elected to upload all the required files
            if self.ESPTOOL_ERASE_USED & (~self.appDFUCheckbox.GetValue() | ~self.partitionDFUCheckbox.GetValue() | ~self.spiffsDFUCheckbox.GetValue()  | ~self.bootloaderDFUCheckbox.GetValue()):
                dialog = wx.MessageDialog(self.mainPanel, 'ESP32DFU detected use of \"Erase ESP\", which means you should reflash all files. Are you sure you want to continue? ','Warning',wx.YES_NO|wx.ICON_EXCLAMATION)
                ret = dialog.ShowModal()

                if ret == wx.ID_NO:
                    return

            # if we're uploading everything, clear the fact that erase_flash has been used
            if self.appDFUCheckbox.GetValue() & self.partitionDFUCheckbox.GetValue() & self.spiffsDFUCheckbox.GetValue() & self.bootloaderDFUCheckbox.GetValue():
                self.ESPTOOL_ERASE_USED = False

            self.ESPTOOLMODE_FLASH = True
            t = threading.Thread(target=self.esptoolRunner, daemon=True)
            t.start()

    ################################################################
    #                      MISC FUNCTIONS                          #
    ################################################################
    def list_serial_devices(self):
        ports = serial.tools.list_ports.comports()
        ports.sort()
        devices = []
        for port in ports:
            devices.append(port.device)
        return devices

    # load project file and set up the options correctly
    def load_options(self):
        config = ConfigParser() 
        try:
            config.read(self.projectText.GetValue())

            com=config.get('comport', 'port')
            self.ESPTOOLARG_SERIALPORT = com
            n=self.serialChoice.FindString(com)
            if n == wx.NOT_FOUND:
                wx.MessageDialog(self, 'COM port set in project file is not found', caption='Error')
            else:
                self.serialChoice.SetSelection(n)

            # not sure how to set the baudrate radiobuttons programatically
            # but we just usually want max speed anyway so just leave it set to default...
            #com=config.get('comport', 'baudrate')
            #self.ESPTOOLARG_BAUD = com
            #self.baudChoice.baudrate = com

            fpath=config.get('files', 'binfile')
            self.app_pathtext.SetValue(fpath)
            self.APPFILE_SELECTED = True
            
            fpath=config.get('files', 'partitionfile')
            self.partition_pathtext.SetValue(fpath)
            self.PARTITIONFILE_SELECTED = True

            fpath=config.get('files', 'spiffsfile')
            self.spiffs_pathtext.SetValue(fpath)
            self.SPIFFSFILE_SELECTED = True

            fpath=config.get('files', 'bootfile')
            self.bootloader_pathtext.SetValue(fpath)
            self.BOOTLOADERFILE_SELECTED = True

            if config.get('files', 'binsel') == "True":
                opt=True
            else:
                opt=False
            self.appDFUCheckbox.SetValue(opt)

            if config.get('files', 'partitionsel') == "True":
                opt=True
            else:
                opt=False
            self.partitionDFUCheckbox.SetValue(opt)

            if config.get('files', 'spiffssel') == "True":
                opt=True
            else:
                opt=False
            self.spiffsDFUCheckbox.SetValue(opt)

            if config.get('files', 'bootsel') == "True":
                opt=True
            else:
                opt=False
            self.bootloaderDFUCheckbox.SetValue(opt)



        except:
            wx.MessageDialog(self, 'Error loading project file', caption='Error')

    ################################################################
    #                    ESPTOOL FUNCTIONS                         #
    ################################################################
    def esptool_cmd_builder(self):
        '''Build the command that we would give esptool on the CLI'''
        cmd = ['--baud',self.ESPTOOLARG_BAUD]

        if self.ESPTOOLARG_AUTOSERIAL == False:
            cmd = cmd + ['--port',self.ESPTOOLARG_SERIALPORT]

        if self.ESPTOOLMODE_ERASE:
            cmd.append('erase_flash')
        elif self.ESPTOOLMODE_FLASH:
            cmd.append('write_flash')
            if self.bootloaderDFUCheckbox.GetValue():
                cmd.append(self.bootloaderAddrText.GetValue())
                cmd.append(self.bootloader_pathtext.GetValue())
            if self.appDFUCheckbox.GetValue():
                cmd.append(self.appAddrText.GetValue())
                cmd.append(self.app_pathtext.GetValue())
            if self.spiffsDFUCheckbox.GetValue():
                cmd.append(self.spiffsAddrText.GetValue())
                cmd.append(self.spiffs_pathtext.GetValue())
            if self.partitionDFUCheckbox.GetValue():
                cmd.append(self.partitionAddrText.GetValue())
                cmd.append(self.partition_pathtext.GetValue())

        print(cmd)
        return cmd

    def esptoolRunner(self):
        '''Handles the interaction with esptool'''
        self.ESPTOOL_BUSY = True

        cmd = self.esptool_cmd_builder()
        try:
            esptool.main(cmd)
            print('esptool execution completed')
        except esptool.FatalError as e:
            print(e)
            pass
        except serial.SerialException as e:
            print(e)
            pass
        except:
            print('unexpected error, maybe you chose invalid files, or files which overlap')
            pass

        self.ESPTOOL_BUSY = False
        self.ESPTOOLMODE_ERASE = False
        self.ESPTOOLMODE_FLASH = False


def main():

    app = wx.App()
    window = dfuTool(None, title='ESP32 Flash Programming Tool')
    window.Show()

    app.MainLoop()

if __name__ == '__main__':
    main()
