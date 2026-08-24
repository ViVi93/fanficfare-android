import json
import os
import sys
import tempfile
import time
import traceback
import zipfile
import xml.etree.ElementTree as ET

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from fanficfare_config import (
    get_config_status,
    get_personal_ini_path,
    get_bundled_defaults_path,
    build_configuration,
    set_config_dir as _cfg_set_config_dir,
    test_configuration as _cfg_test_configuration,
    _get_fanficfare_version as _cfg_get_fanficfare_version,
)

_FANFICFARE_AVAILABLE = None
_FANFICFARE_ERROR = None
_FANFICFARE_TRACEBACK = None
_DOWNLOAD_DEBUG_PATH = os.path.join(tempfile.gettempdir(), "fanficfare_download_debug.log")


def _download_debug_write(line):
    try:
        with open(_DOWNLOAD_DEBUG_PATH, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(time.strftime("%H:%M:%S"), line))
    except Exception:
        pass


def _download_debug_clear():
    try:
        with open(_DOWNLOAD_DEBUG_PATH, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass


def _download_debug_read():
    try:
        with open(_DOWNLOAD_DEBUG_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _import_fanficfare():
    global _FANFICFARE_AVAILABLE, _FANFICFARE_ERROR, _FANFICFARE_TRACEBACK
    if _FANFICFARE_AVAILABLE is not None:
        return _FANFICFARE_AVAILABLE
    try:
        from fanficfare import adapters
        from fanficfare.configurable import Configurable
        from fanficfare import writers
        from fanficfare.epubutils import get_dcsource_chaptercount, get_update_data, get_cover_img
        _FANFICFARE_AVAILABLE = True
        return True
    except Exception as e:
        _FANFICFARE_ERROR = "{}: {}".format(type(e).__name__, e)
        _FANFICFARE_TRACEBACK = traceback.format_exc()
        print("FANFICFARE_IMPORT_ERROR: " + _FANFICFARE_ERROR)
        print(_FANFICFARE_TRACEBACK)
        _FANFICFARE_AVAILABLE = False
        return False


def diagnose_fanficfare_imports():
    global _FANFICFARE_ERROR, _FANFICFARE_TRACEBACK
    results = []
    tests = [
        ("import requests", "import requests"),
        ("import requests_file", "import requests_file"),
        ("import bs4", "import bs4"),
        ("import fanficfare", "import fanficfare"),
        ("from fanficfare import adapters", "from fanficfare import adapters"),
        ("from fanficfare.configurable import Configurable", "from fanficfare.configurable import Configurable"),
        ("from fanficfare import writers", "from fanficfare import writers"),
        ("from fanficfare.epubutils import get_dcsource_chaptercount, get_update_data, get_cover_img", "from fanficfare.epubutils import get_dcsource_chaptercount, get_update_data, get_cover_img"),
        ("import apsw", "import apsw"),
    ]
    for label, stmt in tests:
        try:
            exec(stmt, globals())
            results.append({"test": label, "ok": True})
        except Exception as e:
            tb = traceback.format_exc()
            results.append({
                "test": label,
                "ok": False,
                "error_type": type(e).__name__,
                "error": str(e),
                "traceback": tb,
            })
    return json.dumps({"ok": True, "results": results})


def get_fanficfare_version():
    try:
        return _cfg_get_fanficfare_version() or ""
    except Exception:
        return ""


def set_config_dir(path):
    try:
        _cfg_set_config_dir(path)
    except Exception:
        pass


def test_configuration(url):
    try:
        return _cfg_test_configuration(url)
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error_code": "UNKNOWN",
            "message": str(e),
            "detail": "{}: {}".format(type(e).__name__, e),
        })


def get_login_status(url):
    try:
        from fanficfare import adapters
        sections = adapters.getConfigSectionsFor(url)
        configuration = build_configuration(url, "epub")
        username_present = False
        password_present = False
        matched_section = None
        login_keys = []
        always_login = None
        for section in sections:
            try:
                if configuration.has_section(section):
                    matched_section = section
                    options = configuration.options(section)
                    for key in options:
                        lowered = key.lower()
                        login_keys.append(key)
                        if lowered == "username":
                            username_present = bool(configuration.get(section, key, fallback=None))
                        elif lowered == "password":
                            password_present = bool(configuration.get(section, key, fallback=None))
                if username_present and password_present:
                    break
            except Exception:
                pass
        try:
            always_login = configuration.get("defaults", "always_login", fallback=None)
        except Exception:
            pass
        site = None
        try:
            found = adapters._get_class_for(url)
            if found and found[0]:
                site = found[0].getSiteDomain()
        except Exception:
            pass
        return json.dumps({
            "ok": True,
            "site": site,
            "sections": sections,
            "matched_section": matched_section,
            "username_present": username_present,
            "password_present": password_present,
            "always_login": always_login,
            "login_keys": login_keys,
        })
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error": "{}: {}".format(type(e).__name__, e),
            "sections": [],
            "personal_exists": os.path.isfile(get_personal_ini_path()) if get_personal_ini_path() else False,
        })


def get_literotica_config_status(url):
    try:
        from fanficfare import adapters
        sections = adapters.getConfigSectionsFor(url)
        configuration = build_configuration(url, "epub")
        adapter = adapters.getAdapter(configuration, url)
        cfg_value = adapter.getConfig("is_adult", default=False)
        raw_value = None
        matched_section = None
        for section in sections:
            try:
                if configuration.has_section(section):
                    raw_value = configuration.get(section, "is_adult", fallback=None)
                    matched_section = section
                    break
            except Exception:
                continue
        return json.dumps({
            "ok": True,
            "sections": sections,
            "matched_section": matched_section,
            "key": "is_adult",
            "raw_present": raw_value is not None,
            "raw_value": raw_value,
            "configuration_value": cfg_value,
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": "{}: {}".format(type(e).__name__, e)})


def list_sites():
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    try:
        from fanficfare import adapters
        sites = []
        for site, examples in adapters.getSiteExamples():
            sites.append({"site": site, "examples": examples[:3]})
        return json.dumps({"ok": True, "sites": sites})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def get_metadata(url):
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    try:
        configuration = build_configuration(url, "epub", overrides={"include_images": "coveronly"})
        from fanficfare import adapters
        adapter = adapters.getAdapter(configuration, url)
        adapter.getStoryMetadataOnly()
        return json.dumps({
            "ok": True,
            "title": adapter.story.getMetadata("title") or "",
            "author": adapter.story.getMetadata("author") or "",
            "chapters": adapter.story.getChapterCount(),
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "exception_type": type(e).__name__, "detail": traceback.format_exc()})


def download_story(url, outDir):
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    _download_debug_clear()
    try:
        _download_debug_write("download_story ENTER url={}".format(url))
        from fanficfare import adapters, writers
        _download_debug_write("download_story configuration_start")
        t0 = time.time()
        configuration = build_configuration(url, "epub", overrides={"include_images": "true"})
        _download_debug_write("download_story configuration_ready elapsed={:.3f}s".format(time.time() - t0))
        try:
            cfg = configuration.get("defaults", "is_adult")
        except Exception:
            cfg = None
        _download_debug_write("download_story configuration_is_adult={}".format(cfg))
        t0 = time.time()
        _download_debug_write("download_story adapter_start")
        adapter = adapters.getAdapter(configuration, url)
        _download_debug_write("download_story adapter_ready elapsed={:.3f}s".format(time.time() - t0))
        _download_debug_write("download_story writer_start")
        t0 = time.time()
        writer = writers.getWriter("epub", configuration, adapter)
        _download_debug_write("download_story writer_ready elapsed={:.3f}s".format(time.time() - t0))
        filename = writer.getOutputFileName()
        outpath = os.path.join(outDir, os.path.basename(filename))
        _download_debug_write("download_story fanficfare_call_start")
        t0 = time.time()
        with open(outpath, "wb") as out:
            writer.writeStory(outstream=out)
        _download_debug_write("download_story fanficfare_call_returned elapsed={:.3f}s".format(time.time() - t0))
        stat = os.stat(outpath)
        meta = _extract_epub_metadata(outpath)
        _download_debug_write("download_story RETURN")
        return json.dumps({
            "ok": True,
            "title": meta.get("title") or adapter.story.getMetadata("title") or filename,
            "author": meta.get("author") or adapter.story.getMetadata("author") or "",
            "chapters": meta.get("chapters") or adapter.story.getChapterCount() or 0,
            "cover": meta.get("cover") or "",
            "url": meta.get("url") or url,
            "path": outpath,
            "modified": int(stat.st_mtime * 1000),
            "size": stat.st_size,
        })
    except Exception as e:
        _download_debug_write("download_story EXCEPTION type={} msg={}".format(type(e).__name__, e))
        return json.dumps({
            "ok": False,
            "error": str(e),
            "exception_type": type(e).__name__,
            "detail": traceback.format_exc(),
        })
def _extract_epub_metadata(epubPath):
    title = os.path.basename(epubPath).replace(".epub", "").replace("_", " ")
    author = ""
    url = ""
    chapters = 0
    cover = None

    with zipfile.ZipFile(epubPath, "r") as z:
        names = z.namelist()
        opf_name = None
        for name in names:
            if name.endswith(".opf"):
                opf_name = name
                break
        if opf_name:
            try:
                opf = z.read(opf_name).decode("utf-8", errors="ignore")
                root = ET.fromstring(opf)
                ns = {"dc": "http://purl.org/dc/elements/1.1/", "opf": "http://www.idpf.org/2007/opf/"}
                title_node = root.find(".//dc:title", ns)
                if title_node is not None and title_node.text:
                    title = title_node.text.strip()
                author_node = root.find(".//dc:creator", ns)
                if author_node is not None and author_node.text:
                    author = author_node.text.strip()
                manifest = None
                for elem in root.iter():
                    if elem.tag.endswith("manifest"):
                        manifest = elem
                        break
                for meta in root.findall(".//{http://purl.org/dc/elements/1.1/}meta") + root.findall(".//{http://www.idpf.org/2007/opf/}meta") + root.findall(".//meta"):
                    name_attr = meta.get("name", "") or meta.get("{http://purl.org/dc/elements/1.1/}name", "") or meta.get("{http://www.idpf.org/2007/opf/}name", "")
                    content = meta.get("content", "") or ""
                    if "chaptercount" in name_attr.lower() and content.isdigit():
                        chapters = int(content)
                    elif name_attr.lower() in {"calibredit", "calibreurl", "calibrecontributor"}:
                        pass
                    elif name_attr.lower() == "cover":
                        cover_id = content.strip()
                        if cover_id and manifest is not None:
                            for item in manifest:
                                if item.tag.endswith("item") and item.get("id") == cover_id:
                                    href = item.get("href", "")
                                    media_type = item.get("media-type", "")
                                    if href and media_type.startswith("image/"):
                                        try:
                                            data = z.read(href)
                                            cover = "data:%s;base64,%s" % (media_type, __import__("base64").b64encode(data).decode("ascii"))
                                        except Exception:
                                            pass
                                        break
                    elif "url" in name_attr.lower() or "source" in name_attr.lower():
                        if content.startswith("http://") or content.startswith("https://"):
                            url = content.strip()
                if not url:
                    ident = root.find(".//dc:identifier", ns)
                    if ident is not None and ident.text:
                        text = ident.text.strip()
                        if text.startswith("http://") or text.startswith("https://"):
                            url = text
                if not url:
                    source = root.find(".//dc:source", ns)
                    if source is not None and source.text:
                        text = source.text.strip()
                        if text.startswith("http://") or text.startswith("https://"):
                            url = text
            except Exception:
                pass

        if chapters == 0:
            has_title_page = any(name.lower().endswith("/title_page.xhtml") or name.lower() == "oebps/title_page.xhtml" for name in names)
            for name in names:
                if name.lower().endswith(".ncx"):
                    try:
                        content = z.read(name).decode("utf-8", errors="ignore")
                        count = content.lower().count("<navpoint ")
                        if count > 0:
                            chapters = max(0, count - 1) if has_title_page else count
                    except Exception:
                        pass

        if cover is None:
            for name in names:
                lower = name.lower()
                if lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    base = lower.split("/")[-1].replace(".jpg", "").replace(".jpeg", "").replace(".png", "").replace(".gif", "").replace(".webp", "")
                    if base in {"cover", "coverimage"} or lower.count("/") == 1 and "cover" in base:
                        try:
                            data = z.read(name)
                            mime = "image/jpeg"
                            if lower.endswith(".png"):
                                mime = "image/png"
                            elif lower.endswith(".gif"):
                                mime = "image/gif"
                            elif lower.endswith(".webp"):
                                mime = "image/webp"
                            cover = "data:%s;base64,%s" % (mime, __import__("base64").b64encode(data).decode("ascii"))
                            break
                        except Exception:
                            pass

        if cover is None:
            try:
                manifest = None
                if opf_name:
                    try:
                        opf_bytes = z.read(opf_name)
                        root_for_manifest = ET.fromstring(opf_bytes)
                        for elem in root_for_manifest.iter():
                            if elem.tag.endswith("manifest"):
                                manifest = elem
                                break
                    except Exception:
                        pass
                if manifest is None:
                    for name in names:
                        if name.lower().endswith(".opf"):
                            try:
                                opf_bytes = z.read(name)
                                root_for_manifest = ET.fromstring(opf_bytes)
                                for elem in root_for_manifest.iter():
                                    if elem.tag.endswith("manifest"):
                                        manifest = elem
                                        break
                                if manifest is not None:
                                    break
                            except Exception:
                                pass
                if manifest is not None:
                    for item in manifest:
                        if item.tag.endswith("item"):
                            href = item.get("href", "")
                            media_type = item.get("media-type", "")
                            if media_type.startswith("image/"):
                                try:
                                    data = z.read(href)
                                    cover = "data:%s;base64,%s" % (media_type, __import__("base64").b64encode(data).decode("ascii"))
                                    break
                                except Exception:
                                    pass
            except Exception:
                pass

    return {
        "title": title,
        "author": author,
        "url": url,
        "chapters": chapters,
        "cover": cover,
    }


def _get_dcsource_chaptercount(epubPath):
    try:
        import re
        meta = _extract_epub_metadata(epubPath)
        source = meta.get("url") or ""
        chaptercount = meta.get("chapters") or 0
        if not source:
            with zipfile.ZipFile(epubPath, "r") as z:
                for name in z.namelist():
                    if "calibre" in name.lower() or name.endswith(".txt"):
                        try:
                            content = z.read(name).decode("utf-8", errors="ignore")
                            for line in content.splitlines():
                                if line.startswith("http://") or line.startswith("https://"):
                                    source = line.strip()
                                    break
                            if source:
                                break
                        except Exception:
                            pass
        return source or "", int(chaptercount)
    except Exception:
        pass
    return "", 0


def get_cover_from_epub(epubPath):
    try:
        mime, data = _get_cover_img(epubPath)
        if data is None:
            return json.dumps({"ok": True, "cover": ""})
        encoded = __import__("base64").b64encode(data).decode("ascii")
        return json.dumps({
            "ok": True,
            "cover": "data:%s;base64,%s" % (mime, encoded),
            "original_bytes": len(data),
            "jpeg_bytes": len(data),
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e), "cover": ""})


def _get_cover_img(epubPath):
    try:
        with zipfile.ZipFile(epubPath, "r") as z:
            for name in z.namelist():
                lower = name.lower()
                if lower.endswith((".jpg", ".jpeg", ".png")) and ("/cover" in lower or lower.endswith("/cover.jpg") or lower.endswith("/cover.png")):
                    try:
                        data = z.read(name)
                        mime = "image/png" if lower.endswith(".png") else "image/jpeg"
                        return mime, data
                    except Exception:
                        pass
    except Exception:
        pass
    return None, None


def scan_epub_dir(directory):
    try:
        books = []
        for root, dirs, files in os.walk(directory):
            for f in files:
                if f.lower().endswith(".epub"):
                    path = os.path.join(root, f)
                    stat = os.stat(path)
                    meta = _extract_epub_metadata(path)
                    meta["path"] = path
                    meta["size"] = stat.st_size
                    meta["modified"] = int(stat.st_mtime * 1000)
                    books.append(meta)
        return json.dumps({"ok": True, "books": books})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "books": []})


def extract_epub_metadata(epubPath):
    try:
        return _extract_epub_metadata(epubPath)
    except Exception as e:
        return {
            "title": os.path.basename(epubPath).replace(".epub", ""),
            "author": "",
            "url": "",
            "chapters": 0,
            "cover": None,
        }


def get_epub_update_url(epubPath):
    try:
        source, chaptercount = _get_dcsource_chaptercount(epubPath)
        return json.dumps({
            "ok": True,
            "url": source or "",
            "chapters": chaptercount or 0,
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def delete_epub(epubPath):
    try:
        os.remove(epubPath)
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def update_epub_from_path(epubPath, outDir):
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    try:
        from fanficfare.epubutils import get_update_data, get_dcsource_chaptercount
        from fanficfare import adapters, writers
        from fanficfare_config import build_configuration
        source, chaptercount = get_update_data(epubPath)[0:2]
        if not source:
            return json.dumps({"ok": False, "error": "No story URL found in epub"})
        configuration = build_configuration(source, "epub", overrides={"include_images": "coveronly"})
        adapter = adapters.getAdapter(configuration, source)
        url, ch_begin, ch_end = adapters.get_url_chapter_range(source)
        adapter.setChaptersRange(ch_begin, ch_end)
        adapter.getStoryMetadataOnly()
        urlchaptercount = adapter.getStoryMetadataOnly().getChapterCount()
        if chaptercount == urlchaptercount:
            return json.dumps({"ok": True, "skipped": True, "reason": "already current", "url": source, "chapters": chaptercount})
        elif chaptercount > urlchaptercount:
            return json.dumps({"ok": True, "skipped": True, "reason": "local has more chapters than source", "url": source, "chapters": chaptercount})
        elif chaptercount == 0:
            return json.dumps({"ok": False, "error": "existing epub has 0 recognizable chapters"})
        else:
            (_,
             _,
             adapter.oldchapters,
             adapter.oldimgs,
             adapter.oldcover,
             adapter.calibrebookmark,
             adapter.logfile,
             adapter.oldchaptersmap,
             adapter.oldchaptersdata) = get_update_data(epubPath)[0:9]
            writer = writers.getWriter("epub", configuration, adapter)
            filename = writer.getOutputFileName()
            outpath = os.path.join(outDir, os.path.basename(filename))
            with open(outpath, "wb") as out:
                writer.writeStory(outstream=out, metaonly=False)
            stat = os.stat(outpath)
            meta = _extract_epub_metadata(outpath)
            return json.dumps({
                "ok": True,
                "title": meta.get("title") or adapter.story.getMetadata("title") or filename,
                "author": meta.get("author") or adapter.story.getMetadata("author") or "",
                "chapters": meta.get("chapters") or adapter.story.getChapterCount() or 0,
                "cover": meta.get("cover") or "",
                "url": source,
                "path": outpath,
                "modified": int(stat.st_mtime * 1000),
                "size": stat.st_size,
            })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def force_download_from_epub(epubPath, outDir):
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    try:
        from fanficfare.epubutils import get_update_data
        from fanficfare import adapters, writers
        from fanficfare_config import build_configuration
        source = get_update_data(epubPath)[0]
        if not source:
            return json.dumps({"ok": False, "error": "No story URL found in epub"})
        configuration = build_configuration(source, "epub", overrides={"include_images": "coveronly"})
        adapter = adapters.getAdapter(configuration, source)
        url, ch_begin, ch_end = adapters.get_url_chapter_range(source)
        adapter.setChaptersRange(ch_begin, ch_end)
        adapter.getStoryMetadataOnly()
        writer = writers.getWriter("epub", configuration, adapter)
        filename = writer.getOutputFileName()
        outpath = os.path.join(outDir, os.path.basename(filename))
        out_exists_before = False
        out_size_before = None
        out_mtime_before = None
        try:
            if os.path.exists(outpath):
                st = os.stat(outpath)
                out_exists_before = True
                out_size_before = st.st_size
                out_mtime_before = int(st.st_mtime * 1000)
        except Exception:
            pass
        with open(outpath, "wb") as out:
            writer.writeStory(outstream=out, metaonly=False)
        stat = os.stat(outpath)
        meta = _extract_epub_metadata(outpath)
        out_exists_after = os.path.exists(outpath)
        out_size_after = stat.st_size
        out_mtime_after = int(stat.st_mtime * 1000)
        return json.dumps({
            "ok": True,
            "title": meta.get("title") or adapter.story.getMetadata("title") or filename,
            "author": meta.get("author") or adapter.story.getMetadata("author") or "",
            "chapters": meta.get("chapters") or adapter.story.getChapterCount() or 0,
            "cover": meta.get("cover") or "",
            "url": source,
            "path": outpath,
            "modified": out_mtime_after,
            "size": out_size_after,
            "file": {
                "exists_before": out_exists_before,
                "size_before": out_size_before,
                "mtime_before": out_mtime_before,
                "exists_after": out_exists_after,
                "size_after": out_size_after,
                "mtime_after": out_mtime_after,
                "changed": out_exists_before and (out_size_before != out_size_after or out_mtime_before != out_mtime_after),
            },
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def save_library_index(indexPath, booksJson):
    try:
        with open(indexPath, "w", encoding="utf-8") as f:
            f.write(booksJson)
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def load_library_index(indexPath):
    try:
        if not os.path.exists(indexPath):
            return json.dumps({"ok": True, "books": []})
        with open(indexPath, "r", encoding="utf-8") as f:
            data = f.read()
        return json.dumps({"ok": True, "books": json.loads(data).get("books", [])})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "books": []})


def get_fanficfare_error():
    if _FANFICFARE_ERROR is None:
        return ""
    return str(_FANFICFARE_ERROR)


def clear_download_debug():
    _download_debug_clear()
    return json.dumps({"ok": True})


def read_download_debug():
    text = _download_debug_read()
    return json.dumps({"ok": True, "log": text})


def run_dns_diagnostics():
    print("[fanficfare_bridge] run_dns_diagnostics ENTER")
    try:
        from dns_diagnostic import run_dns_diagnostics
        result = run_dns_diagnostics()
        print("[fanficfare_bridge] run_dns_diagnostics RETURN len={}".format(len(result) if result else 0))
        return result
    except Exception as e:
        msg = "{}: {}".format(type(e).__name__, e)
        print("[fanficfare_bridge] run_dns_diagnostics ERROR {}".format(msg))
        return json.dumps({"ok": False, "error": msg})
