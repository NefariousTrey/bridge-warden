# Bridge Warden setup for Windows PowerShell. Same as: python scripts\bw_setup.py
# Run from the repo folder:   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Extra options pass through, for example:   scripts\setup.ps1 --ag-studio
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { & py -3 "$here\bw_setup.py" @args }
else { & python "$here\bw_setup.py" @args }
exit $LASTEXITCODE
