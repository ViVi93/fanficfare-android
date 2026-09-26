# Third-party notices

Aharana is distributed under the **GNU General Public License v3.0
or later** (see [`LICENSE`](LICENSE)). It bundles or links against the following
third-party components, whose licenses are reproduced or referenced below.

---

## 1. FanFicFare — Apache License 2.0

- **Component:** the fanfiction download engine and site adapters
- **Location in this repo:** `app/src/main/python/fanficfare/`
- **Version bundled:** 4.60.0 (upstream tag `v4.60.0`, commit `86832ac`)
- **Upstream:** <https://github.com/JimmXinu/FanFicFare>
- **Copyright:** Jim Miller and the FanFicFare contributors
- **License:** Apache License 2.0 — full text in
  [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt)

Upstream's own `LICENSE` states that the `fanficfare` and `webservice` code is under
the Apache License, while the Calibre plugin (which derives from other GPLv3 code)
is additionally GPLv3. Only the engine/adapters are bundled here — the Calibre plugin
is **not** included.

The Android app applies a small number of Chaquopy/Android compatibility patches to
the engine. Per Apache-2.0 §4(b), those modified files carry notices of the change;
the exact set of patched files is documented in
[`docs/FANFICFARE.md`](docs/FANFICFARE.md) ("Android-specific modifications").

### Apache-2.0 notice

```
Copyright (c) Jim Miller and the FanFicFare contributors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

## 2. EPUB editing modules — GPL v3

- **Components:** `app/src/main/python/epub_editor.py`, `epub_container.py`,
  `epub_xml.py`, `epub_merge.py`
- **License:** GNU General Public License v3 (declared in each file's
  `__license__` header)
- **Provenance:** a standard-library-only reimplementation of EPUB OPF metadata and
  cover editing, inspired by **calibre**'s `epub.py` / `opf3.py` handling. calibre is
  licensed under the GPLv3; these modules inherit that license.

Because these GPLv3 modules are linked into the application, the application as a
whole is distributed under the GPLv3.

---

## 3. Chaquopy — MIT License

- **Component:** the Python-on-Android runtime and Gradle plugin
- **License:** MIT — see <https://chaquo.com/chaquopy/license/>
- The Chaquopy runtime, its CPython build, and any Java/Kotlin libraries it pulls in
  retain their own licenses, which apply to the built APK.

---

## 4. AndroidX, Material Components, Kotlin

Bundled at build time via Gradle; all are licensed under the **Apache License 2.0**
(AndroidX and Material Components) or the **Apache License 2.0** (Kotlin and the
Kotlin standard library).

| Artifact | License |
|---|---|
| `androidx.*` (appcompat, recyclerview, constraintlayout, lifecycle, room, work, documentfile, swiperefreshlayout) | Apache-2.0 |
| `com.google.android.material:material` | Apache-2.0 |
| `org.jetbrains.kotlin*` / kotlinx-coroutines | Apache-2.0 |

---

## 5. Python packages bundled into the APK

Chaquopy installs these at build time (see the `chaquopy { pip { … } }` block in
`app/build.gradle`); each retains its upstream license inside the APK:

| Package | License |
|---|---|
| `beautifulsoup4` | MIT |
| `chardet` | LGPL-2.1 |
| `html5lib` | MIT |
| `html2text` | GPL-3.0 |
| `cloudscraper` | MIT |
| `requests` | Apache-2.0 |
| `requests-file` | Apache-2.0 |
| `urllib3` | MIT |
| `Brotli` | MIT |

> Licenses listed above reflect the upstream projects. Before publishing a build,
> verify the exact licenses of the pinned versions that Chaquopy packages, and ship
> the corresponding license texts if a package requires it.

---

## Notes for redistributors

- If you distribute a built APK or a modified source tree, keep this file, `LICENSE`,
  `licenses/Apache-2.0.txt`, and the upstream copyright notices intact.
- If you modify any file under `app/src/main/python/fanficfare/`, add a prominent
  notice stating that you changed it (Apache-2.0 §4(b)).
- If you modify any GPLv3 file, the GPLv3 requires you to release the modified source
  under the GPLv3 as well.

*This document is provided for attribution convenience and is not legal advice.*