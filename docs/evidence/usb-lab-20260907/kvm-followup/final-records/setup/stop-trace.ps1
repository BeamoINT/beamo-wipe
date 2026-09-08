$ErrorActionPreference='Stop'
$root='C:\USBLab\Trace'
& logman stop -n BeamoUSBTrace
if($LASTEXITCODE -ne 0){throw 'Trace stop failed'}
& logman delete -n BeamoUSBTrace
if($LASTEXITCODE -ne 0){throw 'Trace collector deletion failed'}
Get-Date -Format o | Set-Content "$root\stopped.txt"
Get-PnpDevice | Where-Object {$_.InstanceId -like 'USB*'} | Format-List * | Out-File "$root\pnp.txt"
Get-ChildItem "$root\*.etl" | ForEach-Object {
 & tracerpt $_.FullName -of XML -o ($_.FullName+'.xml') -y
 if($LASTEXITCODE -ne 0){throw 'Trace export failed'}
}
Copy-Item C:\Windows\INF\setupapi.dev.log "$root\setupapi.dev.log"
Get-ChildItem $root -File | Get-FileHash -Algorithm SHA256 | Format-Table -AutoSize | Out-File "$root\hashes.txt"
