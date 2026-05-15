import telebot

TOKEN = "8661103147:AAGrISexVfd0lz-_DjNX1Y_3MVwiMj-x6PU"

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Bot is working!")

print("Bot running...")

while True:
    try:
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60
        )

    except Exception as e:
        print("Error:", e)