import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

_FANFICFARE_AVAILABLE = None
_FANFICFARE_ERROR = None


def _import_fanficfare():
    global _FANFICFARE_AVAILABLE, _FANFICFARE_ERROR
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
        _FANFICFARE_ERROR = str(e)
        _FANFICFARE_AVAILABLE = False
        return False


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
        return json.dumps({"ok": False, "error": str(e)})


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
        for name in z.namelist():
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
                except Exception:
                    pass
                break

        for name in z.namelist():
            if "calibre" in name.lower() or name.endswith(".txt"):
                try:
                    content = z.read(name).decode("utf-8", errors="ignore")
                    for line in content.splitlines():
                        if line.startswith("http://") or line.startswith("https://"):
                            url = line.strip()
                            break
                except Exception:
                    pass

        try:
            source, chaptercount = _get_dcsource_chaptercount(epubPath)
            if source:
                url = source
            if chaptercount:
                chapters = chaptercount
        except Exception:
            pass

        try:
            cover_type, cover_data = _get_cover_img(epubPath)
            if cover_data:
                mime = cover_type or "image/jpeg"
                cover = "data:%s;base64,%s" % (mime, __import__("base64").b64encode(cover_data).decode("ascii"))
        except Exception:
            cover = None

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
                                pass
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
