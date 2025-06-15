import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient


# متغيرات البيئة
TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622  # عدّل رقمك هنا

maintenance_mode = False # هذا المتغير يتحكم بوضع صيانة فيديوهات2 فقط

# آيدي القناة الخاصة بفيديوهات1
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")
# آيدي القناة الخاصة بفيديوهات2
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")

waiting_for_delete = {}
true_sub_pending = {}  # {user_id: step}

MONGODB_URI = os.environ.get("MONGODB_URI")

# إعداد MongoDB
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

users_col = db["users"]

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

true_subscribe_links = [
    "https://t.me/BLACK_ROOT1",
    "https://t.me/SNOKER_VIP",
    "https://t.me/R2M199"
]

pending_check = {}
owner_upload_mode = {}
waiting_for_broadcast = {}

def load_approved_users(collection):
    """تحميل المستخدمين الموافق عليهم من قاعدة البيانات."""
    return set(doc["user_id"] for doc in collection.find())

def add_approved_user(collection, user_id):
    """إضافة مستخدم موافق عليه إلى قاعدة البيانات."""
    if not collection.find_one({"user_id": user_id}):
        collection.insert_one({"user_id": user_id})

def remove_approved_user(collection, user_id):
    """إزالة مستخدم موافق عليه من قاعدة البيانات."""
    collection.delete_one({"user_id": user_id})

def has_notified(user_id):
    """التحقق مما إذا كان المستخدم قد تم إبلاغه من قبل."""
    return notified_users_col.find_one({"user_id": user_id}) is not None

def add_notified_user(user_id):
    """إضافة مستخدم تم إبلاغه إلى قاعدة البيانات."""
    if not has_notified(user_id):
        notified_users_col.insert_one({"user_id": user_id})

def main_keyboard():
    """إنشاء لوحة المفاتيح الرئيسية للمستخدم العادي."""
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

def owner_keyboard():
    """إنشاء لوحة مفاتيح المالك مع أزرار التحكم الجديدة."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("فيديوهات1", "فيديوهات2")
    markup.row("حذف فيديوهات1", "حذف فيديوهات2")
    markup.row("رفع فيديوهات1", "رفع فيديوهات2")
    markup.row("تنظيف فيديوهات1", "تنظيف فيديوهات2")
    markup.row("تفعيل صيانة فيديوهات2", "إيقاف صيانة فيديوهات2") # أزرار جديدة لوضع الصيانة
    markup.row("رسالة جماعية مع صورة")
    return markup

def get_all_approved_users():
    """الحصول على جميع المستخدمين الموافق عليهم من كلا القسمين."""
    return set(
        user["user_id"] for user in approved_v1_col.find()
    ).union(
        user["user_id"] for user in approved_v2_col.find()
    )

def send_videos(user_id, category):
    """إرسال الفيديوهات من قسم معين إلى المستخدم."""
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
            time.sleep(1)  # لمنع الحظر أو التقييد
        except Exception as e:
            print(f"❌ خطأ أثناء إرسال الفيديو: {e}")

@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات1" and m.from_user.id == OWNER_ID)
def delete_videos_v1(message):
    """معالج لزر حذف فيديوهات1."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    videos = list(db_videos_col.find().limit(20))

    # لوحة مفاتيح جديدة تحتوي على زر "رجوع"
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات1.", reply_markup=owner_keyboard())
        return

    text = "📋 قائمة فيديوهات1:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."

    # إرسال الرسالة مع لوحة المفاتيح الجديدة
    bot.send_message(user_id, text, reply_markup=back_markup)
    waiting_for_delete[user_id] = {"category": "v1", "videos": videos}

@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات2" and m.from_user.id == OWNER_ID)
def delete_videos_v2(message):
    """معالج لزر حذف فيديوهات2."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    videos = list(db_videos_col.find().limit(20))

    # لوحة مفاتيح جديدة تحتوي على زر "رجوع"
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات2.", reply_markup=owner_keyboard())
        return

    text = "📋 قائمة فيديوهات2:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."

    # إرسال الرسالة مع لوحة المفاتيح الجديدة
    bot.send_message(user_id, text, reply_markup=back_markup)
    waiting_for_delete[user_id] = {"category": "v2", "videos": videos}

@bot.message_handler(func=lambda m: m.text == "رجوع" and m.from_user.id in waiting_for_delete)
def handle_back_command(message):
    """معالج لزر الرجوع أثناء عملية الحذف."""
    user_id = message.from_user.id

    # إزالة المستخدم من قائمة الانتظار
    if user_id in waiting_for_delete:
        waiting_for_delete.pop(user_id)

    # إعادة لوحة مفاتيح المالك
    bot.send_message(user_id, "تم الرجوع إلى القائمة الرئيسية", reply_markup=owner_keyboard())

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_delete.get(m.from_user.id))
def handle_delete_choice(message):
    """معالج لاختيار الفيديو المراد حذفه من قبل المالك."""
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
            chat_id = video_to_delete["chat_id"]
            message_id = video_to_delete["message_id"]

            # حذف الرسالة من القناة
            bot.delete_message(chat_id, message_id)

            # حذف السجل من قاعدة البيانات
            db_videos_col = db[f"videos_{category}"]
            db_videos_col.delete_one({"message_id": message_id})

            bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} بنجاح.", reply_markup=owner_keyboard())
            waiting_for_delete.pop(user_id)

        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.")

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.")

# معالج زر "تنظيف فيديوهات1"
@bot.message_handler(func=lambda m: m.text == "تنظيف فيديوهات1" and m.from_user.id == OWNER_ID)
def clean_videos_v1_button(message):
    """معالج لزر تنظيف فيديوهات1."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    channel_id = CHANNEL_ID_V1

    bot.send_message(user_id, "جاري تنظيف فيديوهات1... قد يستغرق هذا بعض الوقت.")

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            # نجرب نرسل رسالة توجيهية لنفسنا (المالك) من القناة، للتأكد من وجود الرسالة
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
        except Exception as e:
            # لو فشل، احذف الفيديو من قاعدة البيانات لأنه غير موجود بالقناة
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات1. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_keyboard())

# معالج زر "تنظيف فيديوهات2"
@bot.message_handler(func=lambda m: m.text == "تنظيف فيديوهات2" and m.from_user.id == OWNER_ID)
def clean_videos_v2_button(message):
    """معالج لزر تنظيف فيديوهات2."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    channel_id = CHANNEL_ID_V2

    bot.send_message(user_id, "جاري تنظيف فيديوهات2... قد يستغرق هذا بعض الوقت.")

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
        except Exception as e:
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات2. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_keyboard())

@bot.message_handler(commands=['start'])
def handle_start(message):
    """معالج لأمر /start للتحقق من الاشتراك."""
    user_id = message.from_user.id
    name = message.from_user.first_name

    user = users_col.find_one({"user_id": user_id})

    # ✅ تحقق فعلي من بقاء الاشتراك إن كان مسجل سابقًا في قاعدة البيانات
    if user and user.get("joined") == True:
        for index, link in enumerate(true_subscribe_links):
            try:
                channel_username = link.split("t.me/")[-1].replace("+", "")
                # حاول الحصول على معلومات القناة باستخدام get_chat لتحديد ما إذا كانت عامة أم لا
                chat_info = bot.get_chat(chat_id=f"@{channel_username}")
                if chat_info.type == 'channel': # تأكد أنها قناة عامة
                    member = bot.get_chat_member(chat_id=f"@{channel_username}", user_id=user_id)
                    if member.status not in ['member', 'administrator', 'creator']:
                        true_sub_pending[user_id] = index
                        break
                elif chat_info.type == 'private': # إذا كانت قناة خاصة، حاول الانضمام أولاً
                    # For private channels, direct check with get_chat_member might not work
                    # without the user being explicitly added or clicking an invite link.
                    # This part needs careful handling or relies on the user clicking the link.
                    # For simplicity, we'll assume the link itself will guide them.
                    true_sub_pending[user_id] = index
                    break
            except Exception as e:
                # إذا حدث خطأ (مثل القناة غير موجودة أو البوت ليس مشرفًا)، اعتبر أن المستخدم غير مشترك
                print(f"Error checking channel {link}: {e}")
                true_sub_pending[user_id] = index
                break
        else:
            return start_actual_logic(message) # إذا كان مشتركًا في الكل، انتقل إلى منطق البداية

    # ⬇️ إذا لم يكن مشتركًا بكل القنوات، نظهر له القناة الحالية بالتسلسل
    step = true_sub_pending.get(user_id, 0)

    if step >= len(true_subscribe_links):
        if user_id in true_sub_pending:
            del true_sub_pending[user_id]

        if not user:
            users_col.insert_one({"user_id": user_id, "joined": True})
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": True}})

        return start_actual_logic(message)

    try:
        current_channel = true_subscribe_links[step]
        channel_username = current_channel.split("t.me/")[-1].replace("+", "")
        member = bot.get_chat_member(chat_id=f"@{channel_username}", user_id=user_id)

        if member.status in ['member', 'administrator', 'creator']:
            step += 1
            true_sub_pending[user_id] = step

            if step >= len(true_subscribe_links):
                if user_id in true_sub_pending:
                    del true_sub_pending[user_id]

                if not user:
                    users_col.insert_one({"user_id": user_id, "joined": True})
                else:
                    users_col.update_one({"user_id": user_id}, {"$set": {"joined": True}})

                return start_actual_logic(message)

        # ✅ إرسال رسالة الاشتراك في القناة التالية
        next_channel = true_subscribe_links[step]
        
        # *** التعديل هنا: إرسال رسالتين منفصلتين ***
        # الرسالة الأولى: رابط القناة
        channel_text = (
            "🔔 لطفاً اشترك بالقناة واستخدم البوت.\n"
            "- قناة البوت 👾👇🏻\n"
            f"📮: {next_channel}"
        )
        bot.send_message(
            user_id,
            channel_text,
            disable_web_page_preview=True,
            reply_markup=types.ReplyKeyboardRemove() # تأكد من إزالة أي لوحة مفاتيح هنا
        )
        
        time.sleep(0.5) # فاصل زمني قصير لضمان وصول الرسائل بالترتيب
        
        # الرسالة الثانية: أمر /start وحده لجعله قابلاً للنقر
        bot.send_message(
            user_id,
            "/start",
            reply_markup=types.ReplyKeyboardRemove() # تأكد من عدم وجود أزرار هنا أيضًا
        )
        return # يجب أن يكون هناك return هنا لمنع استكمال الكود قبل أن يتم الضغط على /start

    except Exception as e:
        print(f"Error in handle_start subscription check: {e}")
        bot.send_message(
            user_id,
