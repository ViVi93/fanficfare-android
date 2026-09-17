# Phase 16 — `_covered.epub` Cleanup Implementation

## Phase 16 — `_covered.epub` Cleanup Implementation

### 1. Starting Checkpoint

- **Branch:** `next-feature-set`
- **Starting HEAD:** `238f1bd9bece3f2291276df7c93814d1fbea69c3`
- **Working-tree state:** Identical to Phase 15 (Phase 2–12 uncommitted work present, plus Phase 14/15 audit reports)
- **Comparison with Phase 15:** HEAD matches Phase 15 checkpoint exactly — no new commits, no pushes

### 2. Preflight Classification

**CONFIRMED — MINIMAL CLEANUP CHANGE WARRANTED**

Evidence:
- `_covered.epub` is still produced at line 508 (`val outPath = localPath.absolutePath.replace(".epub", "_covered.epub")`)
- `copyToOutputDir()` (line 523) persists it to the user's output directory
- No `source.delete()` existed after the copy — confirmed in Phase 15 and verified pre-edit
- No code added since Phase 15 changed this behavior (HEAD unchanged)
- No later consumer references `_covered.epub` (grep confirmed single creation site)
- Phase 10 pattern (`applyMetadataAndCoverSafely`) already uses this cleanup pattern — confirming consistency

### 3. Change Implemented

**File changed:** `app/src/main/java/com/example/fanficfare/BookDetailActivity.kt`
**Method:** `replaceCoverWithImage()`

**Exact change (5 lines added after `copyToOutputDir`):**
```kotlin
val finalPath = StorageBridge.copyToOutputDir(this, source, outputDir)
// Clean up the local _covered.epub working file now that
// it has been persisted to the user's output directory.
// This mirrors the Phase 10 cleanup pattern in
// MetadataPreviewActivity.applyMetadataAndCoverSafely.
source.delete()
```

No other code was modified. No refactoring, no new helpers, no abstraction introduced.

### 4. Cleanup Ordering

**Control flow after implementation:**

```text
copyToOutputDir succeeds
        ↓
source.delete()       ← deletes _covered.epub only
        ↓
runOnUiThread { Toast + finishWithResult(finalPath) }  ← finalPath = output dir copy
```

**Why this ordering is safe:**
1. `copyToOutputDir()` returns `finalPath` — the path in the **output directory** (durable copy), not `source` (the `_covered.epub` path)
2. `finalPath` is captured before `source.delete()` executes
3. `finishWithResult` receives `finalPath`, not `source.absolutePath`
4. `source.delete()` executes only after `copyToOutputDir` returns successfully
5. If `copyToOutputDir` throws, execution jumps to the outer `catch` (line 539), and `source.delete()` is never reached — preserving the file for potential recovery

### 5. Failure-Path Verification

| Scenario | `_covered.epub` deleted? | Correct? |
|---|---|---|
| **Successful copy** | ✅ Yes (line 528) | Correct — persisted to output dir |
| **copyToOutputDir throws** | ❌ No (caught by outer try/catch at line 540) | Correct — preserved for recovery |
| **copyToOutputDir returns but `source` is stale** | ⚠️ `source.delete()` attempts delete | Safe — `File.delete()` returns false, no exception |
| **Early return (source missing)** | N/A (line 533 — `source.exists()` check) | Correct — file doesn't exist |
| **Operation failed (ok=false)** | N/A (line 536 — `ok` check fails) | Correct — Python didn't write `_covered.epub` |
| **Exception in outer try** | ❌ No (line 534 catch) | Correct — preserved for recovery |
| **`.bak` backup files** | ❌ No | Correct — `.bak` is separate from `_covered.epub` |

**Failure-path safety:** The new `source.delete()` is positioned inside the `if (source.exists() && source.isFile)` block and after `copyToOutputDir` succeeds. Any failure before or during `copyToOutputDir` is handled by the outer `try/catch` at line 539, which shows an error and does NOT reach `source.delete()`. The file is preserved on all failure paths, matching the conservative cleanup philosophy.

### 6. Phase 10 Pattern Comparison

| Aspect | Phase 16 (`replaceCoverWithImage`) | Phase 10 (`applyMetadataAndCoverSafely`) |
|---|---|---|
| Persist first | ✅ `copyToOutputDir` | ✅ `copyToOutputDir` |
| Delete local copy after success | ✅ `source.delete()` (line 528) | ✅ `sourceFile.delete()` (line 810) |
| Capture output path before delete | ✅ `finalPath` from `copyToOutputDir` | ✅ `finalPath` from `copyToOutputDir` |
| Delete on failure | ❌ No (preserved for recovery) | ✅ Yes (`sourceFile.delete()` in catch block, line 818) |
| Backup files preserved | ✅ `.bak` untouched | ✅ `.metadata_edit_bak` / `.cover_edit_bak` untouched |

The implementations are consistent in the success path (persist → delete local → return output path). Phase 16 is slightly more conservative on the failure path (preserves the file rather than deleting it), which is a safe difference — no correctness concern.

No refactoring or shared abstraction was introduced, per the Phase 16 scope rules.

### 7. Protected Invariants

**Phase 9:**
- `"authors"` remains `ArrayList<String>` across Intent boundary — `putStringArrayListExtra("authors")` at lines 580/660, `getStringArrayListExtra("authors")` at line 469 — **unchanged** ✅
- Lifecycle guards intact — all `Thread {}` blocks still guarded with `isFinishing || isDestroyed` ✅
- `safeRunOnUiThread` remains the sole UI-update mechanism ✅

**Phase 10:**
- `content://` persistence still uses separate `modified_*` output path (MetadataPreviewActivity line 776) — unchanged ✅
- `withLocalEpub()` still deletes only the temporary input — unchanged ✅
- Modified output still copied to durable output directory — unchanged ✅
- Local modified output still cleaned after successful persistence (line 810) — unchanged ✅
- Atomic metadata + cover writing remains intact — unchanged ✅
- `MetadataPreviewActivity` was NOT modified ✅

**Phase 12:**
- `EDIT_METADATA_REQUEST = 1001`, `REPLACE_COVER_REQUEST = 1002`, `PREVIEW_METADATA_REQUEST = 1003` — all unchanged ✅
- Shared `onActivityResult` handling (`EDIT_METADATA_REQUEST, PREVIEW_METADATA_REQUEST ->`) — unchanged ✅

### 8. Tests

| Test System | Command | Result |
|---|---|---|
| Python unittest discover | `/tmp/ff_venv/bin/python3 -m unittest discover -s tests -v` | **248 tests, OK** ✅ |
| Custom epub_editor runner | `PYTHONPATH=... /tmp/ff_venv/bin/python3 tests/test_epub_editor.py` | **14 passed, 0 failed** ✅ |
| **Total** | | **262 passed, 0 failed** |

Results unchanged from Phase 15 (248 + 14 = 262). No tests were added, removed, or modified. No double-counting (custom runner is procedural, not `unittest.TestCase`).

### 9. Android Build

- Command: `./gradlew clean :app:assembleDebug -x lint`
- Result: **BUILD SUCCESSFUL in 1m 27s** (48 actionable tasks: 48 executed)
- No build errors or warnings ✅

### 10. Diff / Scope Audit

**Production files changed:** 1
- `app/src/main/java/com/example/fanficfare/BookDetailActivity.kt` — +5/-0 (5 lines added: 4 comment + 1 `source.delete()`)

**Untracked audit report files created:** 2
- `PHASE_15_AUDIT.md` (from previous audit)
- `PHASE_16_IMPLEMENTATION.md` (this file)

**No unrelated modifications:** The diff for `BookDetailActivity.kt` consists of:
- Phase 12 pre-existing changes (3 hunks: constant, launch method, onActivityResult handler)
- Phase 16 change: 1 hunk adding 5 lines (4 comment + `source.delete()`) after line 523

No other tracked files were modified by this phase. No layouts, resources, Gradle files, Python files, or other Kotlin files were touched.

### 11. Security / Data Safety

| Check | Result |
|---|---|
| Does NOT delete user's original EPUB | ✅ `source` = `_covered.epub`, original is at `.bak` |
| Does NOT delete durable output EPUB | ✅ `finalPath` (output dir copy) is separate from `source` |
| Does NOT delete another book's EPUB | ✅ Path derived from current EPUB only |
| Does NOT delete `.metadata_edit_bak` | ✅ Only `source` (`_covered.epub`) is targeted |
| Does NOT delete `.cover_edit_bak` | ✅ Only `source` (`_covered.epub`) is targeted |
| Does NOT delete `.bak` | ✅ `.bak` is the backup, `_covered.epub` is the output — distinct files |
| Does NOT confuse temp with durable output | ✅ `finishWithResult` receives `finalPath` (output dir), not `source` |

The deletion targets only the local `_covered.epub` working/output copy, and only after successful persistence to the user's output directory.

### 12. Commit / Push Status

- **No commit** made ✅
- **No push** made ✅
- Working tree remains in its existing uncommitted state plus the intended Phase 16 source change and this report file

### 13. Final Verdict

**PHASE 16 IMPLEMENTATION COMPLETE — `_covered.epub` CLEANUP APPLIED**

The minimal one-line cleanup (`source.delete()`) has been added to `BookDetailActivity.replaceCoverWithImage()` after the successful `copyToOutputDir()` call, mirroring the existing Phase 10 cleanup pattern in `MetadataPreviewActivity.applyMetadataAndCoverSafely`. The change is:

- Safe on all paths (success + failure)
- Consistent with the Phase 10 pattern
- Isolated to a single method in a single file
- Does not touch any protected file or invariant
- Verified by 262 passing tests and a successful Android build
