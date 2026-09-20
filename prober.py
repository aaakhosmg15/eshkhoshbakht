"""
تست واقعی اتصال کانفیگ‌ها با هسته Xray.

برای هر کانفیگ:
  1) یک کلاینت موقت Xray با outbound همان کانفیگ ساخته می‌شود
  2) از طریق SOCKS محلی یک HTTP(S) به آدرس تست زده می‌شود
  3) موفق = واقعاً تونل کار می‌کند (نه فقط پورت باز)

اگر باینری xray در PATH نباشد، همه نتایج با خطای واضح برمی‌گردند
(پینگ TCP فعلی دست‌نخورده می‌ماند).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from config_parser import _b64decode, get_host_port, get_protocol, get_remark

logger = logging.getLogger(__name__)

# محدودیت همزمانی — هر تست یک پروسه xray است
PROBE_CONCURRENCY = int(os.environ.get("PROBE_CONCURRENCY", "3"))
PROBE_TIMEOUT = float(os.environ.get("PROBE_TIMEOUT", "18"))
# آدرس‌های تست (اولین موفق کافی است)
PROBE_URLS = [
    u.strip()
    for u in os.environ.get(
        "PROBE_URLS",
        "https://www.gstatic.com/generate_204,https://cp.cloudflare.com/,http://captive.apple.com/",
    ).split(",")
    if u.strip()
]

_XRAY_BIN: str | None = None


def find_xray() -> str | None:
    global _XRAY_BIN
    if _XRAY_BIN is not None:
        return _XRAY_BIN or None
    for name in ("xray", "xray-linux-amd64", "Xray"):
        p = shutil.which(name)
        if p:
            _XRAY_BIN = p
            return p
    # مسیرهای رایج داخل Docker
    for p in ("/usr/local/bin/xray", "/usr/bin/xray", "/app/bin/xray"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            _XRAY_BIN = p
            return p
    _XRAY_BIN = ""
    return None


def xray_available() -> bool:
    return find_xray() is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _qs(raw_main: str) -> dict[str, str]:
    parsed = urlparse(raw_main)
    out: dict[str, str] = {}
    if parsed.query:
        for k, v in parse_qs(parsed.query, keep_blank_values=True).items():
            out[k.lower()] = v[0] if v else ""
    return out


def _stream_settings_from_qs(qs: dict[str, str]) -> dict:
    network = (qs.get("type") or qs.get("network") or "tcp").lower()
    security = (qs.get("security") or "").lower()
    if security in ("", "none", "0"):
        security = "none"

    stream: dict = {"network": network, "security": security}

    if network in ("ws", "websocket"):
        stream["network"] = "ws"
        stream["wsSettings"] = {
            "path": qs.get("path") or "/",
            "headers": {},
        }
        host = qs.get("host") or qs.get("authority") or ""
        if host:
            stream["wsSettings"]["headers"]["Host"] = host
    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": qs.get("servicename") or qs.get("serviceName") or qs.get("path") or "",
        }
        if qs.get("mode") == "multi":
            stream["grpcSettings"]["multiMode"] = True
    elif network in ("http", "h2", "httpupgrade"):
        if network == "httpupgrade":
            stream["network"] = "httpupgrade"
            stream["httpupgradeSettings"] = {
                "path": qs.get("path") or "/",
                "host": qs.get("host") or "",
            }
        else:
            stream["network"] = "h2"
            stream["httpSettings"] = {
                "path": qs.get("path") or "/",
                "host": [qs.get("host")] if qs.get("host") else [],
            }
    elif network == "splithttp":
        stream["network"] = "splithttp"
        stream["splithttpSettings"] = {
            "path": qs.get("path") or "/",
            "host": qs.get("host") or "",
        }
    else:
        stream["network"] = "tcp"
        header_type = (qs.get("headertype") or qs.get("headerType") or "none").lower()
        if header_type and header_type != "none":
            stream["tcpSettings"] = {"header": {"type": header_type}}

    if security in ("tls", "reality"):
        tls: dict = {
            "serverName": qs.get("sni") or qs.get("host") or qs.get("peer") or "",
            "allowInsecure": (qs.get("allowinsecure") or qs.get("insecure") or "0")
            in ("1", "true", "yes"),
        }
        if qs.get("fp") or qs.get("fingerprint"):
            tls["fingerprint"] = qs.get("fp") or qs.get("fingerprint")
        if qs.get("alpn"):
            tls["alpn"] = [a.strip() for a in qs["alpn"].split(",") if a.strip()]
        if security == "reality":
            stream["security"] = "reality"
            stream["realitySettings"] = {
                "serverName": tls.get("serverName") or "",
                "fingerprint": tls.get("fingerprint") or "chrome",
                "publicKey": qs.get("pbk") or qs.get("publickey") or "",
                "shortId": qs.get("sid") or qs.get("shortid") or "",
                "spiderX": qs.get("spx") or "/",
            }
        else:
            stream["tlsSettings"] = tls

    return stream


def build_xray_outbound(raw: str) -> dict | None:
    """ساخت outbound تکی Xray از URI کانفیگ. None = پشتیبانی نمی‌شود."""
    raw = (raw or "").strip()
    if not raw or "://" not in raw:
        return None
    proto = get_protocol(raw).lower()
    main = raw.split("#", 1)[0]

    if proto == "vmess":
        try:
            data = json.loads(_b64decode(raw[len("vmess://") :]).decode("utf-8", errors="ignore"))
        except Exception:
            return None
        host = data.get("add") or ""
        try:
            port = int(data.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not host or not port:
            return None
        network = (data.get("net") or "tcp").lower()
        security = (data.get("tls") or "").lower() or "none"
        stream: dict = {"network": network, "security": security if security != "" else "none"}
        if network in ("ws", "websocket"):
            stream["network"] = "ws"
            stream["wsSettings"] = {
                "path": data.get("path") or "/",
                "headers": {"Host": data.get("host") or ""} if data.get("host") else {},
            }
        elif network == "grpc":
            stream["grpcSettings"] = {"serviceName": data.get("path") or ""}
        elif network in ("h2", "http"):
            stream["network"] = "h2"
            stream["httpSettings"] = {
                "path": data.get("path") or "/",
                "host": [data.get("host")] if data.get("host") else [],
            }
        if security in ("tls", "xtls"):
            stream["security"] = "tls"
            stream["tlsSettings"] = {
                "serverName": data.get("sni") or data.get("host") or host,
                "allowInsecure": False,
            }
            if data.get("fp"):
                stream["tlsSettings"]["fingerprint"] = data.get("fp")
            if data.get("alpn"):
                stream["tlsSettings"]["alpn"] = [
                    a.strip() for a in str(data.get("alpn")).split(",") if a.strip()
                ]
        return {
            "tag": "proxy",
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": host,
                        "port": port,
                        "users": [
                            {
                                "id": data.get("id") or "",
                                "alterId": int(data.get("aid") or 0),
                                "security": data.get("scy") or "auto",
                            }
                        ],
                    }
                ]
            },
            "streamSettings": stream,
        }

    parsed = urlparse(main)
    host = parsed.hostname or ""
    port = parsed.port or 0
    qs = _qs(main)
    user = unquote(parsed.username) if parsed.username else ""
    password = unquote(parsed.password) if parsed.password else ""

    if proto == "vless":
        if not host or not port or not user:
            return None
        stream = _stream_settings_from_qs(qs)
        user_obj: dict = {"id": user, "encryption": qs.get("encryption") or "none"}
        if qs.get("flow"):
            user_obj["flow"] = qs["flow"]
        return {
            "tag": "proxy",
            "protocol": "vless",
            "settings": {"vnext": [{"address": host, "port": port, "users": [user_obj]}]},
            "streamSettings": stream,
        }

    if proto == "trojan":
        if not host or not port or not user:
            return None
        stream = _stream_settings_from_qs(qs)
        if stream.get("security") == "none":
            stream["security"] = "tls"
            stream.setdefault(
                "tlsSettings",
                {
                    "serverName": qs.get("sni") or host,
                    "allowInsecure": False,
                },
            )
        return {
            "tag": "proxy",
            "protocol": "trojan",
            "settings": {"servers": [{"address": host, "port": port, "password": user}]},
            "streamSettings": stream,
        }

    if proto in ("ss", "shadowsocks"):
        method = ""
        pwd = ""
        if user and password:
            method, pwd = user, password
        elif user and ":" in user:
            method, pwd = user.split(":", 1)
        else:
            # ss://BASE64@host:port یا ss://BASE64#remark
            try:
                body = main[len("ss://") :]
                if "@" in body:
                    userinfo, _rest = body.split("@", 1)
                    decoded = _b64decode(userinfo).decode("utf-8", errors="ignore")
                    if ":" in decoded:
                        method, pwd = decoded.split(":", 1)
                else:
                    decoded = _b64decode(body.split("#")[0]).decode("utf-8", errors="ignore")
                    # method:pass@host:port
                    import re

                    m = re.match(r"([^:]+):([^@]+)@([^:]+):(\d+)", decoded)
                    if m:
                        method, pwd, host, port = m.group(1), m.group(2), m.group(3), int(m.group(4))
            except Exception:
                return None
        if not host or not port or not method or not pwd:
            return None
        return {
            "tag": "proxy",
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": host,
                        "port": int(port),
                        "method": method,
                        "password": pwd,
                    }
                ]
            },
        }

    if proto in ("hysteria2", "hy2"):
        # Xray رسمی hy2 ندارد — پشتیبانی نمی‌شود
        return None

    return None


def build_xray_config(outbound: dict, socks_port: int) -> dict:
    return {
        "log": {"loglevel": "error"},
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": False, "auth": "noauth"},
            }
        ],
        "outbounds": [
            outbound,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "outboundTag": "proxy", "network": "tcp,udp"}],
        },
    }


async def _http_via_socks(socks_port: int, timeout: float) -> tuple[bool, float | None, str]:
    proxy = f"socks5://127.0.0.1:{socks_port}"
    last_err = "no url"
    for url in PROBE_URLS:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                proxy=proxy,
                timeout=timeout,
                follow_redirects=True,
                verify=False,
            ) as client:
                resp = await client.get(url)
                # 204 / 200 / 301 همگی یعنی تونل کار کرده
                if resp.status_code < 500:
                    ms = (time.monotonic() - start) * 1000
                    return True, ms, f"HTTP {resp.status_code}"
                last_err = f"HTTP {resp.status_code}"
        except ImportError as e:
            return False, None, "پکیج socksio نصب نیست — requirements را آپدیت و دوباره دیپلوی کن"
        except Exception as e:
            msg = str(e) or type(e).__name__
            if "socksio" in msg.lower() or "socks" in msg.lower() and "install" in msg.lower():
                return False, None, "پکیج socksio نصب نیست — requirements را آپدیت و دوباره دیپلوی کن"
            last_err = type(e).__name__ + (f": {msg}" if msg else "")
            continue
    return False, None, last_err


async def probe_one(raw: str, timeout: float = PROBE_TIMEOUT) -> dict:
    """
    تست یک کانفیگ.
    خروجی: {ok, ms, error, protocol, remark, supported}
    """
    protocol = get_protocol(raw)
    remark = get_remark(raw) or ""
    base = {
        "ok": False,
        "ms": None,
        "error": "",
        "protocol": protocol,
        "remark": remark,
        "supported": True,
    }

    xray = find_xray()
    if not xray:
        base["error"] = "xray نصب نیست — Docker را با Dockerfile جدید دیپلوی کن"
        base["supported"] = False
        return base

    outbound = build_xray_outbound(raw)
    if outbound is None:
        hp = get_host_port(raw)
        if not hp:
            base["error"] = "پارس کانفیگ ناموفق"
            base["supported"] = False
            return base
        base["error"] = f"پروتکل «{protocol}» برای تست واقعی پشتیبانی نمی‌شود"
        base["supported"] = False
        return base

    socks_port = _free_port()
    conf = build_xray_config(outbound, socks_port)
    conf_path = None
    proc = None
    try:
        fd, conf_path = tempfile.mkstemp(prefix="xray-probe-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(conf, f)

        proc = await asyncio.create_subprocess_exec(
            xray,
            "run",
            "-c",
            conf_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        # کمی صبر تا inbound بالا بیاید
        await asyncio.sleep(0.35)
        if proc.returncode is not None:
            err = b""
            try:
                err = await proc.stderr.read() if proc.stderr else b""
            except Exception:
                pass
            base["error"] = "xray استارت نشد: " + (err.decode("utf-8", errors="ignore")[:120] or "exit")
            return base

        ok, ms, detail = await asyncio.wait_for(
            _http_via_socks(socks_port, max(3.0, timeout - 2)),
            timeout=timeout,
        )
        base["ok"] = ok
        base["ms"] = round(ms, 1) if ms is not None else None
        base["error"] = "" if ok else (detail or "اتصال ناموفق")
        return base
    except asyncio.TimeoutError:
        base["error"] = "تایم‌اوت تست"
        return base
    except Exception as e:
        logger.exception("probe failed")
        base["error"] = f"{type(e).__name__}: {e}"
        return base
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except Exception:
                    proc.kill()
            except Exception:
                pass
        if conf_path:
            try:
                os.unlink(conf_path)
            except Exception:
                pass


async def probe_configs(configs: list[str]) -> dict[int, dict]:
    """تست موازی محدود — کلید = ایندکس کانفیگ."""
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def one(i: int, raw: str) -> tuple[int, dict]:
        async with sem:
            result = await probe_one(raw)
            return i, result

    pairs = await asyncio.gather(*(one(i, raw) for i, raw in enumerate(configs)))
    return dict(pairs)


def format_probe_summary(results: dict[int, dict]) -> tuple[int, int, int]:
    """(alive, dead, unsupported)"""
    alive = dead = unsup = 0
    for r in results.values():
        if not r.get("supported", True):
            unsup += 1
        elif r.get("ok"):
            alive += 1
        else:
            dead += 1
    return alive, dead, unsup
