# FanFicFare for Android

Personal-use Android app for downloading fanfiction to ebook formats using the upstream FanFicFare adapter library, packaged with Chaquopy + Python 3.12.

## Features

- Download stories as EPUB, HTML, TXT, or MOBI
- Background metadata fetch with progress/status tracking
- Add stories by URL with page-list harvest and normalization
- Multi-select update selected stories from library
- Sort library by title, author, date added
- Sort and selection state preserved across restarts
- Background share receiver for direct story URLs
- In-app settings for `personal.ini` import/removal
- In-app diagnostics for config and download debugging
- Material 3 dynamic theming
- Force-download override
- Cancel in-progress downloads

## Verified

- StoriesOnline and Literotica downloads verified on device
- `personal.ini` import and config loading for credential-dependent sites
- Force-download behavior preserved
- Configuration persists across force-stop/reopen

## Build

- Debug APK: `./gradlew clean :app:assembleDebug`
- Output: `app/build/outputs/apk/debug/app-debug.apk`
- Min SDK: 24 / Target SDK: 34
- Chaquopy: 17.0.0 / Kotlin: 1.9.22 / AGP: 8.2.2

## Repository

https://github.com/ViVi93/fanficfare-android

## Notes

- Do not commit `personal.ini` or credentials/secrets
- Release builds are signed via GitHub Actions on push to `master`
