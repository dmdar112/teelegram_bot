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
FINANCE_BOT_USERNAME_V1 = "yynnurybot" 
ACTIVATION_PHRASE_V1 = "• لقد دخلت بنجاح عبر الرابط الذي قدمه صديقك كدعوة، ونتيجة لذلك، حصل صديقك على 2000 نقطة/نقاط كمكافأة ✨."
FINANCE_BOT_LINK_V1 = "https://t.me/yynnurybot?start=0006k43lft" 

# --- إعدادات التفعيل لفيديوهات2 ---
FINANCE_BOT_USERNAME_V2 = "another_finance_bot" 
ACTIVATION_PHRASE_V2 = "✅ تم تفعيل اشتراكك الخاص بمحتوى VIP بنجاح! استمتع بالمشاهدة."
FINANCE_BOT_LINK_V2 = "https://t.me/another_finance_bot?start=vip_access" 

# --- قنوات الاشتراك الإجباري (بعد تفعيل فيديوهات1) ---
# تذكر أن Channel ID يبدأ بـ "-100"
MANDATORY_CHANNELS = [
    {"id": -1001234567890, "link": "https://t.me/your_channel_1"}, # غير الآيدي والرابط
    {"id": -1009876543210, "link": "https://t.me/your_channel_2"}, # غير الآيدي والرابط
    # أضف المزيد من القنوات حسب الحاجة
]


# --- إعداد MongoDB ---
MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"] 
approved_v2_col = db["approved_v2"] 
notified_users_col = db["notified_users"]
# إضافة مجموعة جديدة لتتبع المستخدمين الذين أتموا الاشتراك الإجباري
mandatory_subscribed_col = db["mandatory_subscribed"]


# --- الحالات المؤقتة ---
owner_upload_mode = {}
waiting_for_broadcast = {}
waiting_for_delete = {}
# لتتبع المستخدمين الذين أكملوا تفعيل فيديوهات1 وينتظرون الاشتراك الإجباري
pending_mandatory_check = {} 


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

def is_mandatory_subscribed(user_id):
    """التحقق مما إذا كان المستخدم قد أتم الاشتراك الإجباري."""
    return mandatory_subscribed_col.find_one({"user_id": user_id}) is not None

def set_mandatory_subscribed(user_id):
    """تسجيل أن المستخدم قد أتم الاشتراك الإجباري."""
    if not is_mandatory_subscribed(user_id):
        mandatory_subscribed_col.insert_one({"user_id": user_id, "timestamp": time.time()})

def main_keyboard():
    # هذه هي لوحة المفاتيح للمستخدمين العاديين
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

# --- لوحة مفاتيح المالك الشفافة الجديدة ---
def owner_inline_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("الإدارة 📂", callback_data="admin_menu"))
    markup.add(
        types.InlineKeyboardButton("فيديوهات1 ▶️", callback_data="manage_v1"),
        types.InlineKeyboardButton("فيديوهات2 ▶️", callback_data="manage_v2")
    )
    markup.add(types.InlineKeyboardButton("الإذاعة 📢", callback_data="broadcast_menu"))
    markup.add(
        types.InlineKeyboardButton("رسالة جماعية مع صورة 🖼️", callback_data="broadcast_photo")
    )
    return markup

# --- قوائم فرعية لإدارة الفيديوهات ---
def manage_videos_keyboard(category):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"إضافة فيديو لـ {category.upper()} ➕", callback_data=f"upload_video_{category}"),
        types.InlineKeyboardButton(f"حذف فيديو من {category.upper()} 🗑️", callback_data=f"delete_video_{category}")
    )
    markup.add(types.InlineKeyboardButton("العودة للقائمة الرئيسية ↩️", callback_data="main_admin_menu"))
    return markup


def get_total_approved_users():
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

# --- وظائف الاشتراك الإجباري ---
def check_all_mandatory_subscriptions(user_id):
    """يتحقق مما إذا كان المستخدم مشتركًا في جميع القنوات الإجبارية."""
    for channel in MANDATORY_CHANNELS:
        try:
            member = bot.get_chat_member(channel["id"], user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except telebot.apihelper.ApiTelegramException as e:
            if "User not found in chat" in str(e) or "chat not found" in str(e):
                print(f"Warning: Channel ID {channel['id']} or user {user_id} issue: {e}")
                return False # اعتبرها غير مشترك في حال وجود مشكلة
            raise # أعد رفع أي خطأ آخر
    return True

def send_mandatory_subscription_message(user_id):
    """يرسل رسالة الاشتراك الإجباري مع الأزرار اللازمة."""
    markup = types.InlineKeyboardMarkup()
    for channel in MANDATORY_CHANNELS:
        markup.add(types.InlineKeyboardButton(f"قناة: {channel['link'].split('/')[-1]}", url=channel["link"]))
    markup.add(types.InlineKeyboardButton("✅ تحقق بعد الاشتراك ✅", callback_data="check_mandatory_sub"))
    bot.send_message(
        user_id,
        "⚠️ للوصول إلى محتوى البوت، يرجى الاشتراك في القنوات التالية أولاً:\n\n"
        "بعد الاشتراك في جميع القنوات، اضغط على زر 'تحقق بعد الاشتراك'.",
        reply_markup=markup,
        disable_web_page_preview=True
    )
    pending_mandatory_check[user_id] = True # وضع المستخدم في حالة انتظار التحقق

# --- معالجات الأوامر والرسائل ---

# معالج رسائل التفعيل (V1 و V2)
@bot.message_handler(func=lambda m: (m.text and ACTIVATION_PHRASE_V1 in m.text) or (m.text and ACTIVATION_PHRASE_V2 in m.text))
def handle_activation_messages(message):
    user_id = message.from_user.id
    message_text = message.text if message.text else ""

    # معالجة تفعيل فيديوهات1
    if ACTIVATION_PHRASE_V1 in message_text:
        if user_id not in load_approved_users(approved_v1_col):
            add_approved_user(approved_v1_col, user_id) 
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ User {user_id} granted V1 access (pending mandatory sub).")
            bot.send_message(user_id, "✅ تم تفعيل وصولك إلى **فيديوهات1** بنجاح!")
            send_mandatory_subscription_message(user_id) # طلب الاشتراك الإجباري
        elif not is_mandatory_subscribed(user_id):
            bot.send_message(user_id, "👍🏼 لديك وصول إلى فيديوهات1، ولكن يرجى إكمال الاشتراك الإجباري أولاً.")
            send_mandatory_subscription_message(user_id)
        else:
            bot.send_message(user_id, "👍🏼 لديك بالفعل وصول إلى فيديوهات1.", reply_markup=main_keyboard())
        return

    # معالجة تفعيل فيديوهات2
    if ACTIVATION_PHRASE_V2 in message_text:
        if user_id not in load_approved_users(approved_v2_col):
            add_approved_user(approved_v2_col, user_id) 
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

    # التحقق مما إذا كان المستخدم لديه وصول لـ فيديوهات1 (بشرط إكمال الاشتراك الإجباري)
    has_v1_access = user_id in load_approved_users(approved_v1_col) and is_mandatory_subscribed(user_id)
    has_v2_access = user_id in load_approved_users(approved_v2_col)
    
    # المستخدم لديه أي نوع من الوصول لعرض الأزرار السفلية
    can_access_main_keyboard = has_v1_access or has_v2_access

    if user_id == OWNER_ID:
        bot.send_message(
            user_id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
        bot.send_message(user_id, "✅ تم تحديث لوحة التحكم.", reply_markup=types.ReplyKeyboardRemove())
    elif has_v1_access or has_v2_access:
        # إذا كان لديه أي وصول وتم الاشتراك الإجباري (لفيديوهات1)
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
    elif user_id in load_approved_users(approved_v1_col) and not is_mandatory_subscribed(user_id):
        # المستخدم مفعل لـ فيديوهات1 ولكنه لم يكمل الاشتراك الإجباري
        send_mandatory_subscription_message(user_id)
    else:
        # إذا لم يكن لديه أي وصول بعد (يوجه لتفعيل فيديوهات1)
        bot.send_message(
            user_id,
            "🚫 مرحباً بك! للوصول إلى محتوى البوت، يرجى تفعيل **فيديوهات1** أولاً.\n"
            f"للتفعيل، يرجى الدخول إلى بوت التمويل الخاص بنا عبر هذا الرابط:\n{FINANCE_BOT_LINK_V1}\n\n"
            "ثم أكمل عملية الدخول وقم بإعادة توجيه رسالة التفعيل التي ستصلك إليّ.\n"
            f"✅ يجب أن تحتوي رسالة التفعيل على العبارة: '{ACTIVATION_PHRASE_V1}'.",
            reply_markup=types.ReplyKeyboardRemove(),
            disable_web_page_preview=True
        )


# معالج لزر التحقق من الاشتراك الإجباري
@bot.callback_query_handler(func=lambda call: call.data == "check_mandatory_sub")
def handle_check_mandatory_sub(call):
    bot.answer_callback_query(call.id, "جار التحقق من اشتراكك في القنوات...")
    user_id = call.from_user.id

    if check_all_mandatory_subscriptions(user_id):
        set_mandatory_subscribed(user_id) # تسجيل أن المستخدم قد اشترك إجباريًا
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ تهانينا! لقد أتممت الاشتراك الإجباري بنجاح!\nالآن يمكنك استخدام البوت والوصول إلى الأقسام المفعلة لك.",
            reply_markup=None # إزالة أزرار التحقق
        )
        # إظهار الأزرار السفلية بعد النجاح
        bot.send_message(user_id, "اختر قسم الفيديوهات:", reply_markup=main_keyboard())
        pending_mandatory_check.pop(user_id, None) # إزالة المستخدم من حالة الانتظار
    else:
        bot.send_message(user_id, "⚠️ لم يتم التحقق من اشتراكك في جميع القنوات. يرجى التأكد من الاشتراك ثم أعد المحاولة.")
        send_mandatory_subscription_message(user_id) # أعد إرسال رسالة الاشتراك الإجباري


# معالج لرسائل المستخدمين غير المفعلين (غير المالك) والذين لم يكملوا الاشتراك الإجباري
@bot.message_handler(func=lambda m: m.from_user.id != OWNER_ID and \
                                     not (m.text and (ACTIVATION_PHRASE_V1 in m.text or ACTIVATION_PHRASE_V2 in m.text)) and \
                                     (m.text not in ["فيديوهات1", "فيديوهات2"]) and \
                                     (m.from_user.id in load_approved_users(approved_v1_col) and not is_mandatory_subscribed(m.from_user.id)))
def handle_pending_mandatory_messages(message):
    bot.send_message(message.chat.id, "⚠️ يرجى إكمال الاشتراك في القنوات الإجبارية أولاً للوصول إلى الأقسام.", reply_markup=types.ReplyKeyboardRemove())
    send_mandatory_subscription_message(message.chat.id)


# معالج لرسائل المستخدمين غير المفعلين (غير المالك) والذين لم يفعلوا أي شيء بعد
@bot.message_handler(func=lambda m: m.from_user.id != OWNER_ID and \
                                     not (m.text and (ACTIVATION_PHRASE_V1 in m.text or ACTIVATION_PHRASE_V2 in m.text)) and \
                                     (m.text not in ["فيديوهات1", "فيديوهات2"]) and \
                                     (m.from_user.id not in load_approved_users(approved_v1_col) and m.from_user.id not in load_approved_users(approved_v2_col)))
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


# معالجات أزرار الفيديوهات للمستخدمين العاديين
@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    user_id = message.from_user.id
    if user_id in load_approved_users(approved_v1_col) and is_mandatory_subscribed(user_id):
        send_videos(user_id, "v1")
    elif user_id in load_approved_users(approved_v1_col) and not is_mandatory_subscribed(user_id):
        bot.send_message(user_id, "⚠️ يرجى إكمال الاشتراك في القنوات الإجبارية أولاً للوصول إلى فيديوهات1.")
        send_mandatory_subscription_message(user_id)
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
    # فيديوهات2 لا تتطلب الاشتراك الإجباري
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
            try:
                bot.delete_message(chat_id, message_id)
            except Exception as e:
                print(f"Failed to delete message from channel: {e}")
                bot.send_message(user_id, "⚠️ لم أتمكن من حذف الفيديو من القناة. قد يكون تم حذفه مسبقاً أو هناك مشكلة في الصلاحيات.")

            db_videos_col = db[f"videos_{category}"]
            db_videos_col.delete_one({"message_id": message_id})
            bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} من قسم {category.upper()} بنجاح.", reply_markup=types.ReplyKeyboardRemove())
            bot.send_message(
                user_id,
                "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
                reply_markup=owner_inline_keyboard()
            )
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
        owner_upload_mode.pop(user_id) 
        bot.send_message(
            user_id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو.")

# معالج الرسائل الجماعية (خاص بالمالك)
@bot.message_handler(func=lambda m: waiting_for_broadcast.get("photo") and m.from_user.id == OWNER_ID, content_types=['photo'])
def receive_broadcast_photo(message):
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
        for user_id_to_send in users_to_broadcast: 
            try:
                bot.send_photo(user_id_to_send, photo_id, caption=text)
                sent_count += 1
            except Exception as e:
                print(f"Failed to send broadcast to {user_id_to_send}: {e}")
                pass 
        bot.send_message(OWNER_ID, f"✅ تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.", reply_markup=types.ReplyKeyboardRemove())
        waiting_for_broadcast.clear()
        bot.send_message(
            OWNER_ID,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )

# --- معالجات الـ Inline Callback Query للمالك (لم تتغير) ---
@bot.callback_query_handler(func=lambda call: call.from_user.id == OWNER_ID)
def owner_callback_query_handler(call):
    bot.answer_callback_query(call.id) 
    user_id = call.from_user.id
    data = call.data

    if data == "main_admin_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
        owner_upload_mode.pop(user_id, None)
        waiting_for_delete.pop(user_id, None)
        waiting_for_broadcast.pop(user_id, None)
    
    elif data == "manage_v1":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="إدارة قسم فيديوهات1:",
            reply_markup=manage_videos_keyboard("v1")
        )
    elif data == "manage_v2":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="إدارة قسم فيديوهات2:",
            reply_markup=manage_videos_keyboard("v2")
        )
    elif data.startswith("upload_video_"):
        category = data.split("_")[2]
        owner_upload_mode[user_id] = category
        bot.send_message(user_id, f"أرسل لي الفيديو الذي تريد رفعه لـ **{category.upper()}**.", parse_mode="Markdown")

    elif data.startswith("delete_video_"):
        category = data.split("_")[2]
        db_videos_col = db[f"videos_{category}"]
        videos = list(db_videos_col.find().limit(20)) 

        if not videos:
            bot.send_message(user_id, f"لا يوجد فيديوهات حالياً في قسم {category.upper()} لحذفها.")
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=manage_videos_keyboard(category)
            ) 
            return
        
        text = f"📋 قائمة فيديوهات {category.upper()}:\n"
        for i, vid in enumerate(videos, 1):
            text += f"{i}. رسالة رقم: {vid['message_id']}\n"
        text += "\nأرسل رقم الفيديو الذي تريد حذفه."
        bot.send_message(user_id, text)
        waiting_for_delete[user_id] = {"category": category, "videos": videos}

    elif data == "broadcast_photo":
        waiting_for_broadcast["photo"] = True
        bot.send_message(user_id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.")


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
