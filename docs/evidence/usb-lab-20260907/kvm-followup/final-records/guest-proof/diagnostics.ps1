$ErrorActionPreference='Stop'
$port=New-Object IO.Ports.SerialPort('COM2',115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$port.NewLine="`n";$port.Open()
try { for($i=0;$i -lt 900;$i++) {
  try {
    $pnp=@(Get-CimInstance Win32_PnPEntity | Where-Object {$_.PNPDeviceID -like 'USB*'} | Select-Object Name,PNPDeviceID,Service,Status,ConfigManagerErrorCode)
    $drivers=@(Get-CimInstance Win32_SystemDriver | Where-Object {$_.Name -in @('UASPStor','USBSTOR','USBXHCI')} | Select-Object Name,State,Started,StartMode)
    $port.WriteLine((@{time=(Get-Date -Format o);pnp=$pnp;drivers=$drivers;secureBoot=(Confirm-SecureBootUEFI);setupInProgress=(Get-ItemProperty HKLM:\SYSTEM\Setup).SystemSetupInProgress;os=(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber)} | ConvertTo-Json -Depth 8 -Compress))
  } catch {$port.WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))}
  Start-Sleep -Seconds 5
}} finally {$port.Close()}
