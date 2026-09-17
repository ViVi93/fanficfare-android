# Phase 14 — Read-Only Pre-Implementation Audit Report

## 1. Starting Checkpoint

- **Branch:** `next-feature-set`
- **HEAD:** `238f1bd9bece3f2291276df7c93814d1fbea69c3`
- **origin/next-feature-set:** Does not exist (local-only branch)
- **Working tree:** Intentionally dirty (Phase 2–12 uncommitted work)
- **Commits/pushes since Phase 12:** None
- **Modified tracked files (8):**
  - `.gitignore` (+1)
  - `app/src/main/AndroidManifest.xml` (+1)
  - `app/src/main/java/com/example/fanficfare/BookDetailActivity.kt` (+17/-1, Phase 12)
  - `app/src/main/java/com/example/fanficfare/PythonBridge.kt` (+32)
  - `app/src/main/python/epub_editor.py` (+578)
  - `app/src/main/python/fanficfare_bridge.py` (+201)
  - `app/src/main/python/tests/test_epub_editor.py` (+230)
  - `app/src/main/res/layout/activity_book_detail.xml` (+14/-1)
- **Untracked files (16):** MetadataPreviewActivity.kt, cover_manager.py, metadata_diff.py, metadata_normalizer.py, metadata_providers.py, 6 test files, 5 resource/layout files

## 2. Protected Files

| File | Tracked in HEAD? | Modified in working tree? | Status |
|---|---|---|---|
| `fanficfare/` | Does not exist | N/A | NOT MODIFIED ✅ |
| `fanficfare_config.py` | Not tracked | No | NOT MODIFIED ✅ |
| `personal.ini` | Not tracked | No | NOT MODIFIED ✅ |
| `.github_secret_values.txt` | Not tracked | No | NOT MODIFIED ✅ |

No Phase 14 implementation changes were found. No protected file was modified.

## 3. Phase 12/13 Baseline Verification

| Constant | Value | Used For | Status |
|---|---|---|---|
| `EDIT_METADATA_REQUEST` | 1001 | EditMetadataActivity launch | PASS ✅ |
| `REPLACE_COVER_REQUEST` | 1002 | ACTION_OPEN_DOCUMENT launch | PASS ✅ |
| `PREVIEW_METADATA_REQUEST` | 1003 | MetadataPreviewActivity launch | PASS ✅ |

- No request-code collision
- `onActivityResult()` handles both `EDIT_METADATA_REQUEST` and `PREVIEW_METADATA_REQUEST` via multi-case branch (line 466)
- Both codes share identical result-processing logic
- `REPLACE_COVER_REQUEST` branch untouched

## 4. Phase 9 Author Contract

| Side | Code | Status |
|---|---|---|
| Producer | `putStringArrayListExtra("authors", extractAuthors(onlineMeta))` (lines 580, 660) | PASS ✅ |
| Consumer | `getStringArrayListExtra("authors")` (line 469) | PASS ✅ |
| Type | `ArrayList<String>` on both sides | PASS ✅ |
| Stale `"author"` contract | Not reintroduced in result Intent | PASS ✅ |

## 5. Phase 10 content:// Persistence Invariant

For `content://` EPUBs, the complete flow was traced through `MetadataPreviewActivity`, `StorageBridge.withLocalEpub()`, `PythonBridge`, `fanficfare_bridge.py`, and `epub_editor.py`:

| Step | Verification | Status |
|---|---|---|
| 1. Source copied to temp local EPUB | `copyContentUriToTemp` → `filesDir/tmp_*.epub` | PASS ✅ |
| 2. Python does NOT write final mod to temp input | Python receives separate `output_path` for `modified_*` file | PASS ✅ |
| 3. Separate persistent `modified_*` output | `File(localPath.parentFile, "modified_*")` in filesDir | PASS ✅ |
| 4. `withLocalEpub()` deletes only temp input | `finally { if (isTemp) file.delete() }` — only deletes the `temp` Pair first component | PASS ✅ |
| 5. `copyToOutputDir()` persists to output dir | `copyToOutputDir(this, sourceFile, outputDir)` | PASS ✅ |
| 6. filesDir output copy cleaned up | `sourceFile.delete()` at line 810 | PASS ✅ |
| 7. `output_path` → persistent output | Returns `finalPath` from `copyToOutputDir` | PASS ✅ |

For `file://` EPUBs: `output_path` remains `null`, in-place atomic modification via temp+rename, behavior unchanged.

**`tmp_*` ≠ `modified_*`**: Different filename prefixes, cannot collide. The `withLocalEpub` finally only deletes the `File` returned as the first element of the `Pair` (the temp input), not the `modified_*` output.

## 6. Atomic EPUB Write Verification

| Mode | fields | image | Calls `applyMetadataAndCoverSafely` | → Single `write_metadata_and_cover` | Status |
|---|---|---|---|---|---|
| Metadata only | `fields` | null | ✅ line 565 | ✅ | PASS ✅ |
| Cover only | `{}` | data | ✅ line 701 | ✅ | PASS ✅ |
| Combined | `fields` | data | ✅ line 645 | ✅ | PASS ✅ |

Each mode calls `bridge.applyMetadataAndCover` once → `fanficfare_bridge.apply_metadata_and_cover` (line 1065) → `epub_editor.write_metadata_and_cover` (line 1160):
- One temp output via `tempfile.mkstemp`
- One `zipfile.ZipFile.write` for all entries (metadata + cover in single pass)
- One `shutil.move` atomic rename via `_finalize_write`
- Backup created before write via `_resolve_target` → `shutil.copy2`

No separate metadata + cover writes. No regression to split-write pattern.

## 7. Lifecycle Safety

| Guard | Count | Status |
|---|---|---|
| `safeRunOnUiThread` definition | 1 (line 740) | PASS ✅ |
| `safeRunOnUiThread` call sites | 16 | PASS ✅ |
| `isFinishing \|\| isDestroyed` early-return on Threads | 6 (lines 118, 401, 563, 643, 699, 741) | PASS ✅ |
| Raw `runOnUiThread` outside `safeRunOnUiThread` | 0 | PASS ✅ |

All 5 background `Thread { }` blocks have guards. No new lifecycle hazards introduced by Phase 10–12.

## 8. Result Intent Contract

| Field | Producer (MetadataPreviewActivity) | Consumer (BookDetailActivity) | Status |
|---|---|---|---|
| `title` | `putExtra("title", ...)` | `getStringExtra("title") ?: bookTitle` | PASS ✅ |
| `authors` | `putStringArrayListExtra("authors", ...)` | `getStringArrayListExtra("authors")?.joinToString(", ")` | PASS ✅ |
| `output_path` | `putExtra("output_path", ...)` | `getStringExtra("output_path") ?: bookPath` | PASS ✅ |
| `modified` | `putExtra("modified", ...)` | `getLongExtra("modified", ...)` | PASS ✅ |

- Metadata-only and combined modes return all 4 fields
- Cover-only mode returns only `output_path` + `modified` (correctly omits `title`/`authors`)
- Consumer has correct fallbacks (`?: bookTitle`, `?: bookAuthor`)

**`source` field analysis:** Not consumed by any caller. `MetadataPreviewActivity` does NOT include `"source"` in its result Intent. Classified as **NOT A REAL ISSUE / INFORMATIONAL**.

## 9. Backup-File Assessment

| Scenario | Backup Location | Cleanup | Status |
|---|---|---|---|
| `content://` EPUB | `filesDir/tmp_*.{metadata,cover}_edit_bak` | Persisted (not auto-deleted) | **Intentional recovery** ✅ |
| `file://` EPUB | Alongside original (inplace + suffix) | Persisted (not auto-deleted) | **Intentional recovery** ✅ |

Backup files persist in `filesDir` for `content://` sources. This is **intentional recovery behavior**, consistent with `BookDetailActivity.replaceCoverWithImage` which also leaves `.bak` files. Automatic cleanup would destroy the only recovery copy if the output-dir copy fails.

Classification: **DEFER / potentially destructive** — no concrete evidence of unbounded accumulation (files are only created on explicit user apply, with user-visible backup naming).

## 10. Newly Discovered Issues

### Issue A: Orphaned `_covered.epub` in `replaceCoverWithImage` (Pre-existing)

**Finding:** `BookDetailActivity.replaceCoverWithImage()` (line 486, exists in HEAD at `238f1bd`) creates a `_covered.epub` file in `filesDir` via `outPath = localPath.absolutePath.replace(".epub", "_covered.epub")` (line 508), copies it to the output directory via `copyToOutputDir`, but **never deletes** the `_covered.epub` file from `filesDir`.

**Evidence:**
- Line 507-510: `withLocalEpub` creates `tmp_*.epub`, writes result to `tmp_*_covered.epub`
- `withLocalEpub` finally deletes only `tmp_*.epub` (the temp input)
- Line 523: `copyToOutputDir` copies `tmp_*_covered.epub` → output dir
- **No `delete()` call for the `_covered.epub` file** ← missing cleanup
- Contrast: `MetadataPreviewActivity.applyMetadataAndCoverSafely` explicitly calls `sourceFile.delete()` (line 810)

**Scope:** Pre-existing from Phase 7. Phase 10's fix addressed the MetadataPreviewActivity path with proper cleanup, but `replaceCoverWithImage` (the cover-only path from `ACTION_OPEN_DOCUMENT`) was not updated.

**Classification: CODE-QUALITY / OPTIONAL** — orphaned files in `filesDir` accumulate one per `replaceCoverWithImage` call. Not a data-loss issue (the output is correctly persisted), but the orphaned file is untidy. The fix is a single `source.delete()` line after `copyToOutputDir`, matching the existing pattern in `applyMetadataAndCoverSafely`.

### Issue B: No new issues found

No `REAL BUG`, `REGRESSION RISK`, or new `stale UI/result state` / `incorrect URI/path ownership` / `failure-path inconsistency` / `duplicate writes` / `incorrect cleanup ordering` / `request/result contract mismatch` was introduced by Phase 12.

## 11. Architecture Migration

The project already contains `LibraryViewModel`, `BookRepository`, Room, `DownloadJob`, `FanFicFareWorker`, `ViewModelFactory`, `MyApplication`, and MainActivity/AddFromPageActivity already use that architecture.

`BookDetailActivity`, `MetadataPreviewActivity`, and `EditMetadataActivity` still use direct background Threads. This was NOT escalated to Phase 14 scope because **no concrete correctness bug was demonstrated** that requires migration.

Classification: **DEFER / ARCHITECTURAL FOLLOW-UP** ✅

## 12. Test Discovery Audit

| Test System | Command | Result |
|---|---|---|
| Python unittest | `/tmp/ff_venv/bin/python3 -m unittest discover -s tests -v` | **248 tests, OK** ✅ |
| Custom epub_editor runner | `PYTHONPATH=.../python /tmp/ff_venv/bin/python3 tests/test_epub_editor.py` | **14 passed, 0 failed** ✅ |

**No double-counting:** The custom runner (`test_epub_editor.py`) uses a standalone `run_tests()` function (not `unittest` framework) and is structured as a script, not as `unittest.TestCase` classes. It is not discovered by `unittest discover` because:
- It has no classes inheriting from `unittest.TestCase`
- It uses a procedural `run_tests()` + `sys.exit()` pattern
- The 14 custom tests cover distinct scenarios (export, import, metadata round-trip, atomic writes) not present in the unittest suite

## 13. Android Build

- Command: `./gradlew clean :app:assembleDebug -x lint`
- Result: **BUILD SUCCESSFUL in 40s** (48 actionable tasks: 48 executed)
- No build errors or warnings

## 14. Diff / Scope Audit

| File | Changed? | Phase Attribution |
|---|---|---|
| `.gitignore` | ✅ (+1) | Phase 1 |
| `AndroidManifest.xml` | ✅ (+1) | Phase 7 (MetadataPreviewActivity registration) |
| `BookDetailActivity.kt` | ✅ (+17/-1) | Phase 12: 3 changes (constant, launch, handler) |
| `PythonBridge.kt` | ✅ (+32) | Phase 2/9 |
| `epub_editor.py` | ✅ (+578) | Phase 2–9 |
| `fanficfare_bridge.py` | ✅ (+201) | Phase 2–9 |
| `test_epub_editor.py` | ✅ (+230) | Phase 2–9 |
| `activity_book_detail.xml` | ✅ (+14/-1) | Phase 7 |

**Untracked (Phase 7–9 work, not committed):** MetadataPreviewActivity.kt, 5 Python modules (cover_manager.py, metadata_diff.py, metadata_normalizer.py, metadata_providers.py, fanficfare.py if present), 6 test files, 5 layout/drawable resources.

Phase 12 diff is exactly 3 changes in BookDetailActivity.kt only. No unexpected file modifications.

## 15. Security Audit

| Check | Result |
|---|---|
| Arbitrary filesystem writes | ✅ None — all filenames are system-generated |
| Provider-controlled output paths | ✅ None — output paths use `modified_{timestamp}` prefix |
| Path traversal | ✅ None — `withLocalEpub` copies to controlled `filesDir` |
| Credential leakage | ✅ None — no credentials in code path |
| Secret exposure in logs | ✅ None — only filenames and paths logged |
| Unsafe backup naming | ✅ Backup suffixes are `.metadata_edit_bak`, `.cover_edit_bak`, `.bak` (no user input) |
| Uncontrolled external destinations | ✅ Output dir is user-configured via SettingsActivity |

No security regressions. Phase 12's request-code separation introduced no security issues.

## 16. Phase 14 Scope Determination

| Candidate | Classification | Rationale |
|---|---|---|
| Fix orphaned `_covered.epub` in `replaceCoverWithImage` | CODE-QUALITY / OPTIONAL | 1-line fix (`source.delete()` after `copyToOutputDir`), matches existing pattern in `applyMetadataAndCoverSafely`. Pre-existing Phase 7 issue, not a regression. |
| Thread → ViewModel migration for activities | DEFER / ARCHITECTURAL FOLLOW-UP | No concrete correctness bug demonstrated; architectural improvement only |
| Cleanup orphaned backup files | DEFER / POTENTIALLY DESTRUCTIVE | Would destroy recovery copies if output-dir copy fails |
| Add `"source"` to MetadataPreviewActivity result Intent | NOT A REAL ISSUE | Not consumed by any caller; adding dead fields is unnecessary |
| Fix stale UI/result state | NOT A REAL ISSUE | No stale state found in metadata/cover preview flow |

## 17. Final Verdict

**NO IMPLEMENTATION WARRANTED — CONTINUE WITH VERIFICATION / DEFER**

No `REAL BUG` or `REGRESSION RISK` was discovered by this audit. Phase 12's request-code separation is correctly implemented with no regressions across any Phase 9/10/11 protected invariant.

The single optional finding (orphaned `_covered.epub` in `replaceCoverWithImage`) is:
- Pre-existing from Phase 7 (not introduced by Phase 12)
- Classified as CODE-QUALITY / OPTIONAL
- Fixable with a single line matching an existing pattern
- Does not cause data loss (output is correctly persisted)

If the user wishes to proceed, the smallest coherent Phase 14 implementation is: add `source.delete()` after `copyToOutputDir` in `BookDetailActivity.replaceCoverWithImage()` (line 523-527), matching the pattern already established in `MetadataPreviewActivity.applyMetadataAndCoverSafely`.

All other architectural improvements (ViewModel/Thread migration, backup cleanup, etc.) remain **DEFERRED**.
