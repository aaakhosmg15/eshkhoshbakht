"""
ذخیره‌سازی چند اشتراک برای هر کاربر، با SQLite.

پایداری روی Railway:
  - Volume را روی مسیر /app/data مانت کن
  - DB_PATH پیش‌فرض: /app/data/bot.db (اگر متغیر ست نشود)
  - بدون Volume، با هر دیپلوی/ری‌استارت داده از بین می‌رود
"""
import json
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# اولویت: DB_PATH از env → در غیر این صورت /app/data/bot.db روی سرور، data/bot.db محلی
_default_db = "/app/data/bot.db" if Path("/app/data").is_dir() or os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") else "data/bot.db"
DB_PATH = Path(os.environ.get("DB_PATH", _default_db)).expanduser().resolve()
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except OSError as e:
    logger.error("نمی‌توان پوشه دیتابیس را ساخت (%s): %s — Volume را چک کن", DB_PATH.parent, e)


NEW_COLUMNS = {"id", "user_id", "name", "note", "sub_url", "configs", "updated_at"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    """جدول‌های نسخه‌ی قدیمی رو به اسکیمای جدید مهاجرت می‌ده."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(subs)").fetchall()}
    if existing:
        if "updated_at" not in existing and {"id", "user_id", "name", "note", "sub_url", "configs"}.issubset(existing):
            conn.execute("ALTER TABLE subs ADD COLUMN updated_at TEXT")
            conn.execute("UPDATE subs SET updated_at = ? WHERE updated_at IS NULL", (_now_iso(),))
            conn.commit()
        elif not NEW_COLUMNS.issubset(existing) and existing:
            conn.execute("ALTER TABLE subs RENAME TO subs_old")
            conn.execute(
                """CREATE TABLE subs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    note TEXT,
                    sub_url TEXT NOT NULL,
                    configs TEXT NOT NULL,
                    updated_at TEXT
                )"""
            )
            if {"user_id", "sub_url", "configs"}.issubset(existing):
                old_rows = conn.execute("SELECT user_id, sub_url, configs FROM subs_old").fetchall()
                now = _now_iso()
                for i, (user_id, sub_url, configs) in enumerate(old_rows, start=1):
                    conn.execute(
                        "INSERT INTO subs (user_id, name, note, sub_url, configs, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (user_id, f"اشتراک {i}", "", sub_url, configs, now),
                    )
            conn.execute("DROP TABLE subs_old")
            conn.commit()

    gen_cols = {row[1] for row in conn.execute("PRAGMA table_info(generated_subs)").fetchall()}
    if gen_cols and "expires_at" not in gen_cols:
        conn.execute("ALTER TABLE generated_subs ADD COLUMN expires_at TEXT")
    gen_cols = {row[1] for row in conn.execute("PRAGMA table_info(generated_subs)").fetchall()}
    if gen_cols and "items" not in gen_cols:
        conn.execute("ALTER TABLE generated_subs ADD COLUMN items TEXT")
    gen_cols = {row[1] for row in conn.execute("PRAGMA table_info(generated_subs)").fetchall()}
    if gen_cols and "note" not in gen_cols:
        conn.execute("ALTER TABLE generated_subs ADD COLUMN note TEXT")
        conn.commit()
    gen_cols = {row[1] for row in conn.execute("PRAGMA table_info(generated_subs)").fetchall()}
    if gen_cols and "customer_message" not in gen_cols:
        conn.execute("ALTER TABLE generated_subs ADD COLUMN customer_message TEXT")
        conn.commit()
    gen_cols = {row[1] for row in conn.execute("PRAGMA table_info(generated_subs)").fetchall()}
    if gen_cols and "last_client_fetch" not in gen_cols:
        conn.execute("ALTER TABLE generated_subs ADD COLUMN last_client_fetch TEXT")
        conn.commit()
    gen_cols = {row[1] for row in conn.execute("PRAGMA table_info(generated_subs)").fetchall()}
    if gen_cols and "client_fetch_count" not in gen_cols:
        conn.execute("ALTER TABLE generated_subs ADD COLUMN client_fetch_count INTEGER DEFAULT 0")
        conn.commit()
    gen_cols = {row[1] for row in conn.execute("PRAGMA table_info(generated_subs)").fetchall()}
    if gen_cols and "last_successful_ping" not in gen_cols:
        conn.execute("ALTER TABLE generated_subs ADD COLUMN last_successful_ping TEXT")
        conn.commit()
    sub_cols = {row[1] for row in conn.execute("PRAGMA table_info(subs)").fetchall()}
    if sub_cols and "last_successful_ping" not in sub_cols:
        conn.execute("ALTER TABLE subs ADD COLUMN last_successful_ping TEXT")
        conn.commit()


def _conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    # پایداری بهتر روی Volume / ری‌استارت
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS subs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            note TEXT,
            sub_url TEXT NOT NULL,
            configs TEXT NOT NULL,
            updated_at TEXT,
            last_successful_ping TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS generated_subs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            configs TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            items TEXT,
            note TEXT,
            customer_message TEXT,
            last_client_fetch TEXT,
            client_fetch_count INTEGER DEFAULT 0,
            last_successful_ping TEXT
        )"""
    )
    _migrate(conn)
    return conn


def add_sub(user_id: int, name: str, note: str, sub_url: str, configs: list[str]) -> int:
    from config_parser import disambiguate_duplicates

    configs = disambiguate_duplicates(configs)
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO subs (user_id, name, note, sub_url, configs, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, name, note, sub_url, json.dumps(configs), _now_iso()),
    )
    conn.commit()
    sub_id = cur.lastrowid
    conn.close()
    return sub_id


def list_subs(user_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, name, note, sub_url, configs, updated_at, last_successful_ping FROM subs WHERE user_id=? ORDER BY id",
        (user_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        sub_id, name, note, sub_url, configs_json, updated_at = row[:6]
        last_successful_ping = row[6] if len(row) > 6 else ""
        configs = json.loads(configs_json)
        result.append(
            {
                "id": sub_id,
                "name": name,
                "note": note or "",
                "sub_url": sub_url,
                "config_count": len(configs),
                "updated_at": updated_at or "",
                "last_successful_ping": last_successful_ping or "",
            }
        )
    return result


def get_sub(sub_id: int, user_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT id, name, note, sub_url, configs, updated_at, last_successful_ping FROM subs WHERE id=? AND user_id=?",
        (sub_id, user_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    sid, name, note, sub_url, configs_json, updated_at = row[:6]
    last_successful_ping = row[6] if len(row) > 6 else ""
    return {
        "id": sid,
        "name": name,
        "note": note or "",
        "sub_url": sub_url,
        "configs": json.loads(configs_json),
        "updated_at": updated_at or "",
        "last_successful_ping": last_successful_ping or "",
    }



def update_configs(sub_id: int, user_id: int, configs: list[str]) -> None:
    from config_parser import disambiguate_duplicates

    configs = disambiguate_duplicates(configs)
    conn = _conn()
    conn.execute(
        "UPDATE subs SET configs=?, updated_at=? WHERE id=? AND user_id=?",
        (json.dumps(configs), _now_iso(), sub_id, user_id),
    )
    conn.commit()
    conn.close()


def update_note(sub_id: int, user_id: int, note: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE subs SET note=? WHERE id=? AND user_id=?",
        (note, sub_id, user_id),
    )
    conn.commit()
    conn.close()


def delete_sub(sub_id: int, user_id: int) -> None:
    conn = _conn()
    conn.execute("DELETE FROM subs WHERE id=? AND user_id=?", (sub_id, user_id))
    conn.commit()
    conn.close()


# ---------- اشتراک‌های سفارشی ساخته‌شده ----------


def create_generated_sub(
    user_id: int,
    name: str,
    configs: list[str],
    expires_at: str | None = None,
    items: list[dict] | None = None,
    note: str = "",
) -> tuple[int, str]:
    """items: لیست منبع برای لایوآپدیت — [{"sub_id", "index", "name", "fp"}, ...]"""
    from config_parser import disambiguate_duplicates

    configs = disambiguate_duplicates(configs)
    token = secrets.token_urlsafe(16)
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO generated_subs (user_id, name, token, configs, created_at, expires_at, items, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            name,
            token,
            json.dumps(configs),
            _now_iso(),
            expires_at,
            json.dumps(items) if items is not None else None,
            note or "",
        ),
    )
    conn.commit()
    gen_id = cur.lastrowid
    conn.close()
    return gen_id, token


def _row_to_generated(row) -> dict:
    """پشتیبانی از شکل‌های قدیمی و جدید."""
    # id, user_id, name, token, configs, created_at, expires_at, items, note,
    # customer_message, last_client_fetch, client_fetch_count, last_successful_ping
    n = len(row)
    gid, user_id, name, tok, configs_json, created_at, expires_at = row[:7]
    items_json = row[7] if n >= 8 else None
    note = row[8] if n >= 9 else ""
    customer_message = row[9] if n >= 10 else ""
    last_client_fetch = row[10] if n >= 11 else ""
    client_fetch_count = row[11] if n >= 12 else 0
    last_successful_ping = row[12] if n >= 13 else ""
    items = None
    if items_json:
        try:
            items = json.loads(items_json)
        except Exception:
            items = None
    try:
        client_fetch_count = int(client_fetch_count or 0)
    except (TypeError, ValueError):
        client_fetch_count = 0
    return {
        "id": gid,
        "user_id": user_id,
        "name": name,
        "token": tok,
        "configs": json.loads(configs_json),
        "created_at": created_at,
        "expires_at": expires_at,
        "items": items,
        "note": note or "",
        "customer_message": customer_message or "",
        "last_client_fetch": last_client_fetch or "",
        "client_fetch_count": client_fetch_count,
        "last_successful_ping": last_successful_ping or "",
    }


def get_generated_by_token(token: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT id, user_id, name, token, configs, created_at, expires_at, items, note, customer_message, last_client_fetch, client_fetch_count, last_successful_ping FROM generated_subs WHERE token=?",
        (token,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_generated(row)


def get_generated_by_id(gen_id: int, user_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT id, user_id, name, token, configs, created_at, expires_at, items, note, customer_message, last_client_fetch, client_fetch_count, last_successful_ping FROM generated_subs WHERE id=? AND user_id=?",
        (gen_id, user_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_generated(row)


def list_generated_subs(user_id: int) -> list[dict]:
    # اول اشتراک‌های خیلی قدیمیِ منقضی را پاک کن
    cleanup_old_expired_generated()
    conn = _conn()
    rows = conn.execute(
        "SELECT id, name, token, configs, created_at, expires_at, items, note, customer_message, last_client_fetch, client_fetch_count, last_successful_ping FROM generated_subs WHERE user_id=? ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        gid, name, token, configs_json, created_at, expires_at = row[:6]
        items_json = row[6] if len(row) > 6 else None
        note = row[7] if len(row) > 7 else ""
        customer_message = row[8] if len(row) > 8 else ""
        last_client_fetch = row[9] if len(row) > 9 else ""
        client_fetch_count = row[10] if len(row) > 10 else 0
        last_successful_ping = row[11] if len(row) > 11 else ""
        configs = json.loads(configs_json)
        items = None
        if items_json:
            try:
                items = json.loads(items_json)
            except Exception:
                items = None
        try:
            client_fetch_count = int(client_fetch_count or 0)
        except (TypeError, ValueError):
            client_fetch_count = 0
        result.append(
            {
                "id": gid,
                "name": name,
                "token": token,
                "config_count": len(configs),
                "created_at": created_at,
                "expires_at": expires_at,
                "items": items,
                "note": note or "",
                "customer_message": customer_message or "",
                "last_client_fetch": last_client_fetch or "",
                "client_fetch_count": client_fetch_count,
                "last_successful_ping": last_successful_ping or "",
            }
        )
    return result


def is_generated_expired(gen: dict) -> bool:
    exp = gen.get("expires_at")
    if not exp:
        return False
    try:
        return datetime.fromisoformat(exp) < datetime.now(timezone.utc)
    except Exception:
        return False


def delete_generated_sub(gen_id: int, user_id: int) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM generated_subs WHERE id=? AND user_id=?", (gen_id, user_id))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def revive_generated_sub(gen_id: int, user_id: int, expires_at: str | None) -> bool:
    """زنده کردن اشتراک سفارشی: تاریخ ساخت و انقضا از نو، توکن و کانفیگ‌ها بدون تغییر."""
    conn = _conn()
    cur = conn.execute(
        "UPDATE generated_subs SET created_at=?, expires_at=? WHERE id=? AND user_id=?",
        (_now_iso(), expires_at, gen_id, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def update_generated_expiry(gen_id: int, user_id: int, expires_at: str | None) -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE generated_subs SET expires_at=? WHERE id=? AND user_id=?",
        (expires_at, gen_id, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def update_generated_note(gen_id: int, user_id: int, note: str) -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE generated_subs SET note=? WHERE id=? AND user_id=?",
        (note, gen_id, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def update_generated_customer_message(gen_id: int, user_id: int, message: str) -> bool:
    """پیام قابل‌مشاهده توسط مشتری (جدا از یادداشت خصوصی)."""
    conn = _conn()
    cur = conn.execute(
        "UPDATE generated_subs SET customer_message=? WHERE id=? AND user_id=?",
        (message or "", gen_id, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def touch_generated_client_fetch(token: str) -> None:
    """ثبت زمان و شمارش آخرین بار که مشتری لینک ساب را باز/آپدیت کرد."""
    conn = _conn()
    conn.execute(
        "UPDATE generated_subs SET last_client_fetch=?, client_fetch_count=COALESCE(client_fetch_count, 0) + 1 WHERE token=?",
        (_now_iso(), token),
    )
    conn.commit()
    conn.close()


def set_sub_last_successful_ping(sub_id: int, user_id: int) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE subs SET last_successful_ping=? WHERE id=? AND user_id=?",
        (_now_iso(), sub_id, user_id),
    )
    conn.commit()
    conn.close()


def set_generated_last_successful_ping(gen_id: int, user_id: int) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE generated_subs SET last_successful_ping=? WHERE id=? AND user_id=?",
        (_now_iso(), gen_id, user_id),
    )
    conn.commit()
    conn.close()


def reorder_config_in_generated(gen_id: int, user_id: int, idx: int, direction: int) -> bool:
    """جابه‌جایی کانفیگ در لیست (direction: -1 بالا، +1 پایین). توکن ثابت می‌ماند."""
    conn = _conn()
    row = conn.execute(
        "SELECT configs, items FROM generated_subs WHERE id=? AND user_id=?",
        (gen_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return False
    configs = json.loads(row[0])
    n = len(configs)
    if idx < 0 or idx >= n:
        conn.close()
        return False
    new_idx = idx + direction
    if new_idx < 0 or new_idx >= n:
        conn.close()
        return False
    configs[idx], configs[new_idx] = configs[new_idx], configs[idx]
    items = None
    if row[1]:
        try:
            items = json.loads(row[1])
        except Exception:
            items = None
    if isinstance(items, list) and idx < len(items) and new_idx < len(items):
        items[idx], items[new_idx] = items[new_idx], items[idx]
    conn.execute(
        "UPDATE generated_subs SET configs=?, items=? WHERE id=? AND user_id=?",
        (json.dumps(configs), json.dumps(items) if items is not None else None, gen_id, user_id),
    )
    conn.commit()
    conn.close()
    return True




def _ensure_generated_items(configs: list[str], items) -> list[dict]:
    """اگر items نباشد یا طولش نخواند، از روی configs می‌سازد (برای پین روی snapshot)."""
    from config_parser import config_fingerprint, get_remark

    if isinstance(items, list) and len(items) == len(configs):
        out = []
        for it in items:
            out.append(dict(it) if isinstance(it, dict) else {})
        return out
    result = []
    for i, raw in enumerate(configs):
        result.append(
            {
                "sub_id": -1,
                "index": i,
                "fp": config_fingerprint(raw),
                "name": get_remark(raw) or "",
                "pinned": False,
            }
        )
    return result


def _pinned_first(configs: list[str], items: list[dict]) -> tuple[list[str], list[dict]]:
    """کانفیگ‌های پین‌شده را به ابتدای لیست می‌آورد (ترتیب نسبی حفظ می‌شود)."""
    if len(configs) != len(items):
        return configs, items
    pinned_c, pinned_i = [], []
    rest_c, rest_i = [], []
    for c, it in zip(configs, items):
        if isinstance(it, dict) and it.get("pinned"):
            pinned_c.append(c)
            pinned_i.append(it)
        else:
            rest_c.append(c)
            rest_i.append(it if isinstance(it, dict) else {})
    return pinned_c + rest_c, pinned_i + rest_i


def set_generated_config_pinned(
    gen_id: int, user_id: int, idx: int, pinned: bool | None = None
) -> dict | None:
    """
    پین/آن‌پین یک کانفیگ در اشتراک سفارشی.
    pinned=None یعنی toggle.
    بعد از پین، همهٔ پین‌شده‌ها بالای لیست می‌آیند.
    """
    conn = _conn()
    row = conn.execute(
        "SELECT configs, items FROM generated_subs WHERE id=? AND user_id=?",
        (gen_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return None
    configs = json.loads(row[0])
    if idx < 0 or idx >= len(configs):
        conn.close()
        return None
    items_raw = None
    if row[1]:
        try:
            items_raw = json.loads(row[1])
        except Exception:
            items_raw = None
    items = _ensure_generated_items(configs, items_raw)
    current = bool(items[idx].get("pinned"))
    new_val = (not current) if pinned is None else bool(pinned)
    items[idx]["pinned"] = new_val
    configs, items = _pinned_first(configs, items)
    conn.execute(
        "UPDATE generated_subs SET configs=?, items=? WHERE id=? AND user_id=?",
        (json.dumps(configs), json.dumps(items), gen_id, user_id),
    )
    conn.commit()
    conn.close()
    return {"pinned": new_val, "config_count": len(configs)}


def get_generated_config_pinned_flags(gen: dict) -> list[bool]:
    """لیست بولین پین هم‌تراز با configs فعلی gen."""
    configs = gen.get("configs") or []
    items = gen.get("items")
    if not isinstance(items, list) or len(items) != len(configs):
        return [False] * len(configs)
    return [bool(it.get("pinned")) if isinstance(it, dict) else False for it in items]


def sort_configs_by_ping(configs: list[str], results: dict[int, float | None]) -> list[str]:
    """مرتب‌سازی کانفیگ‌ها: کمترین پینگ اول، تایم‌اوت‌ها آخر + برچسب سریع‌ترین."""
    from config_parser import (
        get_remark,
        rename_config,
        strip_strongest_label,
        with_strongest_label,
    )

    indexed = list(enumerate(configs))
    indexed.sort(
        key=lambda t: (
            results.get(t[0]) is None,
            results.get(t[0]) if results.get(t[0]) is not None else 0,
        )
    )
    ordered = [cfg for _, cfg in indexed]
    ordered_ms = [results.get(old_i) for old_i, _ in indexed]

    # اول برچسب قبلی «سریع ترین» را از همه بردار
    cleaned = []
    for raw in ordered:
        remark = get_remark(raw) or ""
        base = strip_strongest_label(remark)
        if base != remark:
            cleaned.append(rename_config(raw, base) if base else raw)
        else:
            cleaned.append(raw)

    # بهترین پینگ (کمترین ms غیر None)
    best_i = None
    best_ms = None
    for i, ms in enumerate(ordered_ms):
        if ms is None:
            continue
        if best_ms is None or ms < best_ms:
            best_ms = ms
            best_i = i

    if best_i is not None:
        raw = cleaned[best_i]
        remark = get_remark(raw) or "بدون نام"
        labeled = with_strongest_label(remark)
        cleaned[best_i] = rename_config(raw, labeled)

    return cleaned


def sort_sub_configs_by_ping(sub_id: int, user_id: int, results: dict[int, float | None]) -> list[str] | None:
    """مرتب‌سازی و ذخیره کانفیگ‌های اشتراک اصلی بر اساس پینگ (+ برچسب سریع‌ترین)."""
    sub = get_sub(sub_id, user_id)
    if not sub:
        return None
    new_configs = sort_configs_by_ping(sub["configs"], results)
    update_configs(sub_id, user_id, new_configs)
    return new_configs


def sort_generated_configs_by_ping(gen_id: int, user_id: int, results: dict[int, float | None]) -> list[str] | None:
    """مرتب‌سازی و ذخیره کانفیگ‌های اشتراک سفارشی (+ items) بر اساس پینگ و برچسب سریع‌ترین."""
    from config_parser import get_remark, strip_strongest_label, with_strongest_label

    conn = _conn()
    row = conn.execute(
        "SELECT configs, items FROM generated_subs WHERE id=? AND user_id=?",
        (gen_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return None
    configs = json.loads(row[0])
    items = None
    if row[1]:
        try:
            items = json.loads(row[1])
        except Exception:
            items = None
    order = list(range(len(configs)))
    order.sort(
        key=lambda i: (
            results.get(i) is None,
            results.get(i) if results.get(i) is not None else 0,
        )
    )
    # نتایج را به ترتیب جدید نگه می‌داریم تا sort_configs_by_ping درست برچسب بزند
    # configs در ترتیب قدیمی است؛ results با ایندکس قدیمی
    new_configs = sort_configs_by_ping(configs, results)

    new_items = None
    if isinstance(items, list) and len(items) == len(configs):
        new_items = [items[i] for i in order]
        # هم‌تراز کردن name در items با remark نهایی (برای لایو)
        for i, it in enumerate(new_items):
            if not isinstance(it, dict):
                continue
            it = dict(it)
            remark = get_remark(new_configs[i]) if i < len(new_configs) else ""
            if remark:
                it["name"] = remark
            else:
                if it.get("name"):
                    it["name"] = strip_strongest_label(str(it["name"]))
            new_items[i] = it
    else:
        new_items = _ensure_generated_items(new_configs, None)

    # پین‌شده‌ها همیشه بالای لیست بمانند
    if isinstance(new_items, list) and len(new_items) == len(new_configs):
        new_configs, new_items = _pinned_first(new_configs, new_items)

    conn.execute(
        "UPDATE generated_subs SET configs=?, items=? WHERE id=? AND user_id=?",
        (
            json.dumps(new_configs),
            json.dumps(new_items) if new_items is not None else None,
            gen_id,
            user_id,
        ),
    )
    conn.commit()
    conn.close()
    return new_configs


def cleanup_old_expired_generated(grace_days: int = 7) -> int:
    """
    اشتراک‌های سفارشی که بیش از grace_days از تاریخ انقضایشان گذشته را
    به صورت خودکار از دیتابیس حذف می‌کند. تعداد حذف‌شده را برمی‌گرداند.
    """
    from datetime import timedelta

    conn = _conn()
    rows = conn.execute(
        "SELECT id, expires_at FROM generated_subs WHERE expires_at IS NOT NULL AND expires_at != ''"
    ).fetchall()
    now = datetime.now(timezone.utc)
    to_delete = []
    for gid, exp in rows:
        try:
            exp_dt = datetime.fromisoformat(exp)
            if exp_dt + timedelta(days=grace_days) < now:
                to_delete.append(gid)
        except Exception:
            continue
    if to_delete:
        conn.executemany("DELETE FROM generated_subs WHERE id=?", [(i,) for i in to_delete])
        conn.commit()
    conn.close()
    return len(to_delete)


def add_configs_to_generated(
    gen_id: int,
    user_id: int,
    new_configs: list[str],
    new_items: list[dict] | None = None,
) -> int | None:
    """کانفیگ‌های جدید (+ آیتم‌های منبع) را به اشتراک سفارشی اضافه می‌کند."""
    conn = _conn()
    row = conn.execute(
        "SELECT configs, items FROM generated_subs WHERE id=? AND user_id=?",
        (gen_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return None
    existing = json.loads(row[0])
    existing.extend(new_configs)
    from config_parser import disambiguate_duplicates
    existing = disambiguate_duplicates(existing)
    items = None
    if row[1]:
        try:
            items = json.loads(row[1])
        except Exception:
            items = []
    if new_items:
        if items is None:
            items = []
        items.extend(new_items)
    conn.execute(
        "UPDATE generated_subs SET configs=?, items=? WHERE id=? AND user_id=?",
        (json.dumps(existing), json.dumps(items) if items is not None else None, gen_id, user_id),
    )
    conn.commit()
    conn.close()
    return len(existing)


def _resolve_one_item(item: dict, user_id: int, subs_cache: dict) -> tuple[str | None, str | None]:
    """یک آیتم منبع را به کانفیگ خام فعلی تبدیل می‌کند.
    خروجی: (raw_config_or_None, new_fingerprint_or_None)
    اولویت تطبیق:
      ۱) اثرانگشت (fp) — دقیق‌ترین
      ۲) ایندکس — اگر fp عوض شده باشد (مثلاً آدرس سرور تغییر کرده)
    اگر name خالی باشد، remark فعلی منبع حفظ می‌شود (لایو).
    اگر name پر باشد، همان اسم سفارشی ادمین اعمال می‌شود.
    """
    from config_parser import config_fingerprint, rename_config

    try:
        sub_id = int(item["sub_id"])
    except (KeyError, TypeError, ValueError):
        return None, None

    sub = subs_cache.get(sub_id)
    if sub is None:
        sub = get_sub(sub_id, user_id)
        if not sub:
            return None, None
        subs_cache[sub_id] = sub

    configs = sub.get("configs") or []
    fp = item.get("fp") or ""
    idx = item.get("index")
    raw = None
    new_fp = None

    # ۱) جستجو با اثرانگشت
    # اگر چند کانفیگ fp یکسان داشته باشند (دادهٔ قدیمی قبل از لحاظ remark)،
    # ترجیح با ایندکس ذخیره‌شده است تا Usage و Active قاطی نشوند.
    if fp:
        matches = [i for i, cand in enumerate(configs) if config_fingerprint(cand) == fp]
        if len(matches) == 1:
            raw = configs[matches[0]]
            new_fp = config_fingerprint(raw)
        elif len(matches) > 1:
            if isinstance(idx, int) and idx in matches:
                raw = configs[idx]
            else:
                raw = configs[matches[0]]
            new_fp = config_fingerprint(raw)

    # ۲) اگر پیدا نشد، از ایندکس استفاده کن (کانفیگ جابه‌جا / remark عوض شده)
    if raw is None and isinstance(idx, int) and 0 <= idx < len(configs):
        raw = configs[idx]
        new_fp = config_fingerprint(raw)

    if raw is None:
        return None, None

    custom_name = (item.get("name") or "").strip()
    if custom_name:
        raw = rename_config(raw, custom_name)
    return raw, new_fp


def resolve_generated_configs(gen: dict, persist: bool = True) -> list[str]:
    """کانفیگ‌های لایو اشتراک سفارشی را از روی منابع فعلی می‌سازد.
    اگر items نباشد، همان snapshot ذخیره‌شده برمی‌گردد.
    اثرانگشت‌های به‌روز شده هم در items ذخیره می‌شوند.
    """
    items = gen.get("items")
    snapshot = list(gen.get("configs") or [])
    if not items:
        return snapshot

    user_id = gen.get("user_id")
    if user_id is None:
        return snapshot

    subs_cache: dict = {}
    resolved: list[str] = []
    items_updated = False
    new_items = list(items)

    for i, item in enumerate(items):
        raw, new_fp = _resolve_one_item(item, user_id, subs_cache)
        if raw is not None:
            resolved.append(raw)
            # اگر اثرانگشت عوض شده، در recipe به‌روز کن تا دفعه بعد بهتر پیدا شود
            if new_fp and new_fp != (item.get("fp") or ""):
                new_items[i] = dict(item)
                new_items[i]["fp"] = new_fp
                items_updated = True
        elif i < len(snapshot):
            # منبع در دسترس نیست — آخرین نسخه ذخیره‌شده
            resolved.append(snapshot[i])

    # ترتیب پین را حفظ کن (پین‌شده‌ها بالا)
    if isinstance(new_items, list) and len(new_items) == len(resolved):
        resolved, new_items = _pinned_first(resolved, new_items)
        items_updated = True

    if persist and resolved and gen.get("id") is not None:
        conn = _conn()
        if items_updated:
            conn.execute(
                "UPDATE generated_subs SET configs=?, items=? WHERE id=?",
                (json.dumps(resolved), json.dumps(new_items), gen["id"]),
            )
            gen["items"] = new_items
        else:
            conn.execute(
                "UPDATE generated_subs SET configs=? WHERE id=?",
                (json.dumps(resolved), gen["id"]),
            )
        conn.commit()
        conn.close()
        gen["configs"] = resolved

    return resolved


def get_source_sub_ids(gen: dict) -> list[int]:
    """لیست یکتای sub_id های منبع برای یک اشتراک سفارشی."""
    items = gen.get("items") or []
    ids = []
    seen = set()
    for it in items:
        try:
            sid = int(it["sub_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if sid not in seen and sid > 0:
            seen.add(sid)
            ids.append(sid)
    return ids



def delete_config_from_generated(gen_id: int, user_id: int, idx: int) -> int | None:
    """حذف یک کانفیگ از اشتراک سفارشی (و آیتم منبع متناظر). تعداد باقی‌مانده یا None."""
    conn = _conn()
    row = conn.execute(
        "SELECT configs, items FROM generated_subs WHERE id=? AND user_id=?",
        (gen_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return None
    configs = json.loads(row[0])
    if idx < 0 or idx >= len(configs):
        conn.close()
        return None
    configs.pop(idx)
    items = None
    if row[1]:
        try:
            items = json.loads(row[1])
        except Exception:
            items = None
    if isinstance(items, list) and idx < len(items):
        items.pop(idx)
    conn.execute(
        "UPDATE generated_subs SET configs=?, items=? WHERE id=? AND user_id=?",
        (json.dumps(configs), json.dumps(items) if items is not None else None, gen_id, user_id),
    )
    conn.commit()
    conn.close()
    return len(configs)


def rename_config_in_generated(gen_id: int, user_id: int, idx: int, new_name: str) -> str | None:
    """رنیم یک کانفیگ داخل اشتراک سفارشی. remark جدید یا None در صورت خطا."""
    from config_parser import rename_config, get_remark

    conn = _conn()
    row = conn.execute(
        "SELECT configs, items FROM generated_subs WHERE id=? AND user_id=?",
        (gen_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return None
    configs = json.loads(row[0])
    if idx < 0 or idx >= len(configs):
        conn.close()
        return None
    configs[idx] = rename_config(configs[idx], new_name)
    items = None
    if row[1]:
        try:
            items = json.loads(row[1])
        except Exception:
            items = None
    if isinstance(items, list) and idx < len(items) and isinstance(items[idx], dict):
        items[idx]["name"] = new_name
    conn.execute(
        "UPDATE generated_subs SET configs=?, items=? WHERE id=? AND user_id=?",
        (json.dumps(configs), json.dumps(items) if items is not None else None, gen_id, user_id),
    )
    conn.commit()
    conn.close()
    return get_remark(configs[idx]) or new_name


# ---------- بک‌آپ / بازیابی (جابه‌جایی سرور) ----------

BACKUP_VERSION = 1


def export_full_backup() -> dict:
    """
    خروجی کامل دیتابیس برای جابه‌جایی به سرور جدید.
    توکن‌ها و id ها حفظ می‌شوند تا لینک /sub/TOKEN همان بماند.
    """
    conn = _conn()
    subs_rows = conn.execute(
        "SELECT id, user_id, name, note, sub_url, configs, updated_at, last_successful_ping FROM subs ORDER BY id"
    ).fetchall()
    gen_rows = conn.execute(
        "SELECT id, user_id, name, token, configs, created_at, expires_at, items, note, customer_message, last_client_fetch, client_fetch_count, last_successful_ping FROM generated_subs ORDER BY id"
    ).fetchall()
    conn.close()

    subs = []
    for row in subs_rows:
        sid, user_id, name, note, sub_url, configs_json, updated_at = row[:7]
        last_successful_ping = row[7] if len(row) > 7 else ""
        subs.append(
            {
                "id": sid,
                "user_id": user_id,
                "name": name,
                "note": note or "",
                "sub_url": sub_url,
                "configs": json.loads(configs_json),
                "updated_at": updated_at or "",
                "last_successful_ping": last_successful_ping or "",
            }
        )

    generated = []
    for row in gen_rows:
        gid, user_id, name, token, configs_json, created_at, expires_at = row[:7]
        items_json = row[7] if len(row) > 7 else None
        note = row[8] if len(row) > 8 else ""
        customer_message = row[9] if len(row) > 9 else ""
        last_client_fetch = row[10] if len(row) > 10 else ""
        client_fetch_count = row[11] if len(row) > 11 else 0
        last_successful_ping = row[12] if len(row) > 12 else ""
        items = None
        if items_json:
            try:
                items = json.loads(items_json)
            except Exception:
                items = None
        try:
            client_fetch_count = int(client_fetch_count or 0)
        except (TypeError, ValueError):
            client_fetch_count = 0
        generated.append(
            {
                "id": gid,
                "user_id": user_id,
                "name": name,
                "token": token,
                "configs": json.loads(configs_json),
                "created_at": created_at,
                "expires_at": expires_at,
                "items": items,
                "note": note or "",
                "customer_message": customer_message or "",
                "last_client_fetch": last_client_fetch or "",
                "client_fetch_count": client_fetch_count,
                "last_successful_ping": last_successful_ping or "",
            }
        )

    return {
        "version": BACKUP_VERSION,
        "type": "eshkhoshbakht_full_backup",
        "exported_at": _now_iso(),
        "subs": subs,
        "generated_subs": generated,
        "stats": {
            "subs_count": len(subs),
            "generated_count": len(generated),
            "total_configs": sum(len(s["configs"]) for s in subs),
            "generated_configs": sum(len(g["configs"]) for g in generated),
        },
    }


def import_full_backup(data: dict, replace: bool = True) -> dict:
    """
    بازیابی بک‌آپ کامل.
    replace=True: همه داده فعلی پاک و با بک‌آپ جایگزین می‌شود (مناسب جابه‌جایی سرور).
    id و token ها دقیقاً مثل بک‌آپ نوشته می‌شوند تا لینک‌ها و ارجاع items درست بمانند.
    """
    if not isinstance(data, dict):
        raise ValueError("فایل بک‌آپ نامعتبر است.")
    if data.get("type") and data.get("type") != "eshkhoshbakht_full_backup":
        raise ValueError("این فایل بک‌آپ خوشبخت نیست.")
    if "subs" not in data or "generated_subs" not in data:
        raise ValueError("فایل بک‌آپ ناقص است (subs یا generated_subs نیست).")

    subs = data.get("subs") or []
    gens = data.get("generated_subs") or []
    if not isinstance(subs, list) or not isinstance(gens, list):
        raise ValueError("ساختار بک‌آپ نامعتبر است.")

    conn = _conn()
    try:
        if replace:
            conn.execute("DELETE FROM generated_subs")
            conn.execute("DELETE FROM subs")
            conn.commit()

        for s in subs:
            configs = s.get("configs") or []
            if not isinstance(configs, list):
                configs = []
            sid = s.get("id")
            if sid is not None and replace:
                conn.execute(
                    "INSERT INTO subs (id, user_id, name, note, sub_url, configs, updated_at, last_successful_ping) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(sid),
                        int(s["user_id"]),
                        s.get("name") or "بدون نام",
                        s.get("note") or "",
                        s.get("sub_url") or "",
                        json.dumps(configs),
                        s.get("updated_at") or _now_iso(),
                        s.get("last_successful_ping") or "",
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO subs (user_id, name, note, sub_url, configs, updated_at, last_successful_ping) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(s["user_id"]),
                        s.get("name") or "بدون نام",
                        s.get("note") or "",
                        s.get("sub_url") or "",
                        json.dumps(configs),
                        s.get("updated_at") or _now_iso(),
                        s.get("last_successful_ping") or "",
                    ),
                )

        for g in gens:
            configs = g.get("configs") or []
            if not isinstance(configs, list):
                configs = []
            token = (g.get("token") or "").strip()
            if not token:
                token = secrets.token_urlsafe(16)
            items = g.get("items")
            items_json = json.dumps(items) if items is not None else None
            gid = g.get("id")
            if gid is not None and replace:
                conn.execute(
                    "INSERT INTO generated_subs (id, user_id, name, token, configs, created_at, expires_at, items, note, customer_message, last_client_fetch, client_fetch_count, last_successful_ping) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(gid),
                        int(g["user_id"]),
                        g.get("name") or "بدون نام",
                        token,
                        json.dumps(configs),
                        g.get("created_at") or _now_iso(),
                        g.get("expires_at"),
                        items_json,
                        g.get("note") or "",
                        g.get("customer_message") or "",
                        g.get("last_client_fetch") or "",
                        int(g.get("client_fetch_count") or 0),
                        g.get("last_successful_ping") or "",
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO generated_subs (user_id, name, token, configs, created_at, expires_at, items, note, customer_message, last_client_fetch, client_fetch_count, last_successful_ping) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(g["user_id"]),
                        g.get("name") or "بدون نام",
                        token,
                        json.dumps(configs),
                        g.get("created_at") or _now_iso(),
                        g.get("expires_at"),
                        items_json,
                        g.get("note") or "",
                        g.get("customer_message") or "",
                        g.get("last_client_fetch") or "",
                        int(g.get("client_fetch_count") or 0),
                        g.get("last_successful_ping") or "",
                    ),
                )

        # به‌روز کردن sequence برای جلوگیری از تداخل id های بعدی
        max_sub = conn.execute("SELECT COALESCE(MAX(id), 0) FROM subs").fetchone()[0]
        max_gen = conn.execute("SELECT COALESCE(MAX(id), 0) FROM generated_subs").fetchone()[0]
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES ('subs', ?)",
                (max_sub,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES ('generated_subs', ?)",
                (max_gen,),
            )
        except Exception:
            # جدول sqlite_sequence ممکن است هنوز نباشد
            pass

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "subs_restored": len(subs),
        "generated_restored": len(gens),
        "tokens_preserved": sum(1 for g in gens if (g.get("token") or "").strip()),
    }
