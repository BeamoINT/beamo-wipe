from pathlib import Path
import subprocess,secrets,shutil,os
root=Path('/lab/windows-11/seed');root.mkdir(mode=0o700)
password='Lab!'+secrets.token_hex(12)+'7z'
(root/'password').write_text(password);os.chmod(root/'password',0o600)
xml=r'''<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
<settings pass="windowsPE">
<component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"><SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage><InputLocale>0409:00000409</InputLocale><SystemLocale>en-US</SystemLocale><UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale></component>
<component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
<DiskConfiguration><Disk wcm:action="add"><DiskID>0</DiskID><WillWipeDisk>true</WillWipeDisk><CreatePartitions>
<CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>260</Size></CreatePartition>
<CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>16</Size></CreatePartition>
<CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
</CreatePartitions><ModifyPartitions>
<ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Label>System</Label><Format>FAT32</Format></ModifyPartition>
<ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>3</PartitionID><Label>Windows</Label><Letter>C</Letter><Format>NTFS</Format></ModifyPartition>
</ModifyPartitions></Disk><WillShowUI>OnError</WillShowUI></DiskConfiguration>
<ImageInstall><OSImage><InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/INDEX</Key><Value>1</Value></MetaData></InstallFrom><InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo><WillShowUI>OnError</WillShowUI></OSImage></ImageInstall>
<UserData><AcceptEula>true</AcceptEula><FullName>USB Lab</FullName><Organization>Disposable evaluation</Organization></UserData>
</component></settings>
<settings pass="oobeSystem">
<component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"><InputLocale>0409:00000409</InputLocale><SystemLocale>en-US</SystemLocale><UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale></component>
<component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
<OOBE><HideEULAPage>true</HideEULAPage><HideOnlineAccountScreens>true</HideOnlineAccountScreens><HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE><ProtectYourPC>3</ProtectYourPC></OOBE>
<UserAccounts><AdministratorPassword><Value>PASS</Value><PlainText>true</PlainText></AdministratorPassword></UserAccounts>
<AutoLogon><Password><Value>PASS</Value><PlainText>true</PlainText></Password><Username>Administrator</Username><Enabled>true</Enabled><LogonCount>1</LogonCount></AutoLogon>
<TimeZone>UTC</TimeZone>
<FirstLogonCommands><SynchronousCommand wcm:action="add"><Order>1</Order><Description>Disposable USB lab probe</Description><CommandLine>powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$v=Get-Volume | Where-Object {$_.FileSystemLabel -eq 'USBLAB_SEED'}; &amp; ($v.DriveLetter+':\bootstrap.ps1')"</CommandLine></SynchronousCommand></FirstLogonCommands>
</component></settings></unattend>
'''.replace('PASS',password)
(root/'Autounattend.xml').write_text(xml);os.chmod(root/'Autounattend.xml',0o600)
bootstrap=r'''$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force C:\USBLab | Out-Null
Copy-Item ($PSScriptRoot+'\windows_probe.ps1') C:\USBLab\windows_probe.ps1
Copy-Item ($PSScriptRoot+'\diagnostics.ps1') C:\USBLab\diagnostics.ps1
Start-Process powershell.exe -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File C:\USBLab\diagnostics.ps1'
& C:\USBLab\windows_probe.ps1
'''
(root/'bootstrap.ps1').write_text(bootstrap)
diag=r'''$ErrorActionPreference='Stop'
$port=New-Object IO.Ports.SerialPort('COM2',115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$port.NewLine="`n";$port.Open()
try { for($i=0;$i -lt 900;$i++) {
  try {
    $pnp=@(Get-CimInstance Win32_PnPEntity | Where-Object {$_.PNPDeviceID -like 'USB*'} | Select-Object Name,PNPDeviceID,Service,Status,ConfigManagerErrorCode)
    $drivers=@(Get-CimInstance Win32_SystemDriver | Where-Object {$_.Name -in @('UASPStor','USBSTOR','USBXHCI')} | Select-Object Name,State,Started,StartMode)
    $port.WriteLine((@{time=(Get-Date -Format o);pnp=$pnp;drivers=$drivers} | ConvertTo-Json -Depth 8 -Compress))
  } catch {$port.WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))}
  Start-Sleep -Seconds 5
}} finally {$port.Close()}
'''
(root/'diagnostics.ps1').write_text(diag)
shutil.copy('/lab/harness/tools/usb_lab/windows_probe.ps1',root/'windows_probe.ps1')
image=root/'seed.raw'
with image.open('xb') as f:f.truncate(64*1024**2)
subprocess.run(['mkfs.vfat','-F','32','-n','USBLAB_SEED',str(image)],check=True)
for name in ('Autounattend.xml','bootstrap.ps1','windows_probe.ps1','diagnostics.ps1'):
 subprocess.run(['mcopy','-i',str(image),str(root/name),'::/'+name],check=True)
print('Private deployment seed prepared; no credential values emitted')
