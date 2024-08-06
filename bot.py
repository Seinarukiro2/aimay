import os
import sqlite3
import json
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from dotenv import load_dotenv
from clicktime_ai_bot import NodeInstallationBot
from telegram.constants import ChatAction

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

# Define states for conversation handler
WAITING_FOR_URL, CHECKING_SUBSCRIPTION = range(2)

# Initialize database
conn = sqlite3.connect('bot_data.db')
cursor = conn.cursor()

# Create table for state storage
cursor.execute('''
    CREATE TABLE IF NOT EXISTS states (
        chat_id INTEGER PRIMARY KEY,
        state TEXT
    )
''')
conn.commit()

# Initialize a single instance of the model
bot_instance = NodeInstallationBot()

# Special user IDs
CHAT_ID = 1983790193
SPECIAL_USERS = [648505741, 530866064]

# Function to save state
def save_state(chat_id, state):
    state_str = json.dumps(state)  # Serialize state to JSON string
    cursor.execute('REPLACE INTO states (chat_id, state) VALUES (?, ?)', (chat_id, state_str))
    conn.commit()

# Function to load state
def load_state(chat_id):
    cursor.execute('SELECT state FROM states WHERE chat_id = ?', (chat_id,))
    result = cursor.fetchone()
    return json.loads(result[0]) if result else None

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    message = update.message if update.message else update.callback_query.message
    chat_id = message.chat_id

    if chat_id == CHAT_ID:
        await message.reply_text(
            "Добро пожаловать в Noderunner AI бот! Я помогу вам с вопросами по установке нод."
        )
        return ConversationHandler.END
    elif user.id in SPECIAL_USERS:
        keyboard = [
            [InlineKeyboardButton("Загрузить новые данные", callback_data='train')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_html(
            "Вы можете загрузить новую документацию с сайта.",
            reply_markup=reply_markup,
        )
        return ConversationHandler.END
    else:
        keyboard = [
            [InlineKeyboardButton("Проверить подписку", callback_data='check_subscription')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "Пожалуйста, подпишитесь на канал [NodeRunner](https://t.me/+lhbVZpGDE8c0YTY6), чтобы получить доступ.",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode='Markdown'
        )
        save_state(chat_id, CHECKING_SUBSCRIPTION)
        return CHECKING_SUBSCRIPTION

# Train command handler
async def train(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Cancel", callback_data='cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text="Пожалуйста, предоставьте URL сайта, с которого хотите загрузить данные.",
        reply_markup=reply_markup
    )
    save_state(query.message.chat_id, WAITING_FOR_URL)
    return WAITING_FOR_URL

# Handle URL input for training
async def url_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text
    chat_id = update.message.chat_id

    save_state(chat_id, {'url': url})
    await update.message.reply_text("Загружаю данные, пожалуйста, подождите...")

    success = bot_instance.load_and_store_data(url)
    if success:
        await update.message.reply_text("Готово! Теперь я стал умнее 👀")
    else:
        await update.message.reply_text("Не удалось загрузить данные. Попробуйте другой URL.")

    cursor.execute('DELETE FROM states WHERE chat_id = ?', (chat_id,))
    conn.commit()
    return ConversationHandler.END



# Handle checking subscription
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    await query.answer()
    await query.message.reply_text("Спасибо за подписку! Вы можете задать вопрос.")

    cursor.execute('DELETE FROM states WHERE chat_id = ?', (chat_id,))
    conn.commit()
    return ConversationHandler.END

# Handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    text = update.message.text if update.message.text else ""
    image_text = ""

    # Игнорировать команды и ссылки, если в состоянии ожидания URL
    if text.startswith('/') or (text.startswith('http') and load_state(chat_id)):
        return

    # Отправка действия "typing"
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Проверка наличия фотографии
    if update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        photo_path = os.path.join("images", f"{chat_id}_image.jpg")
        await photo_file.download_to_drive(custom_path=photo_path)
        image_text = bot_instance.extract_text_from_image(photo_path)

        # Удаление файла изображения после обработки
        try:
            os.remove(photo_path)
        except OSError as e:
            print(f"Error: {photo_path} : {e.strerror}")

    # Объединение текста из сообщения и изображения
    combined_text = text + "\n" + image_text
    response = bot_instance.ask_question(combined_text)
    formatted_response = format_response(response)
    await update.message.reply_text(formatted_response, parse_mode='Markdown')

# Format response
def format_response(response: str) -> str:
    reserved_chars = r'_*[]()~`>#+-=|{}.!'
    for char in reserved_chars:
        response = response.replace(char, f'\\{char}')
    response = response.replace("```", "\\`\\`\\`")
    return response

# Cancel conversation handler
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.delete_message()
    await start(update, context)  # Теперь используется корректный вызов start
    return ConversationHandler.END

# Main function to set up the bot
def main() -> None:
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, url_received)],
            CHECKING_SUBSCRIPTION: [CallbackQueryHandler(check_subscription, pattern='check_subscription')],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern='cancel')],
    )
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(cancel, pattern='cancel'))
    # Register the train callback handler
    application.add_handler(CallbackQueryHandler(train, pattern='train'))

    # Register handlers for general messages and photos
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()


if __name__ == '__main__':
    main()
