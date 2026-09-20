"""
REST API برای پنل وب. همه‌ی مسیرها نیازمند سشن معتبرن (نگاه کن به auth.py).
هر endpoint دقیقاً همون کاری رو می‌کنه که معادلش تو ربات تلگرام انجام میده،
و روی همون storage.py مشترک کار می‌کنه (دیتای یکسان بین ربات و پنل).
"""
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
from aiohttp import web

import storage
from config_parser import (
    parse_config_details,
    get_host_port,
    config_fingerprint,
    decode_subscription,
    encode_subscription,
    get_protocol,
    get_remark,
    remaining_time_text,
    rename_config,
)
from pinger import ping_configs

BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")


def _make_url(token: str, request: web.Request) -> str:
    if BASE_URL:
        return f"{BASE_URL}/sub/{token}"
    host = request.headers.get("Host", "")
    return f"https://{host}/sub/{token}" if host else f"/sub/{token}"


async def _fetch_configs(sub_url: str) -> tuple[bool, list[str] | str]:
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(sub_url)
            resp.raise_for_status()
            configs = decode_subscription(resp.text)
    except Exception as e:
        return False, f"خطا در دریافت لینک: {e}"
    if not configs:
        return False, "هیچ کانفیگی توی این اشتراک پیدا نشد."
    return True, configs


def _config_summary(idx: int, raw: str, pinned: bool = False) -> dict:
    details = parse_config_details(raw)
    return {
        "index": idx,
        "protocol": details.get("protocol") or get_protocol(raw),
        "remark": details.get("remark") or get_remark(raw) or "",
        "pinned": bool(pinned),
        "host": details.get("host") or "",
        "port": details.get("port"),
        "transport": details.get("transport") or details.get("network") or "",
        "security": details.get("security") or "",
        "network": details.get("network") or "",
        "path": details.get("path") or "",
        "sni": details.get("sni") or "",
        "host_header": details.get("host_header") or "",
        "flow": details.get("flow") or "",
        "encryption": details.get("encryption") or "",
        "alpn": details.get("alpn") or "",
        "fp": details.get("fp") or "",
        "uuid": details.get("uuid") or "",
        "method": details.get("method") or "",
        "details": details,
    }


def _gen_configs_payload(gen: dict, live: list[str]) -> list[dict]:
    flags = storage.get_generated_config_pinned_flags({**gen, "configs": live})
    # اگر طول flags با live نخواند (بعد از resolve)، از items فعلی gen استفاده کن
    if len(flags) != len(live):
        flags = storage.get_generated_config_pinned_flags(gen)
    if len(flags) != len(live):
        flags = [False] * len(live)
    return [_config_summary(i, c, flags[i] if i < len(flags) else False) for i, c in enumerate(live)]


def _sub_summary(sub: dict) -> dict:
    return {
        "id": sub["id"],
        "name": sub["name"],
        "note": sub.get("note", ""),
        "sub_url": sub["sub_url"],
        "config_count": sub.get("config_count", len(sub.get("configs", []))),
        "updated_at": sub.get("updated_at", ""),
        "last_successful_ping": sub.get("last_successful_ping") or "",
    }


def _sub_detail(sub: dict) -> dict:
    d = _sub_summary(sub)
    d["configs"] = [_config_summary(i, c) for i, c in enumerate(sub["configs"])]
    return d


def _gen_summary(gen: dict, request: web.Request) -> dict:
    return {
        "id": gen["id"],
        "name": gen["name"],
        "config_count": gen.get("config_count", len(gen.get("configs", []))),
        "created_at": gen.get("created_at", ""),
        "expires_at": gen.get("expires_at"),
        "expired": storage.is_generated_expired(gen),
        "remaining_text": remaining_time_text(gen.get("expires_at")),
        "note": gen.get("note") or "",
        "customer_message": gen.get("customer_message") or "",
        "last_client_fetch": gen.get("last_client_fetch") or "",
        "client_fetch_count": int(gen.get("client_fetch_count") or 0),
        "last_successful_ping": gen.get("last_successful_ping") or "",
        "url": _make_url(gen["token"], request),
        "live": bool(gen.get("items")),
    }


def _err(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def _json_body(request: web.Request) -> dict | None:
    try:
        return await request.json()
    except Exception:
        return None


# ---------- اشتراک‌ها ----------

async def api_list_subs(request: web.Request) -> web.Response:
    subs = storage.list_subs(request["user_id"])
    return web.json_response([_sub_summary(s) for s in subs])


async def api_add_sub(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if body is None:
        return _err("بدنه‌ی درخواست نامعتبره.")

    sub_url = (body.get("sub_url") or "").strip()
    name = (body.get("name") or "").strip()
    note = (body.get("note") or "").strip()
    if not sub_url or not name:
        return _err("لینک و اسم اجباری هستن.")

    ok, result = await _fetch_configs(sub_url)
    if not ok:
        return _err(result)

    sub_id = storage.add_sub(request["user_id"], name, note, sub_url, result)
    sub = storage.get_sub(sub_id, request["user_id"])
    return web.json_response(_sub_detail(sub), status=201)


async def api_get_sub(request: web.Request) -> web.Response:
    sub_id = int(request.match_info["sub_id"])
    sub = storage.get_sub(sub_id, request["user_id"])
    if not sub:
        return _err("اشتراک پیدا نشد.", 404)
    return web.json_response(_sub_detail(sub))


async def api_refresh_sub(request: web.Request) -> web.Response:
    sub_id = int(request.match_info["sub_id"])
    sub = storage.get_sub(sub_id, request["user_id"])
    if not sub:
        return _err("اشتراک پیدا نشد.", 404)

    ok, result = await _fetch_configs(sub["sub_url"])
    if not ok:
        return _err(result)

    storage.update_configs(sub_id, request["user_id"], result)
    sub = storage.get_sub(sub_id, request["user_id"])
    return web.json_response(_sub_detail(sub))


async def api_delete_sub(request: web.Request) -> web.Response:
    sub_id = int(request.match_info["sub_id"])
    if not storage.get_sub(sub_id, request["user_id"]):
        return _err("اشتراک پیدا نشد.", 404)
    storage.delete_sub(sub_id, request["user_id"])
    return web.json_response({"deleted": True})


async def api_update_note(request: web.Request) -> web.Response:
    sub_id = int(request.match_info["sub_id"])
    sub = storage.get_sub(sub_id, request["user_id"])
    if not sub:
        return _err("اشتراک پیدا نشد.", 404)

    body = await _json_body(request)
    if body is None:
        return _err("بدنه‌ی درخواست نامعتبره.")

    if body.get("clear"):
        storage.update_note(sub_id, request["user_id"], "")
    else:
        text = (body.get("note") or "").strip()
        if not text:
            return _err("متن یادداشت خالیه.")
        new_note = f"{sub['note']}\n{text}" if sub["note"] else text
        storage.update_note(sub_id, request["user_id"], new_note)

    sub = storage.get_sub(sub_id, request["user_id"])
    return web.json_response(_sub_detail(sub))


async def api_export_sub(request: web.Request) -> web.Response:
    sub_id = int(request.match_info["sub_id"])
    sub = storage.get_sub(sub_id, request["user_id"])
    if not sub:
        return _err("اشتراک پیدا نشد.", 404)
    return web.json_response({"content": encode_subscription(sub["configs"])})


async def api_rename_config(request: web.Request) -> web.Response:
    sub_id = int(request.match_info["sub_id"])
    idx = int(request.match_info["idx"])
    sub = storage.get_sub(sub_id, request["user_id"])
    if not sub or idx >= len(sub["configs"]):
        return _err("کانفیگ پیدا نشد.", 404)

    body = await _json_body(request)
    if body is None:
        return _err("بدنه‌ی درخواست نامعتبره.")
    new_name = (body.get("name") or "").strip()
    if not new_name:
        return _err("اسم نمی‌تونه خالی باشه.")

    # این رنیم موقتیه (فقط برای گرفتن خروجی)، مثل ربات، روی خودِ اشتراک ذخیره نمیشه؛
    # برای ذخیره‌ی دائمی باید از "ساخت اشتراک سفارشی" استفاده کنی.
    renamed = rename_config(sub["configs"][idx], new_name)
    return web.json_response({"renamed": renamed})


# ---------- پینگ / حذف مرده‌ها ----------

async def api_ping_sub(request: web.Request) -> web.Response:
    sub_id = int(request.match_info["sub_id"])
    sub = storage.get_sub(sub_id, request["user_id"])
    if not sub:
        return _err("اشتراک پیدا نشد.", 404)

    old_configs = list(sub["configs"])
    results = await ping_configs(old_configs)
    if any(ms is not None for ms in results.values()):
        storage.set_sub_last_successful_ping(sub_id, request["user_id"])
    # مرتب‌سازی دائمی بر اساس پینگ (کمترین بالا)
    sorted_configs = storage.sort_sub_configs_by_ping(sub_id, request["user_id"], results) or old_configs
    # نگاشت ms به ترتیب جدید
    used = set()
    out = []
    for new_i, raw in enumerate(sorted_configs):
        ms = None
        for old_i, old_raw in enumerate(old_configs):
            if old_i in used:
                continue
            if old_raw == raw:
                ms = results.get(old_i)
                used.add(old_i)
                break
        out.append(
            {"index": new_i, "protocol": get_protocol(raw), "remark": get_remark(raw) or "", "ms": ms}
        )
    alive = sum(1 for r in out if r["ms"] is not None)
    dead = len(out) - alive
    sub = storage.get_sub(sub_id, request["user_id"])
    return web.json_response({
        "results": out,
        "alive": alive,
        "dead": dead,
        "total": len(out),
        "sorted": True,
        "sub": _sub_detail(sub) if sub else None,
    })


async def api_delete_dead(request: web.Request) -> web.Response:
    """بدون بدنه (یا بدون indices): پینگ می‌گیره و لیست مرده‌ها رو برمی‌گردونه (پیش‌نمایش، چیزی حذف نمیشه).
    با {"indices": [...]}: دقیقاً همون ایندکس‌ها رو حذف می‌کنه، بدون پینگ گرفتن دوباره
    (که نتیجه‌ی نمایش‌داده‌شده با نتیجه‌ی حذف‌شده همیشه یکی باشه)."""
    sub_id = int(request.match_info["sub_id"])
    sub = storage.get_sub(sub_id, request["user_id"])
    if not sub:
        return _err("اشتراک پیدا نشد.", 404)

    body = await _json_body(request) or {}

    if "indices" in body:
        try:
            dead_indices = {int(i) for i in body["indices"]}
        except (TypeError, ValueError):
            return _err("indices نامعتبره.")
        alive = [c for i, c in enumerate(sub["configs"]) if i not in dead_indices]
        storage.update_configs(sub_id, request["user_id"], alive)
        sub = storage.get_sub(sub_id, request["user_id"])
        return web.json_response({"removed": len(dead_indices), **_sub_detail(sub)})

    if not sub["configs"]:
        return web.json_response({"dead": []})

    results = await ping_configs(sub["configs"])
    dead = [i for i, ms in results.items() if ms is None]
    dead_items = [
        {"index": i, "protocol": get_protocol(sub["configs"][i]), "remark": get_remark(sub["configs"][i]) or ""}
        for i in dead
    ]
    return web.json_response({"dead": dead_items})


# ---------- ساخت اشتراک سفارشی (تک یا چند-منبعی، فرقی نداره) ----------

async def api_build_custom(request: web.Request) -> web.Response:
    body = await _json_body(request)
    if body is None:
        return _err("بدنه‌ی درخواست نامعتبره.")

    name = (body.get("name") or "").strip()
    items = body.get("items") or []
    try:
        expiry_days = int(body.get("expiry_days") or 0)
    except (TypeError, ValueError):
        return _err("expiry_days نامعتبره.")

    if not name:
        return _err("اسم اشتراک اجباریه.")
    if not isinstance(items, list) or not items:
        return _err("حداقل یک کانفیگ انتخاب کن.")

    user_id = request["user_id"]
    subs_cache: dict[int, dict] = {}
    final_configs = []

    recipe = []
    for item in items:
        try:
            sub_id = int(item["sub_id"])
            idx = int(item["index"])
        except (KeyError, TypeError, ValueError):
            return _err("آیتم انتخابی نامعتبره.")

        sub = subs_cache.get(sub_id)
        if sub is None:
            sub = storage.get_sub(sub_id, user_id)
            if not sub:
                return _err(f"اشتراک با id={sub_id} پیدا نشد.", 404)
            subs_cache[sub_id] = sub

        if idx < 0 or idx >= len(sub["configs"]):
            return _err("ایندکس کانفیگ نامعتبره.")

        src_raw = sub["configs"][idx]
        custom_name = (item.get("name") or "").strip()
        raw = rename_config(src_raw, custom_name) if custom_name else src_raw
        final_configs.append(raw)
        _item = {
            "sub_id": sub_id,
            "index": idx,
            "fp": config_fingerprint(src_raw),
            "name": custom_name,
        }
        _hp = get_host_port(src_raw)
        if _hp:
            _item["host"] = _hp[0]
            _item["port"] = int(_hp[1])
        recipe.append(_item)

    expires_at = None
    if expiry_days > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=expiry_days)).isoformat()

    gen_id, _token = storage.create_generated_sub(
        user_id, name, final_configs, expires_at=expires_at, items=recipe
    )
    gen = storage.get_generated_by_id(gen_id, user_id)
    return web.json_response(_gen_summary(gen, request), status=201)


# ---------- اشتراک‌های سفارشی من ----------

async def api_list_generated(request: web.Request) -> web.Response:
    gens = storage.list_generated_subs(request["user_id"])
    return web.json_response([_gen_summary(g, request) for g in gens])


async def _refresh_source_subs_for_gen(gen: dict) -> None:
    """لینک‌های منبع را از اینترنت دوباره می‌گیرد تا resolve لایو باشد."""
    if not gen.get("items"):
        return
    user_id = gen.get("user_id")
    if user_id is None:
        return
    for sub_id in storage.get_source_sub_ids(gen):
        sub = storage.get_sub(sub_id, user_id)
        if not sub or not sub.get("sub_url"):
            continue
        ok, result = await _fetch_configs(sub["sub_url"])
        if ok and isinstance(result, list):
            storage.update_configs(sub_id, user_id, result)


async def api_get_generated(request: web.Request) -> web.Response:
    gen_id = int(request.match_info["gen_id"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    try:
        await _refresh_source_subs_for_gen(gen)
    except Exception:
        pass
    live = storage.resolve_generated_configs(gen, persist=True)
    data = _gen_summary(gen, request)
    data["config_count"] = len(live)
    data["configs"] = _gen_configs_payload(gen, live)
    data["live"] = bool(gen.get("items"))
    return web.json_response(data)



async def api_add_to_generated(request: web.Request) -> web.Response:
    """افزودن کانفیگ از اشتراک‌های اصلی به یک اشتراک سفارشی موجود.
    body: { "items": [ {"sub_id": 1, "index": 0, "name": "اختیاری"}, ... ] }
    لینک ساب عوض نمی‌شود.
    """
    gen_id = int(request.match_info["gen_id"])
    user_id = request["user_id"]
    gen = storage.get_generated_by_id(gen_id, user_id)
    if not gen:
        return _err("پیدا نشد.", 404)

    body = await _json_body(request)
    if body is None:
        return _err("بدنه‌ی درخواست نامعتبره.")

    items = body.get("items") or []
    if not isinstance(items, list) or not items:
        return _err("حداقل یک کانفیگ انتخاب کن.")

    subs_cache: dict[int, dict] = {}
    final_configs = []

    recipe = []
    for item in items:
        try:
            sub_id = int(item["sub_id"])
            idx = int(item["index"])
        except (KeyError, TypeError, ValueError):
            return _err("آیتم انتخابی نامعتبره.")

        sub = subs_cache.get(sub_id)
        if sub is None:
            sub = storage.get_sub(sub_id, user_id)
            if not sub:
                return _err(f"اشتراک با id={sub_id} پیدا نشد.", 404)
            subs_cache[sub_id] = sub

        if idx < 0 or idx >= len(sub["configs"]):
            return _err("ایندکس کانفیگ نامعتبره.")

        src_raw = sub["configs"][idx]
        custom_name = (item.get("name") or "").strip()
        raw = rename_config(src_raw, custom_name) if custom_name else src_raw
        final_configs.append(raw)
        _item = {
            "sub_id": sub_id,
            "index": idx,
            "fp": config_fingerprint(src_raw),
            "name": custom_name,
        }
        _hp = get_host_port(src_raw)
        if _hp:
            _item["host"] = _hp[0]
            _item["port"] = int(_hp[1])
        recipe.append(_item)

    total = storage.add_configs_to_generated(gen_id, user_id, final_configs, new_items=recipe)
    if total is None:
        return _err("پیدا نشد.", 404)

    gen = storage.get_generated_by_id(gen_id, user_id)
    data = _gen_summary(gen, request)
    data["added"] = len(final_configs)
    data["config_count"] = total
    return web.json_response(data)



async def api_rename_gen_config(request: web.Request) -> web.Response:
    gen_id = int(request.match_info["gen_id"])
    idx = int(request.match_info["idx"])
    body = await _json_body(request)
    if body is None:
        return _err("بدنه‌ی درخواست نامعتبره.")
    new_name = (body.get("name") or "").strip()
    if not new_name:
        return _err("اسم جدید اجباریه.")
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    # اول لایو کن تا ایندکس با لیست فعلی یکی باشه
    storage.resolve_generated_configs(gen, persist=True)
    remark = storage.rename_config_in_generated(gen_id, request["user_id"], idx, new_name)
    if remark is None:
        return _err("ایندکس نامعتبره.", 400)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    live = storage.resolve_generated_configs(gen, persist=True)
    data = _gen_summary(gen, request)
    data["config_count"] = len(live)
    data["configs"] = _gen_configs_payload(gen, live)
    data["renamed"] = remark
    return web.json_response(data)


async def api_delete_gen_config(request: web.Request) -> web.Response:
    gen_id = int(request.match_info["gen_id"])
    idx = int(request.match_info["idx"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    storage.resolve_generated_configs(gen, persist=True)
    total = storage.delete_config_from_generated(gen_id, request["user_id"], idx)
    if total is None:
        return _err("ایندکس نامعتبره.", 400)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    live = storage.resolve_generated_configs(gen, persist=True) if gen else []
    data = _gen_summary(gen, request) if gen else {"id": gen_id, "config_count": 0}
    data["config_count"] = len(live)
    data["configs"] = _gen_configs_payload(gen, live)
    data["deleted_index"] = idx
    return web.json_response(data)


async def api_delete_generated(request: web.Request) -> web.Response:
    gen_id = int(request.match_info["gen_id"])
    if not storage.get_generated_by_id(gen_id, request["user_id"]):
        return _err("پیدا نشد.", 404)
    storage.delete_generated_sub(gen_id, request["user_id"])
    return web.json_response({"deleted": True})


async def api_update_generated_expiry(request: web.Request) -> web.Response:
    """body: { "expiry_days": 0|7|30|90|180 }  — از همین لحظه محاسبه می‌شود."""
    gen_id = int(request.match_info["gen_id"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    body = await _json_body(request) or {}
    try:
        days = int(body.get("expiry_days") or 0)
    except (TypeError, ValueError):
        return _err("expiry_days نامعتبره.")
    expires_at = None
    if days > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    storage.update_generated_expiry(gen_id, request["user_id"], expires_at)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    return web.json_response(_gen_summary(gen, request))


async def api_end_generated(request: web.Request) -> web.Response:
    """اتمام فوری اشتراک سفارشی — مثل منقضی شدن: در کلاینت فقط پیام اتمام نمایش داده می‌شود."""
    gen_id = int(request.match_info["gen_id"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    now_iso = datetime.now(timezone.utc).isoformat()
    storage.update_generated_expiry(gen_id, request["user_id"], now_iso)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    return web.json_response(_gen_summary(gen, request))


async def api_revive_generated(request: web.Request) -> web.Response:
    """زنده کردن اشتراک سفارشی: همان توکن و کانفیگ‌ها، تاریخ ساخت و انقضای جدید."""
    gen_id = int(request.match_info["gen_id"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    body = await _json_body(request) or {}
    try:
        days = int(body.get("expiry_days") or 0)
    except (TypeError, ValueError):
        return _err("expiry_days نامعتبره.")
    expires_at = None
    if days > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    storage.revive_generated_sub(gen_id, request["user_id"], expires_at)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    return web.json_response(_gen_summary(gen, request))


async def api_update_generated_note(request: web.Request) -> web.Response:
    """body: { "note": "..." } یا { "clear": true }"""
    gen_id = int(request.match_info["gen_id"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    body = await _json_body(request) or {}
    if body.get("clear"):
        note = ""
    else:
        note = (body.get("note") or "").strip()
    storage.update_generated_note(gen_id, request["user_id"], note)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    return web.json_response(_gen_summary(gen, request))


async def api_update_generated_customer_message(request: web.Request) -> web.Response:
    """body: { "message": "..." } یا { "clear": true } — پیام قابل‌مشاهده مشتری"""
    gen_id = int(request.match_info["gen_id"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    body = await _json_body(request) or {}
    if body.get("clear"):
        msg = ""
    else:
        msg = (body.get("message") or "").strip()
    storage.update_generated_customer_message(gen_id, request["user_id"], msg)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    return web.json_response(_gen_summary(gen, request))


async def api_reorder_gen_config(request: web.Request) -> web.Response:
    """body: { "direction": "up"|"down" } — جابه‌جایی کانفیگ در لیست"""
    gen_id = int(request.match_info["gen_id"])
    idx = int(request.match_info["idx"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    body = await _json_body(request) or {}
    direction = (body.get("direction") or "").strip().lower()
    if direction == "up":
        delta = -1
    elif direction == "down":
        delta = 1
    else:
        return _err("direction باید up یا down باشد.")
    ok = storage.reorder_config_in_generated(gen_id, request["user_id"], idx, delta)
    if not ok:
        return _err("جابه‌جایی ممکن نیست (اول/آخر لیست یا ایندکس نامعتبر).")
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    try:
        live = storage.resolve_generated_configs(gen, persist=True)
    except Exception:
        live = gen.get("configs") or []
    data = _gen_summary(gen, request)
    data["config_count"] = len(live)
    data["configs"] = _gen_configs_payload(gen, live)
    return web.json_response(data)


async def api_backup_export(request: web.Request) -> web.Response:
    """دانلود بک‌آپ کامل JSON برای جابه‌جایی سرور (توکن‌ها حفظ می‌شوند)."""
    data = storage.export_full_backup()
    body = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f"eshkhoshbakht-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    return web.Response(
        text=body,
        content_type="application/json",
        charset="utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


async def api_backup_restore(request: web.Request) -> web.Response:
    """
    بازیابی بک‌آپ کامل.
    body: خود JSON بک‌آپ  یا  { "backup": {...}, "replace": true }
    replace پیش‌فرض true است (جایگزینی کامل — مناسب مهاجرت).
    """
    body = await _json_body(request)
    if body is None:
        return _err("بدنه‌ی درخواست نامعتبره.")

    if "backup" in body and isinstance(body.get("backup"), dict):
        data = body["backup"]
        replace = bool(body.get("replace", True))
    elif body.get("type") == "eshkhoshbakht_full_backup" or ("subs" in body and "generated_subs" in body):
        data = body
        replace = True
    else:
        return _err("فرمت بک‌آپ شناخته نشد.")

    try:
        result = storage.import_full_backup(data, replace=replace)
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"خطا در بازیابی: {e}", 500)

    return web.json_response({"ok": True, **result})



async def api_ping_generated(request: web.Request) -> web.Response:
    """پینگ کانفیگ‌های یک اشتراک سفارشی و مرتب‌سازی دائمی بر اساس پینگ.

    مهم: قبل از پینگ resolve+persist نمی‌کنیم تا اسم‌ها با IP جابه‌جا نشوند.
    روی همان لیست ذخیره‌شده (اسم چسبیده به URI) پینگ و sort می‌کنیم.
    """
    gen_id = int(request.match_info["gen_id"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    configs = list(gen.get("configs") or [])
    if not configs:
        return _err("هیچ کانفیگی وجود نداره.")
    old_configs = list(configs)
    results = await ping_configs(old_configs)
    if any(ms is not None for ms in results.values()):
        storage.set_generated_last_successful_ping(gen_id, request["user_id"])
    sorted_configs = storage.sort_generated_configs_by_ping(
        gen_id, request["user_id"], results, configs_snapshot=old_configs
    ) or old_configs
    aligned = storage.map_ping_results_to_configs(old_configs, sorted_configs, results)
    out = []
    for new_i, raw in enumerate(sorted_configs):
        out.append(
            {
                "index": new_i,
                "protocol": get_protocol(raw),
                "remark": get_remark(raw) or "",
                "ms": aligned.get(new_i),
            }
        )
    alive = sum(1 for r in out if r["ms"] is not None)
    dead = len(out) - alive
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    live = sorted_configs
    data = _gen_summary(gen, request) if gen else {}
    if gen:
        data["config_count"] = len(live)
        data["configs"] = _gen_configs_payload(gen, live)
    return web.json_response({
        "results": out,
        "alive": alive,
        "dead": dead,
        "total": len(out),
        "sorted": True,
        "gen": data,
    })



async def api_pin_gen_config(request: web.Request) -> web.Response:
    """body اختیاری: { "pinned": true|false } — بدون body = toggle"""
    gen_id = int(request.match_info["gen_id"])
    idx = int(request.match_info["idx"])
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    if not gen:
        return _err("پیدا نشد.", 404)
    body = await _json_body(request) or {}
    pinned_arg = body.get("pinned")
    if pinned_arg is not None:
        pinned_arg = bool(pinned_arg)
    else:
        pinned_arg = None
    result = storage.set_generated_config_pinned(gen_id, request["user_id"], idx, pinned_arg)
    if result is None:
        return _err("ایندکس نامعتبره.", 400)
    gen = storage.get_generated_by_id(gen_id, request["user_id"])
    live = storage.resolve_generated_configs(gen, persist=True)
    data = _gen_summary(gen, request)
    data["config_count"] = len(live)
    data["configs"] = _gen_configs_payload(gen, live)
    data["pinned"] = result["pinned"]
    return web.json_response(data)


def add_routes(app: web.Application) -> None:
    app.router.add_get("/api/subs", api_list_subs)
    app.router.add_post("/api/subs", api_add_sub)
    app.router.add_get("/api/subs/{sub_id}", api_get_sub)
    app.router.add_post("/api/subs/{sub_id}/refresh", api_refresh_sub)
    app.router.add_delete("/api/subs/{sub_id}", api_delete_sub)
    app.router.add_post("/api/subs/{sub_id}/note", api_update_note)
    app.router.add_get("/api/subs/{sub_id}/export", api_export_sub)
    app.router.add_post("/api/subs/{sub_id}/configs/{idx}/rename", api_rename_config)
    app.router.add_get("/api/subs/{sub_id}/ping", api_ping_sub)
    app.router.add_get("/api/generated/{gen_id}/ping", api_ping_generated)
    app.router.add_post("/api/subs/{sub_id}/delete-dead", api_delete_dead)
    app.router.add_post("/api/build-custom", api_build_custom)
    app.router.add_get("/api/generated", api_list_generated)
    app.router.add_get("/api/generated/{gen_id}", api_get_generated)
    app.router.add_post("/api/generated/{gen_id}/add-configs", api_add_to_generated)
    app.router.add_post("/api/generated/{gen_id}/configs/{idx}/rename", api_rename_gen_config)
    app.router.add_delete("/api/generated/{gen_id}/configs/{idx}", api_delete_gen_config)
    app.router.add_post("/api/generated/{gen_id}/expiry", api_update_generated_expiry)
    app.router.add_post("/api/generated/{gen_id}/end", api_end_generated)
    app.router.add_post("/api/generated/{gen_id}/revive", api_revive_generated)
    app.router.add_post("/api/generated/{gen_id}/note", api_update_generated_note)
    app.router.add_post("/api/generated/{gen_id}/customer-message", api_update_generated_customer_message)
    app.router.add_post("/api/generated/{gen_id}/configs/{idx}/reorder", api_reorder_gen_config)
    app.router.add_post("/api/generated/{gen_id}/configs/{idx}/pin", api_pin_gen_config)
    app.router.add_delete("/api/generated/{gen_id}", api_delete_generated)
    app.router.add_get("/api/backup", api_backup_export)
    app.router.add_post("/api/backup/restore", api_backup_restore)
