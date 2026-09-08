from pathlib import Path
import subprocess,os,xml.etree.ElementTree as ET,shutil
root=Path('/lab/windows11-native/seed');root.mkdir(mode=0o700)
old=Path('/lab/windows-11/seed')
ns='urn:schemas-microsoft-com:unattend';ET.register_namespace('',ns);ET.register_namespace('wcm','http://schemas.microsoft.com/WMIConfig/2002/State')
tree=ET.parse(old/'Autounattend.xml')
for settings in list(tree.getroot()):
 if settings.attrib.get('pass')=='windowsPE':tree.getroot().remove(settings)
tree.write(root/'usb-lab-unattend.xml',encoding='utf-8',xml_declaration=True)
os.chmod(root/'usb-lab-unattend.xml',0o600)
for name in ('bootstrap.ps1','windows_probe.ps1','diagnostics.ps1'):shutil.copy(old/name,root/name)
(root/'assign.txt').write_bytes(b'select disk 0\r\ndetail disk\r\nselect partition 1\r\nassign letter=S\r\nselect partition 3\r\nassign letter=W\r\nexit\r\n')
cmd=r'''@echo off
echo Configuring only the new disposable SATA Windows image.
diskpart /s "%~dp0assign.txt"
if not exist W:\Windows\System32\bcdboot.exe exit /b 1
W:\Windows\System32\bcdboot.exe W:\Windows /s S: /f UEFI
if errorlevel 1 exit /b 2
if not exist W:\Windows\Panther mkdir W:\Windows\Panther
copy /y "%~dp0usb-lab-unattend.xml" W:\Windows\Panther\unattend.xml >nul
if errorlevel 1 exit /b 3
echo USBLAB_BOOT_CONFIGURATION_COMPLETE
'''
(root/'prepare.cmd').write_bytes(cmd.replace('\n','\r\n').encode())
image=root/'seed.raw'
with image.open('xb') as f:f.truncate(64*1024**2)
os.chmod(image,0o600)
subprocess.run(['mkfs.vfat','-F','32','-n','USBLAB_SEED',str(image)],check=True)
for name in ('usb-lab-unattend.xml','bootstrap.ps1','windows_probe.ps1','diagnostics.ps1','assign.txt','prepare.cmd'):
 subprocess.run(['mcopy','-i',str(image),str(root/name),'::/'+name],check=True)
print('New private seed prepared without any automatic Windows PE repartition answer file.')
