# .github/hooks/scripts/format-and-lint.ps1
# Runs black, isort, and flake8 over Python files modified in the working tree.
# Called by the Stop hook at end of an agent session.

$ErrorActionPreference = "Continue"

$venvPython = ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "HOOK SKIP: .venv not found -- skipping format/lint."
    exit 0
}

# Collect unstaged + staged modified/added Python files
$unstaged = @(git diff --name-only --diff-filter=ACMR 2>$null | Where-Object { $_ -like "*.py" })
$staged   = @(git diff --cached --name-only --diff-filter=ACMR 2>$null | Where-Object { $_ -like "*.py" })
$files    = @($unstaged + $staged | Sort-Object -Unique | Where-Object { Test-Path $_ })

if ($files.Count -eq 0) {
    Write-Host "HOOK SKIP: no modified Python files."
    exit 0
}

Write-Host "HOOK: formatting $($files.Count) file(s) with black..."
& $venvPython -m black --quiet $files 2>&1

Write-Host "HOOK: sorting imports with isort..."
& $venvPython -m isort --quiet $files 2>&1

Write-Host "HOOK: linting with flake8..."
& $venvPython -m flake8 $files 2>&1
$flake8Exit = $LASTEXITCODE

if ($flake8Exit -ne 0) {
    Write-Host "HOOK WARN: flake8 reported issues (see above)."
}

# Always exit 0 so the hook never blocks the session from ending
exit 0
