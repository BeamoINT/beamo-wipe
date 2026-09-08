# Fixture preparation only: never ship this with the product or run on a real PC.
$ErrorActionPreference='Stop'
$computer=Get-CimInstance Win32_ComputerSystem
$os=Get-CimInstance Win32_OperatingSystem
if($computer.Manufacturer -ne 'QEMU' -or $os.Caption -ne 'Microsoft Windows 11 Enterprise Evaluation'){throw 'Not the exact disposable QEMU evaluation fixture'}
if((Get-ItemProperty HKLM:\SYSTEM\Setup).SystemSetupInProgress -ne 0){throw 'Windows setup remains active'}
$disks=@(Get-Disk | Where-Object {$_.SerialNumber.Trim() -eq 'BEAMOBOOT'})
if($disks.Count -ne 1 -or $disks[0].BusType.ToString() -ne 'USB' -or $disks[0].IsBoot -or $disks[0].IsSystem){throw 'Exact product USB identity required'}
$disk=$disks[0]
$parts=@($disk | Get-Partition | Where-Object {$_.DriveLetter})
if($parts.Count -ne 1 -or $disk.PartitionStyle.ToString() -ne 'MBR' -or $disk.Signature -eq 0){throw 'Expected one mounted MBR product partition'}
$part=$parts[0];$root=$part.DriveLetter+':\'
$manifest=Get-Content -Raw ($root+'desktop-build.json') | ConvertFrom-Json
foreach($file in $manifest.files.PSObject.Properties){
 if((Get-FileHash -Algorithm SHA256 ($root+$file.Name)).Hash.ToLower() -ne $file.Value){throw 'Product package hash mismatch'}
}
if(-not (Test-Path -LiteralPath ($root+'EFI\BOOT\BOOTX64.EFI'))){throw 'Expected removable EFI loader missing'}
$out='C:\USBLab\Handoff'
if(Test-Path $out){throw 'Previous handoff evidence exists'}
New-Item -ItemType Directory $out | Out-Null
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class LabEfi {
 const string Guid="{8be4df61-93ca-11d2-aa0d-00e098032b8c}";
 [StructLayout(LayoutKind.Sequential)] struct LUID { public uint Low; public int High; }
 [StructLayout(LayoutKind.Sequential)] struct TP { public uint Count; public LUID Id; public uint Attributes; }
 [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr p,uint a,out IntPtr t);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool LookupPrivilegeValue(string s,string n,out LUID l);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool AdjustTokenPrivileges(IntPtr t,bool d,ref TP p,uint n,IntPtr prev,IntPtr len);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern uint GetFirmwareEnvironmentVariableEx(string n,string g,byte[] b,uint len,out uint a);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool SetFirmwareEnvironmentVariableEx(string n,string g,byte[] b,uint len,uint a);
 public static void Enable() {
  IntPtr t; if(!OpenProcessToken(GetCurrentProcess(),0x28,out t)) throw new Win32Exception();
  try { LUID l; if(!LookupPrivilegeValue(null,"SeSystemEnvironmentPrivilege",out l))throw new Win32Exception();
   TP p=new TP{Count=1,Id=l,Attributes=2};
   if(!AdjustTokenPrivileges(t,false,ref p,0,IntPtr.Zero,IntPtr.Zero)||Marshal.GetLastWin32Error()!=0)throw new Win32Exception();
  } finally {CloseHandle(t);}
 }
 public static byte[] Read(string n) {
  byte[] b=new byte[16384]; uint a; uint len=GetFirmwareEnvironmentVariableEx(n,Guid,b,(uint)b.Length,out a);
  if(len==0){int e=Marshal.GetLastWin32Error();if(e==203)return null;throw new Win32Exception(e);}
  Array.Resize(ref b,(int)len);return b;
 }
 public static void Write(string n,byte[] b) {
  if(n!="Boot9001" && n!="BootOrder")throw new Exception("Fixture write name rejected");
  if(!SetFirmwareEnvironmentVariableEx(n,Guid,b,(uint)b.Length,7))throw new Win32Exception();
 }
}
'@
[LabEfi]::Enable()
if($null -ne [LabEfi]::Read('BootNext') -or $null -ne [LabEfi]::Read('Boot9001')){throw 'Existing one-time boot request or fixture entry; no mutation'}
[byte[]]$before=[LabEfi]::Read('BootOrder')
if($before.Length -lt 2 -or $before.Length -gt 508 -or $before.Length % 2){throw 'Malformed boot order'}
for($i=0;$i -lt $before.Length;$i+=2){if([BitConverter]::ToUInt16($before,$i) -eq 0x9001){throw 'Fixture entry already in boot order'}}
$sector=[uint64]$disk.LogicalSectorSize
if($sector -notin @(512,4096) -or $part.Offset % $sector -or $part.Size % $sector){throw 'Invalid USB partition geometry'}
$path=New-Object IO.MemoryStream
$w=New-Object IO.BinaryWriter($path)
$w.Write([byte]4);$w.Write([byte]1);$w.Write([uint16]42)
$w.Write([uint32]$part.PartitionNumber);$w.Write([uint64]($part.Offset/$sector));$w.Write([uint64]($part.Size/$sector))
$w.Write([uint32]$disk.Signature);$w.Write((New-Object byte[] 12));$w.Write([byte]1);$w.Write([byte]1)
$file=[Text.Encoding]::Unicode.GetBytes("\EFI\BOOT\BOOTX64.EFI`0")
$w.Write([byte]4);$w.Write([byte]4);$w.Write([uint16]($file.Length+4));$w.Write($file)
$w.Write([byte]127);$w.Write([byte]255);$w.Write([uint16]4);$w.Flush()
$option=New-Object IO.MemoryStream
$o=New-Object IO.BinaryWriter($option)
$o.Write([uint32]1);$o.Write([uint16]$path.Length)
$o.Write([Text.Encoding]::Unicode.GetBytes("USB Lab Exact Beamo Entry`0"));$o.Write($path.ToArray());$o.Flush()
[byte[]]$entry=$option.ToArray();[byte[]]$after=$before+[byte]1+[byte]144
@{fixtureOnly=$true;computer=$computer.Model;source=$manifest;usbSerial=$disk.SerialNumber;partitionNumber=$part.PartitionNumber;bootOrderBefore=[Convert]::ToBase64String($before);entry=[Convert]::ToBase64String($entry)} | ConvertTo-Json -Depth 8 | Set-Content "$out\fixture-before.json"
[LabEfi]::Write('Boot9001',$entry)
if([Convert]::ToBase64String([LabEfi]::Read('Boot9001')) -ne [Convert]::ToBase64String($entry)){throw 'Entry readback mismatch'}
[LabEfi]::Write('BootOrder',$after)
if([Convert]::ToBase64String([LabEfi]::Read('BootOrder')) -ne [Convert]::ToBase64String($after)){throw 'Boot order readback mismatch'}
@{fixtureEntry='Boot9001';bootOrderAfter=[Convert]::ToBase64String([LabEfi]::Read('BootOrder'));bootNextAbsent=($null -eq [LabEfi]::Read('BootNext'));secureBoot=(Confirm-SecureBootUEFI)} | ConvertTo-Json | Set-Content "$out\fixture-installed.json"
& ($root+'Start Beamo Wipe.exe') --check-json | Set-Content "$out\launcher-ready.json"
Write-Output 'EXACT_ENTRY_FIXTURE_INSTALLED'
