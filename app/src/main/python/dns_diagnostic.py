"""Temporary DNS diagnostic harness for Android/Chaquopy investigation."""
import json
import socket
import time


def _safe_getaddrinfo(host, port, attempts=1, delay=0.0):
    results = []
    for i in range(1, attempts + 1):
        t0 = time.time()
        try:
            print("[dns_diagnostic] getaddrinfo start host={} port={} attempt={}".format(host, port, i))
            infos = socket.getaddrinfo(host, port)
            elapsed = time.time() - t0
            ipv4 = sorted({info[4][0] for info in infos if info[0] == socket.AF_INET})
            ipv6 = sorted({info[4][0] for info in infos if info[0] == socket.AF_INET6})
            results.append({
                "attempt": i,
                "success": True,
                "elapsed_ms": int(elapsed * 1000),
                "ipv4": ipv4,
                "ipv6": ipv6,
                "family_count": len(infos),
                "exception": None,
                "errno": None,
            })
            print("[dns_diagnostic] getaddrinfo success host={} attempt={} elapsed_ms={} families={}".format(
                host, i, int(elapsed * 1000), len(infos)))
        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                "attempt": i,
                "success": False,
                "elapsed_ms": int(elapsed * 1000),
                "ipv4": [],
                "ipv6": [],
                "family_count": 0,
                "exception": type(e).__name__,
                "errno": getattr(e, "errno", None),
                "msg": str(e),
            })
            print("[dns_diagnostic] getaddrinfo exception host={} attempt={} exception={} errno={} msg={}".format(
                host, i, type(e).__name__, getattr(e, "errno", None), str(e)))
        if delay > 0 and i < attempts:
            time.sleep(delay)
    return results


def run_dns_diagnostics():
    host = "www.literotica.com"
    port = 443
    comparison_host = "github.com"
    try:
        print("[dns_diagnostic] ENTER target={} comparison={}".format(host, comparison_host))
        payload = {
            "ok": True,
            "target": {
                "host": host,
                "port": port,
                "repeated_5": _safe_getaddrinfo(host, port, attempts=5, delay=0.0),
            },
            "comparison": {
                "host": comparison_host,
                "port": 443,
                "repeated_5": _safe_getaddrinfo(comparison_host, port, attempts=5, delay=0.0),
            },
        }
        print("[dns_diagnostic] COMPLETE")
        return json.dumps(payload)
    except Exception as e:
        msg = "{}: {}".format(type(e).__name__, e)
        print("[dns_diagnostic] ERROR {}".format(msg))
        return json.dumps({"ok": False, "error": msg})
