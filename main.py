import os
import time
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient
import cloudinary
import cloudinary.uploader

# متغيرات البيئة
TOKEN = os.environ.get("TOKEN")
OWNER_ID = 5881024874  # عدّل رقمك هنا

CLOUD_NAME = os.environ.get("CLOUD_NAME")
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")

MONGODB_URI = os.environ.get("MONGODB_URI")

# إعداد Cloudinary
cloudinary.config(
    cloud_name=CLOUD_NAME,
    api_key=API_KEY,
    api_secret=API_SECRET,
)

# إعداد MongoDB
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"]
approved_v2_col = db["approved_v2"]
notified_users_col = db["notified_users"]

bot = telebot.TeleBot(TOKEN)

subscribe_links_v1 = [
    "https://t.me/R2M199",
    "https://t.me/SNOKER_VIP",
]

subscribe_links_v2 = [
    "https://t.me/R2M199",
    "https://t.me/SNOKER_VIP",
]

pending_check = {}
owner_upload_mode = {}
waiting_for_broadcast = {}
waiting_for_delete = {}

def load_approved_users(collection):
    return set(doc["user_id"] for doc in collection.find())

def add_approved_user(collection, user_id):
    if not collection.find_one({"user_id": user_id}):
        collection.insert_one({"user_id": user_id})

def remove_approved_user(collection, user_id):
    collection.delete_one({"user_id": user_id})

def has_notified(user_id):
    return notified_users_col.find_one({"user_id": user_id}) is not None

def add_notified_user(user_id):
    if not has_notified(user_id):
        notified_users_col.insert_one({"user_id": user_id})

approved_v1 = load_approved_users(approved_v1_col)
approved_v2 = load_approved_users(approved_v2_col)

def main_keyboard():
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

def owner_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("فيديوهات1", "فيديوهات2")
    markup.row("حذف فيديوهات1", "حذف فيديوهات2")
    markup.row("حذف فيديو واحد")
    markup.row("رسالة جماعية مع صورة")
    return markup

def get_all_approved_users():
    return set(
        user["user_id"] for user in approved_v1_col.find()
    ).union(
        user["user_id"] for user in approved_v2_col.find()
    )

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "لا يوجد اسم"
    username = f"@{message.from_user.username}" if message.from_user.username else "لا يوجد معرف"

    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
        return

    if not has_notified(user_id):
        total_users = len(get_all_approved_users())
        new_user_msg = f"""👾 تم دخول شخص جديد إلى البوت الخاص بك
-----------------------
• الاسم : {first_name}
• المعرف : {username}
• الايدي : {user_id}
-----------------------
• عدد الأعضاء الكلي: {total_users}
"""
        bot.send_message(OWNER_ID, new_user_msg)
        add_notified_user(user_id)

    bot.send_message(user_id, "مرحباً! اختر من الأزرار:", reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    user_id = message.from_user.id
    if user_id in load_approved_users(approved_v1_col):
        send_videos(user_id, "v1")
    else:
        send_required_links(user_id, "v1")

@bot.message_handler(func=lambda m: m.text == "فيديوهات2")
def handle_v2(message):
    user_id = message.from_user.id
    if user_id in load_approved_users(approved_v2_col):
        send_videos(user_id, "v2")
    else:
        send_required_links(user_id, "v2")

def send_required_links(chat_id, category):
    data = pending_check.get(chat_id, {"category": category, "step": 0})
    step = data["step"]
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2
    if step >= len(links):
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة. الرجاء الانتظار.", reply_markup=main_keyboard())
        pending_check.pop(chat_id, None)
        return

    link = links[step]
    text = f"""🚸| عذراً عزيزي .
🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه

- {link}

‼️| اشترك ثم ارسل /start"""

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ بعد الاشتراك اضغط هنا للتحقق", callback_data=f"verify_{category}_{step}"))
    bot.send_message(chat_id, text, reply_markup=markup)

    pending_check[chat_id] = {"category": category, "step": step}

@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    step = int(step_str) + 1
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    if step < len(links):
        pending_check[user_id] = {"category": category, "step": step}
        send_required_links(user_id, category)
    else:
        bot.send_message(user_id, """✅ شكراً لاشتراك.
⏳ انتظر ثوانٍ حتى نتأكد أنك اشتركت في جميع القنوات، سيتم قبولك تلقائياً، وإذا لم تشترك سيتم رفضك⚠️""")
        notify_owner_for_approval(user_id, call.from_user.first_name, category)
        pending_check.pop(user_id, None)

def notify_owner_for_approval(user_id, name, category):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("قبول", callback_data=f"approve_{category}_{user_id}"),
        types.InlineKeyboardButton("رفض", callback_data=f"reject_{category}_{user_id}")
    )
    bot.send_message(OWNER_ID, f"طلب جديد من {name}\nالآيدي: {user_id}\nلفيديوهات {category[-1]}", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_owner_response(call):
    parts = call.data.split("_")
    action, category, user_id = parts[0], parts[1], int(parts[2])

    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "غير مصرح.")
        return

    if action == "approve":
        if category == "v1":
            add_approved_user(approved_v1_col, user_id)
        else:
            add_approved_user(approved_v2_col, user_id)
        bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة! يمكنك الآن استخدام البوت.")
        bot.edit_message_text("تم القبول.", call.message.chat.id, call.message.message_id)
    else:
        bot.send_message(user_id, "❌ لم يتم قبولك. اشترك في قنوات البوت ثم أرسل /start مرة أخرى.")
        bot.edit_message_text("تم الرفض.", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['v1'])
def set_v1_mode(message):
    if message.from_user.id == OWNER_ID:
        owner_upload_mode[message.from_user.id] = "v1"
        bot.reply_to(message, "سيتم حفظ الفيديوهات التالية في فيديوهات1.")

@bot.message_handler(commands=['v2'])
def set_v2_mode(message):
    if message.from_user.id == OWNER_ID:
        owner_upload_mode[message.from_user.id] = "v2"
        bot.reply_to(message, "سيتم حفظ الفيديوهات التالية في فيديوهات2.")

@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.from_user.id
    if user_id == OWNER_ID and user_id in owner_upload_mode:
        category = owner_upload_mode[user_id]

        # تحميل الفيديو من تلغرام
        file_info = bot.get_file(message.video.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # حفظ مؤقت
        tmp_filename = f"temp_video_{int(time.time())}.mp4"
        with open(tmp_filename, "wb") as f:
            f.write(downloaded_file)

        # رفع إلى Cloudinary
        try:
            upload_res = cloudinary.uploader.upload_large(tmp_filename, resource_type="video", folder=f"videos_{category}")
            video_url = upload_res.get("secure_url")

            bot.reply_to(message, f"✅ تم رفع الفيديو على السحابة بنجاح!\nرابط الفيديو:\n{video_url}")
        except Exception as e:
            bot.reply_to(message, f"❌ حدث خطأ أثناء رفع الفيديو: {str(e)}")
        finally:
            # حذف الملف المؤقت
            if os.path.exists(tmp_filename):
                os.remove(tmp_filename)

        # حفظ بيانات الفيديو في قاعدة البيانات حسب الفئة
        video_data = {
            "file_id": message.video.file_id,
            "public_id": upload_res.get("public_id"),
            "url": upload_res.get("secure_url"),
            "user_id": user_id,
            "timestamp": int(time.time())
        }

        if category == "v1":
            approved_v1_col.insert_one(video_data)
        else:
            approved_v2_col.insert_one(video_data)

    elif user_id == OWNER_ID and message.text == "حذف فيديو واحد":
        waiting_for_delete[user_id] = True
        bot.send_message(user_id, "أرسل لي الـ public_id الخاص بالفيديو الذي تريد حذفه:")

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_delete.get(m.from_user.id))
def delete_single_video(message):
    public_id = message.text.strip()
    user_id = message.from_user.id

    # البحث عن الفيديو في المجموعتين
    video_doc = approved_v1_col.find_one({"public_id": public_id})
    collection = approved_v1_col
    if not video_doc:
        video_doc = approved_v2_col.find_one({"public_id": public_id})
        collection = approved_v2_col

    if not video_doc:
        bot.send_message(user_id, "❌ لم أجد فيديو بهذا public_id.")
    else:
        try:
            # حذف من Cloudinary
            result = cloudinary.uploader.destroy(public_id, resource_type="video")
            if result.get("result") == "ok":
                # حذف من MongoDB
                collection.delete_one({"public_id": public_id})
                bot.send_message(user_id, "✅ تم حذف الفيديو بنجاح.")
            else:
                bot.send_message(user_id, f"❌ لم أستطع حذف الفيديو من السحابة: {result}")
        except Exception as e:
            bot.send_message(user_id, f"❌ حدث خطأ أثناء الحذف: {str(e)}")

    waiting_for_delete.pop(user_id, None)

def send_videos(user_id, category):
    collection = approved_v1_col if category == "v1" else approved_v2_col
    videos = list(collection.find())
    if not videos:
        bot.send_message(user_id, "لا توجد فيديوهات متاحة حالياً.")
        return

    for video in videos:
        try:
            bot.send_video(user_id, video["file_id"])
            time.sleep(0.5)  # لتجنب الحظر المؤقت من تلغرام
        except Exception as e:
            print(f"خطأ في إرسال الفيديو: {e}")

def broadcast_message(text):
    users = get_all_approved_users()
    for user_id in users:
        try:
            bot.send_message(user_id, text)
            time.sleep(0.1)
        except Exception:
            pass

# بث رسالة مع صورة (يتم من خلال زر في لوحة مالك البوت)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_broadcast.get(m.from_user.id))
def handle_broadcast_photo(message):
    if not message.photo:
        bot.send_message(message.from_user.id, "يرجى إرسال صورة مع الرسالة.")
        return

    caption = waiting_for_broadcast[message.from_user.id]
    file_id = message.photo[-1].file_id

    users = get_all_approved_users()
    for user_id in users:
        try:
            bot.send_photo(user_id, file_id, caption=caption)
            time.sleep(0.1)
        except Exception:
            pass

    bot.send_message(message.from_user.id, "تم إرسال الرسالة مع الصورة إلى الجميع.")
    waiting_for_broadcast.pop(message.from_user.id, None)

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID)
def handle_owner_text(message):
    text = message.text
    if text == "حذف فيديو واحد":
        waiting_for_delete[message.from_user.id] = True
        bot.send_message(message.from_user.id, "أرسل لي الـ public_id الخاص بالفيديو الذي تريد حذفه:")
    elif text == "رسالة جماعية مع صورة":
        bot.send_message(message.from_user.id, "أرسل لي نص الرسالة التي تريد إرسالها مع الصورة:")
        waiting_for_broadcast[message.from_user.id] = ""
    elif waiting_for_broadcast.get(message.from_user.id) == "":
        waiting_for_broadcast[message.from_user.id] = text
        bot.send_message(message.from_user.id, "الآن أرسل لي الصورة التي تريد إرسالها مع هذه الرسالة:")
    else:
        bot.send_message(message.from_user.id, "استخدم الأزرار في لوحة التحكم.")

def run():
    bot.infinity_polling()

app = Flask("")

@app.route("/")
def home():
    return "بوت يعمل..."

def keep_alive():
    server = Thread(target=app.run, kwargs={"host":"0.0.0.0","port":8080})
    server.start()

if __name__ == "__main__":
    keep_alive()
    run()
