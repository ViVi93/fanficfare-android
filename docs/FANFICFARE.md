# FanFicFare Embedded Engine

| Field | Value |
|-------|-------|
| embedded version | 4.62.0 |
| upstream tag | v4.62.0 |
| upstream commit | c804f5d8daaa4bcc1178907b745ac549b84cd425 |
| import/update date | 2026-10-02 |
| upstream release date | 2026-10-01 |
| upstream repository | https://github.com/JimmXinu/FanFicFare |

## Android-specific modifications

The following files contain changes required for Chaquopy/Android compatibility. They are preserved across upstream updates by `tools/update_fanficfare.py`.

- `adapters/__init__.py`: removed test-only adapters (`adapter_test1`-`adapter_test4`) to reduce APK size
- `adapters/base_adapter.py`: `getChapterTextNum()` retries once on transient network errors (`ChunkedEncodingError`, `ProtocolError`, `IncompleteRead`). Mobile connections drop mid-transfer far more often than desktop, and without this one flaky chapter aborts the whole download. It also retries once on `HTTPErrorFFF` with 429/500/502/503/504 after a 5s pause, so a rate-limited site mid-story no longer aborts a download that the app would then re-fetch from chapter one.
- `fetchers/fetcher_requests.py`: `make_retries()` passes `backoff_max=10` and `retry_after_max=60`. Upstream leaves urllib3's defaults (120s and 21600s), and urllib3 sleeps *inside* the retry ladder where the app cannot interrupt it - so a dead image host, or a rate limiter answering `Retry-After: 21600`, could park a story fetch (and, with the engine gate, the whole download queue) for up to six hours. `retry_after_max` is passed under `try`/`except TypeError` for older urllib3.
- `fetchers/fetcher_requests.py`: **image requests fail fast.** Upstream has no image-specific retry policy (checked against master), so every image reference in a story paid the *page* retry ladder: measured **22s for one dead-host image** (`postimg.org`), and old stories are full of them - FFF only logs "Failed to load or convert image ... skipping" at the end, so the download looks frozen. Images now go through `get_image_session()`: `make_image_retries()` = `Retry(total=1, backoff_factor=1, backoff_max=2)`, an `image_connect_timeout` (default 15s) instead of 60s, and a per-run `dead_image_hosts` memo so the second and later images from a host that already failed are skipped instantly (0s). Image requests are identified by the `Accept: image/*` header `base_fetcher` already sets for them. Measured effect on a 73-chapter story with images on: 85s total (5 chapter images embedded) vs the old path never finishing 60s.
- `browsercache/__init__.py`: guarded `SqldbCache` import so a missing `apsw` does not break package import
- `browsercache/browsercache_sqldb.py`: `apsw` imported under `try`/`except ImportError`, raising a clear error only if the class is actually used. APSW has no Chaquopy Android wheel.
- `dateutils.py`: relative-date parsing keeps its `logger.debug` call (upstream commented it out in v4.62.0); useful when diagnosing bad chapter dates from the app.
- `adapters/adapter_royalroadcom.py`: the `books:rating:value` lookup is guarded against a missing tag in BOTH `extractChapterUrlsAndMetadataRedesign()` and `extractChapterUrlsAndMetadataLegacy()`. Upstream v4.62.0 indexes `['content']` straight off the `find()` result (`stars=soup.find(...)['content']`), so any page without that meta tag raises `TypeError` and aborts the whole download. Our form holds the tag in `stars_tag` and only calls `setMetadata` when it is not None.

  **Do not drop this guard on the next upstream migration.** It is a deliberate, permanent divergence from upstream and is NOT a bug we introduced. Verify it with:

  ```bash
  grep -c stars_tag app/src/main/python/fanficfare/adapters/adapter_royalroadcom.py
  ```

  Expected: `6` (two sites x three occurrences: assignment, `is not None` test, and the `setMetadata` call). A count of `0` means the file was overwritten from upstream and Royal Road downloads will crash on unrated stories. Deliberately kept local rather than reported upstream.

### Corrections from the v4.62.0 audit

The patch list previously documented three changes that are **not** present in the tree and never were:

- `adapters/adapter_literotica.py`: the claimed `is_adult` debug patch does not exist; the file is otherwise stock upstream.
- `fetchers/fetcher_requests.py`: the claimed guarded `requests_file.FileAdapter` import does not exist. `requests-file` is a declared Chaquopy dependency, so the stock unguarded upstream import is correct.
- `browsercache/base_browsercache.py`: the brotlidecpy fallback chain is upstream's own, byte-identical to v4.62.0. Not an Android modification.

The genuine `apsw` guard was also missing from this list despite commit `81e26ed` existing solely to fix an apsw regression.

The `base_adapter.py` chapter retry was also genuinely absent: it existed in `7bceae7` and was stripped in `0f263e2` as collateral damage while removing temporary download instrumentation. It has been re-ported against the v4.62.0 refactor of `add_chapter()`/`ignore_chapter_url_list`.

## Phase 1 integration points

These files are part of the Android application configuration layer and are NOT part of the upstream FanFicFare engine. They are preserved separately.

- `fanficfare_config.py`: `set_config_dir()`, `build_configuration()`, `get_config_status()`
- `fanficfare_bridge.py`: all FanFicFare operations use centralized configuration. Downloads embed chapter images (and the cover) by default; `download_chapter_images:false` in personal.ini (any section) drops to cover-only, matching the update/force paths. `_chapter_images_enabled()` reads either `download_chapter_images` or `include_images`.
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
- urllib3
- Brotli

Optional/bundled fallbacks preserved upstream:

- brotli / brotlidecpy fallback chain in `browsercache/base_browsercache.py`

No new dependencies were introduced by the v4.62.0 update.

## Update procedure

1. Ensure working tree is clean and on `next-feature-set`
2. Run the updater:
   ```bash
   python tools/update_fanficfare.py --tag vX.Y.Z --commit <upstream-commit-sha>
   ```
3. Review the pre-commit comparison report. If any files are classified as `unknown` or `potential conflict`, resolve manually before proceeding.
4. Verify the Android-specific patches listed above are still present. Note that
   `base_adapter.py`, `browsercache/__init__.py` and `browsercache/browsercache_sqldb.py`
   all change upstream between releases, so patches there must be re-ported by hand
   rather than assumed preserved.
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
   git commit -m "chore(upstream): update embedded FanFicFare to vX.Y.Z"
   ```
10. Push:
    ```bash
    git push origin next-feature-set
    ```

## Known limitations

- APSW is not included in the Chaquopy pip block. It is an optional dependency for browsercache SQLite; the Android build uses the non-SQLite cache path.
- `brotli` is provided by the upstream fallback chain (`brotli` → `brotlidecpy` → skip). On Chaquopy, `brotli` pip package satisfies the first import path.
- Test adapters (`adapter_test1`-`adapter_test4`) are excluded from the Android build to reduce APK size and remove unused import overhead.
