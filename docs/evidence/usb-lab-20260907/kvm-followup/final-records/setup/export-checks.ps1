$ErrorActionPreference='Stop'
$v=@(Get-Volume | Where-Object FileSystemLabel -eq USBLABOUT)
if($v.Count -ne 1){throw 'Exact export volume absent'}
$d=Get-Partition -DriveLetter $v[0].DriveLetter | Get-Disk
if($d.SerialNumber.Trim() -ne 'USBLABOUT' -or $d.BusType.ToString() -ne 'USB' -or $d.Size -ne 536870912 -or $d.IsBoot -or $d.IsSystem){throw 'Export fixture identity mismatch'}
$to=$v[0].DriveLetter+':\'
$files=@()
foreach($name in @('Inventory','NativeTestsUpdated','Trace')){
 $source='C:\USBLab\'+$name
 if(-not (Test-Path $source)){throw ('Missing result '+$name)}
 Copy-Item -Recurse -Force $source $to
 foreach($f in @(Get-ChildItem -Recurse -File $source)){
  $relative=$f.FullName.Substring('C:\USBLab\'.Length)
  $a=(Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
  $b=(Get-FileHash ($to+$relative) -Algorithm SHA256).Hash.ToLower()
  if($a -ne $b){throw 'Export hash mismatch'}
  $files+=@{path=$relative;sha256=$a;bytes=$f.Length}
 }
}
@{time=(Get-Date -Format o);files=$files} | ConvertTo-Json -Depth 5 | Set-Content ($to+'export-verified.json')
Write-VolumeCache -DriveLetter $v[0].DriveLetter
