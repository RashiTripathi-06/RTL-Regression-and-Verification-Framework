<#
.SYNOPSIS
    One-Command Verification & Regression Automation Demonstration Script
.DESCRIPTION
    Executes end-to-end audit, Questa/Icarus adapter validation, unit testing,
    benchmark regressions (Scenarios A through N), Path A vs Path B verification,
    Merkle tree caching, CLI replay, and MANTRA2 mutation analysis.
#>

$ErrorActionPreference = "Continue"
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " AUTOMATED RTL VERIFICATION AND REGRESSION AUTOMATION SYSTEM" -ForegroundColor Cyan
Write-Host " Siemens Questa Altera Starter FPGA Edition 2025.3 & Icarus Verilog" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Environment & License Verification
Write-Host "`n[1/6] Inspecting EDA Toolchain & License Environment..." -ForegroundColor Yellow
$PythonVer = python --version 2>&1
Write-Host "  Python:  $PythonVer"

$LicEnv = $env:SALT_LICENSE_SERVER
if (-not $LicEnv) {
    $env:SALT_LICENSE_SERVER = "D:\dop2\LR-213236_License.dat"
    $LicEnv = $env:SALT_LICENSE_SERVER
}
Write-Host "  License: SALT_LICENSE_SERVER = $LicEnv"
if (Test-Path $LicEnv) {
    Write-Host "  License File Exists: OK" -ForegroundColor Green
} else {
    Write-Host "  License File Missing!" -ForegroundColor Red
}

$QuestaVsim = "D:\questa_fse\win64\vsim.exe"
if (Test-Path $QuestaVsim) {
    Write-Host "  Questa Simulator: Detected at $QuestaVsim" -ForegroundColor Green
} else {
    Write-Host "  Questa Simulator: Not found at default path" -ForegroundColor Yellow
}

$Icarus = Get-Command iverilog -ErrorAction SilentlyContinue
if ($Icarus) {
    Write-Host "  Icarus Verilog:   Detected ($($Icarus.Source))" -ForegroundColor Green
}

# 2. Run Complete Unit Test Suite (80 Tests)
Write-Host "`n[2/6] Executing Complete Unit Test Suite..." -ForegroundColor Yellow
$TestFiles = Get-ChildItem -Path "tests" -Filter "*.py"
$TotalPassedTests = 0
$TotalFailedTests = 0

foreach ($TestFile in $TestFiles) {
    Write-Host "  Running $($TestFile.Name)..." -NoNewline
    $Output = python $TestFile.FullName 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " [PASS]" -ForegroundColor Green
        $TotalPassedTests++
    } else {
        Write-Host " [FAIL]" -ForegroundColor Red
        Write-Host $Output
        $TotalFailedTests++
    }
}
Write-Host "  Test Suite Summary: $TotalPassedTests passed, $TotalFailedTests failed." -ForegroundColor Cyan

# 3. Benchmark Regression Suite (Scenarios A through N)
Write-Host "`n[3/6] Executing Benchmark Regression Suite (Scenarios A through N)..." -ForegroundColor Yellow
python src/engine.py --force --workers 1

# 4. Demonstrate Cryptographic Merkle Cache Hit
Write-Host "`n[4/6] Demonstrating Merkle Tree Incremental Regression Caching..." -ForegroundColor Yellow
Write-Host "  Re-running without modifications (expected 100% CACHE HITS):"
python src/engine.py --workers 1

# 5. Demonstrate CLI Replay of Historic Run
Write-Host "`n[5/6] Demonstrating CLI History Replay..." -ForegroundColor Yellow
$HistoryFile = "reports/history.jsonl"
if (Test-Path $HistoryFile) {
    $LastLine = Get-Content $HistoryFile | Select-Object -Last 1
    if ($LastLine) {
        $LastRunObj = $LastLine | ConvertFrom-Json
        $RunId = $LastRunObj.run_id
        Write-Host "  Replaying recorded Run ID: $RunId" -ForegroundColor Cyan
        python src/engine.py --replay $RunId
    }
}

# 6. Standalone Project & Path B Reference Verification Demo
Write-Host "`n[6/6] Demonstrating Path B (Independent Golden Reference Verification)..." -ForegroundColor Yellow
python src/engine.py --project-dir examples/generic_alu --config examples/generic_alu/config.json

Write-Host "`n================================================================================" -ForegroundColor Green
Write-Host " AUTOMATION DEMONSTRATION COMPLETE!" -ForegroundColor Green
Write-Host " Reports generated:" -ForegroundColor Green
Write-Host "   - HTML Dashboard: D:\dop2\reports\regression_report.html"
Write-Host "   - CSV Summary:    D:\dop2\reports\regression_summary.csv"
Write-Host "   - JSON Summary:   D:\dop2\reports\regression_summary.json"
Write-Host "   - Run History:    D:\dop2\reports\history.jsonl"
Write-Host "================================================================================" -ForegroundColor Green
