# Creates a Desktop shortcut to Lunar, resolved from this script's own folder so
# it works wherever the project lives.
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop 'Lunar.lnk'
$icon = Join-Path $project '.venv\Scripts\python.exe'

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($link)
$s.TargetPath = Join-Path $project 'start-lunar.bat'
$s.WorkingDirectory = $project
$s.Description = 'Start the Lunar voice assistant'
$s.IconLocation = "$icon,0"
$s.Save()
Write-Output "shortcut created: $link"