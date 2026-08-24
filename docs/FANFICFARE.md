# FanFicFare Embedded Engine

| Field | Value |
|-------|-------|
| embedded version | 4.60.0 |
| upstream tag | v4.60.0 |
| upstream commit | 86832ac463d00ac6f1dfc10c94c47c0127c2a67c |
| import/update date | 2026-08-24 |
| upstream release date | 2026-08-01 |
| upstream repository | https://github.com/JimmXinu/FanFicFare |

## Android-specific modifications

The following files contain changes required for Chaquopy/Android compatibility. They are preserved across upstream updates by `tools/update_fanficfare.py`.

- `adapters/__init__.py`: removed test-only adapters (`adapter_test1`-`adapter_test4`)
- `adapters/base_adapter.py`: chapter-fetch retry on transient network errors (`ChunkedEncodingError`, `ProtocolError`, `IncompleteRead`)
- `adapters/adapter_literotica.py`: safe `is_adult` config inspection debug logging
- `fetchers/fetcher_requests.py`: guarded `requests_file.FileAdapter` import for Chaquopy environments where the package may be missing
- `browsercache/base_browsercache.py`: brotlidecpy fallback chain for Calibre/Android compatibility

## Phase 1 integration points

These files are part of the Android application configuration layer and are NOT part of the upstream FanFicFare engine. They are preserved separately.

- `fanficfare_config.py`: `set_config_dir()`, `build_configuration()`, `get_config_status()`
- `fanficfare_bridge.py`: all FanFicFare operations use centralized configuration
- Android internal storage: `filesDir/fanficfare/personal.ini`
- Diagnostics: version, configuration validity, credentials present

## Dependencies

Chaquopy pip block covers required packages:

- beautifulsoup4
- chardet
- html5lib
- html2text
- cloudscraper
- requests
- requests-file

Optional/bundled fallbacks preserved upstream:

- brotli / brotlidecpy fallback chain in `browsercache/base_browsercache.py`

No new dependencies were introduced by the v4.60.0 update.

## Update procedure

1. Ensure working tree is clean and on `next-feature-set`
2. Run the updater:
   ```bash
   python tools/update_fanficfare.py --tag vX.Y.Z --commit <upstream-commit-sha>
   ```
3. Review the pre-commit comparison report. If any files are classified as `unknown` or `potential conflict`, resolve manually before proceeding.
4. Verify Android-specific patches are still present in the 5 modified files.
5. Verify Phase 1 integration files (`fanficfare_config.py`, `fanficfare_bridge.py`) are untouched.
6. Run tests:
   ```bash
   python -m unittest app/src/main/python/tests/test_phase1_config.py
   ```
7. Build APK:
   ```bash
   ./gradlew clean :app:assembleDebug
   ```
8. Run real-device regression (Phase 1 critical path):
   - import `personal.ini`
   - Settings shows imported configuration
   - configuration diagnostics correct
   - credentials detected without values displayed
   - StoriesOnline download succeeds
   - Literotica download succeeds
   - force download succeeds
   - force-stop app, restart, credentials still work
   - configuration persists after restart
9. Commit:
   ```bash
   git add app/src/main/python/fanficfare/ tools/update_fanficfare.py docs/FANFICFARE.md
   git commit -m "Phase 2: update embedded FanFicFare to vX.Y.Z"
   ```
10. Push:
    ```bash
    git push origin next-feature-set
    ```

## Known limitations

- APSW is not included in the Chaquopy pip block. It is an optional dependency for browsercache SQLite; the Android build uses the non-SQLite cache path.
- `brotli` is provided by the upstream fallback chain (`brotli` → `brotlidecpy` → skip). On Chaquopy, `brotli` pip package satisfies the first import path.
- Test adapters (`adapter_test1`-`adapter_test4`) are excluded from the Android build to reduce APK size and remove unused import overhead.
