param(
    [string]$MacHost = 'mac-mini',
    [string]$Revision = 'HEAD',
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$taskArguments = @((Join-Path $PSScriptRoot 'build_on_mac.py'), '--host', $MacHost, '--revision', $Revision)
if ($OutputDirectory) { $taskArguments += @('--output', $OutputDirectory) }
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @taskArguments
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @taskArguments
} else {
    throw 'Python 3.10+ is required on Windows. Install Python or run build_on_mac.py with your interpreter.'
}
exit $LASTEXITCODE
