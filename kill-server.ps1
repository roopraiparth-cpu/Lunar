$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' -and ($_.Name -like 'py.exe' -or $_.Name -like 'python.exe') }
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force
    Write-Output ("killed " + $p.ProcessId)
}
if (-not $procs) { Write-Output "no server process found" }
