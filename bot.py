import os
import time
import subprocess
from datetime import datetime

import telebot
from telebot import types
from database import get_db


subprocess.run(["python", "init_db.py"], check=False)

TOKEN = os.environ["BOT_TOKEN"]

bot = telebot.TeleBot(TOKEN, threaded=False)
bot.remove_webhook()
time.sleep(3)


RULES = {
    "Toilet": {"warning": 10, "timeout": 15},
    "Smoke": {"warning": 6, "timeout": 8},
    "Meal": {"warning": 31, "timeout": 35},
}

ROLE_LEVELS = {
    "user": 1,
    "leader": 2,
    "admin": 3,
}


def get_db_cursor():
    conn = get_db()
    return conn, conn.cursor()


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


def get_status(action_type, duration_minutes):
    rule = RULES[action_type]

    if duration_minutes > rule["timeout"]:
        return "Timeout"

    if duration_minutes > rule["warning"]:
        return "Warning"

    return "Normal"


def send_menu(chat_id):
    markup = types.InlineKeyboardMarkup()

    markup.row(
        types.InlineKeyboardButton("🚻 Toilet Out", callback_data="toiletout"),
        types.InlineKeyboardButton("✅ Toilet In", callback_data="toiletin")
    )

    markup.row(
        types.InlineKeyboardButton("🚬 Smoke Out", callback_data="smokeout"),
        types.InlineKeyboardButton("✅ Smoke In", callback_data="smokein")
    )

    markup.row(
        types.InlineKeyboardButton("🍱 Meal Out", callback_data="mealout"),
        types.InlineKeyboardButton("✅ Meal In", callback_data="mealin")
    )

    markup.row(
        types.InlineKeyboardButton("❌ Cancel Last", callback_data="cancel")
    )

    bot.send_message(chat_id, "Attendance Menu", reply_markup=markup)


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
    get_or_create_company(message.chat)
    send_menu(message.chat.id)


@bot.message_handler(commands=["myid"])
def my_id(message):
    bot.reply_to(message, f"Your Telegram ID:\n{message.from_user.id}")


@bot.message_handler(commands=["register"])
def register(message):
    try:
        parts = message.text.split()

        if len(parts) < 3:
            bot.reply_to(
                message,
                "Usage:\n/register STAFF_ID REAL_NAME\n\nExample:\n/register A001 Catherine"
            )
            return

        company_id = get_or_create_company(message.chat)

        staff_id = parts[1]
        real_name = " ".join(parts[2:])
        telegram_id = message.from_user.id
        username = message.from_user.username or ""

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

        if cur.fetchone():
            bot.reply_to(message, "❌ You already registered.")
            cur.close()
            conn.close()
            return

        cur.execute(
            """
            SELECT *
            FROM staff
            WHERE company_id = %s
            AND staff_id = %s
            """,
            (company_id, staff_id)
        )

        if cur.fetchone():
            bot.reply_to(message, "❌ Staff ID already exists.")
            cur.close()
            conn.close()
            return

        cur.execute(
            """
            INSERT INTO staff (
                company_id, telegram_id, staff_id, real_name, username, status
            )
            VALUES (%s, %s, %s, %s, %s, 'Active')
            """,
            (company_id, telegram_id, staff_id, real_name, username)
        )

        conn.commit()
        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Registered successfully\nStaff ID: {staff_id}\nName: {real_name}"
        )

        send_menu(message.chat.id)

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


def start_action(chat, user, action_type):
    try:
        company_id = get_or_create_company(chat)
        staff = find_staff(company_id, user.id)

        if not staff:
            bot.send_message(chat.id, "❌ Please register first.\nExample: /register A001 Catherine")
            return

        existing_open = get_open_record(company_id, user.id)

        if existing_open:
            bot.send_message(
                chat.id,
                f"❌ You already have an open {existing_open['type']} record.\nPlease click In or Cancel first."
            )
            return

        now = datetime.now()

        conn, cur = get_db_cursor()

        cur.execute(
            """
            INSERT INTO break_records (
                company_id, telegram_id, staff_id, name, type, out_time, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'Open')
            """,
            (
                company_id,
                user.id,
                staff["staff_id"],
                staff["real_name"],
                action_type,
                now
            )
        )

        conn.commit()
        cur.close()
        conn.close()

        bot.send_message(
            chat.id,
            f"✅ {action_type} Out recorded\n"
            f"👤 {staff['real_name']}\n"
            f"🕒 {now.strftime('%Y-%m-%d %I:%M:%S %p')}"
        )

        send_menu(chat.id)

    except Exception as e:
        bot.send_message(chat.id, f"❌ Error: {e}")


def end_action(chat, user, action_type):
    try:
        company_id = get_or_create_company(chat)
        staff = find_staff(company_id, user.id)

        if not staff:
            bot.send_message(chat.id, "❌ Please register first.")
            return

        record = get_open_record(company_id, user.id, action_type)

        if not record:
            bot.send_message(chat.id, f"❌ No open {action_type} record found.")
            return

        in_time = datetime.now()
        duration_minutes = round((in_time - record["out_time"]).total_seconds() / 60)
        status = get_status(action_type, duration_minutes)

        conn, cur = get_db_cursor()

        cur.execute(
            """
            UPDATE break_records
            SET in_time = %s,
                duration = %s,
                status = %s
            WHERE id = %s
            """,
            (in_time, duration_minutes, status, record["id"])
        )

        conn.commit()
        cur.close()
        conn.close()

        warning_text = ""

        if status == "Warning":
            warning_text = f"\n⚠️ {action_type} exceeded {RULES[action_type]['warning']} minutes."

        if status == "Timeout":
            warning_text = f"\n🚨 {action_type} exceeded {RULES[action_type]['timeout']} minutes."

        bot.send_message(
            chat.id,
            f"✅ {action_type} In recorded\n"
            f"👤 {staff['real_name']}\n"
            f"⏳ Duration: {duration_minutes} min\n"
            f"📌 Status: {status}"
            f"{warning_text}"
        )

        send_menu(chat.id)

    except Exception as e:
        bot.send_message(chat.id, f"❌ Error: {e}")


def cancel_last(chat, user):
    try:
        company_id = get_or_create_company(chat)
        staff = find_staff(company_id, user.id)

        if not staff:
            bot.send_message(chat.id, "❌ Please register first.")
            return

        record = get_open_record(company_id, user.id)

        if not record:
            bot.send_message(chat.id, "❌ No open record found to cancel.")
            return

        cancel_time = datetime.now()
        duration_minutes = round((cancel_time - record["out_time"]).total_seconds() / 60)

        conn, cur = get_db_cursor()

        cur.execute(
            """
            UPDATE break_records
            SET in_time = %s,
                duration = %s,
                status = 'Cancelled'
            WHERE id = %s
            """,
            (cancel_time, duration_minutes, record["id"])
        )

        conn.commit()
        cur.close()
        conn.close()

        bot.send_message(
            chat.id,
            f"❌ Last record cancelled\n"
            f"👤 {staff['real_name']}\n"
            f"📌 Type: {record['type']}\n"
            f"⏳ Cancelled after: {duration_minutes} min"
        )

        send_menu(chat.id)

    except Exception as e:
        bot.send_message(chat.id, f"❌ Error: {e}")


@bot.callback_query_handler(func=lambda call: True)
def handle_button(call):
    chat = call.message.chat
    user = call.from_user

    if call.data == "toiletout":
        start_action(chat, user, "Toilet")

    elif call.data == "toiletin":
        end_action(chat, user, "Toilet")

    elif call.data == "smokeout":
        start_action(chat, user, "Smoke")

    elif call.data == "smokein":
        end_action(chat, user, "Smoke")

    elif call.data == "mealout":
        start_action(chat, user, "Meal")

    elif call.data == "mealin":
        end_action(chat, user, "Meal")

    elif call.data == "cancel":
        cancel_last(chat, user)

    bot.answer_callback_query(call.id)


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

        bot.reply_to(message, text)

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

        old_staff_id = parts[1]
        new_staff_id = parts[2]
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
                real_name = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE company_id = %s
            AND staff_id = %s
            """,
            (new_staff_id, new_name, company_id, old_staff_id)
        )

        conn.commit()
        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Staff updated\n"
            f"Old ID: {old_staff_id}\n"
            f"New ID: {new_staff_id}\n"
            f"Name: {new_name}"
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

        bot.reply_to(message, f"✅ Leader added\nTelegram ID: {telegram_id}")

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

        bot.reply_to(message, f"✅ Admin added\nTelegram ID: {telegram_id}")

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["removerole"])
def remove_role(message):
    try:
        company_id = get_or_create_company(message.chat)

        if not has_role(company_id, message.from_user.id, "admin"):
            bot.reply_to(message, "❌ Admin only.")
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.reply_to(message, "Usage:\n/removerole TELEGRAM_ID")
            return

        telegram_id = int(parts[1])

        conn, cur = get_db_cursor()

        cur.execute(
            """
            DELETE FROM roles
            WHERE company_id = %s
            AND telegram_id = %s
            """,
            (company_id, telegram_id)
        )

        conn.commit()
        cur.close()
        conn.close()

        bot.reply_to(message, f"✅ Role removed\nTelegram ID: {telegram_id}")

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["today"])
def today_report(message):
    try:
        company_id = get_or_create_company(message.chat)

        conn, cur = get_db_cursor()

        cur.execute(
            """
            SELECT name, type, duration, status
            FROM break_records
            WHERE company_id = %s
            AND DATE(out_time) = CURRENT_DATE
            AND status != 'Open'
            ORDER BY name
            """,
            (company_id,)
        )

        records = cur.fetchall()

        cur.close()
        conn.close()

        if not records:
            bot.reply_to(message, "No records for today.")
            return

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

        report = "📊 Daily Report\n\n"

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

        bot.reply_to(message, report)

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


print("Bot is running...")

bot.infinity_polling(
    timeout=60,
    long_polling_timeout=60,
    skip_pending=True
)