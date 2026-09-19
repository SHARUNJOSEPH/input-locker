# 📦 Windows Package Manager (winget) Submission & Maintenance Guide

This document outlines the official process for publishing, testing, and updating **Input Locker** in the official [Microsoft Community Package Repository (`microsoft/winget-pkgs`)](https://github.com/microsoft/winget-pkgs).

---

## 1. Package Overview

- **Package Identifier**: `SharunJoseph.InputLocker`
- **Package Version**: `0.1.0`
- **Installer Type**: `inno` (Inno Setup 6)
- **Architecture**: `x64`
- **Download URL**: `https://github.com/SHARUNJOSEPH/input-locker/releases/download/v0.1.0/InputLocker-Setup-v0.1.0.exe`
- **Installer SHA256**: `0B05A9C822CA6A5C2D04C6672CFF42E0BBBA74E891CEA495D22D37A948958563`
- **Silent Install Flags**: `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`

---

## 2. Local Manifest Verification

Before submitting to Microsoft, you can test-install Input Locker locally using the generated manifests:

```powershell
# Navigate to the repo root
cd C:\Users\user\teamwork_projects\input_locker

# Validate manifest schema and test installation locally
winget validate packaging\winget\manifests\s\SharunJoseph\InputLocker\0.1.0\
winget install --manifest packaging\winget\manifests\s\SharunJoseph\InputLocker\0.1.0\
```

---

## 3. Submission Workflow to `microsoft/winget-pkgs`

### Option A: Using `wingetcreate` (Automated CLI)

Microsoft provides the official `wingetcreate` utility to submit pull requests directly to `microsoft/winget-pkgs`:

1. Install `wingetcreate`:
   ```powershell
   winget install Microsoft.WingetCreate
   ```

2. Submit the release:
   ```powershell
   wingetcreate submit packaging\winget\manifests\s\SharunJoseph\InputLocker\0.1.0\
   ```
   *(You will be prompted to authenticate with your GitHub account `SHARUNJOSEPH`. The tool will automatically fork `microsoft/winget-pkgs`, create a branch, and open a Pull Request).*

---

### Option B: Manual GitHub Pull Request

1. Fork the [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) repository on GitHub.
2. Clone your fork locally or use the GitHub Web UI.
3. Copy the manifest folder:
   ```powershell
   # In winget-pkgs fork:
   mkdir -p manifests/s/SharunJoseph/InputLocker/0.1.0/
   cp packaging/winget/manifests/s/SharunJoseph/InputLocker/0.1.0/* manifests/s/SharunJoseph/InputLocker/0.1.0/
   ```
4. Commit and push:
   ```bash
   git checkout -b add-input-locker-0.1.0
   git add manifests/s/SharunJoseph/InputLocker/0.1.0/
   git commit -m "New package: SharunJoseph.InputLocker version 0.1.0"
   git push origin add-input-locker-0.1.0
   ```
5. Open a Pull Request against `microsoft:master`.
6. Microsoft's automated Azure Pipelines bot will run validation tests (static schema verification, sandbox install, virus scan, and uninstall verification).
7. Once merged, users worldwide can install Input Locker via:
   ```powershell
   winget install SharunJoseph.InputLocker
   ```

---

## 4. How to Update for Future Releases

When release `v0.2.0` is published:
```powershell
wingetcreate update SharunJoseph.InputLocker --urls "https://github.com/SHARUNJOSEPH/input-locker/releases/download/v0.2.0/InputLocker-Setup-v0.2.0.exe" --version 0.2.0
```
This automatically downloads the new binary, calculates the new SHA256, and submits the update PR to `winget-pkgs`.
