import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient


# --- متغيرات البيئة والإعدادات العامة ---
TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622  # عدّل رقمك هنا


CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")  # آيدي القناة الخاصة بفيديوهات1
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")  # آيدي القناة الخاصة بفيديوهات2

# --- إعدادات التفعيل لفيديوهات1 ---
# اسم مستخدم بوت التمويل الخاص بتفعيل فيديوهات1 (إذا كان لديك واحد محدد)
FINANCE_BOT_USERNAME_V1 = "yynnurybot" 
# العبارة المتوقعة في رسالة التفعيل الخاصة بفيديوهات1
ACTIVATION_PHRASE_V1 = "• لقد دخلت بنجاح عبر الرابط الذي قدمه صديقك كدعوة، ونتيجة لذلك، حصل صديقك على 2000 نقطة/نقاط كمكافأة ✨."
# رابط بوت التمويل الخاص بتفعيل فيديوهات1
FINANCE_BOT_LINK_V1 = "https://t.me/yynnurybot?start=0006k43lft" # **غير هذا الرابط حسب الحاجة**

# --- إعدادات التفعيل لفيديوهات2 ---
# اسم مستخدم بوت التمويل الخاص بتفعيل فيديوهات2 (إذا كان لديك واحد محدد)
FINANCE_BOT_USERNAME_V2 = "yynnurybot" # **غير هذا الاسم إذا كان مختلفًا**
# العبارة المتوقعة في رسالة التفعيل الخاصة بفيديوهات2
# **مهم جداً: يجب تغيير هذه العبارة لتكون فريدة ومختلفة عن ACTIVATION_PHRASE_V1**
ACTIVATION_PHRASE_V2 = "✅ تم تفعيل اشتراكك الخاص بمحتوى VIP بنجاح! استمتع بالمشاهدة."
# رابط بوت التمويل الخاص بتفعيل فيديوهات2
FINANCE_BOT_LINK_V2 = "https://t.me/yynnurybot?start=0006k43lft" # **غير هذا الرابط ليناسب بوت التمويل الثاني أو رابط تفعيل خاص**


# --- إعداد MongoDB ---
MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"] # للمستخدمين الذين يمكنهم الوصول لفيديوهات1
approved_v2_col = db["approved_v2"] # للمستخدمين الذين يمكنهم الوصول لفيديوهات2
notified_users_col = db["notified_users"]


# --- الحالات المؤقتة ---
owner_upload_mode = {}
waiting_for_broadcast = {}
waiting_for_delete = {}


# --- دوال مساعدة عامة ---

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

def get_total_approved_users():
    # مجموع المستخدمين الذين لديهم وصول لأي من القسمين
    return len(load_approved_users(approved_v1_col).union(load_approved_users(approved_v2_col)))

def send_videos(user_id, category):
    collection_name = f"videos_{category}"
    videos_collection = db[collection_name]
    videos = list(videos_collection.find())

    if not videos:
        bot.send_message(user_id, "❌ لا توجد فيديوهات حالياً في هذا القسم.")
        return

    for video in videos:
        try:
            bot.copy_message(
                chat_id=user_id,
                from_chat_id=video["chat_id"],
                message_id=video["message_id"],
                caption="",
                caption_entities=None
            )
            time.sleep(1)
        except Exception as e:
            print(f"❌ خطأ أثناء إرسال الفيديو: {e}")


# --- معالجات الأوامر والرسائل ---

# معالجات الأوامر الخاصة بالمالك (مثل /v1, /v2)
@bot.message_handler(commands=['v1', 'v2'])
def set_upload_mode(message):
    if message.from_user.id == OWNER_ID:
        mode = message.text[1:]
        owner_upload_mode[message.from_user.id] = mode
        bot.reply_to(message, f"✅ سيتم حفظ الفيديوهات التالية في قسم {mode.upper()}.")

# معالج رسائل التفعيل (V1 و V2)
@bot.message_handler(func=lambda m: (m.text and ACTIVATION_PHRASE_V1 in m.text) or (m.text and ACTIVATION_PHRASE_V2 in m.text))
def handle_activation_messages(message):
    user_id = message.from_user.id
    message_text = message.text if message.text else ""

    # تحقق من تفعيل فيديوهات1
    if ACTIVATION_PHRASE_V1 in message_text:
        # إذا لم يكن المستخدم لديه وصول لفيديوهات1 بالفعل
        if user_id not in load_approved_users(approved_v1_col):
            add_approved_user(approved_v1_col, user_id) # منح الوصول لفيديوهات1
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ User {user_id} granted V1 access.")
            bot.send_message(user_id, "✅ تم تفعيل وصولك إلى **فيديوهات1** بنجاح! يمكنك الآن الضغط على زر **فيديوهات1**.", reply_markup=main_keyboard())
        else:
            bot.send_message(user_id, "👍🏼 لديك بالفعل وصول إلى فيديوهات1.", reply_markup=main_keyboard())
        return

    # تحقق من تفعيل فيديوهات2
    if ACTIVATION_PHRASE_V2 in message_text:
        # إذا لم يكن المستخدم لديه وصول لفيديوهات2 بالفعل
        if user_id not in load_approved_users(approved_v2_col):
            add_approved_user(approved_v2_col, user_id) # منح الوصول لفيديوهات2
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ User {user_id} granted V2 access.")
            bot.send_message(user_id, "✅ تم تفعيل وصولك إلى **فيديوهات2** بنجاح! يمكنك الآن الضغط على زر **فيديوهات2**.", reply_markup=main_keyboard())
        else:
            bot.send_message(user_id, "👍🏼 لديك بالفعل وصول إلى فيديوهات2.", reply_markup=main_keyboard())
        return

# دالة /start (واجهة المستخدم الأولية)
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "لا يوجد اسم"

    # التحقق مما إذا كان المستخدم لديه وصول لأي من القسمين لعرض لوحة المفاتيح الرئيسية
    has_any_access = user_id in load_approved_users(approved_v1_col) or user_id in load_approved_users(approved_v2_col)

    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
    elif has_any_access:
        welcome_message = (
            f"🔞 مرحباً بك ( {first_name} ) 🏳‍🌈\n"
            "📂اختر قسم الفيديوهات من الأزرار بالأسفل!\n\n"
            "⚠️ المحتوى +18 - للكبار فقط!"
        )
        bot.send_message(user_id, welcome_message, reply_markup=main_keyboard())

        if not has_notified(user_id):
            total_users = get_total_approved_users()
            new_user_msg = f"""👾 تم دخول شخص جديد إلى البوت الخاص بك
-----------------------
• الاسم : {first_name}
• الايدي : {user_id}
-----------------------
• عدد الأعضاء الكلي: {total_users}
"""
            bot.send_message(OWNER_ID, new_user_msg)
            add_notified_user(user_id)
    else:
        # إذا لم يكن لديه أي وصول، نوجهه للتفعيل الأساسي (لفيديوهات1)
        bot.send_message(
            user_id,
            "🚫 مرحباً بك! للوصول إلى محتوى البوت، يرجى تفعيل **فيديوهات1** أولاً.\n"
            f"للتفعيل، يرجى الدخول إلى بوت التمويل الخاص بنا عبر هذا الرابط:\n{FINANCE_BOT_LINK_V1}\n\n"
            "ثم أكمل عملية الدخول وقم بإعادة توجيه رسالة التفعيل التي ستصلك إليّ.\n"
            f"✅ يجب أن تحتوي رسالة التفعيل على العبارة: '{ACTIVATION_PHRASE_V1}'.",
            reply_markup=types.ReplyKeyboardRemove(),
            disable_web_page_preview=True
        )
        # إذا أرسل المستخدم رسالة ليست تفعيل وهو لا يملك أي صلاحيات
        @bot.message_handler(func=lambda m: not (m.text and ACTIVATION_PHRASE_V1 in m.text) and not (m.text and ACTIVATION_PHRASE_V2 in m.text) and not (m.from_user.id == OWNER_ID) and not has_any_access)
        def handle_unactivated_user_messages(message):
            bot.send_message(
                message.chat.id,
                "🚫 يرجى تفعيل البوت أولاً للوصول إلى المحتوى.\n"
                f"للتفعيل، يرجى الدخول إلى بوت التمويل الخاص بنا عبر هذا الرابط:\n{FINANCE_BOT_LINK_V1}\n\n"
                "ثم أكمل عملية الدخول وقم بإعادة توجيه رسالة التفعيل التي ستصلك إليّ.\n"
                f"✅ يجب أن تحتوي رسالة التفعيل على العبارة: '{ACTIVATION_PHRASE_V1}'.",
                reply_markup=types.ReplyKeyboardRemove(),
                disable_web_page_preview=True
            )


# معالجات أزرار الفيديوهات
@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    user_id = message.from_user.id
    if user_id in load_approved_users(approved_v1_col):
        send_videos(user_id, "v1")
    else:
        bot.send_message(
            user_id,
            "🚫 للوصول إلى **فيديوهات1**، يرجى تفعيلها أولاً.\n"
            f"يرجى الدخول إلى بوت التمويل عبر هذا الرابط وإعادة توجيه رسالة التفعيل إليّ:\n{FINANCE_BOT_LINK_V1}\n\n"
            f"✅ يجب أن تحتوي رسالة التفعيل على العبارة: '{ACTIVATION_PHRASE_V1}'.",
            disable_web_page_preview=True
        )

@bot.message_handler(func=lambda m: m.text == "فيديوهات2")
def handle_v2(message):
    user_id = message.from_user.id
    
    if user_id in load_approved_users(approved_v2_col):
        send_videos(user_id, "v2")
    else:
        bot.send_message(
            user_id,
            "🚫 للوصول إلى **فيديوهات2**، يتطلب هذا القسم تفعيلاً منفصلاً.\n"
            f"يرجى الدخول إلى بوت التمويل الخاص بفيديوهات2 عبر هذا الرابط وإعادة توجيه رسالة التفعيل إليّ:\n{FINANCE_BOT_LINK_V2}\n\n"
            f"✅ يجب أن تحتوي رسالة التفعيل على العبارة: '{ACTIVATION_PHRASE_V2}'.",
            disable_web_page_preview=True
        )

# معالجات حذف الفيديوهات (خاصة بالمالك)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.text == "حذف فيديوهات1")
def delete_videos_v1(message):
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    videos = list(db_videos_col.find().limit(20))
    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات1.", reply_markup=owner_keyboard())
        return
    text = "📋 قائمة فيديوهات1:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."
    bot.send_message(user_id, text)
    waiting_for_delete[user_id] = {"category": "v1", "videos": videos}

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.text == "حذف فيديوهات2")
def delete_videos_v2(message):
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    videos = list(db_videos_col.find().limit(20))
    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات2.", reply_markup=owner_keyboard())
        return
    text = "📋 قائمة فيديوهات2:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."
    bot.send_message(user_id, text)
    waiting_for_delete[user_id] = {"category": "v2", "videos": videos}

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_delete.get(m.from_user.id))
def handle_delete_choice(message):
    user_id = message.from_user.id
    data = waiting_for_delete.get(user_id)
    if not data: return
    try:
        choice = int(message.text)
        videos = data["videos"]
        category = data["category"]
        if 1 <= choice <= len(videos):
            video_to_delete = videos[choice - 1]
            chat_id = video_to_delete["chat_id"]
            message_id = video_to_delete["message_id"]
            bot.delete_message(chat_id, message_id)
            db_videos_col = db[f"videos_{category}"]
            db_videos_col.delete_one({"message_id": message_id})
            bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} بنجاح.", reply_markup=owner_keyboard())
            waiting_for_delete.pop(user_id)
        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.")
    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.")

# معالج رفع الفيديوهات (خاص بالمالك)
@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    user_id = message.from_user.id
    mode = owner_upload_mode.get(user_id)
    if user_id != OWNER_ID or not mode: return
    try:
        sent = bot.send_video(
            chat_id=os.environ.get(f"CHANNEL_ID_{mode.upper()}"),
            video=message.video.file_id,
            caption=f"📥 فيديو جديد من المالك - قسم {mode.upper()}",
        )
        db[f"videos_{mode}"].insert_one({
            "chat_id": sent.chat.id,
            "message_id": sent.message_id
        })
        bot.reply_to(message, f"✅ تم حفظ الفيديو في قسم {mode.upper()}.")
    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو.")

# معالج الرسائل الجماعية (خاص بالمالك)
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
        users_to_broadcast = load_approved_users(approved_v1_col).union(load_approved_users(approved_v2_col))
        sent_count = 0
        for user_id in users_to_broadcast:
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
