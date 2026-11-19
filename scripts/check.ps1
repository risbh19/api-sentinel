$ErrorActionPreference = 'Stop'
$check = Join-Path $PSScriptRoot 'check.py'
python $check
exit $LASTEXITCODE
