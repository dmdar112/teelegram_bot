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

maintenance_mode = False
# هنا بعد تعريف المتغيرات والثوابت اكتب:
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")  # آيدي القناة الخاصة بفيديوهات1
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")  # آيدي القناة الخاصة بفيديوهات2

waiting_for_delete = {}
true_sub_pending = {}  # {user_id: step}

@bot.message_handler(commands=['off'])
def enable_maintenance(message):
    if message.from_user.id == OWNER_ID:
        global maintenance_mode
        maintenance_mode = True
        bot.reply_to(message, "✅ تم تفعيل وضع الصيانة. البوت الآن في وضع الصيانة.")
        # إرسال رسالة لكل المستخدمين أن البوت في الصيانة (اختياري)
        # users = get_all_approved_users()
        # for user_id in users:
        #     try:
        #         bot.send_message(user_id, "⚙️ البوت حالياً في وضع صيانة. الرجاء المحاولة لاحقاً.")
        #     except:
        #         pass

@bot.message_handler(commands=['on'])
def disable_maintenance(message):
    if message.from_user.id == OWNER_ID:
        global maintenance_mode
        maintenance_mode = False
        bot.reply_to(message, "✅ تم إيقاف وضع الصيانة. البوت عاد للعمل.")
# ثم يبدأ الكود الأساسي (تهيئة البوت، الدوال، المعالجات ... الخ)


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

# 1. تعديل دالة owner_keyboard():
def owner_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # نضع أزرار الوصول لأدوات كل قسم
    markup.row("أدوات فيديوهات1", "أدوات فيديوهات2")
    markup.row("رسالة جماعية مع صورة")
    # يمكنك إضافة أي أزرار أخرى عامة هنا
    return markup

def get_all_approved_users():
    return set(
        user["user_id"] for user in approved_v1_col.find()
    ).union(
        user["user_id"] for user in approved_v2_col.find()
    )

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
            time.sleep(1)  # لمنع الحظر أو التقييد
        except Exception as e:
            print(f"❌ خطأ أثناء إرسال الفيديو: {e}")

# 2. إضافة معالجات جديدة لأزرار "أدوات فيديوهات1" و "أدوات فيديوهات2"
@bot.message_handler(func=lambda m: m.text == "أدوات فيديوهات1" and m.from_user.id == OWNER_ID)
def show_v1_tools(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("حذف فيديوهات1", callback_data="owner_delete_v1"))
    markup.add(types.InlineKeyboardButton("رفع فيديوهات1", callback_data="owner_upload_v1"))
    markup.add(types.InlineKeyboardButton("تنظيف فيديوهات1", callback_data="owner_clean_v1"))
    bot.send_message(message.chat.id, "اختر أداة لإدارة فيديوهات1:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "أدوات فيديوهات2" and m.from_user.id == OWNER_ID)
def show_v2_tools(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("حذف فيديوهات2", callback_data="owner_delete_v2"))
    markup.add(types.InlineKeyboardButton("رفع فيديوهات2", callback_data="owner_upload_v2"))
    markup.add(types.InlineKeyboardButton("تنظيف فيديوهات2", callback_data="owner_clean_v2"))
    bot.send_message(message.chat.id, "اختر أداة لإدارة فيديوهات2:", reply_markup=markup)


# 3. تعديل معالجات Callback Query للأدوات
@bot.callback_query_handler(func=lambda call: call.data.startswith("owner_"))
def handle_owner_tools_callback(call):
    user_id = call.from_user.id
    action = call.data.split("_")[1] # "delete", "upload", "clean"
    category = call.data.split("_")[2] # "v1" or "v2"

    bot.answer_callback_query(call.id) # لإخفاء حالة التحميل من الزر

    # قم بإنشاء رسالة وهمية لتمريرها إلى دوال الحذف والتنظيف التي تتوقع كائن Message
    # لأن دوال الـ delete_videos و clean_videos تتوقع كائن Message
    # يمكننا إنشاء كائن Message بسيط يحتوي على user_id
    temp_message = types.Message(message_id=call.message.message_id, from_user=call.from_user,
                                 date=call.message.date, chat=call.message.chat,
                                 json_string=call.message.json_string)
    temp_message.text = "TEMP_COMMAND_FOR_DELETION_OR_CLEANING" # نص وهمي لتجنب أخطاء

    if action == "delete":
        if category == "v1":
            delete_videos_v1(temp_message)
        elif category == "v2":
            delete_videos_v2(temp_message)
    elif action == "upload":
        owner_upload_mode[user_id] = category
        bot.send_message(user_id, f"✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات{category[-1]}.", reply_markup=owner_keyboard())
    elif action == "clean":
        if category == "v1":
            clean_videos_v1(temp_message)
        elif category == "v2":
            clean_videos_v2(temp_message)

    # اختياري: يمكنك تعديل الرسالة الأصلية التي تحتوي على الأزرار الفرعية
    # bot.edit_message_text("تم اختيار الأداة.", call.message.chat.id, call.message.message_id, reply_markup=None)


# معالجين delete_videos_v1 و delete_videos_v2 تم تعديل تعريفهما ليتم استدعاؤهما من الـ callback
# نترك الـ @bot.message_handler كما هو، ولكن الأولوية ستكون للـ callback
@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات1" and m.from_user.id == OWNER_ID)
def delete_videos_v1(message):
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    videos = list(db_videos_col.find().limit(20))

    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات1.", reply_markup=owner_keyboard())
        return

    text = "📋 قائمة فيديوهات1:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."

    bot.send_message(user_id, text, reply_markup=back_markup)
    waiting_for_delete[user_id] = {"category": "v1", "videos": videos}

@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات2" and m.from_user.id == OWNER_ID)
def delete_videos_v2(message):
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    videos = list(db_videos_col.find().limit(20))

    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات2.", reply_markup=owner_keyboard())
        return

    text = "📋 قائمة فيديوهات2:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."

    bot.send_message(user_id, text, reply_markup=back_markup)
    waiting_for_delete[user_id] = {"category": "v2", "videos": videos}


# معالج جديد لزر "رجوع"
@bot.message_handler(func=lambda m: m.text == "رجوع" and m.from_user.id in waiting_for_delete)
def handle_back_command(message):
    user_id = message.from_user.id

    # إزالة المستخدم من قائمة الانتظار
    if user_id in waiting_for_delete:
        waiting_for_delete.pop(user_id)

    # إعادة لوحة مفاتيح المالك
    bot.send_message(user_id, "تم الرجوع إلى القائمة الرئيسية", reply_markup=owner_keyboard())

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

true_sub_pending = {}  # {user_id: step}

@bot.message_handler(commands=['clean_videos_v1']) # هذا المعالج لا يتم استخدامه مباشرة من الأزرار بعد الآن
def clean_videos_v1(message):
    if message.from_user.id != OWNER_ID:
        return

    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]  # اسم collection لفيديوهات1 في MongoDB
    channel_id = CHANNEL_ID_V1  # استخدم المتغير الذي عرّفته مسبقًا (آيدي القناة من متغير البيئة)

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

    bot.send_message(user_id, f"تم تنظيف فيديوهات1. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_keyboard())

@bot.message_handler(commands=['clean_videos_v2']) # هذا المعالج لا يتم استخدامه مباشرة من الأزرار بعد الآن
def clean_videos_v2(message):
    if message.from_user.id != OWNER_ID:
        return

    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    channel_id = CHANNEL_ID_V2

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
        except Exception as e:
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, f"تم تنظيف فيديوهات2. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_keyboard())

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    name = message.from_user.first_name

    user = users_col.find_one({"user_id": user_id})

    # ✅ تحقق فعلي من بقاء الاشتراك إن كان مسجل سابقًا في قاعدة البيانات
    if user and user.get("joined") == True:
        for index, link in enumerate(true_subscribe_links):
            try:
                channel_username = link.split("t.me/")[-1].replace("+", "")
                member = bot.get_chat_member(chat_id=f"@{channel_username}", user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    true_sub_pending[user_id] = index
                    break
            except:
                true_sub_pending[user_id] = index
                break
        else:
            return start(message)

    # ⬇️ إذا لم يكن مشتركًا بكل القنوات، نظهر له القناة الحالية بالتسلسل
    step = true_sub_pending.get(user_id, 0)

    if step >= len(true_subscribe_links):
        if user_id in true_sub_pending:
            del true_sub_pending[user_id]

        if not user:
            users_col.insert_one({"user_id": user_id, "joined": True})
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": True}})

        return start(message)

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

                return start(message)

        # ✅ إرسال رسالة الاشتراك في القناة التالية
        next_channel = true_subscribe_links[step]
        text = (
            "🔔 لطفاً اشترك بالقناة واستخدم البوت.\n"
            "- ثم اضغط /start ~\n"
            "- قناة البوت 👾👇🏻\n"
            f"📮: {next_channel}"
        )
        bot.send_message(
            user_id,
            text,
            disable_web_page_preview=True,
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    except Exception as e:
        return bot.send_message(
            user_id,
            f"⚠️ تعذر التحقق من الاشتراك. تأكد أن البوت مشرف في القناة:\n\n{current_channel}",
            reply_markup=types.ReplyKeyboardRemove()
        )

    # ✅ تنظيف قائمة الانتظار إذا تم التحقق
    if user_id in true_sub_pending:
        del true_sub_pending[user_id]

    start(message)
# الدالة الأصلية بعد الاشتراك
def start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "لا يوجد اسم"

    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
        return

    bot.send_message(user_id, f"""🔞 مرحباً بك ( {first_name} ) 🏳‍🌈
📂اختر قسم الفيديوهات من الأزرار بالأسفل!

⚠️ المحتوى +18 - للكبار فقط!""", reply_markup=main_keyboard())

    if not has_notified(user_id):
        total_users = len(get_all_approved_users())
        bot.send_message(OWNER_ID, f"""👾 تم دخول شخص جديد إلى البوت الخاص بك

• الاسم : {first_name}
• الايدي : {user_id}
• عدد الأعضاء الكلي: {total_users}
""")
        add_notified_user(user_id)

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
        bot.send_message(user_id, "⚙️ زر فيديوهات 2️⃣ حالياً في وضع صيانة. الرجاء المحاولة لاحقاً.")
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

    link = links[step]  # 🔴 هذا السطر مهم لتعريف المتغير "link"

    text = f"""- لطفاً اشترك بالقناة واستخدم البوت .
- ثم اضغط / تحقق في الاسفل  ~
- قناة البوت 👾.👇🏻
📬:  {link}
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👾 تحقق الانْ بعد الاشتراك 👾", callback_data=f"verify_{category}_{step}"))
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

    pending_check[chat_id] = {"category": category, "step": step}

@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    bot.answer_callback_query(call.id)  # لحل مشكلة الزر المعلق

    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    step = int(step_str) + 1
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    if step < len(links):
        pending_check[user_id] = {"category": category, "step": step}
        send_required_links(user_id, category)
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🚸إذا كنت غير مشترك، اشترك الآن🚸", callback_data=f"resend_{category}")
        )
        bot.send_message(
            user_id,
            "⏳ يرجى الانتظار قليلاً حتى نتحقق من اشتراكك في جميع القنوات.\n"
            "إذا كنت مشتركًا سيتم قبولك تلقائيًا، وإذا كنت غير مشترك لا يمكنك استخدام البوت ⚠️",
            reply_markup=markup
        )
        notify_owner_for_approval(user_id, call.from_user.first_name, category)
        pending_check.pop(user_id, None)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resend_"))
def resend_links(call):
    bot.answer_callback_query(call.id)  # لحل مشكلة الزر المعلق

    user_id = call.from_user.id
    category = call.data.split("_")[1]
    pending_check[user_id] = {"category": category, "step": 0}
    send_required_links(user_id, category)

def notify_owner_for_approval(user_id, name, category):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("✅ قبول المستخدم", callback_data=f"approve_{category}_{user_id}"),
        types.InlineKeyboardButton("❌ رفض المستخدم", callback_data=f"reject_{category}_{user_id}")
    )
    message_text = (
        f"📥 طلب انضمام جديد\n"
        f"👤 الاسم: {name}\n"
        f"🆔 الآيدي: {user_id}\n"
        f"📁 الفئة: فيديوهات {category[-1]}"
    )
    bot.send_message(OWNER_ID, message_text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_owner_response(call):
    parts = call.data.split("_")
    action, category, user_id = parts[0], parts[1], int(parts[2])

    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🚫 غير مصرح لك بالقيام بهذا الإجراء.")
        return

    if action == "approve":
        if category == "v1":
            add_approved_user(approved_v1_col, user_id)
        else:
            add_approved_user(approved_v2_col, user_id)
        bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة! يمكنك الآن استخدام البوت بكل المزايا.")
        bot.edit_message_text("✅ تم قبول المستخدم.", call.message.chat.id, call.message.message_id)
    else:
        bot.send_message(user_id, "❌ لم يتم قبولك. الرجاء الاشتراك في جميع قنوات البوت ثم أرسل /start مرة أخرى.")
        bot.edit_message_text("❌ تم رفض المستخدم.", call.message.chat.id, call.message.message_id)


# معالج `handle_video_upload` لا يزال كما هو، حيث يعتمد على `owner_upload_mode`
@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    user_id = message.from_user.id
    mode = owner_upload_mode.get(user_id)

    if user_id != OWNER_ID or not mode:
        return  # تجاهل أي فيديو من غير المالك أو إن لم يحدد القسم

    # رفع الفيديو إلى القناة الخاصة
    try:
        sent = bot.send_video(
            chat_id=os.environ.get(f"CHANNEL_ID_{mode.upper()}"),
            video=message.video.file_id,
            caption=f"📥 فيديو جديد من المالك - قسم {mode.upper()}",
        )
        # تخزين في قاعدة البيانات
        db[f"videos_{mode}"].insert_one({
            "chat_id": sent.chat.id,
            "message_id": sent.message_id
        })

        bot.reply_to(message, f"✅ تم حفظ الفيديو في قسم {mode.upper()}.")
        # بعد الرفع، نعود لوحة المالك الرئيسية
        owner_upload_mode.pop(user_id, None) # نخرج من وضع الرفع بعد الرفع
        bot.send_message(user_id, "تم الانتهاء من الرفع. يمكنك اختيار أمر آخر.", reply_markup=owner_keyboard())

    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو.")


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
