$ErrorActionPreference='Stop'
$root='C:\USBLab\Trace'
if(Test-Path -LiteralPath $root){throw 'Trace directory exists; preserve prior evidence'}
New-Item -ItemType Directory -Path $root | Out-Null
& logman create trace -n BeamoUSBTrace -o "$root\usb.etl" -f bincirc -max 64 -nb 16 64 -bs 128
if($LASTEXITCODE -ne 0){throw 'Trace creation failed'}
foreach($provider in @('Microsoft-Windows-USB-USBXHCI','Microsoft-Windows-USB-UCX','Microsoft-Windows-USB-USBHUB3')){
 & logman update trace -n BeamoUSBTrace -p $provider '(Default,PartialDataBusTrace,StateMachine)'
 if($LASTEXITCODE -ne 0){throw ('Provider failed: '+$provider)}
}
& logman update trace -n BeamoUSBTrace -p Microsoft-Windows-Kernel-PnP 0xffffffffffffffff 5
if($LASTEXITCODE -ne 0){throw 'PnP provider failed'}
& logman start -n BeamoUSBTrace
if($LASTEXITCODE -ne 0){throw 'Trace start failed'}
Get-Date -Format o | Set-Content "$root\started.txt"
