import logging
import os
import time
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    CallbackContext,
)

import openai

openai.api_key = ""
TELEGRAM_API_TOKEN = ''

logging.basicConfig(level=logging.INFO)

user_settings = {}

def truncate_history(user_history, max_tokens):
    tokens_count = 0
    for msg in reversed(user_history):
        tokens_count += len(msg["content"].split())
        if tokens_count > max_tokens:
            user_history.remove(msg)

def main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("Помощь", callback_data="help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def read_allowed_users_from_file():
    with open("allowed_users.txt", "r") as file:
        return [int(line.strip()) for line in file.readlines()]

ALLOWED_USERS = read_allowed_users_from_file()

def restricted(func):
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        chat_type = update.effective_chat.type

        if chat_type != "group" and chat_type != "supergroup" and user_id not in ALLOWED_USERS:
            restricted_access(update, context)
            return
        if 'update' in func.__code__.co_varnames and 'context' in func.__code__.co_varnames:
            return func(update, context, *args, **kwargs)
        else:
            return func(user_id, *args, **kwargs)
    return wrapped

def restricted_access(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    update.message.reply_text(
        f"Извините, у вас нет доступа к этому боту.\n"
        f"Ваш Telegram ID: {user_id}\n"
        f"Если вы хотите получить доступ, отправьте этот ID автору бота."
    )
def menu_button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    if query.data == "settings":
        settings_query(query, context)
    elif query.data == "reset_context":
        reset_context_query(query, context)
    elif query.data == "help":
        query.edit_message_text(
            f"Доступные команды:\n"
            f"/resetcontext для сброса контекста.\n"
            f"/settemperature Для установки температуры от 0 до 1. Например: /settemperature 0.7\n"
            f"/setmodel выбрать модель. Например: /setmodel gpt-3.5-turbo\n"
            f"/setmaxtokens Для установки максимального количества токенов. Например: /setmaxtokens 1500"
        )

def settings_query(query, context):
    user_id = query.from_user.id
    settings = get_user_settings(user_id, context)
    query.edit_message_text(
        f"Текущие настройки:\nМодель: {settings['model']}\nТемпература: {settings['temperature']}\nМакс. количество токенов: {settings['max_tokens']}"
    )

def reset_context_query(query, context):
    user_id = query.from_user.id
    if user_id in context.user_data:
        del context.user_data[user_id]
    query.edit_message_text("Контекст успешно сброшен.")

def get_user_settings(user_id, context):
    if 'user_settings' not in context.user_data:
        context.user_data['user_settings'] = {}
    if user_id not in context.user_data['user_settings']:
        context.user_data['user_settings'][user_id] = {'model': 'gpt-3.5-turbo', 'temperature': 0.7, 'max_tokens': 1500}
    return context.user_data['user_settings'][user_id]

@restricted
def start(update: Update, context: CallbackContext):
    global ALLOWED_USERS
    ALLOWED_USERS = read_allowed_users_from_file()
    user_id = update.message.from_user.id
    settings = get_user_settings(user_id, context)
    update.message.reply_text(
        'Привет! Я бот, использующий ChatGPT для разговора. Напиши мне что-нибудь!',
        reply_markup=main_menu_keyboard()
    )

def settings(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    settings = get_user_settings(user_id, context)
    update.message.reply_text(f"Текущие настройки:\nМодель: {settings['model']}\nТемпература: {settings['temperature']}\nМакс. количество токенов: {settings['max_tokens']}")

def set_model(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    model = context.args[0] if context.args else None
    if model:
        get_user_settings(user_id, context)['model'] = model
        update.message.reply_text(f"Модель изменена на {model}")
    else:
        update.message.reply_text("Введите модель после команды. Например: /setmodel text-davinci-003")

def set_temperature(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    temperature = float(context.args[0]) if context.args else None
    if temperature is not None:
        get_user_settings(user_id, context)['temperature'] = temperature
        update.message.reply_text(f"Температура изменена на {temperature}")
    else:
        update.message.reply_text("Введите значение температуры после команды. Например: /settemperature 0.7")

def set_max_tokens(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    max_tokens = int(context.args[0]) if context.args else None
    if max_tokens is not None:
        get_user_settings(user_id, context)['max_tokens'] = max_tokens
        update.message.reply_text(f"Макс. количество токенов изменено на {max_tokens}")
    else:
        update.message.reply_text("Введите максимальное количество токенов после команды. Например: /setmaxtokens 150")

def escape_reserved_chars(text: str) -> str:
    reserved_chars = ['.', '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '!', '\\']
    escaped_text = ''

    for char in text:
        if char in reserved_chars:
            escaped_text += '\\'
        escaped_text += char

    return escaped_text

def chat_gpt_response(text, user_id, context, user_history):
    settings = get_user_settings(user_id, context)

    custom_context = context.user_data.get(user_id, {}).get('custom_context', 'You are a friendly and informal assistant.')

    user_history.append({'role': 'user', 'content': text})

    truncate_history(user_history, 4096 - 1500)  # Reserve 1500 tokens for model's response

    all_messages = [{'role': 'system', 'content': custom_context}] + user_history

    response = openai.ChatCompletion.create(
        model=settings['model'],
        messages=all_messages,
        temperature=settings['temperature'],
        max_tokens=settings['max_tokens'],
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
    )
    return response.choices[0].message['content'].strip()

def get_user_history(user_id, context):
    if 'user_history' not in context.user_data:
        context.user_data['user_history'] = {}

    if user_id not in context.user_data['user_history']:
        context.user_data['user_history'][user_id] = []

    return context.user_data['user_history'][user_id]

def clear_history(update, context):
    user_id = update.message.from_user.id
    user_history = get_user_history(user_id, context)
    user_history.clear()
    update.message.reply_text('История общения успешно очищена.')

def reset_context(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_history = get_user_history(user_id, context)
    user_history.clear()
    if user_id in context.user_data:
        del context.user_data[user_id]
    update.message.reply_text("Контекст успешно сброшен.")

def message_handler(update: Update, context: CallbackContext):
    if update.message is None:
        return

    user_id = update.message.from_user.id
    user_name = update.message.from_user.username
    user_mention = update.message.from_user.mention_markdown_v2()
    chat_type = update.effective_chat.type
    bot_username = context.bot.username
    bot_mention = f"@{bot_username}"

    if chat_type in ("group", "supergroup") and bot_mention.lower() not in update.message.text.lower():
        return

    if user_id not in context.user_data:
        context.user_data[user_id] = {}

    user_data = context.user_data[user_id]

    input_text = update.message.text
    try:
        user_history = get_user_history(user_id, context)
        user_history.append({'role': 'user', 'content': input_text})
        gpt_response = chat_gpt_response(input_text, user_id, context, user_history)

        if chat_type in ("group", "supergroup"):
            escaped_response = escape_reserved_chars(gpt_response)
            user_history.append({'role': 'assistant', 'content': escaped_response})

        else:
            user_history.append({'role': 'assistant', 'content': gpt_response})

        if chat_type in ("group", "supergroup"):
            update.message.reply_text(f"{user_mention}, {escaped_response}", parse_mode="MarkdownV2")
        else:
            update.message.reply_text(gpt_response)
    except Exception as e:
        logging.error(e)
        update.message.reply_text('Извините, произошла ошибка при обработке вашего сообщения.')

def set_context(update, context):
    new_context = ' '.join(context.args)
    if not new_context:
        update.message.reply_text('Пожалуйста, укажите новый контекст после команды /setcontext.')
        return

    user_id = update.message.from_user.id
    if user_id not in context.user_data:
        context.user_data[user_id] = {}

    context.user_data[user_id]['custom_context'] = new_context
    update.message.reply_text(f'Контекст успешно изменен на: {new_context}')

def show_context(update: Update, context: CallbackContext):
    user_data = context.user_data
    chat_data = context.chat_data
    bot_data = context.bot_data

    user_data_text = '\n'.join([f"{key}: {value}" for key, value in user_data.items()])
    chat_data_text = '\n'.join([f"{key}: {value}" for key, value in chat_data.items()])
    bot_data_text = '\n'.join([f"{key}: {value}" for key, value in bot_data.items()])

    context_text = f"User data:\n{user_data_text}\n\nChat data:\n{chat_data_text}\n\nBot data:\n{bot_data_text}"
    update.message.reply_text(f"Текущий контекст:\n{context_text}")

def help(update, context):
    update.message.reply_text(
            f"Доступные команды:\n"
                        f"/help - Получить справку\n"
                        f"/resetchat Сброс чата на начальные настройки. Чат забудет историю и контекст. Переписка при этом останется на месте.\n"
            f"/setcontext Тонкая настройка чата. Задает кем быть модели. Пример:\n"
                        f"* ты эксперт в истории ацтеков;\n"
            f"* ты преподаватель математики;\n"
                        f"* ты специализируешься на предоставлении советов по путешествиям;\n"
                        f"* ты проффесиональный кино-критик\n; И Т.д.\n"
            f"/settemperature Для установки температуры от 0 до 1. Например: /settemperature 0.7\n"
                        f"Более высокие значения, такие как 0,8, сделают вывод более случайным, а более низкие значения,\n"
                        f"такие как 0,2, сделают его более сфокусированным и детерминированным.\n"
            f"/setmaxtokens Для установки максимального количества токенов. Например: /setmaxtokens 1500\n"
                        f"\tМаксимальное количество токенов для генерации при завершении чата.\n"
            f"\tОбщая длина входных и сгенерированных токенов ограничена длиной контекста модели.\n"
                        f"/settings - Показать текущие настройки\n"
            )

def main():
    updater = Updater(TELEGRAM_API_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("setcontext", set_context, pass_args=True))
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('help', help))
    dp.add_handler(CommandHandler('settings', settings))
    dp.add_handler(CommandHandler('showcontext', show_context))
    dp.add_handler(CommandHandler('settemperature', set_temperature))
    dp.add_handler(CommandHandler("resetchat", reset_context))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler, pass_user_data=True))
    dp.add_handler(CallbackQueryHandler(menu_button_handler))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
