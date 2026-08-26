# FanFicFare for Android

Personal-use Android app for downloading fanfiction to ebook formats via the upstream FanFicFare adapter library.

## Current status
- Android/Kotlin UI with Chaquopy Python 3.12 integration
- Bundled FanFicFare adapters/writers for EPUB/HTML/TXT/MOBI output
- `personal.ini` import into app-private storage
- Centralized FanFicFare configuration loading from `personal.ini`
- Site-specific credential detection without exposing credential values
- Metadata, download, update, and force-download paths
- In-app diagnostics covering configuration and download debug logging
- GitHub Actions debug APK build

## Verified functionality
- `personal.ini` import and removal from Settings
- Configuration loaded for credential-dependent downloads
- StoriesOnline and Literotica downloads verified on device
- Force-download behavior preserved
- Configuration persists across force-stop/reopen
- Diagnostics show runtime configuration state: config directory, `personal.ini` path, existence, size, credentials detected, configuration validity, and FanFicFare version when available

## Build
- Local debug build: `./gradlew clean :app:assembleDebug`
- Debug APK: `app/build/outputs/apk/debug/app-debug.apk`
- Minimum SDK: 24
- Target SDK: 34
- Chaquopy: 17.0.0
- Kotlin: 1.9.22
- AGP: 8.2.2

## Repository
https://github.com/ViVi93/fanficfare-android

Development branch: `next-feature-set`

## Notes
- `personal.ini` is stored in app-private files under `filesDir/fanficfare/personal.ini`
- FanFicFare receives the explicit Android config path through the Python bridge at startup
- Do not commit `personal.ini` or any credentials/secrets
- Storage, EPUB metadata parser, and existing download semantics are preserved from prior debugging
