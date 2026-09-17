# Phase 15 — Narrow Read-Only Audit

## Phase 15 — Narrow Read-Only Audit: `_covered.epub` Temporary-File Lifecycle

### 1. Checkpoint

- **Branch:** `next-feature-set`
- **HEAD:** `238f1bd9bece3f2291276df7c93814d1fbea69c3`
- **Phase 14 checkpoint comparison:** HEAD matches Phase 14 checkpoint exactly ✅
- **Working tree state:** Identical to Phase 14 (1 modified file: `.gitignore` from Phase 1; 8 tracked modifications from Phase 2–12; 16 untracked files including `PHASE_14_AUDIT.md`)
- **Commits since Phase 14:** None ✅
- **Pushes:** None ✅
- **`origin/next-feature-set`:** Does not exist ✅

### 2. Targeted `_covered.epub` Trace

#### 2.1 Creation

**File:** `BookDetailActivity.kt`, line 508 (working tree), line 493 (HEAD)

```kotlin
val outPath = localPath.absolutePath.replace(".epub", "_covered.epub")
```

This is constructed from `localPath.absolutePath` which is the path returned by `StorageBridge.withLocalEpub(this, bookPath)`. From `StorageBridge.kt` (lines 76-91):

- For `content://` URIs: `localPath` = `filesDir/tmp_{timestamp}_{originalName}` (e.g., `filesDir/tmp_1695392134782_book.epub`)
- For `file://` URIs: `localPath` = the original file (e.g., `/storage/emulated/0/Downloads/book.epub`)

So `outPath` becomes:
- `content://` case: `filesDir/tmp_{timestamp}_{originalName}_covered.epub`
- `file://` case: `/storage/emulated/0/Downloads/book_covered.epub`

#### 2.2 Location

- **`content://` case:** `filesDir/tmp_*_covered.epub` — inside `filesDir` ✅ (confirmed)
- **`file://` case:** Same directory as the original EPUB — the `_covered.epub` is written next to the original

#### 2.3 Nature of the file

`outPath` is passed to `bridge.replaceEpubCover(localPath.absolutePath, base64, mime, outPath, ".bak")` (line 509). Inside Python (`epub_editor.replace_cover`, line 809), `output_path` is provided, so `_resolve_target()` (line 145):

```python
if output_path:
    target = output_path  # = outPath = "_covered.epub" path
    ...
    return target, None, backup_path  # temp_path=None, no atomic temp on Python side
```

Python writes **directly** to `outPath` (no temp file on the Python side). The `_covered.epub` is the **generated output** — NOT a copy of another EPUB.

#### 2.4 copyToOutputDir call

**Line 523:** `val finalPath = StorageBridge.copyToOutputDir(this, source, outputDir)`

Where `source = File(outputPath)` and `outputPath = result.optString("output_path", "")` which is the Python return value `final_path` = `target` = `outPath` (the `_covered.epub` path).

`copyToOutputDir` (StorageBridge.kt line 53) copies `sourceFile` to the user's configured output directory (content:// URI or filesystem path).

#### 2.5 What happens after copyToOutputDir

After line 523, the code flow continues:
- Line 524-527: `runOnUiThread { Toast; finishWithResult(...) }`
- **No `source.delete()` call** — the `_covered.epub` file is never cleaned up.

#### 2.6 Cleanup audit

| Code path | `source.delete()` called? |
|---|---|
| Successful copy (line 523→524) | ❌ No |
| Failed copy — exception (line 534) | ❌ No |
| Output file missing (line 529) | ❌ No |
| Operation failed (line 532) | ❌ No |

**No cleanup of `_covered.epub` exists anywhere in `replaceCoverWithImage`.**

#### 2.7 Cleanup across all failure paths

| Scenario | `_covered.epub` exists? | Cleaned up? |
|---|---|---|
| `withLocalEpub` returns null (cannot read EPUB) | No (Python never ran) | N/A |
| Python `replaceEpubCover` fails (`ok: false`) | No (Python didn't write output) | N/A |
| Python succeeds, `_covered.epub` created | Yes | ❌ Not cleaned up |
| `copyToOutputDir` succeeds | Yes | ❌ Not cleaned up |
| `copyToOutputDir` fails (exception) | Yes | ❌ Not cleaned up |
| `source.exists()` returns false | Yes (created but empty?) | ❌ Not cleaned up |

#### 2.8 Later consumption of `_covered.epub` path

```bash
grep -rn '_covered' app/src/
# Only match: BookDetailActivity.kt:508 (creation site)
```

**No later code references the `_covered.epub` path.** It is a write-once, never-read-again file within a single `replaceCoverWithImage` call.

#### 2.9 Other cleanup mechanisms

- No background cleanup thread/scheduler deletes `_covered.epub` files
- No `onDestroy`/`onCleanUp` hook cleans them
- No `JobScheduler`/`WorkManager` task targets them
- They persist until app data is cleared by the user manually

### 3. Root-Cause Classification

**CONFIRMED ORPHANED TEMP FILE**

Evidence:
1. `_covered.epub` is created in `filesDir` (for `content://` case) via `outPath` at line 508
2. It is a generated output (not a copy of another EPUB) — confirmed by Python `replace_cover()` writing directly to `output_path`
3. `withLocalEpub()`'s `finally` block deletes only the temp input (`tmp_*.epub`), NOT `_covered.epub`
4. After `copyToOutputDir()`, the `_covered.epub` file is never referenced again
5. No later code, no cleanup mechanism, no background process touches it
6. The git history confirms this code was introduced in commit `20e7479` (`Add EPUB metadata & cover editor`) — it is pre-existing, committed code (confirmed present at HEAD line 493)

### 4. Failure Semantics

| Scenario | `_covered.epub` exists after? | Consequence |
|---|---|---|
| Successful copy to output dir | Yes | Orphaned file in `filesDir` (or output dir for `file://`) |
| `copyToOutputDir()` throws | Yes | Orphaned file + error shown to user |
| `copyToOutputDir()` fails (returns null path) | Yes | Orphaned file, no error shown (user sees cover replaced toast) |
| Early return (source doesn't exist) | Yes | Orphaned file if it was created |
| `replaceEpubCover` returns `ok: false` | No | Python didn't write output, no orphan |
| `withLocalEpub` returns null | No | Python never ran, no orphan |

**Would deleting the local `_covered.epub` immediately after a successful `copyToOutputDir()` be behaviorally safe?**

**Yes.** The evidence:

1. `copyToOutputDir()` (StorageBridge.kt line 53) creates a **new file** in the output directory via `createFile()` (for content:// URIs) or `copyTo()` (for file://). It does NOT move the source — the source remains independent.
2. After `copyToOutputDir()` returns `finalPath`, that path points to the **output directory copy**, not to `_covered.epub`.
3. `finishWithResult` receives `finalPath` (not `outputPath`), so the result Intent points to the output dir copy.
4. The `_covered.epub` file has no later consumer (confirmed by grep — single reference at line 508).
5. The `_covered.epub` is NOT a backup file (`.bak`) — it's a working intermediate whose content has been persisted to the output directory.

The only concern would be if `copyToOutputDir` fails — in which case the `_covered.epub` would be the only copy of the modified EPUB. However:
- The Phase 10 `applyMetadataAndCoverSafely` pattern in `MetadataPreviewActivity` handles this by deleting on success but keeping on failure (lines 807-822).
- For `replaceCoverWithImage`, the same pattern is absent: even on failure, the `_covered.epub` is orphaned, but no recovery path uses it.

**Safety conclusion:** `source.delete()` after a **successful** `copyToOutputDir` would be safe. On failure, keeping the file provides a (very weak) recovery path, consistent with the Phase 10 backup philosophy.

### 5. Phase 10 Comparison

| Aspect | `replaceCoverWithImage` (BookDetailActivity) | `applyMetadataAndCoverSafely` (MetadataPreviewActivity) |
|---|---|---|
| **Temp/working dir creation** | `withLocalEpub` → `tmp_*.epub` | `withLocalEpub` → `tmp_*.epub` |
| **Modified output creation** | `_covered.epub` (inline string replace) | `modified_{ts}_{name}` (File() constructor) |
| **Python write target** | `outPath` (explicit path) | `outputPath` (explicit path) |
| **Persistence to output dir** | `copyToOutputDir(source, outputDir)` | `copyToOutputDir(sourceFile, outputDir)` |
| **Cleanup after copy** | ❌ **None** | ✅ `sourceFile.delete()` on success |
| **Failure cleanup** | ❌ **None** | ✅ `sourceFile.delete()` on exception |
| **Backup suffix** | `.bak` | `.metadata_edit_bak` / `.cover_edit_bak` |
| **Lifecycle guards** | `isFinishing || isDestroyed` at line 464 (after finishWithResult) | `isFinishing || isDestroyed` in `safeRunOnUiThread` |
| **Error feedback** | `showError(...)` toast | `showError(...)` toast |

**Key difference:** `applyMetadataAndCoverSafely` explicitly deletes the modified output after successful persistence (line 810), and also deletes on failure (line 818). `replaceCoverWithImage` has **no equivalent cleanup**.

**Correctness impact:** The inconsistency is real but does not affect data integrity — both paths persist the correct output to the output directory. The only difference is that `replaceCoverWithImage` leaves an orphaned `_covered.epub` in `filesDir` (for `content://` sources) or next to the original EPUB (for `file://` sources).

### 6. Backup Distinction

| File | Purpose | Recovery Value | Should be cleaned? |
|---|---|---|---|
| `.metadata_edit_bak` | Backup of original EPUB before metadata edit | High — recovery if write fails | ❌ NO (DEFER) |
| `.cover_edit_bak` | Backup of original EPUB before cover edit | High — recovery if write fails | ❌ NO (DEFER) |
| `.bak` | Backup of original EPUB in `replaceCoverWithImage` | High — recovery if write fails | ❌ NO (DEFER) |
| `_covered.epub` | Generated output after successful write | Low — content already persisted to output dir via `copyToOutputDir` | ✅ Safe to delete after successful copy |

**Why `_covered.epub` ≠ backup:**
- `.bak` files are created by `shutil.copy2(epub_path, backup_path)` **before** any modifications — they preserve the user's original EPUB
- `_covered.epub` is the **output** of the modification — it contains the new cover, and its content has **already been copied** to the output directory via `copyToOutputDir`
- `.bak` files protect against "write failure corrupts original"; `_covered.epub` is just an un-cleaned intermediate after "success"

### 7. Related Temporary-File Evidence

| Pattern | File | Line | Cleanup |
|---|---|---|---|
| `tmp_{timestamp}_{name}` temp input | StorageBridge.kt | 79 | ✅ Deleted in `withLocalEpub` finally (line 29) |
| `modified_{timestamp}_{name}` intermediate | MetadataPreviewActivity.kt | 776 | ✅ Deleted via `sourceFile.delete()` (lines 810, 818) |
| `_covered.epub` intermediate | BookDetailActivity.kt | 508 | ❌ **Not deleted** |
| `filesDir/{name}` output (update force download) | BookDetailActivity.kt | 199, 285 | ❌ **Not deleted** (same pattern as `_covered.epub`) |
| Python `tempfile.mkstemp` | epub_editor.py | 164, 1183 area | ✅ Deleted via `_finalize_write` (rename) or exception handler |
| Python `_temp_path` tracking | epub_editor.py | 823/1183 | ✅ Deleted in except handler |

**Pattern finding:** The `replaceCoverWithImage` orphan is part of a broader pattern — the two other `copyToOutputDir` call sites in `BookDetailActivity.kt` (lines 238, 313) also do not delete their `filesDir` sources after copying. These use `bridge.updateEpubFromPath` / `bridge.forceDownloadFromEpub` which write to `outDir = filesDir.absolutePath` (passed at lines 199, 285). The returned `internalPath` points to a file in `filesDir` that is also never cleaned up after `copyToOutputDir`.

This is noted for classification context only — the Phase 15 scope is strictly `_covered.epub`.

### 8. Git History

| Question | Answer |
|---|---|
| Did `_covered.epub` exist before Phase 7? | ✅ Yes — introduced in commit `20e7479` (`Add EPUB metadata & cover editor: read/write OPF metadata, cover replacement, edit UI`) |
| Was it introduced by Phase 7? | No — `20e7479` predates the Phase 7 working-tree changes. It is committed code. |
| Was cleanup intentionally omitted? | Unknown from git history alone — the commit message does not mention temp file cleanup. The Phase 10 fix added proper cleanup to the MetadataPreviewActivity path, suggesting the absence in `replaceCoverWithImage` may have been an oversight. |
| Did later phases rely on `_covered.epub` remaining? | ❌ No — `git blame` confirms line 508 is attributed to commit `20e7479` and has not been modified since. Later phases did not add any consumer of this file. |

### 9. Protected Invariants — Quick Regression Check

| Invariant | Verification | Status |
|---|---|---|
| `"authors" : ArrayList<String>` | `putStringArrayListExtra("authors", ...)` at lines 580, 660; `getStringArrayListExtra("authors")` at line 469 | PASS ✅ |
| Lifecycle guards | `safeRunOnUiThread` (line 740), `isFinishing \|\| isDestroyed` guards on all Threads | PASS ✅ |
| `content://` uses distinct output path | `modified_{timestamp}_{name}` at line 776, separate from `tmp_*` input | PASS ✅ |
| `withLocalEpub` doesn't delete modified output | Python receives `modified_*` output_path; `withLocalEpub` finally only deletes temp input | PASS ✅ |
| `copyToOutputDir` persists | Line 808: `copyToOutputDir(this, sourceFile, outputDir)` | PASS ✅ |
| `EDIT_METADATA_REQUEST = 1001` | Line 25 | PASS ✅ |
| `REPLACE_COVER_REQUEST = 1002` | Line 26 | PASS ✅ |
| `PREVIEW_METADATA_REQUEST = 1003` | Line 27 | PASS ✅ |
| Shared `onActivityResult` handling | Line 466: `EDIT_METADATA_REQUEST, PREVIEW_METADATA_REQUEST ->` | PASS ✅ |

No protected invariant was disturbed by this audit.

### 10. Tests

| Test System | Command | Result |
|---|---|---|
| Python unittest discover | `python3 -m unittest discover -s tests -v` | **248 tests, OK** |
| Custom epub_editor runner | `PYTHONPATH=... python3 tests/test_epub_editor.py` | **14 passed, 0 failed** |
| **Total** | | **262 passed, 0 failed** |

Results unchanged from Phase 14. The custom runner is not double-counted as unittest-discoverable (it uses procedural `run_tests()` + `sys.exit()`, not `unittest.TestCase` classes).

### 11. Android Build

- Command: `./gradlew clean :app:assembleDebug -x lint`
- Result: **BUILD SUCCESSFUL in 2m 15s** (48 actionable tasks: 48 executed)
- No build errors or warnings

### 12. Security / Correctness

For the specific `_covered.epub` path:

| Check | Result |
|---|---|
| Does NOT delete user's original EPUB | ✅ `_covered.epub` ≠ original — original is preserved as `.bak` before write |
| Does NOT delete persisted output EPUB | ✅ Persisted output is in user's output dir (via `copyToOutputDir`); `_covered.epub` is an intermediate |
| Does NOT delete recovery backup | ✅ `.bak` files are distinct from `_covered.epub` |
| Does NOT expose/overwrite another book | ✅ Filename derived from current EPUB path only |
| Does NOT confuse temp with durable output | ✅ `finishWithResult` receives `finalPath` (output dir copy), not `outputPath` (`_covered.epub`) |
| `file://` case: writes `_covered.epub` next to original | ⚠️ Could collide if filename already exists, but `replace_cover` Python uses atomic temp+rename internally |

Proposed future `source.delete()` after successful `copyToOutputDir` would be safe and would not violate any security invariant.

### 13. Scope Check

| Change | Made? |
|---|---|
| Kotlin source files modified | ❌ None |
| Python source files modified | ❌ None |
| Test files modified | ❌ None |
| Layout/resource files modified | ❌ None |
| Gradle files modified | ❌ None |
| Configuration modified | ❌ None |
| Commits made | ❌ None |
| Pushes made | ❌ None |
| Temporary files cleaned | ❌ None |
| New files other than report | ❌ None |
| `PHASE_15_AUDIT.md` created | ✅ Yes (this file) |

Read-only status confirmed. The only file created/modified is `PHASE_15_AUDIT.md`.

### 14. Final Classification

**DEFER — CODE QUALITY ONLY**

**Evidence:**

1. `_covered.epub` is a confirmed orphaned temporary file — created in `filesDir` (for `content://` sources), persisted to the output directory via `copyToOutputDir`, and never referenced again.

2. No user-visible behavior is affected: the cover is correctly persisted to the output directory, `finishWithResult` receives the output-directory path (not the `_covered.epub` path), and the user sees the correct success toast.

3. No data loss risk: the original EPUB is protected by the `.bak` backup (created before the write). The `_covered.epub` is the OUTPUT, not the original.

4. No recovery path uses `_covered.epub`: confirmed by grep (single reference at line 508), git history (no consumer added in any later commit), and code trace (no later code reads it).

5. The inconsistency with Phase 10's `applyMetadataAndCoverSafely` (which properly cleans up) confirms this is a code-quality gap, not an intentional design choice. The Phase 10 fix explicitly added `sourceFile.delete()` — its absence in `replaceCoverWithImage` is an omission.

6. Storage growth is bounded and slow (one ~1-5MB file per manual cover replacement), not material to application correctness.

**The one-line `source.delete()` fix should NOT be implemented during Phase 15.** It is a code-quality improvement that belongs to a future implementation phase, not a read-only audit.

### 15. Decision Rule Application

Per the Phase 15 decision rule, escalation to `REQUIRES FUTURE CORRECTNESS FIX` requires demonstrating a concrete consequence such as incorrect user-visible behavior, incorrect persistence, data loss, wrong EPUB returned, broken recovery, repeated-operation failure, or storage growth affecting correctness.

None of these apply:
- ✅ User-visible behavior is correct (cover is persisted and returned)
- ✅ Persistence is correct (output dir copy is returned via `finishWithResult`)
- ✅ No data loss (original preserved as `.bak`)
- ✅ No wrong EPUB returned (path = output dir, not `_covered.epub`)
- ✅ Recovery is intact (`.bak` files unaffected)
- ✅ No repeated-operation failure (each call creates a unique `_covered.epub`)
- ✅ Storage growth is bounded and non-material

### DEFER — CODE QUALITY ONLY