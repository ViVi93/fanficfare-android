import json
import os
import sys
import traceback
import zipfile
import xml.etree.ElementTree as ET

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

_FANFICFARE_AVAILABLE = None
_FANFICFARE_ERROR = None
_FANFICFARE_TRACEBACK = None


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
        from fanficfare.configurable import Configuration
        from fanficfare import adapters
        configuration = Configuration(["test1.com"], "epub")
        configuration.addUrlConfigSection(url)
        adapter = adapters.getAdapter(configuration, url)
        adapter.getStoryMetadataOnly()
        return json.dumps({
            "ok": True,
            "title": adapter.story.getMetadata("title") or "",
            "author": adapter.story.getMetadata("author") or "",
            "chapters": adapter.story.getChapterCount(),
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": "{}: {}".format(type(e).__name__, e), "exception_type": type(e).__name__, "detail": traceback.format_exc()})


def download_story(url, outDir):
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    try:
        from fanficfare.configurable import Configuration
        from fanficfare import adapters, writers
        configuration = Configuration(["test1.com"], "epub")
        configuration.addUrlConfigSection(url)
        adapter = adapters.getAdapter(configuration, url)
        writer = writers.getWriter("epub", configuration, adapter)
        filename = writer.getOutputFileName()
        outpath = os.path.join(outDir, os.path.basename(filename))
        with open(outpath, "wb") as out:
            writer.writeStory(outstream=out)
        stat = os.stat(outpath)
        meta = _extract_epub_metadata(outpath)
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
        return json.dumps({"ok": False, "error": str(e)})


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
            for name in names:
                if name.lower().endswith(".ncx"):
                    try:
                        content = z.read(name).decode("utf-8", errors="ignore")
                        count = content.lower().count("<navpoint ")
                        if count > 0:
                            chapters = count
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


def _get_cover_img(epubPath):
    try:
        with zipfile.ZipFile(epubPath, "r") as z:
            for name in z.namelist():
                if "/cover" in name.lower() or name.lower().endswith("/cover.jpg") or name.lower().endswith("/cover.png"):
                    try:
                        data = z.read(name)
                        mime = "image/jpeg"
                        if name.lower().endswith(".png"):
                            mime = "image/png"
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
        from fanficfare.configurable import Configuration
        from fanficfare import adapters, writers
        source, chaptercount = get_update_data(epubPath)[0:2]
        if not source:
            return json.dumps({"ok": False, "error": "No story URL found in epub"})
        try:
            configuration = Configuration(adapters.getConfigSectionsFor(source), "epub")
        except Exception:
            configuration = Configuration(["test1.com"], "epub")
        configuration.addUrlConfigSection(source)
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
        from fanficfare.configurable import Configuration
        from fanficfare import adapters, writers
        source = get_update_data(epubPath)[0]
        if not source:
            return json.dumps({"ok": False, "error": "No story URL found in epub"})
        try:
            configuration = Configuration(adapters.getConfigSectionsFor(source), "epub")
        except Exception:
            configuration = Configuration(["test1.com"], "epub")
        configuration.addUrlConfigSection(source)
        adapter = adapters.getAdapter(configuration, source)
        url, ch_begin, ch_end = adapters.get_url_chapter_range(source)
        adapter.setChaptersRange(ch_begin, ch_end)
        adapter.getStoryMetadataOnly()
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
