"""Username and password sign-in.

- Passwords are stored only as salted PBKDF2-SHA256 hashes (600,000 rounds).
- After 5 wrong passwords an account is locked for 15 minutes.
- "Keep me signed in" stores a random token in a browser cookie; the database
  keeps only a hash of it, so a leaked database can't be used to sign in.
- The first person to register becomes the owner. Everyone after that needs the
  family invite code, which the owner can see and change in Settings.
"""
import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from core.db import fetch_one, invalidate, run_many, transact

ITERATIONS = 600_000
MAX_TRIES = 5
LOCK_MINUTES = 15
REMEMBER_DAYS = 30
SHORT_SESSION_HOURS = 12
COOKIE = "cashew_session"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,29}$")
MIN_PASSWORD = 8


# ---- passwords -------------------------------------------------------------
def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(test, base64.b64decode(digest))
    except Exception:
        return False


_DUMMY = hash_password(secrets.token_hex(8))  # checked when a username doesn't exist, so timing gives nothing away


# ---- checks used for live validation ------------------------------------------------
def username_problem(username):
    u = (username or "").strip().lower()
    if not u:
        return "Choose a username."
    if not USERNAME_RE.match(u):
        return "Use 3 to 30 letters, numbers, dots, dashes or underscores, starting with a letter or number."
    return None


def username_taken(username):
    return fetch_one("SELECT 1 FROM users WHERE username = %s", ((username or "").strip().lower(),)) is not None


def password_problem(password, username=""):
    if len(password or "") < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if username and password.lower() == username.strip().lower():
        return "Don't use your username as your password."
    if password.lower() in {"password", "password1", "12345678", "123456789", "cashew123", "qwertyui"}:
        return "That password is too easy to guess."
    return None


def password_strength(password):
    """Rough strength, for the hint under the password box."""
    p = password or ""
    kinds = sum(bool(re.search(r, p)) for r in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    score = (len(p) >= 8) + (len(p) >= 12) + (kinds >= 2) + (kinds >= 3)
    return ["Weak", "Weak", "Fair", "Good", "Strong"][score]


# ---- accounts --------------------------------------------------------------
def user_count():
    return fetch_one("SELECT count(*) FROM users")[0]


def invite_code():
    row = fetch_one("SELECT value FROM app_meta WHERE key = 'invite_code'")
    return row[0] if row else None


def new_invite_code():
    code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    run_many([("INSERT INTO app_meta (key, value) VALUES ('invite_code', %s) "
               "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (code,))], refresh=False)
    return code


def _public(row):
    uid, username, name, owner = row
    return {"id": uid, "username": username, "name": name, "is_owner": bool(owner)}


def register(username, display_name, password, code=None):
    """Create an account. Returns (user, None) or (None, reason)."""
    username = username.strip().lower()
    display_name = (display_name or "").strip() or username.title()
    if username_problem(username):
        return None, username_problem(username)
    if password_problem(password, username):
        return None, password_problem(password, username)
    hashed = hash_password(password)  # slow on purpose, so done before the users table is locked

    def work(conn):
        with conn.cursor() as cur:
            # lock so two people can't both become the first (owner) account at once
            cur.execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE")
            cur.execute("SELECT count(*) FROM users")
            first = cur.fetchone()[0] == 0
            if not first:
                cur.execute("SELECT value FROM app_meta WHERE key = 'invite_code'")
                row = cur.fetchone()
                if not row or not code or not hmac.compare_digest(row[0].upper(), code.strip().upper()):
                    return None, "That invite code isn't right. Ask the account owner for the current code."
            cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return None, "That username is taken."
            cur.execute(
                "INSERT INTO users (username, display_name, password_hash, is_owner, last_login) "
                "VALUES (%s, %s, %s, %s, now()) RETURNING id, username, display_name, is_owner",
                (username, display_name, hashed, first),
            )
            return _public(cur.fetchone()), None

    user, err = transact(work)
    if user:
        invalidate()  # so the new person shows up straight away
        if user["is_owner"]:
            new_invite_code()
    return user, err


def sign_in(username, password):
    """Returns (user, None) or (None, reason). Wrong username and wrong password get the same message."""
    username = (username or "").strip().lower()
    row = fetch_one(
        "SELECT id, username, display_name, is_owner, password_hash, failed_logins, locked_until "
        "FROM users WHERE username = %s", (username,))
    if row is None:
        check_password(password or "", _DUMMY)
        return None, "Wrong username or password."
    uid, uname, name, owner, stored, failed, locked_until = row
    now = datetime.now(timezone.utc)
    if locked_until and locked_until > now:
        mins = max(1, int((locked_until - now).total_seconds() // 60) + 1)
        return None, f"Too many wrong tries. Try again in {mins} minute{'s' if mins != 1 else ''}."
    if not check_password(password or "", stored):
        failed += 1
        lock = now + timedelta(minutes=LOCK_MINUTES) if failed >= MAX_TRIES else None
        run_many([("UPDATE users SET failed_logins = %s, locked_until = %s WHERE id = %s",
                   (0 if lock else failed, lock, uid))], refresh=False)
        if lock:
            return None, f"Too many wrong tries. Try again in {LOCK_MINUTES} minutes."
        left = MAX_TRIES - failed
        return None, f"Wrong username or password. {left} tr{'ies' if left != 1 else 'y'} left before a short lock."
    run_many([("UPDATE users SET failed_logins = 0, locked_until = NULL, last_login = now() WHERE id = %s", (uid,))],
             refresh=False)
    return _public((uid, uname, name, owner)), None


def change_password(user_id, current, new, keep_token=None):
    """Change your own password. Every other device you're signed in on is signed out (a lost phone stops
    working); the browser making the change, whose token is keep_token, stays signed in."""
    row = fetch_one("SELECT username, password_hash FROM users WHERE id = %s", (user_id,))
    if not row or not check_password(current, row[1]):
        return "Your current password isn't right."
    problem = password_problem(new, row[0])
    if problem:
        return problem
    run_many([
        ("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(new), user_id)),
        ("DELETE FROM sessions WHERE user_id = %s AND token_hash <> %s", (user_id, _token_hash(keep_token))),
    ])  # refresh, so the other open browsers notice and sign out
    return None


def set_password(user_id, new, username=""):
    """Owner resets someone's password. Signs them out everywhere."""
    problem = password_problem(new, username)
    if problem:
        return problem
    run_many([
        ("UPDATE users SET password_hash = %s, failed_logins = 0, locked_until = NULL WHERE id = %s",
         (hash_password(new), user_id)),
        ("DELETE FROM sessions WHERE user_id = %s", (user_id,)),
    ])  # refresh, so their open browsers notice and sign out
    return None


# ---- remembered sessions -----------------------------------------------------
def token_hash(token):
    return hashlib.sha256((token or "").encode()).hexdigest()


_token_hash = token_hash


def start_session(user_id, remember):
    """Returns (token, max_age_seconds or None). The token goes in a cookie; only its hash is stored."""
    token = secrets.token_urlsafe(32)
    lifetime = timedelta(days=REMEMBER_DAYS) if remember else timedelta(hours=SHORT_SESSION_HOURS)
    run_many([
        ("DELETE FROM sessions WHERE expires_at < now()", None),
        ("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
         (_token_hash(token), user_id, lifetime)),
    ])  # refresh, so the new session is in the list of live ones straight away
    return token, int(lifetime.total_seconds()) if remember else None


def user_for_token(token):
    if not token or len(token) > 100:
        return None
    row = fetch_one(
        "SELECT u.id, u.username, u.display_name, u.is_owner FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = %s AND s.expires_at > now()", (_token_hash(token),))
    return _public(row) if row else None


def end_session(token):
    if token:
        run_many([("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))], refresh=False)
