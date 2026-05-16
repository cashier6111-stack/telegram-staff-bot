import os
import time
import subprocess
from datetime import datetime

import telebot
from database import get_db


# 自动初始化 database tables
subprocess.run(["python", "init_db.py"])

TOKEN = os.environ["BOT_TOKEN"]

bot = telebot.TeleBot(TOKEN, threaded=False)

# 防止 webhook / polling 冲突
bot.remove_webhook()
time.sleep(3)


@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "✅ Bot is working!")


@bot.message_handler(commands=["addstaff"])
def add_staff(message):
    try:
        parts = message.text.split()

        if len(parts) < 3:
            bot.reply_to(message, "Usage:\n/addstaff STAFF_ID NAME")
            return

        staff_id = parts[1]
        name = " ".join(parts[2:])

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO staff (staff_id, name)
            VALUES (%s, %s)
            ON CONFLICT (staff_id) DO NOTHING
            """,
            (staff_id, name)
        )

        conn.commit()
        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Staff added\nID: {staff_id}\nName: {name}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["liststaff"])
def list_staff(message):
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT staff_id, name
            FROM staff
            ORDER BY staff_id
        """)

        staffs = cur.fetchall()

        cur.close()
        conn.close()

        if not staffs:
            bot.reply_to(message, "No staff found.")
            return

        text = "👥 Staff List\n\n"

        for s in staffs:
            text += f"{s['staff_id']} - {s['name']}\n"

        bot.reply_to(message, text)

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["record"])
def add_record(message):
    try:
        parts = message.text.split()

        if len(parts) < 4:
            bot.reply_to(
                message,
                "Usage:\n/record STAFF_ID TYPE DURATION\n\nExample:\n/record S001 Toilet 10"
            )
            return

        staff_id = parts[1]
        action_type = parts[2]
        duration = int(parts[3])

        if action_type not in ["Toilet", "Smoke", "Meal"]:
            bot.reply_to(message, "❌ Type must be Toilet, Smoke, or Meal.")
            return

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT name
            FROM staff
            WHERE staff_id = %s
            """,
            (staff_id,)
        )

        staff = cur.fetchone()

        if not staff:
            bot.reply_to(message, "❌ Staff ID not found.")
            cur.close()
            conn.close()
            return

        name = staff["name"]

        cur.execute(
            """
            INSERT INTO break_records (
                staff_id, name, type, out_time, duration, status
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                staff_id,
                name,
                action_type,
                datetime.now(),
                duration,
                "Normal"
            )
        )

        conn.commit()
        cur.close()
        conn.close()

        bot.reply_to(
            message,
            f"✅ Record added\n"
            f"ID: {staff_id}\n"
            f"Name: {name}\n"
            f"Type: {action_type}\n"
            f"Duration: {duration} min"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=["today"])
def today_report(message):
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT name, type, duration, status
            FROM break_records
            WHERE DATE(out_time) = CURRENT_DATE
            ORDER BY name
        """)

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
            elif status == "Warning":
                summary[name]["Warning Count"] += 1
            elif status == "Timeout":
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


print("Bot running...")

bot.infinity_polling(
    timeout=60,
    long_polling_timeout=60,
    skip_pending=True,
    allowed_updates=None
)