"""
پارس و رنیم کردن کانفیگ‌های داخل یک لینک اشتراک (subscription).
پشتیبانی از: vmess, vless, trojan, ss (shadowsocks), ssr, hysteria2, tuic
"""
import base64
import json
import re
from urllib.parse import quote, unquote, urlparse


def _b64decode(s: str) -> bytes:
    s = s.strip().replace("-", "+").replace("_", "/")
    padding = "=" * (-len(s) % 4)
    return base64.b64decode(s + padding)


def decode_subscription(content: str) -> list[str]:
    """محتوای body لینک اشتراک (معمولا base64) رو به لیست خطوط کانفیگ خام تبدیل می‌کنه."""
    content = content.strip()
    try:
        decoded = _b64decode(content).decode("utf-8", errors="ignore")
    except Exception:
        decoded = content  # شاید از قبل متن ساده (plain) باشه

    lines = [line.strip() for line in decoded.splitlines() if line.strip()]
    # فیلتر کردن خطوطی که واقعا شبیه یک URI کانفیگ هستن
    lines = [l for l in lines if "://" in l]
    return lines


def encode_subscription(configs: list[str]) -> str:
    """لیست کانفیگ‌ها رو به یک رشته base64 (لینک اشتراک) تبدیل می‌کنه."""
    body = "\n".join(configs)
    return base64.b64encode(body.encode("utf-8")).decode("utf-8")


def get_protocol(raw: str) -> str:
    return raw.split("://", 1)[0] if "://" in raw else "unknown"


def get_remark(raw: str) -> str:
    """اسم فعلی (remark) یک کانفیگ رو استخراج می‌کنه."""
    if raw.startswith("vmess://"):
        try:
            data = json.loads(_b64decode(raw[len("vmess://"):]))
            return data.get("ps", "")
        except Exception:
            return ""
    if "#" in raw:
        try:
            return unquote(raw.split("#", 1)[1])
        except Exception:
            return raw.split("#", 1)[1]
    return ""


def get_host_port(raw: str) -> tuple[str, int] | None:
    """آدرس سرور و پورت رو از یک کانفیگ خام استخراج می‌کنه (برای تست پینگ)."""
    if raw.startswith("vmess://"):
        try:
            data = json.loads(_b64decode(raw[len("vmess://"):]))
            host = data.get("add")
            port = int(data.get("port"))
            if host and port:
                return host, port
        except Exception:
            pass
        return None

    try:
        parsed = urlparse(raw)
        if parsed.hostname and parsed.port:
            return parsed.hostname, parsed.port
    except Exception:
        pass

    # فرمت قدیمی ss:// که همه چیز قبل از # به صورت base64 هست
    if raw.startswith("ss://"):
        try:
            body = raw[len("ss://"):].split("#", 1)[0]
            decoded = _b64decode(body).decode("utf-8", errors="ignore")
            m = re.search(r"@([^:/?#]+):(\d+)", decoded)
            if m:
                return m.group(1), int(m.group(2))
        except Exception:
            pass

    return None



# ---------- پرچم کشور از روی اسم ----------

# نام‌های رایج (فارسی + انگلیسی) → پرچم
# کلیدها lowercase؛ تطبیق با کلمه کامل در اسم
_COUNTRY_FLAGS: list[tuple[tuple[str, ...], str]] = [
    # طولانی‌ترها اول تا «united states» قبل از «us» نیاید به‌اشتباه — با word boundary کار می‌کنیم
    (("united arab emirates", "امارات", "dubai", "دبی", "uae"), "🇦🇪"),
    (("united states", "آمریکا", "امریکا", "usa", "america", "us"), "🇺🇸"),
    (("united kingdom", "انگلستان", "بریتانیا", "england", "britain", "uk"), "🇬🇧"),
    (("saudi arabia", "عربستان", "سعودی"), "🇸🇦"),
    (("south korea", "کره جنوبی", "کره"), "🇰🇷"),
    (("north korea", "کره شمالی"), "🇰🇵"),
    (("hong kong", "هنگ کنگ", "هنگ‌کنگ"), "🇭🇰"),
    (("new zealand", "نیوزیلند", "نیوزلند"), "🇳🇿"),
    (("south africa", "آفریقای جنوبی"), "🇿🇦"),
    (("czech", "چک", "czechia"), "🇨🇿"),
    (("iran", "ایران", "ir"), "🇮🇷"),
    (("germany", "آلمان", "deutschland", "de"), "🇩🇪"),
    (("france", "فرانسه", "fr"), "🇫🇷"),
    (("netherlands", "netherland", "هلند", "holland", "nl"), "🇳🇱"),
    (("albania", "آلبانی", "al"), "🇦🇱"),
    (("turkey", "turkiye", "türkiye", "ترکیه", "tr"), "🇹🇷"),
    (("canada", "کانادا", "ca"), "🇨🇦"),
    (("japan", "ژاپن", "jp"), "🇯🇵"),
    (("china", "چین", "cn"), "🇨🇳"),
    (("russia", "روسیه", "ru"), "🇷🇺"),
    (("india", "هند", "in"), "🇮🇳"),
    (("singapore", "سنگاپور", "sg"), "🇸🇬"),
    (("sweden", "سوئد", "se"), "🇸🇪"),
    (("switzerland", "سوئیس", "ch"), "🇨🇭"),
    (("austria", "اتریش", "at"), "🇦🇹"),
    (("italy", "ایتالیا", "it"), "🇮🇹"),
    (("spain", "اسپانیا", "es"), "🇪🇸"),
    (("poland", "لهستان", "pl"), "🇵🇱"),
    (("finland", "فنلاند", "fi"), "🇫🇮"),
    (("norway", "نروژ", "no"), "🇳🇴"),
    (("denmark", "دانمارک", "dk"), "🇩🇰"),
    (("belgium", "بلژیک", "be"), "🇧🇪"),
    (("portugal", "پرتغال", "pt"), "🇵🇹"),
    (("greece", "یونان", "gr"), "🇬🇷"),
    (("ireland", "ایرلند", "ie"), "🇮🇪"),
    (("australia", "استرالیا", "au"), "🇦🇺"),
    (("brazil", "برزیل", "br"), "🇧🇷"),
    (("mexico", "مکزیک", "mx"), "🇲🇽"),
    (("argentina", "آرژانتین", "ar"), "🇦🇷"),
    (("ukraine", "اوکراین", "ua"), "🇺🇦"),
    (("romania", "رومانی", "ro"), "🇷🇴"),
    (("bulgaria", "بلغارستان", "bg"), "🇧🇬"),
    (("hungary", "مجارستان", "hu"), "🇭🇺"),
    (("serbia", "صربستان", "rs"), "🇷🇸"),
    (("croatia", "کرواسی", "hr"), "🇭🇷"),
    (("slovakia", "اسلواکی", "sk"), "🇸🇰"),
    (("slovenia", "اسلوونی", "si"), "🇸🇮"),
    (("lithuania", "لیتوانی", "lt"), "🇱🇹"),
    (("latvia", "لتونی", "lv"), "🇱🇻"),
    (("estonia", "استونی", "ee"), "🇪🇪"),
    (("iceland", "ایسلند", "is"), "🇮🇸"),
    (("luxembourg", "لوکزامبورگ", "lu"), "🇱🇺"),
    (("malaysia", "مالزی", "my"), "🇲🇾"),
    (("thailand", "تایلند", "th"), "🇹🇭"),
    (("vietnam", "ویتنام", "vn"), "🇻🇳"),
    (("indonesia", "اندونزی", "id"), "🇮🇩"),
    (("philippines", "فیلیپین", "ph"), "🇵🇭"),
    (("taiwan", "تایوان", "tw"), "🇹🇼"),
    (("israel", "اسرائیل", "il"), "🇮🇱"),
    (("iraq", "عراق", "iq"), "🇮🇶"),
    (("qatar", "قطر", "qa"), "🇶🇦"),
    (("kuwait", "کویت", "kw"), "🇰🇼"),
    (("bahrain", "بحرین", "bh"), "🇧🇭"),
    (("oman", "عمان", "om"), "🇴🇲"),
    (("egypt", "مصر", "eg"), "🇪🇬"),
    (("pakistan", "پاکستان", "pk"), "🇵🇰"),
    (("afghanistan", "افغانستان", "af"), "🇦🇫"),
    (("azerbaijan", "آذربایجان", "az"), "🇦🇿"),
    (("armenia", "ارمنستان", "am"), "🇦🇲"),
    (("georgia", "گرجستان", "ge"), "🇬🇪"),
    (("kazakhstan", "قزاقستان", "kz"), "🇰🇿"),
    (("uzbekistan", "ازبکستان", "uz"), "🇺🇿"),
    (("cyprus", "قبرس", "cy"), "🇨🇾"),
    (("moldova", "مولداوی", "md"), "🇲🇩"),
    (("belarus", "بلاروس", "by"), "🇧🇾"),
    (("chile", "شیلی", "cl"), "🇨🇱"),
    (("colombia", "کلمبیا", "co"), "🇨🇴"),
    (("peru", "پرو", "pe"), "🇵🇪"),
    (("nigeria", "نیجریه", "ng"), "🇳🇬"),
    (("kenya", "کنیا", "ke"), "🇰🇪"),
    (("morocco", "مراکش", "ma"), "🇲🇦"),
]


def _strip_leading_flags(text: str) -> str:
    """پرچم‌های ابتدای رشته را برمی‌دارد (برای جلوگیری از تکرار)."""
    out = text.strip()
    # پرچم‌ها معمولاً دو codepoint منطقه‌ای هستند
    while out:
        # اگر با regional indicator pair شروع شود
        if len(out) >= 2 and "\U0001F1E6" <= out[0] <= "\U0001F1FF" and "\U0001F1E6" <= out[1] <= "\U0001F1FF":
            out = out[2:].lstrip(" \t-|–—:")
            continue
        break
    return out


def apply_country_flag(name: str) -> str:
    """
    اگر در اسم کانفیگ نام کشور باشد و پرچم نباشد، پرچم را اول اسم می‌گذارد.
    اگر از قبل پرچم باشد، عوض نمی‌کند مگر اینکه کشور دیگری در متن باشد.
    """
    if not name or not name.strip():
        return name
    original = name.strip()
    body = _strip_leading_flags(original)
    lower = body.casefold()
    # نرمال‌سازی ی فارسی
    lower = lower.replace("ي", "ی").replace("ك", "ک")

    matched_flag = None
    matched_len = 0
    for names, flag in _COUNTRY_FLAGS:
        for n in names:
            key = n.casefold().replace("ي", "ی").replace("ك", "ک")
            # کدهای دو حرفی فقط به‌صورت کلمهٔ جدا
            if len(key) <= 2:
                pattern = r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])"
            else:
                # فارسی/لاتین: زیررشته با مرز نرم
                pattern = r"(?<![a-zA-Z0-9\u0600-\u06FF])" + re.escape(key) + r"(?![a-zA-Z0-9\u0600-\u06FF])"
            if re.search(pattern, lower, flags=re.IGNORECASE):
                if len(key) > matched_len:
                    matched_flag = flag
                    matched_len = len(key)

    if not matched_flag:
        return original

    # اگر همین پرچم از قبل اول اسم بود
    if original.startswith(matched_flag):
        return original

    return f"{matched_flag} {body}"



STRONGEST_LABEL = " (سریع ترین)"


def strip_strongest_label(name: str) -> str:
    """برچسب «سریع ترین» را از انتهای اسم برمی‌دارد (اگر باشد)."""
    text = (name or "").strip()
    for suffix in (
        STRONGEST_LABEL,
        "(سریع ترین)",
        "سریع ترین",
        "(قوی ترین)",
        "قوی ترین",
        " (قوی ترین)",
    ):
        suf = suffix.strip()
        if text.endswith(suf):
            text = text[: -len(suf)].rstrip(" -_|")
        text = text.replace(suffix, "")
        text = " ".join(text.split())
    return text.strip()


def with_strongest_label(name: str) -> str:
    base = strip_strongest_label(name) or name or ""
    if not base:
        base = "بدون نام"
    return base + STRONGEST_LABEL


def rename_config(raw: str, new_name: str) -> str:
    """یک کانفیگ خام رو با اسم جدید برمی‌گردونه (پرچم کشور خودکار اگر نام کشور باشد)."""
    new_name = apply_country_flag((new_name or "").strip())
    if raw.startswith("vmess://"):
        try:
            data = json.loads(_b64decode(raw[len("vmess://"):]))
            data["ps"] = new_name
            new_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            new_b64 = base64.b64encode(new_json.encode("utf-8")).decode("utf-8")
            return f"vmess://{new_b64}"
        except Exception:
            return raw
    else:
        base = raw.split("#", 1)[0]
        return f"{base}#{quote(new_name)}"


def config_fingerprint(raw: str) -> str:
    """شناسه کانفیگ برای همگام‌سازی با منبع.

    host/port/id به‌تنهایی کافی نیست: بعضی ساب‌ها چند نود «اطلاعاتی»
    با آدرس یکسان (مثلاً 127.0.0.1) و فقط remark متفاوت دارند
    (مثل Usage و Active). اگر remark در اثرانگشت نباشد، هر دو به
    یک کانفیگ resolve می‌شوند و اسم‌ها یکی می‌شود.

    remark هم بخشی از اثرانگشت است تا این نودها جدا بمانند.
    اگر منبع remark را عوض کند (مثلاً عدد مصرف)، fp عوض می‌شود
    و resolve با fallback روی index به نسخهٔ جدید می‌رسد.
    """
    proto = get_protocol(raw)
    hp = get_host_port(raw)
    host_port = f"{hp[0]}:{hp[1]}" if hp else ""
    remark = get_remark(raw) or ""
    if raw.startswith("vmess://"):
        try:
            data = json.loads(_b64decode(raw[len("vmess://"):]))
            uid = data.get("id") or ""
            return f"vmess|{host_port}|{uid}|{remark}"
        except Exception:
            pass
    try:
        base = raw.split("#", 1)[0]
        return f"{proto}|{host_port}|{base[-48:]}|{remark}"
    except Exception:
        return f"{proto}|{raw[:64]}|{remark}"


# ---------- کانفیگ فیک نمایش‌دهنده مدت اعتبار ----------

def remaining_time_text(expires_at: str | None) -> str:
    """متن فارسی مدت اعتبار باقی‌مانده (یا وضعیت منقضی / بدون محدودیت)."""
    from datetime import datetime, timezone

    if not expires_at:
        return "♾ بدون محدودیت زمانی"
    try:
        exp_dt = datetime.fromisoformat(expires_at)
        now = datetime.now(timezone.utc)
        if exp_dt <= now:
            return "⛔ اشتراک شما به اتمام رسیده"
        delta = exp_dt - now
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        if days > 0:
            return f"⏳ باقیمانده: {days} روز و {hours} ساعت"
        if hours > 0:
            return f"⏳ باقیمانده: {hours} ساعت و {minutes} دقیقه"
        return f"⏳ باقیمانده: {minutes} دقیقه"
    except Exception:
        return "⏰ تاریخ انقضا نامعتبر"


def make_expiry_info_config(expires_at: str | None) -> str:
    """
    کانفیگ فیک برای نمایش مدت اعتبار در لیست کانفیگ‌های کلاینت.
    هر بار که مشتری ساب را آپدیت کند، با مقدار به‌روز ساخته می‌شود.
    """
    remark = remaining_time_text(expires_at)
    return (
        "vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1"
        f"?encryption=none&security=none&type=tcp#{quote(remark)}"
    )


def make_customer_message_config(message: str) -> str:
    """
    کانفیگ فیک برای نمایش پیام ادمین به مشتری در لیست کانفیگ‌های کلاینت.
    """
    text = (message or "").strip()
    if not text:
        return ""
    # محدودیت طول remark در بعضی کلاینت‌ها
    if len(text) > 80:
        text = text[:77] + "…"
    remark = f"📢 {text}"
    return (
        "vless://00000000-0000-0000-0000-000000000001@127.0.0.1:1"
        f"?encryption=none&security=none&type=tcp#{quote(remark)}"
    )


# ---------- متمایزسازی کانفیگ‌های هم‌فینگرپرینت (بدون حذف) ----------


def _split_query(raw: str) -> tuple[str, dict, str]:
    """base (قبل از ?) ، دیکشنری پارامترهای query ، fragment (بعد از #) رو برمی‌گردونه."""
    body, _, frag = raw.partition("#")
    base, sep, query = body.partition("?")
    params: dict[str, str] = {}
    if sep:
        for part in query.split("&"):
            if not part:
                continue
            k, _, v = part.partition("=")
            params[k] = v
    return base, params, frag


def _join_query(base: str, params: dict, frag: str) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    result = f"{base}?{query}" if query else base
    if frag:
        result += f"#{frag}"
    return result


def _disambiguate_one(raw: str, salt: int) -> str:
    """
    یه کپی «تکنیکی یکسان» رو با یه فیلد بی‌اثر (که رو مسیر واقعی اتصال تأثیر نداره)
    از بقیه متمایز می‌کنه، تا کلاینت اونا رو به‌جای یک نود، چند نود جدا ببینه.
    remark (اسم) دست‌نخورده می‌مونه.
    """
    proto = get_protocol(raw)

    if proto == "vmess":
        try:
            data = json.loads(_b64decode(raw[len("vmess://"):]))
            # فیلد ناشناخته — کلاینت‌های vmess فیلدهای ناآشنا رو نادیده می‌گیرن، رو مسیر تأثیر نداره
            data["_dd"] = salt
            new_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            new_b64 = base64.b64encode(new_json.encode("utf-8")).decode("utf-8")
            return f"vmess://{new_b64}"
        except Exception:
            return raw

    if "?" not in raw:
        return raw

    base, params, frag = _split_query(raw)
    if params.get("security") == "reality":
        # spx (spiderX) فقط رو ترافیک نمایشی reality اثر داره، نه رو تونل واقعی
        params["spx"] = quote(f"/{salt}")
    else:
        params["_dd"] = str(salt)
    return _join_query(base, params, frag)


def disambiguate_duplicates(configs: list[str]) -> list[str]:
    """
    اگه چند کانفیگ فینگرپرینت یکسان داشته باشن (یعنی از نظر اتصال واقعاً یکی‌ان،
    فقط اسمشون فرق داره)، نسخه‌های بعد از اولی رو با یه فیلد بی‌اثر متمایز می‌کنه
    تا کلاینت همه‌شون رو جدا نشون بده. هیچ کانفیگی حذف نمی‌شه، ترتیب حفظ می‌شه.
    """
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw in configs:
        fp = config_fingerprint(raw)
        count = seen.get(fp, 0)
        seen[fp] = count + 1
        if count == 0:
            result.append(raw)
        else:
            result.append(_disambiguate_one(raw, count))
    return result
