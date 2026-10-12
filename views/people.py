import pandas as pd
import streamlit as st

from core import auth
from core.backup import backup_filename, export_zip
from core.data import book
from core.db import execute, transact
from ui.components import card, confirm, empty, field_msg, flash, page_header, section


def _my_account(user):
    ss = st.session_state
    with card("me-name"):
        section("Your name")
        name = st.text_input("Name shown on your entries", value=user["name"], max_chars=50,
                             key=f"me_name_{user['id']}").strip()
        if st.button("Save name", disabled=not name or name == user["name"], key="me_name_save", icon=":material/check:"):
            execute("UPDATE users SET display_name = %s WHERE id = %s", (name, user["id"]))
            ss["user"] = {**user, "name": name}
            flash("Name saved")
            st.rerun()

    with card("me-password"):
        section("Change your password")
        current = st.text_input("Current password", type="password", key="pw_current", autocomplete="current-password")
        new = st.text_input("New password", type="password", key="pw_new", autocomplete="new-password")
        problem = auth.password_problem(new, user["username"]) if new else None
        if problem:
            field_msg(problem)
        elif new:
            field_msg(f"Strength: {auth.password_strength(new)}", "ok")
        again = st.text_input("Type the new password again", type="password", key="pw_again", autocomplete="new-password")
        mismatch = bool(again) and again != new
        if mismatch:
            field_msg("The two passwords don't match.")
        ready = bool(current and new and again) and not problem and not mismatch
        if st.button("Change password", type="primary", disabled=not ready, key="pw_save", icon=":material/lock_reset:"):
            with st.spinner("Saving…"):
                err = auth.change_password(user["id"], current, new)
            if err:
                st.error(err)
            else:
                for k in ("pw_current", "pw_new", "pw_again"):
                    ss.pop(k, None)
                flash("Password changed", ":material/lock:")
                st.rerun()


def _owner_tools(user):
    ss = st.session_state
    b = book()
    with card("invite"):
        section("Invite your family")
        code = auth.invite_code() or auth.new_invite_code()
        st.write("Share the app link and this code. They choose **I have an invite code** on the sign-in screen.")
        st.code(code, language=None)
        if st.button("Make a new code", icon=":material/refresh:", key="invite_new",
                     help="The old code stops working. Accounts already created aren't affected."):
            auth.new_invite_code()
            flash("New invite code made. The old one no longer works.", ":material/key:")
            st.rerun()

    _reminders()

    with card("backup"):
        section("Backups")
        st.write("A full copy of everything (entries, budgets, goals, accounts, people) as a zip of spreadsheets. "
                 "The daily GitHub backup keeps an encrypted copy too.")
        st.download_button("Download a backup", data=lambda: transact(export_zip)[0],
                           file_name=backup_filename(), mime="application/zip", icon=":material/download:",
                           key="backup_dl", on_click="ignore")
        st.caption("Keep it somewhere private: it includes everyone's records. To load one back in, use restore.py.")

    users = b.users
    with card("people"):
        section("People", f"{len(users)} account{'s' if len(users) != 1 else ''}")
        table = pd.DataFrame({
            "Name": users["display_name"],
            "Username": users["username"],
            "Role": users["is_owner"].map({True: "Owner", False: "Member"}),
            "Last signed in": pd.to_datetime(users["last_login"], utc=True).dt.tz_convert(None),
        })
        st.dataframe(table, hide_index=True, width="stretch",
                     column_config={"Last signed in": st.column_config.DatetimeColumn(format="D MMM YYYY, HH:mm")})

        others = users[users["id"] != user["id"]]
        if not len(others):
            empty("Nobody else has joined yet.")
            return
        labels = {int(r["id"]): f"{r['display_name']} (@{r['username']})" for _, r in others.iterrows()}
        pick = st.selectbox("Person", list(labels), format_func=lambda i: labels[i], key="person_pick")
        row = others[others["id"] == pick].iloc[0]
        tab_pw, tab_owner, tab_remove = st.tabs(["Set a new password", "Owner", "Remove"])
        with tab_pw:
            new = st.text_input(f"New password for {row['display_name']}", type="password", key=f"reset_{pick}",
                                autocomplete="new-password")
            problem = auth.password_problem(new, row["username"]) if new else None
            if problem:
                field_msg(problem)
            if st.button("Set password", type="primary", disabled=not new or bool(problem), key=f"reset_go_{pick}"):
                err = auth.set_password(int(pick), new, row["username"])
                if err:
                    st.error(err)
                else:
                    ss.pop(f"reset_{pick}", None)
                    flash(f"New password set for {row['display_name']}. Tell them in person or by phone.", ":material/key:")
                    st.rerun()
            st.caption("For when someone forgets theirs. They're signed out on every device.")
        with tab_owner:
            if row["is_owner"]:
                st.write(f"{row['display_name']} is an owner.")
                if st.button("Make them a member", key=f"demote_{pick}"):
                    execute("UPDATE users SET is_owner = FALSE WHERE id = %s", (int(pick),))
                    flash(f"{row['display_name']} is now a member")
                    st.rerun()
            else:
                st.write("Owners can invite people, reset passwords and remove accounts.")
                if st.button("Make them an owner", key=f"promote_{pick}"):
                    execute("UPDATE users SET is_owner = TRUE WHERE id = %s", (int(pick),))
                    flash(f"{row['display_name']} is now an owner")
                    st.rerun()
        with tab_remove:
            st.write("Their entries stay. They just can't sign in any more.")
            if st.button(f"Remove {row['display_name']}", icon=":material/person_remove:", key=f"remove_{pick}"):
                confirm(f"Remove **{row['display_name']}**'s account? Their entries stay in the records.",
                        [("DELETE FROM users WHERE id = %s", (int(pick),))], f"Removed {row['display_name']}",
                        button="Remove")


def render():
    user = st.session_state["user"]
    page_header("People & sign-in", "Your account, and who else can use this Cashew")
    if user["is_owner"]:
        left, right = st.columns([1, 1], gap="medium")
        with left:
            _my_account(user)
        with right:
            _owner_tools(user)
    else:
        _my_account(user)
        st.caption("To invite someone or reset a password, ask the account owner.")



def _as_html(text):
    return "<br>".join(text.split("\n"))


def _reminders():
    """Set-up help, a preview of the messages, and a way to send a test."""
    import json
    import urllib.request
    from datetime import datetime

    from core.data import book as money_book
    from meals.briefing import evening, morning
    from meals.data import kitchen
    from notify import food_budget_left, send

    with card("reminders"):
        section("Phone reminders (Telegram)")
        st.write("Every morning at 6:00: today's meals, prep and shopping to do, leftovers to eat, low stock and "
                 "safe to spend. In the evening, only when something needs doing tonight.")
        k, b = kitchen(), money_book()
        now = datetime.now()
        tab_m, tab_e, tab_s = st.tabs(["Morning preview", "Evening preview", "Set up"])
        with tab_m:
            st.html(f'<div class="tg-preview">{_as_html(morning(k, b, now, food_budget_left(b, k, now.date())))}</div>')
        with tab_e:
            msg = evening(k, now)
            if msg:
                st.html(f'<div class="tg-preview">{_as_html(msg)}</div>')
            else:
                st.caption("Nothing needs doing tonight, so no evening message would be sent.")
        with tab_s:
            st.markdown(
                "1. In Telegram, open **@BotFather**, send `/newbot` and follow the steps. Copy the token it gives you.\n"
                "2. Everyone who wants reminders opens your new bot and taps **Start**. Or add the bot to a family "
                "group and send one message there.\n"
                "3. Paste the token below and tap **Find chats** to get the chat IDs.\n"
                "4. In GitHub, open the repository's **Settings → Secrets and variables → Actions** and add "
                "`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (several IDs separated by commas).\n"
                "5. From the **Actions** tab, run **Phone reminders** once to check it arrives.")
            token = st.text_input("Bot token", type="password", key="tg_token",
                                  help="Only sent to Telegram, never saved by Cashew.")
            if st.button("Find chats", disabled=not token, key="tg_find", icon=":material/search:"):
                try:
                    with urllib.request.urlopen(f"https://api.telegram.org/bot{token.strip()}/getUpdates", timeout=15) as r:
                        updates = json.loads(r.read()).get("result", [])
                    chats = {}
                    for u in updates:
                        m = u.get("message") or u.get("my_chat_member") or {}
                        c = m.get("chat") or {}
                        if c.get("id"):
                            chats[c["id"]] = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)
                    if chats:
                        st.code(",".join(str(i) for i in chats), language=None)
                        st.caption("Chats found: " + ", ".join(f"{n} ({i})" for i, n in chats.items()))
                    else:
                        st.warning("No chats yet. Open the bot in Telegram, tap Start, then try again.")
                except Exception as exc:
                    st.error(f"Telegram didn't answer: {exc}. Check the token.")
            chats = st.text_input("Chat IDs", key="tg_chats", placeholder="e.g. 123456789,987654321")
            if st.button("Send the morning message now", disabled=not (token and chats), key="tg_test",
                         icon=":material/send:"):
                try:
                    n = send(morning(k, b, now, food_budget_left(b, k, now.date())), token.strip(), chats)
                    flash(f"Sent to {n} chat{'s' if n != 1 else ''}. Check Telegram.", ":material/send:")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Couldn't send: {exc}")
