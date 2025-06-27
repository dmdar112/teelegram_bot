import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# --- إعدادات ---
TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622

MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]
approved_v1_col = db["approved_v1"]
approved_v2_col = db["approved_v2"]
notified_users_col = db["notified_users"]

waiting_for_broadcast = {}

def owner_main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔔 إشعار الدخول", callback_data="notify"),
        InlineKeyboardButton("📎 الاشتراك الإجباري", callback_data="force_sub"),
        InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"),
        InlineKeyboardButton("🖋️ تعديل الأزرار", callback_data="edit_buttons"),
        InlineKeyboardButton("📢 الإذاعة", callback_data="broadcast_menu"),
        InlineKeyboardButton("🎥 قسم الفيديوهات", callback_data="videos_menu")
    )
    return markup

def back_button():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 رجوع", callback_data="main_menu"))
    return markup

def broadcast_menu():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🖼️ رسالة جماعية مع صورة", callback_data="broadcast_photo"))
    markup.add(InlineKeyboardButton("🔙 رجوع", callback_data="main_menu"))
    return markup

def videos_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎞️ فيديوهات1", callback_data="v1"),
        InlineKeyboardButton("🎞️ فيديوهات2", callback_data="v2"),
        InlineKeyboardButton("🗑️ حذف فيديوهات1", callback_data="del_v1"),
        InlineKeyboardButton("🗑️ حذف فيديوهات2", callback_data="del_v2")
    )
    markup.add(InlineKeyboardButton("🔙 رجوع", callback_data="main_menu"))
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id == OWNER_ID:
        bot.send_message(message.chat.id, "🛠️ لوحة التحكم:", reply_markup=owner_main_menu())
    else:
        bot.send_message(message.chat.id, "👋 مرحباً! لا تملك صلاحيات كافية.")

@bot.callback_query_handler(func=lambda call: call.from_user.id == OWNER_ID)
def handle_owner_buttons(call):
    data = call.data

    if data == "main_menu":
        bot.edit_message_text("🛠️ لوحة التحكم:", call.message.chat.id, call.message.message_id, reply_markup=owner_main_menu())

    elif data == "notify":
        bot.edit_message_text("🔔 إشعار الدخول: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

    elif data == "force_sub":
        bot.edit_message_text("📎 الاشتراك الإجباري: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

    elif data == "stats":
        bot.edit_message_text("📊 الإحصائيات: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

    elif data == "edit_buttons":
        bot.edit_message_text("🖋️ تعديل الأزرار: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

    elif data == "broadcast_menu":
        bot.edit_message_text("📢 الإذاعة:", call.message.chat.id, call.message.message_id, reply_markup=broadcast_menu())

    elif data == "broadcast_photo":
        waiting_for_broadcast[call.from_user.id] = True
        bot.send_message(call.message.chat.id, "🖼️ أرسل الصورة التي تريد إرسالها مع الرسالة.")

    elif data == "videos_menu":
        bot.edit_message_text("🎥 قسم الفيديوهات:", call.message.chat.id, call.message.message_id, reply_markup=videos_menu())

    elif data == "v1":
        bot.send_message(call.message.chat.id, "📤 سيتم عرض فيديوهات1 هنا.")

    elif data == "v2":
        bot.send_message(call.message.chat.id, "📤 سيتم عرض فيديوهات2 هنا.")

    elif data == "del_v1":
        bot.send_message(call.message.chat.id, "🗑️ حذف فيديوهات1: سيتم تنفيذه لاحقاً.")

    elif data == "del_v2":
        bot.send_message(call.message.chat.id, "🗑️ حذف فيديوهات2: سيتم تنفيذه لاحقاً.")

@bot.message_handler(content_types=['photo'])
def handle_broadcast_photo(message):
    if waiting_for_broadcast.get(message.from_user.id):
        waiting_for_broadcast.pop(message.from_user.id)
        bot.send_message(message.chat.id, "✅ تم استلام الصورة، الآن أرسل نص الرسالة.")
        # (يمكن استكمال المنطق لاحقاً)

# --- Flask Server لتشغيل البوت ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = import os import time import json from flask import Flask from threading import Thread

import telebot from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton from pymongo import MongoClient

--- إعدادات ---

TOKEN = os.environ.get("TOKEN") bot = telebot.TeleBot(TOKEN) OWNER_ID = 7054294622

MONGODB_URI = os.environ.get("MONGODB_URI") client = MongoClient(MONGODB_URI) db = client["telegram_bot_db"] approved_v1_col = db["approved_v1"] approved_v2_col = db["approved_v2"] notified_users_col = db["notified_users"]

waiting_for_broadcast = {}

def owner_main_menu(): markup = InlineKeyboardMarkup(row_width=2) markup.add( InlineKeyboardButton("🔔 إشعار الدخول", callback_data="notify"), InlineKeyboardButton("📎 الاشتراك الإجباري", callback_data="force_sub"), InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"), InlineKeyboardButton("🖋️ تعديل الأزرار", callback_data="edit_buttons"), InlineKeyboardButton("📢 الإذاعة", callback_data="broadcast_menu"), InlineKeyboardButton("🎥 قسم الفيديوهات", callback_data="videos_menu") ) return markup

def back_button(): markup = InlineKeyboardMarkup() markup.add(InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")) return markup

def broadcast_menu(): markup = InlineKeyboardMarkup() markup.add(InlineKeyboardButton("🖼️ رسالة جماعية مع صورة", callback_data="broadcast_photo")) markup.add(InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")) return markup

def videos_menu(): markup = InlineKeyboardMarkup(row_width=2) markup.add( InlineKeyboardButton("🎞️ فيديوهات1", callback_data="v1"), InlineKeyboardButton("🎞️ فيديوهات2", callback_data="v2"), InlineKeyboardButton("🗑️ حذف فيديوهات1", callback_data="del_v1"), InlineKeyboardButton("🗑️ حذف فيديوهات2", callback_data="del_v2") ) markup.add(InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")) return markup

@bot.message_handler(commands=['start']) def start(message): if message.from_user.id == OWNER_ID: bot.send_message(message.chat.id, "🛠️ لوحة التحكم:", reply_markup=owner_main_menu()) else: bot.send_message(message.chat.id, "👋 مرحباً! لا تملك صلاحيات كافية.")

@bot.callback_query_handler(func=lambda call: call.from_user.id == OWNER_ID) def handle_owner_buttons(call): data = call.data

if data == "main_menu":
    bot.edit_message_text("🛠️ لوحة التحكم:", call.message.chat.id, call.message.message_id, reply_markup=owner_main_menu())

elif data == "notify":
    bot.edit_message_text("🔔 إشعار الدخول: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

elif data == "force_sub":
    bot.edit_message_text("📎 الاشتراك الإجباري: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

elif data == "stats":
    bot.edit_message_text("📊 الإحصائيات: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

elif data == "edit_buttons":
    bot.edit_message_text("🖋️ تعديل الأزرار: (سيتم إضافته لاحقاً)", call.message.chat.id, call.message.message_id, reply_markup=back_button())

elif data == "broadcast_menu":
    bot.edit_message_text("📢 الإذاعة:", call.message.chat.id, call.message.message_id, reply_markup=broadcast_menu())

elif data == "broadcast_photo":
    waiting_for_broadcast[call.from_user.id] = True
    bot.send_message(call.message.chat.id, "🖼️ أرسل الصورة التي تريد إرسالها مع الرسالة.")

elif data == "videos_menu":
    bot.edit_message_text("🎥 قسم الفيديوهات:", call.message.chat.id, call.message.message_id, reply_markup=videos_menu())

elif data == "v1":
    bot.send_message(call.message.chat.id, "📤 سيتم عرض فيديوهات1 هنا.")

elif data == "v2":
    bot.send_message(call.message.chat.id, "📤 سيتم عرض فيديوهات2 هنا.")

elif data == "del_v1":
    bot.send_message(call.message.chat.id, "🗑️ حذف فيديوهات1: سيتم تنفيذه لاحقاً.")

elif data == "del_v2":
    bot.send_message(call.message.chat.id, "🗑️ حذف فيديوهات2: سيتم تنفيذه لاحقاً.")

@bot.message_handler(content_types=['photo']) def handle_broadcast_photo(message): if waiting_for_broadcast.get(message.from_user.id): waiting_for_broadcast.pop(message.from_user.id) bot.send_message(message.chat.id, "✅ تم استلام الصورة، الآن أرسل نص الرسالة.") # (يمكن استكمال المنطق لاحقاً)

--- Flask Server لتشغيل البوت ---

app = Flask('')

@app.route('/') def home(): return "Bot is running"

def run(): app.run(host='0.0.0.0', port=3000)

def keep_alive(): t = Thread(target=run) t.start()

keep_alive() bot.infinity_polling()

(target=run)
    t.start()

keep_alive()
bot.infinity_polling()
