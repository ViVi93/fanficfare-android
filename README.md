# FanFicFare for Android

Personal-use Android app for downloading fanfiction to ebook formats.

## Features ported
- Upstream `fanficfare` adapter library bundled for 100+ sites
- EPUB/HTML/TXT download path via Kotlin UI
- Update metadata flow stub
- Offline-first download list UI
- GitHub Actions debug APK build

## Not yet ported / blocked
- Chaquopy Python runtime is currently disabled in local builds
- On-device Python execution is pending a working Chaquopy/x86_64 build environment
- Full conversion/update pipeline is UI-ready but returns bridge-unavailable until Chaquopy is enabled

## Build
- Local ARM64 build is blocked by AAPT2 architecture mismatch in this VM
- Use GitHub Actions to build debug APK:
  - Push to `master`
  - Download artifact from Actions tab

## Repo
https://github.com/ViVi93/fanficfare-android
