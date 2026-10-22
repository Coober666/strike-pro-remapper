param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][string]$ResultPath
)
# Runs without Python, Node, Git or package installation. Use a clean Windows VM
# for clean-OS acceptance; running this on a developer PC does not establish that.
$ErrorActionPreference = 'Stop'
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
$resultFile = [IO.Path]::GetFullPath($ResultPath)
$runRoot = Join-Path ([IO.Path]::GetTempPath()) ('strike-clean-check-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $runRoot | Out-Null
$digest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$sidecar = [IO.Path]::ChangeExtension($archivePath, '.sha256.txt')
if ((Get-Content -LiteralPath $sidecar -Raw).Split()[0].ToLowerInvariant() -ne $digest) { throw 'ZIP checksum mismatch' }
Expand-Archive -LiteralPath $archivePath -DestinationPath $runRoot
$app = Join-Path $runRoot 'Strike Remapper'
$manifest = Get-Content -LiteralPath (Join-Path $app 'PACKAGE-MANIFEST.json') -Raw | ConvertFrom-Json
function Test-Payload {
    $files = @(Get-ChildItem -LiteralPath $app -Recurse -File | Where-Object { $_.Name -ne 'PACKAGE-MANIFEST.json' })
    if ($files.Count -ne @($manifest.files.PSObject.Properties).Count) { throw 'Unexpected payload file count' }
    foreach ($entry in $manifest.files.PSObject.Properties) {
        $target = [IO.Path]::GetFullPath((Join-Path $app $entry.Name))
        if (-not $target.StartsWith($app + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe manifest path' }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw ('Payload mismatch: ' + $entry.Name) }
    }
}
Test-Payload
$savedEnvironment = @{}
Get-ChildItem Env: | Where-Object { $_.Name -match '^(PATH$|PYTHON|TCL|TK|VIRTUAL_ENV)' } | ForEach-Object { $savedEnvironment[$_.Name] = $_.Value }
$results = @{archive_sha256=$digest; payload_files=@($manifest.files.PSObject.Properties).Count; working_directory=$runRoot; clean_os_acceptance='Requires execution on an independently clean Windows environment'}
try {
    foreach ($key in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key,$null,'Process') }
    $env:PATH = Join-Path $env:SystemRoot 'System32'
    $helper = Join-Path $app '_internal/StrikeHelper.exe'
    foreach ($mode in 'probe','smoke') {
        $stdout = Join-Path $runRoot ($mode + '.json')
        $stderr = Join-Path $runRoot ($mode + '.stderr.txt')
        $arguments = $mode
        if ($mode -eq 'smoke') { $arguments += ' "' + (Join-Path $runRoot 'Disposable library') + '"' }
        $process = Start-Process -FilePath $helper -ArgumentList $arguments -WorkingDirectory $runRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if (-not $process.WaitForExit(120000)) { $process.Kill(); throw ($mode + ' timed out') }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw (Get-Content -LiteralPath $stderr -Raw) }
        $results[$mode] = Get-Content -LiteralPath $stdout -Raw | ConvertFrom-Json
    }
    $guiRoot = Join-Path $runRoot 'Launcher check'
    $process = Start-Process -FilePath (Join-Path $app 'Strike Remapper.exe') -ArgumentList ('--check-launcher "' + $guiRoot + '"') -WorkingDirectory $runRoot -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'Launcher check timed out' }
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw 'Launcher check failed; inspect its error.txt' }
    $results.gui = Get-Content -LiteralPath (Join-Path $guiRoot 'result.json') -Raw | ConvertFrom-Json
    Test-Payload
    $results | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $resultFile -Encoding UTF8
    Write-Output ('Passed. Evidence: ' + $resultFile + '. Temporary test files retained at ' + $runRoot)
} finally {
    foreach ($key in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key,$savedEnvironment[$key],'Process') }
}
