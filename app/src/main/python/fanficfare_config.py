import json
import os
import traceback

SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def get_personal_ini_path():
    return os.path.join(os.path.expanduser("~"), "fanficfare", "personal.ini")


def get_bundled_defaults_path():
    return os.path.join(SRC_DIR, "fanficfare", "defaults.ini")


def build_configuration(url, fileform="epub", overrides=None):
    if not _import_fanficfare():
        raise RuntimeError("FanFicFare not available")
    from fanficfare.configurable import Configuration
    from fanficfare import adapters

    try:
        sections = adapters.getConfigSectionsFor(url)
    except Exception:
        sections = ["test1.com"]

    configuration = Configuration(sections, fileform)

    bundled_defaults = get_bundled_defaults_path()
    if bundled_defaults and os.path.isfile(bundled_defaults):
        try:
            configuration.read(bundled_defaults)
        except Exception:
            pass

    personal_ini = get_personal_ini_path()
    if personal_ini and os.path.isfile(personal_ini):
        try:
            configuration.read(personal_ini)
        except Exception:
            pass

    if overrides:
        for key, value in overrides.items():
            try:
                configuration.set("overrides", key, value)
            except Exception:
                pass

    configuration.addUrlConfigSection(url)

    return configuration


def get_config_status():
    try:
        path = get_personal_ini_path()
        home = os.path.expanduser("~")
        abs_path = os.path.abspath(path)
        exists = bool(path and os.path.isfile(path))
        size = 0
        try:
            if exists:
                size = os.path.getsize(path)
        except Exception:
            pass
        home_dir_names = []
        try:
            home_dir_names = sorted(os.listdir(home)) if os.path.isdir(home) else []
        except Exception:
            pass
        known_dir_names = []
        known_dir = "/data/data/com.example.fanficfare/files/fanficfare"
        try:
            known_dir_names = sorted(os.listdir(known_dir)) if os.path.isdir(known_dir) else []
        except Exception:
            pass
        status = {
            "exists": exists,
            "path": path or "",
            "size": size,
            "modified": 0,
            "parse_error": None,
            "resolved_personal_path": path or "",
            "resolved_exists": exists,
            "resolved_size": size,
            "home_dir": home,
            "abs_personal_path": abs_path,
            "home_exists": os.path.isdir(home),
            "env_home": os.environ.get("HOME", ""),
            "personal_exists": exists,
            "personal_isfile": os.path.isfile(path) if path else False,
            "home_dir_names": home_dir_names,
            "known_dir_names": known_dir_names,
            "storiesonline_section_username": None,
            "storiesonline_section_password_present": False,
            "storiesonline_defaults_username": None,
            "always_login": None,
            "login_test_attempted": False,
            "login_test_error": None,
        }
        if exists:
            try:
                st = os.stat(path)
                status["modified"] = int(st.st_mtime * 1000)
            except Exception:
                pass
            try:
                cfg = __import__(
                    "fanficfare.configurable", fromlist=["Configuration"]
                ).Configuration(["test1.com"], "epub")
                cfg.read(path)
                status["parse_error"] = None
                try:
                    status["storiesonline_section_username"] = cfg.get("storiesonline.net", "username", fallback=None)
                    status["storiesonline_section_password_present"] = bool(cfg.get("storiesonline.net", "password", fallback=None))
                except Exception:
                    pass
                try:
                    status["storiesonline_defaults_username"] = cfg.get("defaults", "username", fallback=None)
                except Exception:
                    pass
                try:
                    status["always_login"] = cfg.get("defaults", "always_login", fallback=None)
                except Exception:
                    pass
            except Exception as e:
                status["parse_error"] = "{}: {}".format(type(e).__name__, e)
        return status
    except Exception as e:
        return {
            "exists": False,
            "path": "",
            "size": 0,
            "modified": 0,
            "parse_error": "{}: {}".format(type(e).__name__, e),
            "resolved_personal_path": "",
            "resolved_exists": False,
            "resolved_size": 0,
            "home_dir": "",
            "abs_personal_path": "",
            "home_exists": False,
            "env_home": os.environ.get("HOME", ""),
            "personal_exists": False,
            "personal_isfile": False,
            "home_dir_names": [],
            "known_dir_names": [],
            "storiesonline_section_username": None,
            "storiesonline_section_password_present": False,
            "storiesonline_defaults_username": None,
            "always_login": None,
            "login_test_attempted": False,
            "login_test_error": None,
        }


def _import_fanficfare():
    global _FANFICFARE_AVAILABLE, _FANFICFARE_ERROR, _FANFICFARE_TRACEBACK
    if "_FANFICFARE_AVAILABLE" not in globals():
        _FANFICFARE_AVAILABLE = None
        _FANFICFARE_ERROR = None
        _FANFICFARE_TRACEBACK = None
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
        _FANFICFARE_AVAILABLE = False
        return False
