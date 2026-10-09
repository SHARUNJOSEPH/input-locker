# Publish Input Locker v0.2.10 to GitHub (run on Windows, from the repo root).
# Prerequisites: git auth to GitHub; optional: gh CLI; optional: local Inno/PyInstaller.
#
#   powershell -ExecutionPolicy Bypass -File docs\releases\PUBLISH_v0.2.10.ps1

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))

Write-Host "Repo: $(Get-Location)" -ForegroundColor Cyan
Write-Host "Local tip:" -ForegroundColor DarkCyan
git log -1 --oneline
git show-ref --tags v0.2.10

Write-Host "`n[1/3] Pushing main + tag v0.2.10 ..." -ForegroundColor Yellow
git push origin main
git push origin v0.2.10
Write-Host "Push complete. GitHub Actions release.yml should build Setup + zip." -ForegroundColor Green
Write-Host "Watch: https://github.com/SHARUNJOSEPH/input-locker/actions" -ForegroundColor DarkCyan

# Optional local build + attach assets if Actions is not enough / fails.
$buildLocal = Read-Host "`nAlso build locally and upload assets with gh? (y/N)"
if ($buildLocal -match '^[Yy]') {
    Write-Host "`n[2/3] Building with scripts\build.ps1 ..." -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Version 0.2.10
    if (-not (Test-Path "dist\InputLocker-Setup-v0.2.10.exe")) {
        Write-Warning "Setup exe missing — Inno may not be installed. Zip/exe may still exist."
    }
    Write-Host "`n[3/3] Creating/updating GitHub release with assets ..." -ForegroundColor Yellow
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Error "gh CLI not found. Install from https://cli.github.com/ or rely on Actions."
    }
    $assets = @(
        "dist\InputLocker-Setup-v0.2.10.exe",
        "dist\InputLocker-v0.2.10-Windows-x64.zip",
        "dist\InputLocker.exe",
        "dist\InputLocker-Windows-x64.zip"
    ) | Where-Object { Test-Path $_ }

    # If Actions already created the release from the tag, upload assets onto it.
    $exists = gh release view v0.2.10 2>$null
    if ($LASTEXITCODE -eq 0) {
        gh release upload v0.2.10 @assets --clobber
        gh release edit v0.2.10 --title "Input Locker v0.2.10" --notes-file docs\releases\v0.2.10.md
    } else {
        gh release create v0.2.10 @assets `
            --title "Input Locker v0.2.10" `
            --notes-file docs\releases\v0.2.10.md
    }
    Write-Host "Release page: https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.2.10" -ForegroundColor Green
} else {
    Write-Host "`nSkipping local build. After Actions finishes, verify:" -ForegroundColor DarkYellow
    Write-Host "  https://github.com/SHARUNJOSEPH/input-locker/releases/tag/v0.2.10"
}

Write-Host "`nDone." -ForegroundColor Green
