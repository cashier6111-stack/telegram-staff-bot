import os
import time
import threading
import subprocess
from datetime import datetime, timedelta, timezone

import telebot
from telebot import types

from database import get_db
from sync_to_sheet import (
    sync_staff_to_sheet,
    sync_record_to_sheet,
    sync_monthly_summary_to_sheet
)

subprocess.run(["python", "init_db.py"], check=False)

TOKEN = os.environ["BOT_TOKEN"]

bot = telebot.TeleBot(TOKEN, threaded=False)
bot.remove_webhook()

bot.set_my_commands([
    types.BotCommand("start", "Open attendance menu"),
    types.BotCommand("menu", "Show shortcut buttons"),
    types.BotCommand("myid", "Get your Telegram ID"),
    types.BotCommand("today", "Show today report"),
    types.BotCommand("report", "Show report by date"),
])

time.sleep(3)


# Cambodia UTC+7
KH_TZ = timezone(timedelta(hours=7))

FIRST_ADMIN_ID = 8439975606


RULES = {
    "Toilet": {"warning": 10, "timeout": 15},
    "Smoke": {"warning": 6, "timeout": 8},
    "Meal": {"warning": 31, "timeout": 35},
}

def get_rules_for_chat(chat_title):
    if "[CASHIER]" in chat_title:
        return {
            "Toilet": {"warning": 10, "timeout": 15},
            "Smoke": {"warning": 6, "timeout": 8},
            "Meal": {"warning": 31, "timeout": 35},
        }

    return {
        "Toilet": {"warning": 10, "timeout": 15},
        "Smoke": {"warning": 6, "timeout": 8},
        "Meal": {"warning": 41, "timeout": 45},
    }


ROLE_LEVELS = {
    "user": 1,
    "leader": 2,
    "admin": 3,
}


def now_kh():
    return datetime.now(KH_TZ).replace(tzinfo=None)

def format_time(dt):
    if not dt:
        return ""

    return dt.strftime("%Y-%m-%d %I:%M:%S %p")


def send_long_message(chat_id, text, limit=3500):
    if not text:
        return

    while len(text) > limit:
        split_index = text.rfind("\n", 0, limit)

        if split_index == -1:
            split_index = limit

        chunk = text[:split_index].strip()

        if chunk:
            bot.send_message(chat_id, chunk)

        text = text[split_index:].strip()

    if text:
        bot.send_message(chat_id, text)


def get_db_cursor():
    conn = get_db()
    return conn, conn.cursor()


def safe_sync_staff(chat):
    try:
        sync_staff_to_sheet(chat.title or str(chat.id))
    except Exception as e:
        print("Google Sheet staff sync error:", e)


def safe_sync_record(chat, record_id):
    try:
        sync_record_to_sheet(chat.title or str(chat.id), record_id)
    except Exception as e:
        print("Google Sheet record sync error:", e)


def get_register_example(chat_title):
    if "[8MBET]" in chat_title:
        return "/register 8M001 Cat"

    if "[MJ88]" in chat_title:
        return "/register MJ001 Cat"

    if "[ESEWA12]" in chat_title:
        return "/register E001 Cat"

    if "[MAGAR33]" in chat_title:
        return "/register MG001 Cat"

    if "[NPR77]" in chat_title:
        return "/register NPR001 Cat"
    
    if "[NPL11]" in chat_title:
        return "/register NPL001 Cat"

    if "[CASHIER]" in chat_title:
        return "/register C001 Cat"

    return "/register STAFF_ID Cat"


def is_valid_staff_id(chat_title, staff_id):
    staff_id = staff_id.upper()

    if "[8MBET]" in chat_title:
        return staff_id.startswith("8M")

    if "[MJ88]" in chat_title:
        return staff_id.startswith("MJ")

    if "[ESEWA12]" in chat_title:
        return staff_id.startswith("E")

    if "[MAGAR33]" in chat_title:
        return staff_id.startswith("MG")

    if "[NPR77]" in chat_title:
        return staff_id.startswith("NPR")
    
    if "[NPL11]" in chat_title:
        return staff_id.startswith("NPL")

    if "[CASHIER]" in chat_title:
        return staff_id.startswith("C")

    return True


def get_or_create_company(chat):
    chat_title = chat.title or str(chat.id)

    conn, cur = get_db_cursor()

    cur.execute(
        """
        INSERT INTO companies (chat_title, telegram_chat_id)
        VALUES (%s, %s)
        ON CONFLICT (telegram_chat_id)
        DO UPDATE SET chat_title = EXCLUDED.chat_title
        RETURNING id
        """,
        (chat_title, chat.id)
    )

    company = cur.fetchone()

    conn.commit()

    cur.close()
    conn.close()

    return company["id"]

def get_role(company_id, telegram_id):
    if telegram_id == FIRST_ADMIN_ID:
        return "admin"

    conn, cur = get_db_cursor()

    cur.execute(
        """
        SELECT role
        FROM roles
        WHERE company_id = %s
        AND telegram_id = %s
        """,
        (company_id, telegram_id)
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return "user"

    return row["role"]


def has_role(company_id, telegram_id, required_role):
    current_role = get_role(company_id, telegram_id)

    return ROLE_LEVELS[current_role] >= ROLE_LEVELS[required_role]


VALID_COMMANDS = [
    "/start",
    "/menu",
    "/myid",
    "/register",
    "/today",
    "/report",
    "/liststaff",
    "/editstaff",
    "/removestaff",
    "/addleader",
    "/addadmin",
    "/removeleader",
    "/removeadmin",
]


VALID_BUTTONS = [
    "📝 How To Register",
    "🆔 My Telegram ID",
    "🚻 Toilet Out",
    "✅ Toilet In",
    "🚬 Smoke Out",
    "✅ Smoke In",
    "🍱 Meal Out",
    "✅ Meal In",
    "❌ Cancel Last",
    "📊 Today Report",
    "👥 List Staff",
    "✏️ Edit Staff Help",
    "❌ Remove Staff Help",
    "➕ Add Leader Help",
    "➕ Add Admin Help",
    "➖ Remove Leader Help",
    "➖ Remove Admin Help",
]


def is_valid_command(text):
    if not text:
        return False

    first_word = text.split()[0]

    for command in VALID_COMMANDS:
        if first_word == command or first_word.startswith(command + "@"):
            return True

    return False


def delete_non_admin_noise(message):
    try:
        text = message.text or ""

        if text in VALID_BUTTONS:
            return

        if is_valid_command(text):
            return

        company_id = get_or_create_company(message.chat)

        if has_role(company_id, message.from_user.id, "admin"):
            return

        bot.delete_message(
            message.chat.id,
            message.message_id
        )

    except Exception as e:
        print("Delete message error:", e)


def get_status(chat_title, action_type, duration_minutes):
    rules = get_rules_for_chat(chat_title)
    rule = rules[action_type]

    if duration_minutes >= rule["timeout"]:
        return "Timeout"

    if duration_minutes >= rule["warning"]:
        return "Warning"

    return "Normal"


def send_menu(message, company_id=None, telegram_id=None):
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
        row_width=2
    )

    role = "user"

    if company_id and telegram_id:
        role = get_role(company_id, telegram_id)

    markup.add(types.KeyboardButton("🆔 My Telegram ID"))

    if role in ["user", "leader"]:
        markup.add(types.KeyboardButton("📝 How To Register"))

        markup.add(
            types.KeyboardButton("🚻 Toilet Out"),
            types.KeyboardButton("✅ Toilet In")
        )

        markup.add(
            types.KeyboardButton("🚬 Smoke Out"),
            types.KeyboardButton("✅ Smoke In")
        )

        markup.add(
            types.KeyboardButton("🍱 Meal Out"),
            types.KeyboardButton("✅ Meal In")
        )

        markup.add(types.KeyboardButton("❌ Cancel Last"))

    if role in ["leader", "admin"]:
        markup.add(types.KeyboardButton("📊 Today Report"))
        markup.add(types.KeyboardButton("👥 List Staff"))
        markup.add(types.KeyboardButton("✏️ Edit Staff Help"))
        markup.add(types.KeyboardButton("❌ Remove Staff Help"))

    if role == "admin":
        markup.add(types.KeyboardButton("➕ Add Leader Help"))
        markup.add(types.KeyboardButton("➕ Add Admin Help"))
        markup.add(types.KeyboardButton("➖ Remove Leader Help"))
        markup.add(types.KeyboardButton("➖ Remove Admin Help"))

    bot.reply_to(
        message,
        f"Attendance Menu\nRole: {role}",
        reply_markup=markup
    )


def find_staff(company_id, telegram_id):
    conn, cur = get_db_cursor()

    cur.execute(
        """
        SELECT *
        FROM staff
        WHERE company_id = %s
        AND telegram_id = %s
        AND is_active = TRUE
        """,
        (company_id, telegram_id)
    )

    staff = cur.fetchone()

    cur.close()
    conn.close()

    return staff


def get_open_record(company_id, telegram_id, action_type=None):
    conn, cur = get_db_cursor()

    if action_type:
        cur.execute(
            """
            SELECT *
            FROM break_records
            WHERE company_id = %s
            AND telegram_id = %s
            AND type = %s
            AND status = 'Open'
            ORDER BY out_time DESC
            LIMIT 1
            """,
            (company_id, telegram_id, action_type)
        )

    else:
        cur.execute(
            """
            SELECT *
            FROM break_records
            WHERE company_id = %s
            AND telegram_id = %s
            AND status = 'Open'
            ORDER BY out_time DESC
            LIMIT 1
            """,
            (company_id, telegram_id)
        )

    record = cur.fetchone()

    cur.close()
    conn.close()

    return record

@bot.message_handler(commands=["start", "menu"])
def show_menu(message):
    company_id = get_or_create_company(message.chat)

    send_menu(
        message,
        company_id,
        message.from_user.id
    )


@bot.message_handler(commands=["myid"])
def my_id(message):
    bot.reply_to(
        message,
        f"🆔 Your Telegram ID:\n{message.from_user.id}"
    )


@bot.message_handler(commands=["register"])
def register(message):
    try:
        parts = message.text.split()

        chat_title = message.chat.title or ""

        example = get_register_example(chat_title)

        if len(parts) < 3:
            bot.reply_to(
                message,
                "Usage:\n/register STAFF_ID REAL_NAME\n\n"
                f"Example:\n{example}"
            )
            return

        company_id = get_or_create_company(message.chat)

        staff_id = parts[1].upper()

        real_name = " ".join(parts[2:])

        telegram_id = message.from_user.id

        username = message.from_user.username or ""

        if not is_valid_staff_id(chat_title, staff_id):
            bot.reply_to(
                message,
                "❌ Invalid Staff ID format.\n\n"
                f"Example:\n{example}"
            )
            return

        conn, cur = get_db_cursor()

        cur.execute(
            """
            SELECT *
            FROM staff
            WHERE company_id = %s
            AND telegram_id = %s
            """,
            (company_id, telegram_id)
        )

        existing_user = cur.fetchone()

        if existing_user and existing_user["is_active"]:
            bot.reply_to(
                message,
                "❌ You already registered."
            )

            cur.close()
            conn.close()

            return

        cur.execute(
            """
            SELECT *
            FROM staff
            WHERE company_id = %s
            AND staff_id = %s
            AND is_active = TRUE
            """,
            (company_id, staff_id)
        )

        if cur.fetchone():
            bot.reply_to(
                message,
                "❌ Staff ID already exists."
            )

            cur.close()
            conn.close()

            return

        current_time = now_kh()

        if existing_user and not existing_user["is_active"]:
            cur.execute(
                """
                UPDATE staff
                SET staff_id = %s,
                    name = %s,
                    real_name = %s,
                    username = %s,
                    status = 'Active',
                    is_active = TRUE,
                    updated_at = %s
                WHERE company_id = %s
                AND telegram_id = %s
                """,
                (
                    staff_id,
                    real_name,
                    real_name,
                    username,
                    current_time,
                    company_id,
                    telegram_id
                )
            )

        else:
            cur.execute(
                """
                INSERT INTO staff (
                    company_id,
                    telegram_id,
                    staff_id,
                    name,
                    real_name,
                    username,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'Active', %s, %s)
                """,
                (
                    company_id,
                    telegram_id,
                    staff_id,
                    real_name,
                    real_name,
                    username,
                    current_time,
                    current_time
                )
            )

        conn.commit()

        cur.close()
        conn.close()

        safe_sync_staff(message.chat)

        bot.reply_to(
            message,
            f"✅ Registered Successfully\n\n"
            f"🏢 Company: {chat_title}\n"
            f"🆔 Staff ID: {staff_id}\n"
            f"👤 Name: {real_name}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


def start_action(chat, user, action_type):
    try:
        company_id = get_or_create_company(chat)

        staff = find_staff(company_id, user.id)

        if not staff:
            example = get_register_example(chat.title or "")

            bot.send_message(
                chat.id,
                f"❌ Please register first.\n\nExample:\n{example}"
            )

            return

        existing_open = get_open_record(company_id, user.id)

        if existing_open:
            bot.send_message(
                chat.id,
                f"❌ You already have an open {existing_open['type']} record.\n"
                "Please click In or Cancel first."
            )

            return

        now = now_kh()

        conn, cur = get_db_cursor()

        cur.execute(
            """
            INSERT INTO break_records (
                company_id,
                telegram_id,
                staff_id,
                name,
                type,
                out_time,
                status,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'Open', %s)
            RETURNING id
            """,
            (
                company_id,
                user.id,
                staff["staff_id"],
                staff["real_name"],
                action_type,
                now,
                now
            )
        )

        new_record = cur.fetchone()

        record_id = new_record["id"]

        conn.commit()

        cur.close()
        conn.close()

        safe_sync_record(chat, record_id)

        bot.send_message(
            chat.id,
            f"✅ {action_type} Out recorded\n"
            f"👤 {staff['real_name']}\n"
            f"🕒 {format_time(now)}"
        )

    except Exception as e:
        bot.send_message(chat.id, f"❌ Error: {e}")


def end_action(chat, user, action_type):
    try:
        company_id = get_or_create_company(chat)

        staff = find_staff(company_id, user.id)

        if not staff:
            example = get_register_example(chat.title or "")

            bot.send_message(
                chat.id,
                f"❌ Please register first.\n\nExample:\n{example}"
            )

            return

        record = get_open_record(company_id, user.id, action_type)

        if not record:
            bot.send_message(
                chat.id,
                f"❌ No open {action_type} record found."
            )

            return

        in_time = now_kh()

        duration_minutes = round(
            (in_time - record["out_time"]).total_seconds() / 60
        )

        status = get_status(chat.title or "", action_type, duration_minutes)

        conn, cur = get_db_cursor()

        cur.execute(
            """
            UPDATE break_records
            SET in_time = %s,
                duration = %s,
                status = %s
            WHERE id = %s
            """,
            (
                in_time,
                duration_minutes,
                status,
                record["id"]
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        safe_sync_record(chat, record["id"])

        warning_text = ""

        rules = get_rules_for_chat(chat.title or "")

        if status == "Warning":
            warning_text = (
                f"\n⚠️ {action_type} reached "
                f"{rules[action_type]['warning']} minutes."
            )

        if status == "Timeout":
            warning_text = (
                f"\n🚨 {action_type} reached "
                f"{rules[action_type]['timeout']} minutes."
            )

        bot.send_message(
            chat.id,
            f"✅ {action_type} In recorded\n"
            f"👤 {staff['real_name']}\n"
            f"⏳ Duration: {duration_minutes} min\n"
            f"📌 Status: {status}"
            f"{warning_text}"
        )

    except Exception as e:
        bot.send_message(chat.id, f"❌ Error: {e}")


def cancel_last(chat, user):
    try:
        company_id = get_or_create_company(chat)

        staff = find_staff(company_id, user.id)

        if not staff:
            example = get_register_example(chat.title or "")

            bot.send_message(
                chat.id,
                f"❌ Please register first.\n\nExample:\n{example}"
            )

            return

        record = get_open_record(company_id, user.id)

        if not record:
            bot.send_message(
                chat.id,
                "❌ No open record found to cancel."
            )

            return

        cancel_time = now_kh()

        duration_minutes = round(
            (cancel_time - record["out_time"]).total_seconds() / 60
        )

        conn, cur = get_db_cursor()

        cur.execute(
            """
            UPDATE break_records
            SET in_time = %s,
                duration = %s,
                status = 'Cancelled'
            WHERE id = %s
            """,
            (
                cancel_time,
                duration_minutes,
                record["id"]
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        safe_sync_record(chat, record["id"])

        bot.send_message(
            chat.id,
            f"❌ Last record cancelled\n"
            f"👤 {staff['real_name']}\n"
            f"📌 Type: {record['type']}\n"
            f"⏳ Cancelled after: {duration_minutes} min"
        )

    except Exception as e:
        bot.send_message(chat.id, f"❌ Error: {e}")


@bot.message_handler(commands=["liststaff"])
def list_staff(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "leader"):
            bot.reply_to(message, "❌ Leader or Admin only.")
            return

        conn, cur = get_db_cursor()

        cur.execute(
            """
            SELECT staff_id, real_name, username, status
            FROM staff
            WHERE company_id = %s
            ORDER BY staff_id
            """,
            (company_id,)
        )

        rows = cur.fetchall()

        cur.close()
        conn.close()

        if not rows:
            bot.reply_to(message, "No staff found.")
            return

        text = "👥 Staff List\n\n"

        for row in rows:
            username = row["username"] or "-"

            text += (
                f"ID: {row['staff_id']}\n"
                f"Name: {row['real_name']}\n"
                f"Username: @{username}\n"
                f"Status: {row['status']}\n\n"
            )

        send_long_message(message.chat.id, text)

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["editstaff"])
def edit_staff(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "leader"):
            bot.reply_to(message, "❌ Leader or Admin only.")
            return

        parts = message.text.split()

        if len(parts) < 4:
            bot.reply_to(
                message,
                "Usage:\n/editstaff OLD_STAFF_ID NEW_STAFF_ID NEW_NAME"
            )
            return

        old_staff_id = parts[1].upper()
        new_staff_id = parts[2].upper()
        new_name = " ".join(parts[3:])

        conn, cur = get_db_cursor()

        cur.execute(
            """
            SELECT *
            FROM staff
            WHERE company_id = %s
            AND staff_id = %s
            """,
            (company_id, old_staff_id)
        )

        target_staff = cur.fetchone()

        if not target_staff:
            bot.reply_to(message, "❌ Staff ID not found.")
            cur.close()
            conn.close()
            return

        cur.execute(
            """
            SELECT *
            FROM staff
            WHERE company_id = %s
            AND staff_id = %s
            AND staff_id != %s
            """,
            (company_id, new_staff_id, old_staff_id)
        )

        if cur.fetchone():
            bot.reply_to(message, "❌ New Staff ID already exists.")
            cur.close()
            conn.close()
            return

        cur.execute(
            """
            UPDATE staff
            SET staff_id = %s,
                name = %s,
                real_name = %s,
                updated_at = %s
            WHERE company_id = %s
            AND staff_id = %s
            """,
            (
                new_staff_id,
                new_name,
                new_name,
                now_kh(),
                company_id,
                old_staff_id
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        safe_sync_staff(message.chat)

        bot.reply_to(
            message,
            f"✅ Staff updated\n"
            f"Old ID: {old_staff_id}\n"
            f"New ID: {new_staff_id}\n"
            f"Name: {new_name}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["removestaff"])
def remove_staff(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "leader"):
            bot.reply_to(message, "❌ Leader or Admin only.")
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.reply_to(message, "Usage:\n/removestaff STAFF_ID")
            return

        staff_id = parts[1].upper()

        conn, cur = get_db_cursor()

        cur.execute(
            """
            SELECT *
            FROM staff
            WHERE company_id = %s
            AND staff_id = %s
            """,
            (company_id, staff_id)
        )

        staff = cur.fetchone()

        if not staff:
            bot.reply_to(message, "❌ Staff not found.")
            cur.close()
            conn.close()
            return

        cur.execute(
            """
            UPDATE staff
            SET is_active = FALSE,
                status = 'Removed',
                updated_at = %s
            WHERE company_id = %s
            AND staff_id = %s
            """,
            (now_kh(), company_id, staff_id)
        )

        conn.commit()

        cur.close()
        conn.close()

        safe_sync_staff(message.chat)

        bot.reply_to(
            message,
            f"✅ Staff removed\n\n"
            f"ID: {staff_id}\n"
            f"Name: {staff['real_name']}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["addleader"])
def add_leader(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "admin"):
            bot.reply_to(message, "❌ Admin only.")
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.reply_to(message, "Usage:\n/addleader TELEGRAM_ID")
            return

        telegram_id = int(parts[1])

        conn, cur = get_db_cursor()

        cur.execute(
            """
            INSERT INTO roles (company_id, telegram_id, role)
            VALUES (%s, %s, 'leader')
            ON CONFLICT (company_id, telegram_id)
            DO UPDATE SET role = 'leader'
            """,
            (company_id, telegram_id)
        )

        conn.commit()

        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Leader added\nTelegram ID: {telegram_id}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["addadmin"])
def add_admin(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "admin"):
            bot.reply_to(message, "❌ Admin only.")
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.reply_to(message, "Usage:\n/addadmin TELEGRAM_ID")
            return

        telegram_id = int(parts[1])

        conn, cur = get_db_cursor()

        cur.execute(
            """
            INSERT INTO roles (company_id, telegram_id, role)
            VALUES (%s, %s, 'admin')
            ON CONFLICT (company_id, telegram_id)
            DO UPDATE SET role = 'admin'
            """,
            (company_id, telegram_id)
        )

        conn.commit()

        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Admin added\nTelegram ID: {telegram_id}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["removeleader"])
def remove_leader(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "admin"):
            bot.reply_to(message, "❌ Admin only.")
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.reply_to(message, "Usage:\n/removeleader TELEGRAM_ID")
            return

        telegram_id = int(parts[1])

        conn, cur = get_db_cursor()

        cur.execute(
            """
            DELETE FROM roles
            WHERE company_id = %s
            AND telegram_id = %s
            AND role = 'leader'
            """,
            (company_id, telegram_id)
        )

        conn.commit()

        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Leader removed\nTelegram ID: {telegram_id}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["removeadmin"])
def remove_admin(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "admin"):
            bot.reply_to(message, "❌ Admin only.")
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.reply_to(message, "Usage:\n/removeadmin TELEGRAM_ID")
            return

        telegram_id = int(parts[1])

        if telegram_id == FIRST_ADMIN_ID:
            bot.reply_to(
                message,
                "❌ Cannot remove first admin."
            )
            return

        conn, cur = get_db_cursor()

        cur.execute(
            """
            DELETE FROM roles
            WHERE company_id = %s
            AND telegram_id = %s
            AND role = 'admin'
            """,
            (company_id, telegram_id)
        )

        conn.commit()

        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Admin removed\nTelegram ID: {telegram_id}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


def build_daily_report(company_id, target_date):
    day_start = target_date.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    next_day = day_start + timedelta(days=1)

    conn, cur = get_db_cursor()

    cur.execute(
        """
        SELECT name, type, duration, status
        FROM break_records
        WHERE company_id = %s
        AND out_time >= %s
        AND out_time < %s
        AND status != 'Open'
        ORDER BY name
        """,
        (company_id, day_start, next_day)
    )

    records = cur.fetchall()

    cur.close()
    conn.close()

    if not records:
        return f"📊 Daily Report {target_date.strftime('%Y-%m-%d')}\n\nNo records."

    summary = {}

    for row in records:
        name = row["name"]
        action_type = row["type"]
        duration = row["duration"] or 0
        status = row["status"]

        if name not in summary:
            summary[name] = {
                "Toilet": 0,
                "Smoke": 0,
                "Meal": 0,
                "Toilet Count": 0,
                "Smoke Count": 0,
                "Meal Count": 0,
                "Cancelled Count": 0,
                "Warning Count": 0,
                "Timeout Count": 0,
            }

        if action_type in ["Toilet", "Smoke", "Meal"]:
            summary[name][action_type] += duration
            summary[name][f"{action_type} Count"] += 1

        if status == "Cancelled":
            summary[name]["Cancelled Count"] += 1

        if status == "Warning":
            summary[name]["Warning Count"] += 1

        if status == "Timeout":
            summary[name]["Timeout Count"] += 1

    report = f"📊 Daily Report {target_date.strftime('%Y-%m-%d')}\n\n"

    for name, data in summary.items():
        report += (
            f"👤 {name}\n"
            f"🚻 Toilet: {data['Toilet']} min / {data['Toilet Count']} times\n"
            f"🚬 Smoke: {data['Smoke']} min / {data['Smoke Count']} times\n"
            f"🍱 Meal: {data['Meal']} min / {data['Meal Count']} times\n"
            f"⚠️ Warning: {data['Warning Count']} times\n"
            f"🚨 Timeout: {data['Timeout Count']} times\n"
            f"❌ Cancelled: {data['Cancelled Count']} times\n\n"
        )

    return report


@bot.message_handler(commands=["today"])
def today_report(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "leader"):
            bot.reply_to(message, "❌ Leader or Admin only.")
            return

        report = build_daily_report(company_id, now_kh())

        send_long_message(message.chat.id, report)

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["report"])
def report_by_date(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "leader"):
            bot.reply_to(message, "❌ Leader or Admin only.")
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.reply_to(
                message,
                "Usage:\n/report YYYY-MM-DD\n\nExample:\n/report 2026-05-26"
            )
            return

        target_date = datetime.strptime(parts[1], "%Y-%m-%d")

        report = build_daily_report(company_id, target_date)

        send_long_message(message.chat.id, report)

    except ValueError:
        bot.reply_to(
            message,
            "❌ Invalid date format.\nUse:\n/report YYYY-MM-DD"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def auto_sheet_sync_loop():
    while True:
        try:
            conn, cur = get_db_cursor()

            cur.execute("""
                SELECT chat_title
                FROM companies
            """)

            companies = cur.fetchall()

            cur.close()
            conn.close()

            for company in companies:
                try:
                    sync_monthly_summary_to_sheet(company["chat_title"])
                    print(f"Monthly summary synced: {company['chat_title']}")
                except Exception as e:
                    print("Monthly summary error:", e)

            time.sleep(300)

        except Exception as e:
            print("Auto sheet sync error:", e)
            time.sleep(60)


def auto_daily_report_loop():
    last_sent_date = None

    while True:
        try:
            kh_now = now_kh()

            print("Cambodia time:", kh_now)

            if kh_now.hour == 0 and kh_now.minute <= 5:
                report_date = kh_now - timedelta(days=1)

                if last_sent_date != report_date.date():

                    print("Sending auto report...")

                    conn, cur = get_db_cursor()

                    cur.execute(
                        """
                        SELECT id, chat_title, telegram_chat_id
                        FROM companies
                        """
                    )

                    companies = cur.fetchall()

                    cur.close()
                    conn.close()

                    for company in companies:
                        try:
                            report = build_daily_report(
                                company["id"],
                                report_date
                            )

                            send_long_message(
                                company["telegram_chat_id"],
                                report
                            )

                        except Exception as e:
                            print("Auto report send error:", e)

                    last_sent_date = report_date.date()

            time.sleep(30)

        except Exception as e:
            print("Auto daily report loop error:", e)
            time.sleep(60)


@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    text = message.text or ""

    chat = message.chat
    user = message.from_user

    if text == "📝 How To Register":
        example = get_register_example(chat.title or "")

        bot.send_message(
            chat.id,
            "📝 Please register using:\n\n" + example
        )

    elif text == "🆔 My Telegram ID":
        bot.send_message(
            chat.id,
            f"🆔 Your Telegram ID:\n{user.id}"
        )

    elif text == "🚻 Toilet Out":
        start_action(chat, user, "Toilet")

    elif text == "✅ Toilet In":
        end_action(chat, user, "Toilet")

    elif text == "🚬 Smoke Out":
        start_action(chat, user, "Smoke")

    elif text == "✅ Smoke In":
        end_action(chat, user, "Smoke")

    elif text == "🍱 Meal Out":
        start_action(chat, user, "Meal")

    elif text == "✅ Meal In":
        end_action(chat, user, "Meal")

    elif text == "❌ Cancel Last":
        cancel_last(chat, user)

    elif text == "📊 Today Report":
        company_id = get_or_create_company(chat)

        if not has_role(company_id, user.id, "leader"):
            bot.send_message(
                chat.id,
                "❌ Leader or Admin only."
            )
            return

        report = build_daily_report(company_id, now_kh())

        send_long_message(chat.id, report)

    elif text == "👥 List Staff":
        list_staff(message)

    elif text == "✏️ Edit Staff Help":
        bot.send_message(
            chat.id,
            "✏️ Edit Staff Usage:\n\n"
            "/editstaff OLD_STAFF_ID NEW_STAFF_ID NEW_NAME"
        )

    elif text == "❌ Remove Staff Help":
        bot.send_message(
            chat.id,
            "❌ Remove Staff Usage:\n\n"
            "/removestaff STAFF_ID"
        )

    elif text == "➕ Add Leader Help":
        bot.send_message(
            chat.id,
            "➕ Add Leader Usage:\n\n"
            "/addleader TELEGRAM_ID"
        )

    elif text == "➕ Add Admin Help":
        bot.send_message(
            chat.id,
            "➕ Add Admin Usage:\n\n"
            "/addadmin TELEGRAM_ID"
        )

    elif text == "➖ Remove Leader Help":
        bot.send_message(
            chat.id,
            "➖ Remove Leader Usage:\n\n"
            "/removeleader TELEGRAM_ID"
        )

    elif text == "➖ Remove Admin Help":
        bot.send_message(
            chat.id,
            "➖ Remove Admin Usage:\n\n"
            "/removeadmin TELEGRAM_ID"
        )

    else:
        delete_non_admin_noise(message)


print("Bot is running...")

threading.Thread(
    target=auto_sheet_sync_loop,
    daemon=True
).start()

threading.Thread(
    target=auto_daily_report_loop,
    daemon=True
).start()

bot.infinity_polling(
    timeout=60,
    long_polling_timeout=60,
    skip_pending=True
)