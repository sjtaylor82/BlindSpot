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
    Write-Host "Preparing the BlindSpot portable update."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $payloadRoot = [System.IO.Path]::GetFullPath(
        $payload + [System.IO.Path]::DirectorySeparatorChar)
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    $extractedFiles = 0
    try {
        foreach ($entry in $archive.Entries) {
            $relativePath = $entry.FullName.Replace(
                "/", [System.IO.Path]::DirectorySeparatorChar)
            $destination = [System.IO.Path]::GetFullPath(
                (Join-Path $payload $relativePath))
            if (-not $destination.StartsWith(
                    $payloadRoot,
                    [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "The update archive contains an unsafe path."
            }
            if ([string]::IsNullOrEmpty($entry.Name)) {
                New-Item -ItemType Directory -Path $destination -Force |
                    Out-Null
                continue
            }
            $destinationParent = Split-Path -Parent $destination
            New-Item -ItemType Directory -Path $destinationParent -Force |
                Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile(
                $entry, $destination, $true)
            $extractedFiles++
        }
    } finally {
        $archive.Dispose()
    }
    Write-UpdateLog ("Archive prepared: " + $extractedFiles + " files extracted.")
    $newApp = Get-ChildItem -LiteralPath $payload -Recurse -Filter "BlindSpot.exe" -File |
        Select-Object -First 1
    if ($null -eq $newApp) {
        throw "The update does not contain BlindSpot.exe."
    }
    $newRoot = $newApp.Directory.FullName
    Set-Content -LiteralPath $ReadyPath -Value "ready" -Encoding ASCII
    Write-UpdateLog "Preparation complete; waiting for BlindSpot to close."
    Write-Host "Preparation complete. Closing BlindSpot."
    Wait-Process -Id $BlindSpotProcessId -ErrorAction SilentlyContinue
    $appWasClosed = $true
    Write-UpdateLog "BlindSpot closed; installing prepared files."
    Write-Host "Installing the update. Please keep this window open."

    Get-ChildItem -LiteralPath $AppDirectory -Force |
        Where-Object { $_.Name -ne "data" } |
        ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination $backup -Force }
    Get-ChildItem -LiteralPath $newRoot -Force |
        Where-Object { $_.Name -ne "data" } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $AppDirectory -Recurse -Force }

    $success = $true
    Write-UpdateLog "Portable update completed."
    Write-Host "Update complete. Restarting BlindSpot."
} catch {
    Write-UpdateLog ("Portable update failed: " + $_.Exception.Message)
    Write-Host ("The portable update failed: " + $_.Exception.Message)
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
