import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient
import cloudinary
import cloudinary.uploader

# متغيرات البيئة
TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622  # عدّل رقمك هنا

maintenance_mode = False
# هنا بعد تعريف المتغيرات والثوابت اكتب:

waiting_for_delete = {}

@bot.message_handler(commands=['off'])
def enable_maintenance(message):
    if message.from_user.id == OWNER_ID:
        global maintenance_mode
        maintenance_mode = True
        bot.reply_to(message, "✅ تم تفعيل وضع الصيانة. البوت الآن في وضع الصيانة.")
        # إرسال رسالة لكل المستخدمين أن البوت في الصيانة
        users = get_all_approved_users()
        for user_id in users:
            try:
                bot.send_message(user_id, "⏳ انتظر ثوانٍ نتحقق أنك اشتركت في جميع القنوات📂،")
            except:
                pass

@bot.message_handler(commands=['on'])
def disable_maintenance(message):
    if message.from_user.id == OWNER_ID:
        global maintenance_mode
        maintenance_mode = False
        bot.reply_to(message, "✅ تم إيقاف وضع الصيانة. البوت عاد للعمل.")
        # إرسال رسالة لكل المستخدمين أن البوت عاد للعمل
        users = get_all_approved_users()
        for user_id in users:
            try:
                bot.send_message(user_id, "✅ تم إيقاف وضع الصيانة، البوت عاد للعمل. يمكنك استخدام الفيديوهات والاشتراك.")
            except:
                pass
# ثم يبدأ الكود الأساسي (تهيئة البوت، الدوال، المعالجات ... الخ)

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

subscribe_links_v1 = [
    "https://t.me/+2L5KrXuCDUA5ZWIy",
    "https://t.me/+SPTrcs3tJqhlMDVi",
    "https://t.me/+W2KuzsUu_zcyODIy",
    "https://t.me/+CFA6qHiV0zw1NjRk",
]

subscribe_links_v2 = [
    "https://t.me/R2M199",
    "https://t.me/SNOKER_VIP",
]

pending_check = {}
owner_upload_mode = {}
waiting_for_broadcast = {}

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

def main_keyboard():
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

def owner_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("فيديوهات1", "فيديوهات2")
    markup.row("حذف فيديوهات1", "حذف فيديوهات2")
    markup.row("رسالة جماعية مع صورة")
    return markup

def get_all_approved_users():
    return set(
        user["user_id"] for user in approved_v1_col.find()
    ).union(
        user["user_id"] for user in approved_v2_col.find()
    )

@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات1" and m.from_user.id == OWNER_ID)
def delete_videos_v1(message):
    user_id = message.from_user.id
    try:
        res = cloudinary.Search().expression("folder:videos_v1").max_results(20).execute()
        videos = res.get("resources", [])
        if not videos:
            bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات1.", reply_markup=owner_keyboard())
            return

        text = "📋 قائمة فيديوهات1:\n"
        for i, vid in enumerate(videos, 1):
            text += f"{i}. {vid['public_id'].split('/')[-1]}\n"
        text += "\nأرسل رقم الفيديو الذي تريد حذفه."

        bot.send_message(user_id, text)
        waiting_for_delete[user_id] = {"category": "v1", "videos": videos}

    except Exception as e:
        bot.send_message(user_id, f"حدث خطأ أثناء جلب الفيديوهات: {str(e)}", reply_markup=owner_keyboard())

@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات2" and m.from_user.id == OWNER_ID)
def delete_videos_v2(message):
    user_id = message.from_user.id
    try:
        res = cloudinary.Search().expression("folder:videos_v2").max_results(20).execute()
        videos = res.get("resources", [])
        if not videos:
            bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات2.", reply_markup=owner_keyboard())
            return

        text = "📋 قائمة فيديوهات2:\n"
        for i, vid in enumerate(videos, 1):
            text += f"{i}. {vid['public_id'].split('/')[-1]}\n"
        text += "\nأرسل رقم الفيديو الذي تريد حذفه."

        bot.send_message(user_id, text)
        waiting_for_delete[user_id] = {"category": "v2", "videos": videos}

    except Exception as e:
        bot.send_message(user_id, f"حدث خطأ أثناء جلب الفيديوهات: {str(e)}", reply_markup=owner_keyboard())

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_delete.get(m.from_user.id))
def handle_delete_choice(message):
    user_id = message.from_user.id
    data = waiting_for_delete.get(user_id)
    if not data:
        return

    try:
        choice = int(message.text)
        videos = data["videos"]
        category = data["category"]

        if 1 <= choice <= len(videos):
            video_to_delete = videos[choice - 1]
            public_id = video_to_delete["public_id"]

            cloudinary.uploader.destroy(public_id, resource_type="video")

            bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} بنجاح.", reply_markup=owner_keyboard())
            waiting_for_delete.pop(user_id)

        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.")

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.")

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

    bot.send_message(user_id, "! اختر الفيدوهات من الأزرار🪩:", reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    user_id = message.from_user.id

    if user_id in load_approved_users(approved_v1_col):
        send_videos(user_id, "v1")
    else:
        # ✅ عرض رسالة ترحيبية فقط إذا لم يكن مشتركًا بعد
        bot.send_message(user_id, "👋 أهلاً بك في قسم فيديوهات 1!\nللوصول إلى المحتوى، الرجاء الاشتراك في القنوات التالية:")

        # نكمل الاشتراك من حيث توقف المستخدم
        data = pending_check.get(user_id)
        if data and data["category"] == "v1":
            send_required_links(user_id, "v1")
        else:
            pending_check[user_id] = {"category": "v1", "step": 0}
            send_required_links(user_id, "v1")
            
@bot.message_handler(func=lambda m: m.text == "فيديوهات2")
def handle_v2(message):
    user_id = message.from_user.id

    if maintenance_mode and user_id != OWNER_ID:
        bot.send_message(user_id, "⏳ انتظر ثوانٍ نتحقق أنك اشتركت في جميع القنوات📂،")
        return

    if user_id in load_approved_users(approved_v2_col):
        send_videos(user_id, "v2")
    else:
        bot.send_message(user_id, "👋 أهلاً بك في قسم فيديوهات 2!\nللوصول إلى الفيديوهات، الرجاء الاشتراك في القنوات التالية:")

        data = pending_check.get(user_id)
        if data and data["category"] == "v2":
            send_required_links(user_id, "v2")
        else:
            pending_check[user_id] = {"category": "v2", "step": 0}
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
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

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
        bot.send_message(user_id, """⏳ انتظر ثوانٍ نتحقق أنك اشتركت في جميع القنوات📂،""")
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

    else:
        bot.reply_to(message, "❌ لا يمكنك إرسال فيديوهات.")

def send_videos(chat_id, category):
    # استعلام عن فيديوهات من Cloudinary بالمسار المناسب
    try:
        res = cloudinary.Search().expression(f"folder:videos_{category}").max_results(20).execute()
        resources = res.get("resources", [])
        if not resources:
            bot.send_message(chat_id, "لا يوجد فيديوهات حالياً.", reply_markup=main_keyboard())
            return

        for video in resources:
            url = video["secure_url"]
            bot.send_video(chat_id, url)
    except Exception as e:
        bot.send_message(chat_id, f"حدث خطأ في جلب الفيديوهات: {str(e)}", reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text == "رسالة جماعية مع صورة" and m.from_user.id == OWNER_ID)
def ask_broadcast_photo(message):
    bot.send_message(message.chat.id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.")
    waiting_for_broadcast["photo"] = True

@bot.message_handler(content_types=['photo'])
def receive_broadcast_photo(message):
    if waiting_for_broadcast.get("photo") and message.from_user.id == OWNER_ID:
        waiting_for_broadcast["photo_file_id"] = message.photo[-1].file_id
        waiting_for_broadcast["photo"] = False
        waiting_for_broadcast["awaiting_text"] = True
        bot.send_message(message.chat.id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة.")

@bot.message_handler(func=lambda m: waiting_for_broadcast.get("awaiting_text") and m.from_user.id == OWNER_ID)
def receive_broadcast_text(message):
    if waiting_for_broadcast.get("awaiting_text"):
        photo_id = waiting_for_broadcast.get("photo_file_id")
        text = message.text
        users = get_all_approved_users()
        sent_count = 0
        for user_id in users:
            try:
                bot.send_photo(user_id, photo_id, caption=text)
                sent_count += 1
            except Exception:
                pass
        bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.")
        waiting_for_broadcast.clear()

# --- Flask Web Server لتشغيل البوت على Render + UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()
bot.infinity_polling()
