import os
import time
import json # قد لا نحتاجه بعد الآن لـ activated_users لكن يمكن تركه
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient


# --- متغيرات البيئة والإعدادات العامة ---
TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622  # عدّل رقمك هنا

maintenance_mode = False
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")  # آيدي القناة الخاصة بفيديوهات1
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")  # آيدي القناة الخاصة بفيديوهات2

# اسم مستخدم بوت التمويل الرسمي للتفعيل (تأكد من صحته)
FINANCE_BOT_USERNAME = "yynnurybot" # !!! تأكد من هذا الاسم !!!

# --- إعداد MongoDB ---
MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"]
approved_v2_col = db["approved_v2"]
notified_users_col = db["notified_users"]
users_col = db["users"] # أضفنا هذه المجموعة لتخزين المستخدمين الحقيقيين
activated_users_col = db["activated_users"] # المجموعة الجديدة للمستخدمين المفعلين


# --- قوائم الروابط والحالات المؤقتة ---
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

pending_check = {} # للاشتراك الحقيقي
fake_sub_pending = {} # للاشتراك الوهمي
owner_upload_mode = {}
waiting_for_broadcast = {}
waiting_for_delete = {}
true_sub_pending = {} # لحالة انتظار التحقق من الاشتراك الحقيقي (إذا كان الكود الأصلي يستخدمها)


# --- دوال مساعدة عامة ---

# دوال إدارة المستخدمين المفعلين في MongoDB
def is_user_activated(user_id):
    """التحقق مما إذا كان المستخدم مفعلًا في MongoDB."""
    return activated_users_col.find_one({"user_id": user_id}) is not None

def activate_user(user_id):
    """تفعيل المستخدم وحفظه في MongoDB."""
    if not is_user_activated(user_id):
        activated_users_col.insert_one({"user_id": user_id, "activation_time": time.time()})

# دوال أخرى
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
    markup.row("/on", "/off") # أضفنا أزرار للتحكم بوضع الصيانة
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

# 🟢 وظائف الاشتراك الحقيقي (إن وجدت في كودك الأصلي)
def check_true_subscription(user_id, first_name):
    # هذه دالة افتراضية، يجب عليك التأكد من أنها تعكس منطقك الفعلي
    # للتحقق من الاشتراك في القنوات الإجبارية
    
    # مثال افتراضي: التحقق من قناة إجبارية واحدة
    mandatory_channel_id = "-1002142277026" # استبدل بآيدي قناتك الإجبارية الحقيقية
    try:
        member = bot.get_chat_member(mandatory_channel_id, user_id)
        if member.status in ["member", "administrator", "creator"]:
            all_channels_subscribed = True # افترض أن كل القنوات الإجبارية تم الاشتراك فيها
        else:
            all_channels_subscribed = False
    except Exception as e:
        print(f"Error checking true subscription for {user_id}: {e}")
        all_channels_subscribed = False

    if all_channels_subscribed:
        if user_id in true_sub_pending:
            del true_sub_pending[user_id] # إزالة المستخدم بعد اكتمال التحقق

        # تحديث حالة الاشتراك في قاعدة البيانات
        user_data_db = users_col.find_one({"user_id": user_id})
        if not user_data_db:
            users_col.insert_one({"user_id": user_id, "joined": True, "first_name": first_name})
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": True, "first_name": first_name}})

        # بدء عملية الاشتراك الوهمي (فيديوهات1) بعد الانتهاء من الإجباري
        fake_sub_pending[user_id] = {"category": "v1", "step": 0}
        send_required_links_fake(user_id, "v1")
    else:
        # هنا يتم توجيه المستخدم للاشتراك في القنوات الإجبارية
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("اشترك في القناة الإجبارية", url=f"https://t.me/+2L5KrXuCDUA5ZWIy") # ضع رابط قناتك الإجبارية هنا
        )
        markup.add(
            types.InlineKeyboardButton("✅ تحقق بعد الاشتراك", callback_data="check_mandatory_sub")
        )
        bot.send_message(user_id, "⚠️ يرجى الاشتراك في القناة الإجبارية للمتابعة:", reply_markup=markup)
        true_sub_pending[user_id] = True # وضع المستخدم في حالة الانتظار للتحقق

@bot.callback_query_handler(func=lambda call: call.data == "check_mandatory_sub")
def handle_check_mandatory_sub(call):
    bot.answer_callback_query(call.id, "جار التحقق...")
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم"
    check_true_subscription(user_id, first_name)


# 🟢 وظائف الاشتراك الوهمي (Fake Subscription)
def send_required_links_fake(chat_id, category):
    data = fake_sub_pending.get(chat_id, {"category": category, "step": 0})
    step = data["step"]
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2 # استخدم الروابط الخاصة بالفيديوهات هنا

    if step >= len(links):
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة. الرجاء الانتظار.", reply_markup=main_keyboard())
        fake_sub_pending.pop(chat_id, None)
        return

    link = links[step]
    text = f"""- لطفاً اشترك بالقناة واستخدم البوت .
- ثم اضغط / تحقق في الاسفل  ~
- قناة البوت 👾.👇🏻
📬:  {link}
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👾 تحقق الانْ بعد الاشتراك 👾", callback_data=f"verify_fake_{category}_{step}"))
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
    fake_sub_pending[chat_id] = {"category": category, "step": step}


@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_fake_"))
def verify_fake_subscription_callback(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    _, fake_prefix, category, step_str = call.data.split("_")
    step = int(step_str) + 1
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    if step < len(links):
        fake_sub_pending[user_id] = {"category": category, "step": step}
        send_required_links_fake(user_id, category)
    else:
        bot.send_message(
            user_id,
            "⏳ يرجى الانتظار قليلاً حتى نتحقق من اشتراكك في جميع القنوات.\n"
            "إذا كنت مشتركًا سيتم قبولك تلقائيًا، وإذا كنت غير مشترك سيتم رفضك ولا يمكنك الوصول للمقاطع ‼️"
        )
        notify_owner_for_approval(user_id, call.from_user.first_name, category, is_fake=True)
        fake_sub_pending.pop(user_id, None)

# --- معالجات الأوامر والرسائل (مرتبة حسب الأولوية) ---

# 1. معالج وضع الصيانة (الأولوية القصوى)
@bot.message_handler(func=lambda m: maintenance_mode and m.from_user.id != OWNER_ID)
def handle_maintenance_mode(message):
    bot.send_message(message.chat.id, "⚙️ البوت حالياً في وضع صيانة. الرجاء المحاولة لاحقاً.")

# 2. معالجات الأوامر الخاصة بالمالك (مثل /on, /off, /v1, /v2)
@bot.message_handler(commands=['off'])
def enable_maintenance(message):
    if message.from_user.id == OWNER_ID:
        global maintenance_mode
        maintenance_mode = True
        bot.reply_to(message, "✅ تم تفعيل وضع الصيانة. البوت الآن في وضع الصيانة.")

@bot.message_handler(commands=['on'])
def disable_maintenance(message):
    if message.from_user.id == OWNER_ID:
        global maintenance_mode
        maintenance_mode = False
        bot.reply_to(message, "✅ تم إيقاف وضع الصيانة. البوت عاد للعمل.")

@bot.message_handler(commands=['v1', 'v2'])
def set_upload_mode(message):
    if message.from_user.id == OWNER_ID:
        mode = message.text[1:]
        owner_upload_mode[message.from_user.id] = mode
        bot.reply_to(message, f"✅ سيتم حفظ الفيديوهات التالية في قسم {mode.upper()}.")

# 3. معالج رسالة التفعيل (للمستخدمين غير المفعلين) - هذا هو الأهم
@bot.message_handler(func=lambda m: not is_user_activated(m.from_user.id))
def handle_activation_check(message):
    if message.forward_from_chat and message.forward_from_chat.username == FINANCE_BOT_USERNAME:
        expected_phrase = "لقد دخلت بنجاح عبر الرابط الذي قدمه صديقك كدعوة، ونتيجة لذلك، حصل صديقك على 2000 نقطة"
        if expected_phrase in message.text:
            activate_user(message.from_user.id) # استخدم دالة التفعيل الجديدة
            bot.send_message(message.from_user.id, "✅ تم التفعيل بنجاح! يمكنك الآن استخدام البوت. اضغط /start للمتابعة.")
        else:
            bot.send_message(message.from_user.id, "❌ تم إعادة توجيه الرسالة لكن محتواها غير مطابق.\nالرجاء التأكد من الرسالة الصحيحة.")
    else:
        bot.send_message(
            message.from_user.id,
            "🚫 يجب تفعيل البوت أولاً.\nالرجاء إعادة توجيه رسالة التفعيل الأصلية من بوت التمويل الرسمي (مثل: @FinanceBot).\n"
            "لا تقم بنسخ الرسالة يدويًا."
        )

# 4. دالة /start (بعد التفعيل)
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "لا يوجد اسم"

    # إذا لم يكن المستخدم مفعلًا، دالة handle_activation_check هي التي ستتعامل معه
    if not is_user_activated(user_id):
        # هنا لا نفعل شيئًا، لأن handle_activation_check ستلتقط الرسالة
        # ويمكن أن نرسل رسالة توجيهية بسيطة لضمان الوضوح
        bot.send_message(user_id, "🚫 يجب تفعيل البوت أولاً. يرجى إرسال رسالة التفعيل المطلوبة.")
        return # نوقف التنفيذ هنا لمنع الوصول لوظائف البوت

    # للمالك
    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
    else:
        # للمستخدمين المفعلين
        welcome_message = (
            f"🔞 مرحباً بك ( {first_name} ) 🏳‍🌈\n"
            "📂اختر قسم الفيديوهات من الأزرار بالأسفل!\n\n"
            "⚠️ المحتوى +18 - للكبار فقط!"
        )
        bot.send_message(user_id, welcome_message, reply_markup=main_keyboard())

        if not has_notified(user_id):
            total_users = len(get_all_approved_users())
            new_user_msg = f"""👾 تم دخول شخص جديد إلى البوت الخاص بك
-----------------------
• الاسم : {first_name}
• الايدي : {user_id}
-----------------------
• عدد الأعضاء الكلي: {total_users}
"""
            bot.send_message(OWNER_ID, new_user_msg)
            add_notified_user(user_id)

# 5. باقي معالجات الرسائل (للمستخدمين المفعلين فقط)
@bot.message_handler(func=lambda m: is_user_activated(m.from_user.id) and m.text == "فيديوهات1")
def handle_v1(message):
    user_id = message.from_user.id
    if user_id in load_approved_users(approved_v1_col):
        send_videos(user_id, "v1")
    else:
        bot.send_message(user_id, "👋 أهلاً بك في قسم فيديوهات 1!\nللوصول إلى المحتوى، الرجاء الاشتراك في القنوات التالية:")
        data = pending_check.get(user_id)
        if data and data["category"] == "v1":
            send_required_links(user_id, "v1")
        else:
            pending_check[user_id] = {"category": "v1", "step": 0}
            send_required_links(user_id, "v1")

@bot.message_handler(func=lambda m: is_user_activated(m.from_user.id) and m.text == "فيديوهات2")
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
        # هنا يجب استخدام activated_users_col للحصول على جميع المستخدمين المفعلين للبث
        users_to_broadcast = activated_users_col.find({}, {"user_id": 1}) # جلب فقط user_id
        sent_count = 0
        for user_doc in users_to_broadcast:
            user_id = user_doc["user_id"]
            try:
                bot.send_photo(user_id, photo_id, caption=text)
                sent_count += 1
            except Exception:
                pass
        bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.")
        waiting_for_broadcast.clear()

# --- معالج ردود المالك (قبول/رفض) ---
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
        bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة! يمكنك الآن استخدام البوت بكل المزايا.", reply_markup=main_keyboard())
        bot.edit_message_text("✅ تم قبول المستخدم.", call.message.chat.id, call.message.message_id)
    else:
        bot.send_message(user_id, "❌ لم يتم قبولك. الرجاء الاشتراك في جميع قنوات البوت ثم أرسل /start مرة أخرى.")
        bot.edit_message_text("❌ تم رفض المستخدم.", call.message.chat.id, call.message.message_id)


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
