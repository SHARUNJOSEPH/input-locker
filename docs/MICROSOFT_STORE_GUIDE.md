# Microsoft Store Publishing & False Positive Resolution Guide

This document explains why Windows Defender / SmartScreen may flag unsigned AV utilities, how publishing to the **Microsoft Store** solves it permanently, and how to track downloads and usage with **zero user data collection**.

---

## 1. Why Did Windows Flag the Software?

### The Technical Cause
1. **Low-Level OS Hooks (`WH_KEYBOARD_LL` and `WH_MOUSE_LL`)**:
   Input Locker legitimately uses Windows low-level input hooks to swallow global keystrokes and mouse clicks during AV staging. However, malicious keyloggers also use these exact same Win32 APIs.
2. **Unsigned PyInstaller Executables**:
   Compiling Python with PyInstaller creates a generic bootloader. Without a commercial Code Signing Certificate (EV Certificate), Windows assigns the executable **zero reputation**.
3. **Heuristic False Positives**:
   When Windows Defender encounters a newly generated, unsigned executable that registers global keyboard hooks, its heuristic analysis flags it defensively as "Trojan:Script/Wacatac" or blocks it via SmartScreen / Application Control policies (`WinError 4551`).

---

## 2. How Publishing to Microsoft Store Fixes This Permanently

When you publish **Input Locker** to the Microsoft Store:
- **Microsoft Security Review**: Microsoft's security team and automated scanners inspect the application and verify it is legitimate AV staging software.
- **Trusted Microsoft Signature**: Microsoft cryptographically signs your package with the official **Microsoft Store Root Certificate**.
- **Universal Trust**: Every Windows 10 and Windows 11 computer in the world trusts the Microsoft Store certificate. Windows Defender and SmartScreen will **never** block or flag the app.
- **One-Click Installs**: Users can install safely from the Microsoft Store app or via PowerShell (`winget install "Input Locker"`).

---

## 3. Step-by-Step Microsoft Store Submission (Win32 App)

Microsoft now allows publishing standard Win32 `.exe` desktop applications directly without needing complex code changes!

### Step 1: Register as a Microsoft Developer
1. Go to **[partner.microsoft.com/dashboard](https://partner.microsoft.com/dashboard)**.
2. Sign in with your Microsoft account.
3. Register for a Windows Developer account (One-time registration fee of ~$19 USD for an individual account).

### Step 2: Reserve the App Name
1. In the Partner Center dashboard, navigate to **Apps and games** → **New product**.
2. Select **Windows app**.
3. Enter the name: **`Input Locker`** and click **Reserve product name**.

### Step 3: Choose Win32 App Submission
1. In your application dashboard, click **Start your submission**.
2. For package type, select **Win32 Application** (or upload the MSIX package generated in `packaging/msix`).
3. Under **Package URL / Installer Download**, enter your direct release download link:
   ```text
   https://github.com/SHARUNJOSEPH/input-locker/releases/latest/download/InputLocker.exe
   ```
4. **Installer arguments**: Enter `--configure` (or leave blank).

### Step 4: Store Listing & Visual Assets
Use the high-resolution assets generated in this project:
- **Title**: `Input Locker`
- **Short Description**: `Zero-latency Windows AV staging lock that swallows keyboard and mouse inputs behind a non-activating glass overlay.`
- **App Icon**: Select `assets/store/Square150x150Logo.png` or `assets/logo.png`.
- **Screenshots / Hero**: Upload:
  - `assets/branding/github_hero_banner.jpg` (16:9 Banner)
  - `assets/branding/security_workflow_infographic.jpg` (16:9 Workflow)
  - `assets/branding/social_media_card.jpg` (1:1 Card)
- **Privacy Policy URL**:
  ```text
  https://github.com/SHARUNJOSEPH/input-locker/blob/main/PRIVACY.md
  ```
- **Support Contact**: Your email or GitHub issues URL (`https://github.com/SHARUNJOSEPH/input-locker/issues`).

### Step 5: Certification & Publishing
1. Click **Submit to the Store**.
2. Microsoft's automated certification will review the application (usually completes within 24 to 48 hours).
3. Once approved, your software is live on the Microsoft Store worldwide!

---

## 4. Privacy-First Download & Usage Metrics

You requested:
> *"i dont want this software to collect any user data but just want to know how many are downloding and using this."*

Here is how you track both metrics with **zero user data collection**:

### A. How to Track Downloads (2 Ways)

1. **Live GitHub Download Counter**:
   - A live download badge is now embedded directly at the top of your [`README.md`](../README.md):
     ```markdown
     [![Downloads](https://img.shields.io/github/downloads/SHARUNJOSEPH/input-locker/total.svg?style=flat&color=success)](https://github.com/SHARUNJOSEPH/input-locker/releases)
     ```
   - Run our local metrics script anytime to see exact download numbers for `.exe` and `.zip`:
     ```powershell
     python scripts/stats.py
     ```
   - GitHub counts downloads on their servers. **No code on the user's machine runs to track this.**

2. **Microsoft Store Analytics (Partner Center)**:
   - Under Partner Center → **Analytics** → **Acquisitions**, Microsoft provides:
     - Exact number of daily and monthly downloads.
     - Downloads grouped by country/region.
     - Windows OS versions (Windows 10 vs 11).
   - This data is aggregated by Microsoft and complies with strict GDPR/privacy laws — you never receive any personal user data.

---

### B. How to Track Active Usage (Without Collecting User Data)

1. **Microsoft Store Active Devices Dashboard**:
   - In Partner Center → **Analytics** → **Usage**:
   - Microsoft shows **Active Devices (last 30 days)**.
   - You can see how many total machines currently have Input Locker running.

2. **GitHub Repository Traffic (Insights)**:
   - When Input Locker launches, it checks for updates by querying:
     `https://api.github.com/repos/SHARUNJOSEPH/input-locker/releases/latest`
   - In your GitHub repo, click **Insights** → **Traffic**:
     - View **Unique Visitors** and **Total Views**.
     - View **Git Clones** and **Unique Cloners**.
   - Because this uses standard HTTP GET without parameters, **zero user data, device IDs, or IP addresses are stored or processed by the application**.
