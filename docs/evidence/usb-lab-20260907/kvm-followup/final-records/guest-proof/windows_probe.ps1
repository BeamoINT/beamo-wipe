# Only for an isolated evaluation guest connected through its virtual COM1.
$ErrorActionPreference='Stop'
function Inventory {
  $disks=@(Get-Disk | ForEach-Object { @{number=$_.Number;serial=$_.SerialNumber.Trim();transport=$_.BusType.ToString();size=$_.Size;readonly=$_.IsReadOnly;offline=$_.IsOffline;partitionStyle=$_.PartitionStyle.ToString();friendlyName=$_.FriendlyName} })
  $pnp=@(Get-CimInstance Win32_DiskDrive | Select-Object Index,Model,PNPDeviceID,InterfaceType,SerialNumber)
  return @{disks=$disks;pnp=$pnp;os=(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber)}
}
function Target($serial) {
  $items=@(Get-Disk | Where-Object {$_.SerialNumber.Trim() -eq $serial})
  if($items.Count -ne 1){throw 'USB identity absent or ambiguous'}
  if($items[0].BusType.ToString() -ne 'USB'){throw 'Not a USB disk'}
  return $items[0]
}
function Execute($request) {
  # Test-fixture evidence transport only. No arbitrary paths or commands.
  if($request.action -eq 'lab_evidence'){
    $names=@('native-updated-direct.txt','native-updated-exit.txt','NativeTestsUpdated\receipt.json','NativeTestsUpdated\stdout.txt','NativeTestsUpdated\stderr.txt','Trace\summary.txt','Handoff\fixture-before.json','Handoff\fixture-installed.json','Handoff\launcher-ready.json')
    $out=@{}
    foreach($name in $names){
      $path='C:\USBLab\'+$name
      if(Test-Path -LiteralPath $path -PathType Leaf){
        $bytes=[IO.File]::ReadAllBytes($path)
        if($bytes.Length -gt 262144){throw 'Oversized test evidence'}
        $out[$name]=[Convert]::ToBase64String($bytes)
      }
    }
    return $out
  }
  if($request.action -eq 'lab_shutdown_history'){
    return @(Get-WinEvent -FilterHashtable @{LogName='System';Id=1074,6006,6008} -MaxEvents 8 | Select-Object TimeCreated,Id,ProviderName,Message)
  }
  if($request.action -eq 'lab_export'){
    $d=Target 'USBLABOUT'
    if($d.Size -ne 536870912 -or $d.IsBoot -or $d.IsSystem){throw 'Exact export fixture required'}
    $vol=@($d | Get-Partition | Get-Volume | Where-Object {$_.DriveLetter -and $_.FileSystemLabel -eq 'USBLABOUT'})
    if($vol.Count -ne 1){throw 'Exact export volume required'}
    $to=$vol[0].DriveLetter+':\guest-proof'
    if(Test-Path -LiteralPath $to){throw 'Prior export exists'}
    Copy-Item -LiteralPath C:\USBLab -Destination $to -Recurse
    $files=@()
    foreach($file in @(Get-ChildItem -LiteralPath $to -Recurse -File)){
      $files+=@{path=$file.FullName.Substring($to.Length+1);sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLower();bytes=$file.Length}
    }
    Write-VolumeCache -DriveLetter $vol[0].DriveLetter
    return $files
  }

  if($request.action -eq 'inventory'){return (Inventory)}
  $disk=Target $request.serial
  if($request.action -eq 'product'){
    $volumes=@($disk | Get-Partition | Get-Volume | Where-Object {$_.DriveLetter})
    if($volumes.Count -ne 1){throw 'Expected exactly one mounted product volume'}
    $root=$volumes[0].DriveLetter+':\'
    $manifest=Get-Content -Raw -LiteralPath ($root+'desktop-build.json') | ConvertFrom-Json
    $hashes=@{}
    foreach($file in $manifest.files.PSObject.Properties){
      $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath ($root+$file.Name)).Hash.ToLower()
      if($actual -ne $file.Value){throw 'Packaged launcher checksum differs'}
      $hashes[$file.Name]=$actual
    }
    $exe=$root+'Start Beamo Wipe.exe'
    $json=(& $exe '--check-json' | Out-String)
    return @{hashes=$hashes;check=($json | ConvertFrom-Json);exit_code=$LASTEXITCODE;volume=$volumes[0].DriveLetter;driveType=$volumes[0].DriveType.ToString()}
  }
  if($request.action -notin @('read','write')){throw 'Unknown action'}
  if($request.serial -notmatch '^USBLAB[A-Z0-9]+$' -or $disk.Size -ne 67108864){throw 'Only exact 64 MiB USBLAB scratch fixtures permit raw I/O'}
  $access=[IO.FileAccess]::Read
  if($request.action -eq 'write'){$access=[IO.FileAccess]::ReadWrite}
  $stream=New-Object IO.FileStream(('\\.\PhysicalDrive'+$disk.Number),[IO.FileMode]::Open,$access,[IO.FileShare]::ReadWrite)
  try{
    [void]$stream.Seek(8388608,[IO.SeekOrigin]::Begin)
    $bytes=New-Object byte[] 4096
    if($request.action -eq 'write'){
      for($i=0;$i -lt $bytes.Length;$i++){$bytes[$i]=33}
      $prefix=[Text.Encoding]::ASCII.GetBytes("USBLAB-WRITE`n")
      [Array]::Copy($prefix,$bytes,$prefix.Length)
      $stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)
    }else{
      $n=$stream.Read($bytes,0,$bytes.Length)
      if($n -ne 4096){throw 'Short read'}
    }
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$hash=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLower()}finally{$sha.Dispose()}
    return @{sha256=$hash}
  }finally{$stream.Dispose()}
}
$port=New-Object IO.Ports.SerialPort('COM1',115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$port.NewLine="`n";$port.Open()
try{
  while($true){
    try{
      $request=$port.ReadLine() | ConvertFrom-Json
      $response=@{ok=$true;result=(Execute $request)}
    }catch{$response=@{ok=$false;error=$_.Exception.GetType().Name;message=$_.Exception.Message}}
    $port.WriteLine(($response | ConvertTo-Json -Depth 12 -Compress))
  }
}finally{$port.Close()}
