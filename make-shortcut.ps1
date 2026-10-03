$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('C:\Users\Parth\Desktop\Lunar.lnk')
$s.TargetPath = 'C:\Users\Parth\Lunar\start-lunar.bat'
$s.WorkingDirectory = 'C:\Users\Parth\Lunar'
$s.Description = 'Start the Lunar voice assistant'
$s.IconLocation = 'C:\Users\Parth\Lunar\.venv\Scripts\python.exe,0'
$s.Save()
Write-Output 'shortcut created: C:\Users\Parth\Desktop\Lunar.lnk'
