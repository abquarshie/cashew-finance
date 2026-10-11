"""Sign-in, registration and the remembered-session cookie."""
import base64
import json
from pathlib import Path

import streamlit as st

from core import auth
from ui.components import field_msg, flash


# ---- who is signed in --------------------------------------------------------
def current_user():
    ss = st.session_state
    if "user" in ss:
        return ss["user"]
    if ss.get("_signed_out"):
        return None
    try:
        token = st.context.cookies.get(auth.COOKIE)
    except Exception:
        token = None
    user = auth.user_for_token(token) if token else None
    if user:
        ss["user"] = user
        ss["_token"] = token
    return user


def _finish_sign_in(user, remember):
    ss = st.session_state
    token, max_age = auth.start_session(user["id"], remember)
    ss["user"] = user
    ss["_token"] = token
    ss["_cookie"] = (token, max_age)
    ss.pop("_signed_out", None)


def sign_out():
    ss = st.session_state
    auth.end_session(ss.get("_token"))
    for k in [k for k in ss.keys() if k not in ("_flash",)]:
        del ss[k]
    ss["_cookie"] = ("", 0)
    ss["_signed_out"] = True
    flash("Signed out", ":material/logout:")


def write_cookie():
    """Set or clear the remember-me cookie. Must render on a run after the change, so it reaches the browser."""
    pending = st.session_state.pop("_cookie", None)
    if pending is None:
        return
    token, max_age = pending
    age = f"; max-age={max_age}" if max_age is not None else ""
    st.html(
        f"""<script>
        (() => {{
          const secure = location.protocol === 'https:' ? '; Secure' : '';
          document.cookie = '{auth.COOKIE}=' + {json.dumps(token)} + '; path=/{age}; SameSite=Strict' + secure;
        }})();
        </script>""",
        unsafe_allow_javascript=True,
        width="content",
    )


# ---- screens -------------------------------------------------------------------
def _header(subtitle):
    logo = base64.b64encode((Path(__file__).parent.parent / "assets" / "icon.svg").read_bytes()).decode()
    st.html(
        f'<div class="auth-head"><img class="auth-logo" alt="" src="data:image/svg+xml;base64,{logo}">'
        f'<div class="auth-title">Cashew</div><div class="auth-sub">{subtitle}</div></div>'
    )


def _sign_in_form():
    with st.form("signin", border=False, enter_to_submit=True):
        username = st.text_input("Username", autocomplete="username", key="si_user")
        password = st.text_input("Password", type="password", autocomplete="current-password", key="si_pass")
        remember = st.checkbox("Keep me signed in on this device", value=True, key="si_remember")
        go = st.form_submit_button("Sign in", type="primary", width="stretch", icon=":material/login:")
    if go:
        if not username.strip() or not password:
            st.error("Enter your username and password.")
            return
        with st.spinner("Signing in…"):
            user, err = auth.sign_in(username, password)
        if err:
            st.error(err)
            return
        _finish_sign_in(user, remember)
        flash(f"Welcome back, {user['name']}", ":material/waving_hand:")
        st.rerun()


def _register_form(first):
    """Account creation with checks that update as you type."""
    ss = st.session_state
    name = st.text_input("Your name", placeholder="e.g. Ama", key="rg_name", max_chars=50,
                         help="Shown on entries you add. You can use your first name.")
    username = st.text_input("Username", key="rg_user", autocomplete="username", max_chars=30,
                             help="What you'll type to sign in. Lower case, no spaces.")
    u_err = None
    if username:
        u_err = auth.username_problem(username)
        if not u_err and auth.username_taken(username):
            u_err = "That username is taken."
        field_msg(u_err, "error") if u_err else field_msg("Username is available.", "ok")
    password = st.text_input("Password", type="password", key="rg_pass", autocomplete="new-password")
    p_err = None
    if password:
        p_err = auth.password_problem(password, username)
        if p_err:
            field_msg(p_err, "error")
        else:
            strength = auth.password_strength(password)
            field_msg(f"Strength: {strength}" + ("" if strength in ("Good", "Strong") else
                      ". Longer is stronger; a short phrase works well."), "ok" if strength in ("Good", "Strong") else "warn")
    confirm = st.text_input("Type the password again", type="password", key="rg_pass2", autocomplete="new-password")
    c_err = None
    if confirm and confirm != password:
        c_err = "The two passwords don't match."
        field_msg(c_err, "error")
    code = None
    if not first:
        code = st.text_input("Invite code", key="rg_code", placeholder="e.g. 4F2A-91C0-7B3E",
                             help="The account owner can find this in Settings, under People.")
    remember = st.checkbox("Keep me signed in on this device", value=True, key="rg_remember")

    ready = bool(username and password and confirm) and not (u_err or p_err or c_err) and (first or bool(code))
    label = "Create owner account" if first else "Create account"
    if st.button(label, type="primary", width="stretch", disabled=not ready, key="rg_go", icon=":material/person_add:"):
        with st.spinner("Creating your account…"):
            user, err = auth.register(username, name, password, code)
        if err:
            st.error(err)
            return
        for k in ("rg_pass", "rg_pass2", "rg_code"):
            ss.pop(k, None)
        _finish_sign_in(user, remember)
        flash(f"Welcome, {user['name']}" + (". You're the owner of this Cashew." if user["is_owner"] else ""),
              ":material/waving_hand:")
        st.rerun()
    if not ready:
        missing = "Fill in a username, a password and the invite code." if not first else "Fill in a username and a password."
        field_msg(missing, "hint")


def login_screen():
    """Shown instead of any page until someone signs in."""
    write_cookie()
    try:
        first = auth.user_count() == 0
    except Exception as exc:
        st.error(f"Couldn't reach the database. Check DATABASE_URL in your secrets. ({exc})")
        return
    with st.container(key="card-auth"):
        if first:
            _header("Set up sign-in for your family")
            st.html('<div class="auth-note">You\'re the first person here, so this account will be the <b>owner</b>. '
                    "Afterwards you'll get an invite code to share with your family.</div>")
            _register_form(first=True)
        else:
            _header("Your family's money, in one place")
            tab_in, tab_up = st.tabs(["Sign in", "I have an invite code"])
            with tab_in:
                _sign_in_form()
                st.caption("Forgot your password? Ask the account owner to set a new one for you.")
            with tab_up:
                _register_form(first=False)
