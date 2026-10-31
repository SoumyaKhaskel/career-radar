param([Parameter(Mandatory=$true)][ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$Time)
$ErrorActionPreference = 'Stop'
$Project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Project '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Create the .venv and install requirements.txt first.' }
$Action = New-ScheduledTaskAction -Execute $Python -Argument '-m app.scan_cli' -WorkingDirectory $Project
$At = [datetime]::ParseExact($Time, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$Days = @('Monday','Wednesday','Friday')
$Triggers = foreach ($Day in $Days) { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At }
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'Career Radar Scan' -Action $Action -Trigger $Triggers -Settings $Settings -Description 'Runs local Career Radar scans on Monday, Wednesday and Friday.' -Force | Out-Null
Write-Host "Installed Career Radar scan at $Time Asia/Kolkata local time, Monday/Wednesday/Friday. Task Scheduler uses the Windows system time zone; set Windows to Asia/Kolkata for this time to match."
