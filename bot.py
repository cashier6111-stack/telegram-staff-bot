import subprocess
subprocess.run(["python", "init_db.py"])

import os
import telebot
import time

TOKEN = os.environ["BOT_TOKEN"]

bot = telebot.TeleBot(TOKEN, threaded=False)

bot.remove_webhook()

time.sleep(2)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Bot is working!")

print("Bot running...")

while True:
    try:
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60,
            skip_pending=True
        )

    except Exception as e:
        print("Error:", e)
        time.sleep(5)