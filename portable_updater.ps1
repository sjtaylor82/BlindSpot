param(
    [int]$BlindSpotProcessId,
    [string]$ZipPath,
    [string]$AppDirectory,
    [string]$ExecutablePath,
    [string]$ReadyPath
)

$ErrorActionPreference = "Stop"
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("BlindSpot-update-" + [guid]::NewGuid())
$payload = Join-Path $staging "payload"
$backup = Join-Path $staging "backup"
$logDirectory = Join-Path $AppDirectory "data"
$log = Join-Path $logDirectory "update.log"
$appWasClosed = $false
$success = $false

New-Item -ItemType Directory -Path $payload -Force | Out-Null
New-Item -ItemType Directory -Path $backup -Force | Out-Null
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$host.UI.RawUI.WindowTitle = "BlindSpot Portable Update"

function Write-UpdateLog([string]$Message) {
    Add-Content -LiteralPath $log -Value ("[" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "] " + $Message) -Encoding UTF8
}

try {
    Write-UpdateLog "Portable update started."
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $payload -Force
    $newApp = Get-ChildItem -LiteralPath $payload -Recurse -Filter "BlindSpot.exe" -File |
        Select-Object -First 1
    if ($null -eq $newApp) {
        throw "The update does not contain BlindSpot.exe."
    }
    $newRoot = $newApp.Directory.FullName
    Set-Content -LiteralPath $ReadyPath -Value "ready" -Encoding ASCII
    Wait-Process -Id $BlindSpotProcessId -ErrorAction SilentlyContinue
    $appWasClosed = $true

    Get-ChildItem -LiteralPath $AppDirectory -Force |
        Where-Object { $_.Name -ne "data" } |
        ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination $backup -Force }
    Get-ChildItem -LiteralPath $newRoot -Force |
        Where-Object { $_.Name -ne "data" } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $AppDirectory -Recurse -Force }

    $success = $true
    Write-UpdateLog "Portable update completed."
} catch {
    Write-UpdateLog ("Portable update failed: " + $_.Exception.Message)
    if ($appWasClosed) {
        Get-ChildItem -LiteralPath $AppDirectory -Force |
            Where-Object { $_.Name -ne "data" } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -LiteralPath $backup -Force |
            ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination $AppDirectory -Force }
    }
    if (-not (Test-Path -LiteralPath $ReadyPath)) {
        Set-Content -LiteralPath $ReadyPath -Value "error" -Encoding ASCII
    }
} finally {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    if ($success) {
        Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
    }
    if ($appWasClosed -and (Test-Path -LiteralPath $ExecutablePath)) {
        Start-Process -FilePath $ExecutablePath
    }
}
