"""
احراز هویت پنل وب:
- Telegram Login (سیستم جدید OpenID Connect)
- ورود با یوزرنیم / پسورد (متغیرهای محیطی PANEL_USER و PANEL_PASSWORD)
- Telegram Mini App (initData) — برای وقتی پنل داخل خودِ تلگرام باز میشه

نحوه‌ی کار تلگرام (OpenID Connect جدید):
۱. کاربر تو صفحه‌ی لاگین روی «ورود با تلگرام» کلیک می‌کنه.
۲. به https://oauth.telegram.org/auth ریدایرکت می‌شه (با client_id و redirect_uri).
۳. بعد از تأیید، تلگرام با code به /panel/auth/callback برمی‌گرده.
۴. بک‌اند code را با Client Secret عوض می‌کند و id_token (JWT) را وریفای می‌کند.
۵. اگر id توی ADMIN_IDS بود، سشن ساخته می‌شود.

نحوه‌ی کار یوزرنیم/پسورد:
۱. کاربر فرم لاگین رو پر می‌کنه و به /panel/auth/password پست می‌کنه.
۲. با PANEL_USER و PANEL_PASSWORD مقایسه می‌شه (مقایسه‌ی زمان‌ثابت).
۳. سشن با user_id مربوط به ادمین ساخته می‌شه (اولین ADMIN_IDS یا PANEL_USER_ID).

نحوه‌ی کار Mini App:
۱. کاربر از داخل ربات دکمه‌ی «باز کردن پنل» رو می‌زنه.
۲. initData با HMAC-SHA256 (کلید WebAppData) وریفای می‌شه.
۳. اگر معتبر و مجاز بود، سشن ساخته می‌شه.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from urllib.parse import parse_qsl, urlencode

import httpx
import jwt
from aiohttp import web
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}

# ورود با یوزرنیم / پسورد (اختیاری)
PANEL_USER = os.environ.get("PANEL_USER", "").strip()
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "").strip()
_panel_uid_raw = os.environ.get("PANEL_USER_ID", "").strip()
PANEL_USER_ID: int | None = int(_panel_uid_raw) if _panel_uid_raw.isdigit() else None

# سیستم جدید Telegram Login (OpenID Connect)
# Client ID و Client Secret را از بخش Login Widget در BotFather بگیر
TELEGRAM_CLIENT_ID = os.environ.get("TELEGRAM_CLIENT_ID", "").strip()
TELEGRAM_CLIENT_SECRET = os.environ.get("TELEGRAM_CLIENT_SECRET", "").strip()

COOKIE_NAME = "kh_session"
SESSION_TTL = 30 * 24 * 3600  # ۳۰ روز
AUTH_MAX_AGE = 86400  # حداکثر قدمت داده‌ی ورود تلگرام (ثانیه)

# بعد از bot.get_me() توی main() پر میشه
BOT_USERNAME: str = ""

# سشن‌ها فقط تو حافظه نگه داشته می‌شن
_sessions: dict[str, dict] = {}

# state موقت برای OIDC (ضد CSRF)
_oidc_states: dict[str, float] = {}  # state -> expire_timestamp

JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
TOKEN_URL = "https://oauth.telegram.org/token"
AUTH_URL = "https://oauth.telegram.org/auth"
_jwks_client: PyJWKClient | None = None


def password_login_enabled() -> bool:
    return bool(PANEL_USER and PANEL_PASSWORD)


def telegram_oidc_enabled() -> bool:
    return bool(TELEGRAM_CLIENT_ID and TELEGRAM_CLIENT_SECRET)


def panel_enabled() -> bool:
    """پنل وقتی فعاله که ADMIN_IDS یا یوزرنیم/پسورد یا OIDC ست شده باشه."""
    return bool(ADMIN_IDS) or password_login_enabled() or telegram_oidc_enabled()


def _password_session_user_id() -> int | None:
    if PANEL_USER_ID is not None:
        return PANEL_USER_ID
    if ADMIN_IDS:
        return sorted(ADMIN_IDS)[0]
    return 1


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwks_client


def create_oidc_state() -> str:
    """یک state تصادفی برای جلوگیری از CSRF می‌سازد و ذخیره می‌کند."""
    state = secrets.token_urlsafe(24)
    _oidc_states[state] = time.time() + 600  # ۱۰ دقیقه اعتبار
    # پاکسازی stateهای منقضی
    now = time.time()
    expired = [k for k, exp in _oidc_states.items() if exp < now]
    for k in expired:
        _oidc_states.pop(k, None)
    return state


def consume_oidc_state(state: str | None) -> bool:
    if not state:
        return False
    exp = _oidc_states.pop(state, None)
    if exp is None or exp < time.time():
        return False
    return True


def build_telegram_auth_url(redirect_uri: str) -> str | None:
    """آدرس ریدایرکت به صفحهٔ ورود تلگرام را می‌سازد."""
    if not telegram_oidc_enabled():
        return None
    state = create_oidc_state()
    params = {
        "client_id": TELEGRAM_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code_and_verify(code: str, redirect_uri: str) -> int | None:
    """
    code را با Client Secret عوض می‌کند، id_token را وریفای می‌کند
    و در صورت موفقیت user_id تلگرام را برمی‌گرداند.
    """
    if not telegram_oidc_enabled():
        return None

    credentials = f"{TELEGRAM_CLIENT_ID}:{TELEGRAM_CLIENT_SECRET}"
    basic = base64.b64encode(credentials.encode()).decode()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": TELEGRAM_CLIENT_ID,
                },
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if resp.status_code != 200:
                logger.warning("Telegram token exchange failed: %s %s", resp.status_code, resp.text[:300])
                return None
            token_data = resp.json()
    except Exception as e:
        logger.exception("Token exchange error: %s", e)
        return None

    id_token = token_data.get("id_token")
    if not id_token:
        logger.warning("No id_token in token response")
        return None

    try:
        jwks = _get_jwks_client()
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "ES256", "EdDSA"],
            audience=TELEGRAM_CLIENT_ID,
            issuer="https://oauth.telegram.org",
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except Exception as e:
        logger.warning("ID token verification failed: %s", e)
        return None

    # استخراج user_id
    # در توکن‌های تلگرام معمولاً فیلد "id" یا "sub" وجود دارد
    user_id = None
    if "id" in payload:
        try:
            user_id = int(payload["id"])
        except (TypeError, ValueError):
            pass
    if user_id is None and "sub" in payload:
        try:
            user_id = int(payload["sub"])
        except (TypeError, ValueError):
            pass

    if user_id is None:
        logger.warning("Could not extract user_id from id_token payload: %s", payload)
        return None

    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        logger.info("User %s not in ADMIN_IDS", user_id)
        return None

    return user_id


# ---------- سازگاری با ویجت قدیمی (در صورت نیاز) ----------
def verify_telegram_login(data: dict) -> int | None:
    """ویجت قدیمی (legacy) — فقط برای سازگاری نگه داشته شده."""
    received_hash = data.get("hash")
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()) if k != "hash")
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    try:
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - auth_date > AUTH_MAX_AGE:
        return None

    try:
        user_id = int(data.get("id"))
    except (TypeError, ValueError):
        return None

    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        return None

    return user_id


def verify_webapp_init_data(raw_init_data: str) -> int | None:
    """initData ارسالی از Telegram Mini App رو وریفای می‌کنه."""
    if not raw_init_data:
        return None

    try:
        pairs = parse_qsl(raw_init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    try:
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - auth_date > AUTH_MAX_AGE:
        return None

    try:
        user_obj = json.loads(data.get("user", "{}"))
        user_id = int(user_obj["id"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None

    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        return None

    return user_id


def verify_password_login(username: str, password: str) -> int | None:
    if not password_login_enabled():
        return None
    if not username or not password:
        return None
    user_ok = secrets.compare_digest(username.strip(), PANEL_USER)
    pass_ok = secrets.compare_digest(password, PANEL_PASSWORD)
    if not (user_ok and pass_ok):
        return None
    return _password_session_user_id()


def create_session(user_id: int) -> str:
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = {"user_id": user_id, "expires": time.time() + SESSION_TTL}
    return session_id


def get_session_user(session_id: str | None) -> int | None:
    if not session_id:
        return None
    s = _sessions.get(session_id)
    if not s:
        return None
    if s["expires"] < time.time():
        _sessions.pop(session_id, None)
        return None
    return s["user_id"]


def destroy_session(session_id: str | None) -> None:
    if session_id:
        _sessions.pop(session_id, None)


_PUBLIC_PANEL_PATHS = {
    "/panel/login",
    "/panel/auth/callback",
    "/panel/auth/password",
    "/panel/logout",
    "/panel/miniapp",
    "/api/auth/webapp",
}


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path

    if path.startswith("/panel/static/") or path in _PUBLIC_PANEL_PATHS:
        return await handler(request)

    if path.startswith("/api/"):
        session_id = request.cookies.get(COOKIE_NAME)
        user_id = get_session_user(session_id)
        if user_id is None:
            return web.json_response({"error": "لاگین نکردی یا سشنت منقضی شده."}, status=401)
        request["user_id"] = user_id

    return await handler(request)
