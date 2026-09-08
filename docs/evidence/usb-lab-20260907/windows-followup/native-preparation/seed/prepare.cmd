@echo off
echo Configuring only the new disposable SATA Windows image.
diskpart /s "%~dp0assign.txt"
if not exist W:\Windows\System32\bcdboot.exe exit /b 1
W:\Windows\System32\bcdboot.exe W:\Windows /s S: /f UEFI
if errorlevel 1 exit /b 2
if not exist W:\Windows\Panther mkdir W:\Windows\Panther
copy /y "%~dp0usb-lab-unattend.xml" W:\Windows\Panther\unattend.xml >nul
if errorlevel 1 exit /b 3
echo USBLAB_BOOT_CONFIGURATION_COMPLETE
