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
        from fanficfare.configurable import Configurable
        from fanficfare import adapters
        configuration = Configurable("test1.com", None, None)
        configuration.setConfig("url", url)
        adapter = adapters.getAdapter(configuration, url)
        adapter.getStoryMetadataOnly()
        return json.dumps({
            "ok": True,
            "title": adapter.story.title or "",
            "author": adapter.story.author or "",
            "chapters": adapter.story.getChapterCount(),
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": "{}: {}".format(type(e).__name__, e), "exception_type": type(e).__name__, "detail": traceback.format_exc()})


def download_story(url, outDir):
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    try:
        from fanficfare.configurable import Configurable
        from fanficfare import adapters, writers
        configuration = Configurable("test1.com", None, None)
        configuration.setConfig("url", url)
        adapter = adapters.getAdapter(configuration, url)
        writer = writers.getWriter("epub", configuration, adapter)
        filename = writer.getOutputFileName()
        outpath = os.path.join(outDir, os.path.basename(filename))
        with open(outpath, "wb") as out:
            writer.writeStory(outstream=out)
        return json.dumps({
            "ok": True,
            "title": adapter.story.title or filename,
            "path": outpath,
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
        for name in names:
            if name.endswith(".opf"):
                try:
                    opf = z.read(name).decode("utf-8", errors="ignore")
                    root = ET.fromstring(opf)
                    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
                    title_node = root.find(".//dc:title", ns)
                    if title_node is not None and title_node.text:
                        title = title_node.text.strip()
                    author_node = root.find(".//dc:creator", ns)
                    if author_node is not None and author_node.text:
                        author = author_node.text.strip()
                    for meta in root.findall(".//{http://purl.org/dc/elements/1.1/}meta") + root.findall(".//meta"):
                        name_attr = meta.get("name", "") or meta.get("{http://purl.org/dc/elements/1.1/}name", "")
                        content = meta.get("content", "") or ""
                        if "chaptercount" in name_attr.lower() and content.isdigit():
                            chapters = content.toInt()
                        elif name_attr.lower() in {"calibredit", "calibreurl", "calibrecontributor"}:
                            pass
                        elif "url" in name_attr.lower() or "source" in name_attr.lower():
                            if content.startswith("http://") or content.startswith("https://"):
                                url = content.strip()
                except Exception:
                    pass
                break

        for name in names:
            if name.endswith(".txt") or name.endswith(".ncx") or name.lower().startswith("content/"):
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("http://") or stripped.startswith("https://"):
                            url = stripped
                            break
                    if url:
                        break
                except Exception:
                    pass

        for name in names:
            if name.lower().endswith(".ncx"):
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    chaptercount = content.lower().split("totalpagecount")[1].split("\"")[1]
                    chapters = int(chaptercount) if chaptercount.isdigit() else chapters
                except Exception:
                    pass

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
        with zipfile.ZipFile(epubPath, "r") as z:
            for name in z.namelist():
                if "calibre" in name.lower() or name.endswith(".txt"):
                    try:
                        content = z.read(name).decode("utf-8", errors="ignore")
                        source = None
                        chaptercount = 0
                        for line in content.splitlines():
                            if "DateThis" in line or "chaptercount" in line.lower():
                                m = re.search(r'chaptercount["\s:=]+(\d+)', line, re.IGNORECASE)
                                if m:
                                    chaptercount = int(m.group(1))
                            if line.startswith("http://") or line.startswith("https://"):
                                source = line.strip()
                        return source or "", chaptercount
                    except Exception:
                        pass
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
                    meta["modified"] = stat.st_mtime
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
        source, _ = _get_dcsource_chaptercount(epubPath)
        if not source:
            return json.dumps({"ok": False, "error": "No story URL found in epub"})
        from fanficfare.configurable import Configurable
        from fanficfare import adapters, writers
        configuration = Configurable("test1.com", None, None)
        configuration.setConfig("url", source)
        adapter = adapters.getAdapter(configuration, source)
        writer = writers.getWriter("epub", configuration, adapter)
        filename = writer.getOutputFileName()
        outpath = os.path.join(outDir, os.path.basename(filename))
        with open(outpath, "wb") as out:
            writer.writeStory(outstream=out, metaonly=False, update=True, oldfile=epubPath)
        return json.dumps({
            "ok": True,
            "title": adapter.story.title or filename,
            "path": outpath,
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def force_download_from_epub(epubPath, outDir):
    if not _import_fanficfare():
        return json.dumps({"ok": False, "error": "FanFicFare not available", "detail": _FANFICFARE_ERROR or ""})
    try:
        source, _ = _get_dcsource_chaptercount(epubPath)
        if not source:
            return json.dumps({"ok": False, "error": "No story URL found in epub"})
        return download_story(source, outDir)
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
