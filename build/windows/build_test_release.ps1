# Build and validate the isolated Pharmacy Management System TEST release.
#
#   .\build\windows\build_test_release.ps1
#   .\build\windows\build_test_release.ps1 -SkipBuild   # validate an existing temp build
#
# Safety model:
#   * The build is written to a FRESH temporary directory. The existing
#     dist\PharmacyManagementSystem_Test is never deleted before a successful
#     build; it is renamed aside (preserved) only during publication.
#   * The output folder is checked for running processes / locked files before
#     the build and again before publication. A lock fails early with the
#     exact process and locked file names.
#   * data\pharmacy.db and staging\pharmacy_staging.db are only ever read.
#   * Every step must pass; publication happens last.

[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [string]$TempRoot
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtualenv Python not found: $Python"
}

$StagingDb = Join-Path $Root "staging\pharmacy_staging.db"
$ActiveDb  = Join-Path $Root "data\pharmacy.db"
$Dist      = Join-Path $Root "dist\PharmacyManagementSystem_Test"
$Spec      = Join-Path $Root "build\windows\pharmacy_management_test.spec"

$Validation = Join-Path $Root "test_release_validation"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ProfileRoot = Join-Path $Validation "profile_$Stamp"
$ProfileLocal = Join-Path $ProfileRoot "LocalAppData"
$SummaryPath = Join-Path $Validation "validation_summary_$Stamp.json"

if (-not $TempRoot) {
    $TempRoot = Join-Path $Root "build\test_release_staging\$Stamp"
}
$TempDist = Join-Path $TempRoot "dist"
$TempWork = Join-Path $TempRoot "work"
$TempRelease = Join-Path $TempDist "PharmacyManagementSystem_Test"
$TempExe = Join-Path $TempRelease "PharmacyManagementSystem_Test.exe"

New-Item -ItemType Directory -Force -Path $ProfileLocal | Out-Null
New-Item -ItemType Directory -Force -Path $TempDist | Out-Null

function Get-Sha256([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower()
    }
    return $null
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw "VALIDATION FAILED: $Message"
    }
    Write-Host "  [PASS] $Message" -ForegroundColor Green
}

function Get-TestAppProcesses {
    @(Get-Process -Name "PharmacyManagementSystem_Test" -ErrorAction SilentlyContinue)
}

function Get-LockedFiles([string]$Folder) {
    $locked = New-Object System.Collections.Generic.List[string]
    if (-not (Test-Path -LiteralPath $Folder)) { return $locked }
    $files = Get-ChildItem -LiteralPath $Folder -Recurse -File -ErrorAction SilentlyContinue
    foreach ($file in $files) {
        try {
            $stream = [System.IO.File]::Open(
                $file.FullName,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::None
            )
            $stream.Close()
            $stream.Dispose()
        } catch {
            $locked.Add($file.FullName)
        }
    }
    return $locked
}

function Assert-OutputFree([string]$Folder, [string]$When) {
    $processes = Get-TestAppProcesses
    $locked = @(Get-LockedFiles $Folder)
    if ($processes.Count -eq 0 -and $locked.Count -eq 0) {
        Write-Host "  [PASS] ${When}: $Folder is not in use" -ForegroundColor Green
        return
    }

    Write-Host ""
    Write-Host "[BLOCKED] The test release output is still in use ($When): $Folder" -ForegroundColor Red
    foreach ($process in $processes) {
        Write-Host ("  process     : PID {0}  {1}  window='{2}'" -f `
            $process.Id, $process.ProcessName, $process.MainWindowTitle) -ForegroundColor Yellow
    }
    if ($locked.Count -gt 0) {
        Write-Host ("  locked files: {0}" -f $locked.Count) -ForegroundColor Yellow
        foreach ($path in ($locked | Select-Object -First 20)) {
            Write-Host "    $path" -ForegroundColor Yellow
        }
        if ($locked.Count -gt 20) {
            Write-Host ("    ... and {0} more" -f ($locked.Count - 20)) -ForegroundColor Yellow
        }
    }
    if ($processes.Count -eq 0) {
        Write-Host "  No test application process was found; the lock is held by another" -ForegroundColor Yellow
        Write-Host "  process (antivirus, Explorer preview, indexing). Close/allow-list it." -ForegroundColor Yellow
    } else {
        Write-Host "  Close the PharmacyManagementSystem_Test window normally, then rerun." -ForegroundColor Yellow
        Write-Host "  If no window is visible, stop ONLY that PID (never python.exe)." -ForegroundColor Yellow
    }
    throw "Test release output is in use."
}

function Publish-Release([string]$Source, [string]$Destination, [string]$StampSuffix) {
    $previous = $null

    Assert-OutputFree $Destination "before publish"

    $parent = Split-Path $Destination -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    if (Test-Path -LiteralPath $Destination) {
        $previous = "$Destination.previous-$StampSuffix"
        $suffix = 2
        while (Test-Path -LiteralPath $previous) {
            $previous = "$Destination.previous-$StampSuffix-$suffix"
            $suffix++
        }
        Rename-Item -LiteralPath $Destination -NewName (Split-Path $previous -Leaf) -ErrorAction Stop
        Write-Host "  Previous test release preserved: $previous" -ForegroundColor Cyan
    }

    try {
        Move-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop
    } catch {
        if ($previous -and (Test-Path -LiteralPath $previous) -and -not (Test-Path -LiteralPath $Destination)) {
            Rename-Item -LiteralPath $previous -NewName (Split-Path $Destination -Leaf) -ErrorAction Stop
            Write-Host "  Publish failed; the previous test release was restored." -ForegroundColor Yellow
        }
        throw
    }
    return $previous
}

function Invoke-PythonTests([string]$Label, [string[]]$Arguments) {
    Write-Host "  Running $Label..." -ForegroundColor Cyan
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python @Arguments | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    Write-Host ("  {0} exit code: {1}" -f $Label, $code) -ForegroundColor $(if ($code -eq 0) { "Green" } else { "Red" })
    return [int]$code
}

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  PHARMACY MANAGEMENT SYSTEM -- ISOLATED TEST RELEASE BUILD" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " Project       : $Root"
Write-Host " Staging       : $StagingDb"
Write-Host " Live DB       : $ActiveDb (must remain unchanged)"
Write-Host " Temp build    : $TempRoot"
Write-Host " Publish to    : $Dist"
Write-Host " Profile       : $ProfileRoot"
Write-Host "------------------------------------------------------------------------------"

$stagingBefore = Get-Sha256 $StagingDb
$activeBefore = Get-Sha256 $ActiveDb
Write-Host " Staging SHA-256 before : $stagingBefore"
Write-Host " Live DB SHA-256 before : $activeBefore"
Write-Host ""

# Preflight: fail early if the current release is in use ----------------------
Write-Host "[PREFLIGHT] Checking that the current test release is not in use..." -ForegroundColor Cyan
Assert-OutputFree $Dist "before build"
Write-Host ""

# 1. Pre-build source verification -------------------------------------------
Write-Host "[1/7] Verifying the staging snapshot (read-only)..." -ForegroundColor Cyan
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python (Join-Path $Root "tools\verify_test_release_source.py")
$verifyExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($verifyExit -ne 0) {
    throw "Source verification failed (exit $verifyExit). Refusing to build."
}
Write-Host ""

# 2. Build into the fresh temporary directory --------------------------------
if (-not $SkipBuild) {
    Write-Host "[2/7] Building with PyInstaller into the temporary directory..." -ForegroundColor Cyan
    Write-Host "      distpath : $TempDist"
    Write-Host "      workpath : $TempWork"
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python -m PyInstaller $Spec --noconfirm --distpath $TempDist --workpath $TempWork
    $pyExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    if ($pyExit -ne 0) {
        throw "PyInstaller failed (exit $pyExit). The previous release was not touched."
    }
} else {
    Write-Host "[2/7] Skipping build (-SkipBuild)." -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath $TempExe)) {
    throw "Temporary executable not found: $TempExe"
}
$tempExeHash = Get-Sha256 $TempExe
Write-Host ""

# 3. Package inspection ------------------------------------------------------
Write-Host "[3/7] Inspecting the packaged files..." -ForegroundColor Cyan
$files = Get-ChildItem -LiteralPath $TempRelease -Recurse -File
$seedInPackage = Join-Path $TempRelease "_internal\seed\pharmacy_staging.db"
$allDbs = $files | Where-Object { $_.Extension -eq ".db" }
$unexpectedDbs = $allDbs | Where-Object {
    $_.FullName -ne (Resolve-Path -LiteralPath $seedInPackage).Path
}
$qwindows = $files | Where-Object { $_.Name -eq "qwindows.dll" }
$qoffscreen = $files | Where-Object { $_.Name -eq "qoffscreen.dll" }
$pkgSizeMb = [math]::Round((($files | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)

Write-Host ("  Files: {0}, size: {1} MB" -f $files.Count, $pkgSizeMb)
Assert-True (Test-Path -LiteralPath $seedInPackage) "bundled seed exists at _internal\seed\pharmacy_staging.db"
Assert-True ($unexpectedDbs.Count -eq 0) "no database other than the intended seed is bundled"
Assert-True ($qwindows.Count -ge 1) "Qt Windows platform plugin (qwindows.dll) is packaged"
Assert-True ($qoffscreen.Count -ge 1) "Qt offscreen platform plugin (qoffscreen.dll) is packaged"
$seedHash = Get-Sha256 $seedInPackage
Assert-True ($seedHash -eq $stagingBefore) "packaged seed is byte-identical to the verified staging snapshot"
Write-Host ""

# 4. Clean-profile first launch (seeding) ------------------------------------
Write-Host "[4/7] Running the packaged EXE self-check in a clean profile (first launch)..." -ForegroundColor Cyan
$savedLocalAppData = $env:LOCALAPPDATA
$normalProfileFolder = Join-Path $ProfileLocal "PharmacyManagementSystem"
$testProfileFolder = Join-Path $ProfileLocal "PharmacyManagementSystem-Test"
$selfCheckJson = Join-Path $testProfileFolder "test_release_self_check.json"
$runtimeDb = Join-Path $testProfileFolder "pharmacy.db"

try {
    $env:LOCALAPPDATA = $ProfileLocal

    $firstProcess = Start-Process -FilePath $TempExe -ArgumentList "--self-check" -Wait -PassThru
    if (-not (Test-Path -LiteralPath $selfCheckJson)) {
        throw "Self-check report was not written: $selfCheckJson"
    }
    $first = Get-Content -LiteralPath $selfCheckJson -Raw | ConvertFrom-Json
    $dbHashFirst = Get-Sha256 $runtimeDb
    $dbSizeFirst = (Get-Item -LiteralPath $runtimeDb).Length
    $firstMarkerRows = [int]$first.marker_rows_persisted

    Write-Host ("  first exit code      : {0}" -f $firstProcess.ExitCode)
    Write-Host ("  database initialised : {0}" -f $first.checks.database_initialisation)
    Write-Host ("  database             : {0}" -f $first.database_path)
    Write-Host ("  sales / items        : {0} / {1}" -f $first.database_info.counts.sales_invoices, $first.database_info.counts.items)
    Write-Host ("  pages built (offscreen): {0}" -f $first.packaged_environment.pages_built)

    Assert-True ($firstProcess.ExitCode -eq 0) "first self-check exited 0"
    Assert-True ($first.ok -eq $true) "first self-check reported ok"
    Assert-True ($first.checks.database_initialisation -eq "seeded") "first launch seeded the test database"
    Assert-True ($first.database_info.counts.sales_invoices -eq 72175) "seeded sales count is 72,175"
    Assert-True ($first.database_info.counts.items -eq 940) "seeded item count is 940"
    Assert-True ($first.checks.isolated_from_production -eq $true) "runtime DB is not data\pharmacy.db"
    Assert-True ($first.checks.isolated_from_normal_app_data -eq $true) "runtime DB is not the normal per-user DB"
    Assert-True ($first.checks.seed_unchanged -eq $true) "bundled seed remained byte-identical"
    Assert-True ($first.checks.marker_write_changed_test_db -eq $true) "a write changed only the isolated test DB"
    Assert-True ($first.packaged_environment.pages_built -gt 30) "all application screens load in the packaged EXE"
    Assert-True (-not (Test-Path -LiteralPath $normalProfileFolder)) "no normal %LOCALAPPDATA%\PharmacyManagementSystem folder was created"

    # 5. Second launch (persistence) -----------------------------------------
    Write-Host ""
    Write-Host "[5/7] Running the packaged EXE self-check again (second launch)..." -ForegroundColor Cyan
    $secondProcess = Start-Process -FilePath $TempExe -ArgumentList "--self-check" -Wait -PassThru
    $second = Get-Content -LiteralPath $selfCheckJson -Raw | ConvertFrom-Json
    $dbHashSecond = Get-Sha256 $runtimeDb
    $dbSizeSecond = (Get-Item -LiteralPath $runtimeDb).Length
    $secondMarkerRows = [int]$second.marker_rows_persisted

    Write-Host ("  second exit code     : {0}" -f $secondProcess.ExitCode)
    Write-Host ("  database initialised : {0}" -f $second.checks.database_initialisation)
    Write-Host ("  marker rows          : first={0}, second={1}" -f $firstMarkerRows, $secondMarkerRows)

    Assert-True ($secondProcess.ExitCode -eq 0) "second self-check exited 0"
    Assert-True ($second.ok -eq $true) "second self-check reported ok"
    Assert-True ($second.checks.database_initialisation -eq "preserved") "second launch preserved the existing test DB"
    Assert-True ($secondMarkerRows -gt $firstMarkerRows) "the disposable marker transaction persisted across launches"
    Assert-True ($dbHashSecond -ne $dbHashFirst) "the second launch wrote only to the isolated test DB"
    Assert-True ($dbSizeSecond -gt 0) "the test DB still exists and is non-empty"
}
finally {
    $env:LOCALAPPDATA = $savedLocalAppData
}
Write-Host ""

# 6. Isolation / preservation checks -----------------------------------------
Write-Host "[6/7] Confirming source databases were preserved..." -ForegroundColor Cyan
$stagingAfter = Get-Sha256 $StagingDb
$activeAfter = Get-Sha256 $ActiveDb
Write-Host "  Staging SHA-256 after  : $stagingAfter"
Write-Host "  Live DB SHA-256 after  : $activeAfter"
Assert-True ($stagingAfter -eq $stagingBefore) "staging source database is byte-identical"
Assert-True ($activeAfter -eq $activeBefore) "active data\pharmacy.db is byte-identical"
Write-Host ""

# 7. Focused + configured regression tests -----------------------------------
Write-Host "[7/7] Running focused and configured regression tests..." -ForegroundColor Cyan
$uppercaseExit = Invoke-PythonTests "uppercase-input focused tests" @("test_uppercase_input.py")
$backupExit = Invoke-PythonTests "backup/restore focused tests" @("test_backup_restore.py")
$targetedExit = Invoke-PythonTests "configured targeted suite" @((Join-Path $Root "tools\run_targeted_tests.py"))
Write-Host ""

# Final source-database hash check after the test runs -----------------------
$stagingFinal = Get-Sha256 $StagingDb
$activeFinal = Get-Sha256 $ActiveDb
Assert-True ($stagingFinal -eq $stagingBefore) "staging database is still byte-identical after tests"
Assert-True ($activeFinal -eq $activeBefore) "active database is still byte-identical after tests"
Assert-True ($uppercaseExit -eq 0) "focused uppercase-input tests passed"
Assert-True ($backupExit -eq 0) "focused backup/restore tests passed"
Assert-True ($targetedExit -eq 0) "configured targeted suite passed"
Write-Host ""

# Publication — only after every check above succeeded ------------------------
Write-Host "[PUBLISH] Publishing the validated release..." -ForegroundColor Cyan
$previousRelease = Publish-Release $TempRelease $Dist $Stamp
$publishedExe = Join-Path $Dist "PharmacyManagementSystem_Test.exe"
Assert-True (Test-Path -LiteralPath $publishedExe) "published EXE exists at dist\PharmacyManagementSystem_Test"
Assert-True ((Get-Sha256 $publishedExe) -eq $tempExeHash) "published EXE is byte-identical to the validated build"
Write-Host "  Published EXE: $publishedExe" -ForegroundColor Cyan
Write-Host ""

# Summary --------------------------------------------------------------------
$summary = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    project_root = $Root
    validated_executable_before_publish = $TempExe
    published_executable = $publishedExe
    previous_release_preserved = $previousRelease
    temp_build_root = $TempRoot
    build_command = ".venv\Scripts\python.exe -m PyInstaller build\windows\pharmacy_management_test.spec --noconfirm --distpath <temp>\dist --workpath <temp>\work"
    packaging_mode = "PyInstaller --onedir (built in a fresh temp directory)"
    package_file_count = $files.Count
    package_size_mb = $pkgSizeMb
    staging_sha256_before = $stagingBefore
    staging_sha256_after = $stagingFinal
    staging_unchanged = ($stagingFinal -eq $stagingBefore)
    active_db_sha256_before = $activeBefore
    active_db_sha256_after = $activeFinal
    active_db_unchanged = ($activeFinal -eq $activeBefore)
    seed_in_package = $seedInPackage
    seed_sha256 = $seedHash
    seed_matches_staging = ($seedHash -eq $stagingBefore)
    runtime_db_path = $runtimeDb
    clean_profile = $ProfileRoot
    first_launch = $first
    second_launch = $second
    focused_uppercase_exit_code = $uppercaseExit
    focused_backup_restore_exit_code = $backupExit
    targeted_tests_exit_code = $targetedExit
    ok = ($first.ok -and $second.ok `
        -and ($stagingFinal -eq $stagingBefore) `
        -and ($activeFinal -eq $activeBefore) `
        -and ($uppercaseExit -eq 0) -and ($backupExit -eq 0) `
        -and ($targetedExit -eq 0) -and ($seedHash -eq $stagingBefore) `
        -and (Test-Path -LiteralPath $publishedExe))
}

New-Item -ItemType Directory -Force -Path $Validation | Out-Null
$summary | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 -LiteralPath $SummaryPath

Write-Host "==============================================================================" -ForegroundColor Cyan
if ($summary.ok) {
    Write-Host "  [PASS] TEST RELEASE BUILT AND VALIDATED" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] TEST RELEASE VALIDATION FOUND PROBLEMS" -ForegroundColor Red
}
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " EXE           : $publishedExe"
Write-Host " Validation    : $SummaryPath"
Write-Host " Test profile  : $ProfileRoot"
if ($previousRelease) {
    Write-Host " Previous rel. : $previousRelease (preserved)"
}
Write-Host " Temp build    : $TempRoot"
Write-Host "=============================================================================="

if (-not $summary.ok) { exit 1 }
