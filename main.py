import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot import types
from telebot import apihelper # Import for ApiTelegramException

from pymongo import MongoClient
import re # Import for regular expressions

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


# --- إعداد MongoDB ---
MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"] 
approved_v2_col = db["approved_v2"] 
notified_users_col = db["notified_users"]
mandatory_subscribed_col = db["mandatory_subscribed"]
# مجموعات جديدة لإدارة الاشتراك الإجباري والقنوات من لوحة التحكم
mandatory_channels_col = db["mandatory_channels"] 
mandatory_message_col = db["mandatory_message"] # لتخزين نص رسالة الاشتراك الإجباري
# --- إضافة مجموعة جديدة لحالة زر التحقق بعد الاشتراك ---
post_subscribe_check_status_col = db["post_subscribe_check_status"]
# مجموعة جديدة لتتبع تقدم المستخدم في الاشتراك الإجباري
user_mandatory_progress_col = db["user_mandatory_progress"]


# --- الحالات المؤقتة ---
owner_upload_mode = {}
waiting_for_broadcast = {}
waiting_for_delete = {}
pending_mandatory_check = {} 
# حالة المالك لإدارة إدخالاته (تعيين/حذف قنوات، تعيين رسالة)
owner_state = {}


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
    """التحقق مما إذا كان المستخدم قد أتم الاشتراك الإجباري في جميع القنوات."""
    # تعتمد الآن على وجود المستند في mandatory_subscribed_col فقط
    # لأن التقدم الفردي للقنوات يتم إدارته بواسطة user_mandatory_progress_col
    return mandatory_subscribed_col.find_one({"user_id": user_id}) is not None

def set_mandatory_subscribed(user_id):
    """تسجيل أن المستخدم قد أتم الاشتراك الإجباري في جميع القنوات."""
    if not is_mandatory_subscribed(user_id):
        mandatory_subscribed_col.insert_one({"user_id": user_id, "timestamp": time.time()})
    # مسح تقدم المستخدم بعد إكمال جميع القنوات لضمان بدء جديد إذا تم إعادة تعيينه
    user_mandatory_progress_col.delete_one({"user_id": user_id})


def main_keyboard():
    # هذه هي لوحة المفاتيح للمستخدمين العاديين
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

# --- لوحة مفاتيح المالك الشفافة الجديدة ---
def owner_inline_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    # تم حذف زر "الإدارة 📂" بناءً على طلب المستخدم
    markup.add(
        types.InlineKeyboardButton("فيديوهات1 ▶️", callback_data="manage_v1"),
        types.InlineKeyboardButton("فيديوهات2 ▶️", callback_data="manage_v2")
    )
    # زر الإذاعة الذي سيقود إلى قائمة فرعية
    markup.add(types.InlineKeyboardButton("الإذاعة 📢", callback_data="broadcast_menu"))
    # إضافة قسم الاشتراك الإجباري
    markup.add(types.InlineKeyboardButton("الاشتراك الإجباري ✨", callback_data="mandatory_sub_menu"))
    # إضافة قسم الإحصائيات
    markup.add(types.InlineKeyboardButton("الإحصائيات 📊", callback_data="statistics_menu"))
    return markup

# --- لوحة مفاتيح قسم الإذاعة للمالك ---
def broadcast_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("رسالة جماعية مع صورة 🖼️", callback_data="broadcast_photo"))
    markup.add(types.InlineKeyboardButton("العودة للقائمة الرئيسية ↩️", callback_data="main_admin_menu"))
    return markup

# --- لوحة مفاتيح قسم الاشتراك الإجباري للمالك ---
def mandatory_sub_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("تعيين قناة إجبارية بالرابط ➕", callback_data="set_mandatory_channel_by_link_start"))
    markup.add(types.InlineKeyboardButton("حذف قناة إجبارية 🗑️", callback_data="delete_mandatory_channel_start"))
    markup.add(types.InlineKeyboardButton("تعيين رسالة الاشتراك الإجباري 📝", callback_data="set_mandatory_message_start"))
    
    current_status = is_post_subscribe_check_enabled()
    status_text = "✅ تشغيل تحقق بعد الاشتراك" if current_status else "❌ إيقاف تحقق بعد الاشتراك"
    callback_data = "toggle_post_subscribe_check_off" if current_status else "toggle_post_subscribe_check_on"
    markup.add(types.InlineKeyboardButton(status_text, callback_data=callback_data))

    markup.add(types.InlineKeyboardButton("العودة للقائمة الرئيسية ↩️", callback_data="main_admin_menu"))
    return markup

# --- لوحة مفاتيح قسم الإحصائيات للمالك ---
def statistics_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("تنظيف المستخدمين المقبولين 🧹", callback_data="clear_approved_users_confirm")) # إضافة تأكيد
    markup.add(types.InlineKeyboardButton("العودة للقائمة الرئيسية ↩️", callback_data="main_admin_menu"))
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
def get_mandatory_channels():
    """يجلب القنوات الإجبارية من MongoDB."""
    return list(mandatory_channels_col.find({}))

def get_mandatory_message_text():
    """يجلب نص رسالة الاشتراك الإجباري من MongoDB أو نص افتراضي."""
    message_doc = mandatory_message_col.find_one({})
    if message_doc and "text" in message_doc:
        return message_doc["text"]
    return "⚠️ للوصول إلى محتوى البوت، يرجى الاشتراك في القنوات التالية أولاً:\n\nبعد الاشتراك في جميع القنوات، اضغط على زر 'تحقق بعد الاشتراك'." # رسالة افتراضية

def is_post_subscribe_check_enabled():
    """يجلب حالة تفعيل زر 'تحقق بعد الاشتراك' من MongoDB."""
    status_doc = post_subscribe_check_status_col.find_one({})
    # الافتراضي: يكون مفعلاً إذا لم يتم تعيينه صراحةً على False
    return status_doc.get("enabled", True) if status_doc else True


def get_user_mandatory_progress(user_id):
    """يجلب مؤشر القناة الحالية التي يجب على المستخدم الاشتراك بها."""
    progress_doc = user_mandatory_progress_col.find_one({"user_id": user_id})
    return progress_doc.get("current_channel_index", 0) if progress_doc else 0

def update_user_mandatory_progress(user_id, index):
    """يحدث مؤشر القناة الحالية للمستخدم."""
    user_mandatory_progress_col.update_one(
        {"user_id": user_id},
        {"$set": {"current_channel_index": index}},
        upsert=True
    )

def send_mandatory_subscription_message(user_id):
    """يرسل رسالة الاشتراك الإجباري مع الأزرار اللازمة، مع إظهار قناة واحدة فقط."""
    if not is_post_subscribe_check_enabled():
        print(f"Post-subscribe check is disabled for user {user_id}. Skipping mandatory message.")
        if user_id in load_approved_users(approved_v1_col):
            set_mandatory_subscribed(user_id) # اعتباره مشتركاً لأنه لا يوجد تحقق
            bot.send_message(user_id, "✅ تم تفعيل وصولك، ولا يتطلب الاشتراك الإجباري حالياً.", reply_markup=main_keyboard())
        return
    
    channels = get_mandatory_channels()
    if not channels:
        bot.send_message(user_id, "لا توجد قنوات إجبارية محددة حالياً.", reply_markup=main_keyboard())
        return

    current_index = get_user_mandatory_progress(user_id)

    if current_index >= len(channels):
        # المستخدم قد أتم جميع الاشتراكات
        set_mandatory_subscribed(user_id)
        bot.send_message(user_id, "✅ تهانينا! لقد أتممت الاشتراك الإجباري بنجاح!\nالآن يمكنك استخدام البوت والوصول إلى الأقسام المفعلة لك.", reply_markup=main_keyboard())
        pending_mandatory_check.pop(user_id, None)
        return

    # إظهار القناة الحالية فقط
    channel_to_show = channels[current_index]
    
    # نص الرسالة الجديد كما طلب المستخدم
    message_text = (
        "🚸| عذراً عزيزي..\n"
        "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه\n\n"
        f"- Link: {channel_to_show['link']}\n\n"
        "‼️| اشترك ثم ارسل /start"
    )

    markup = types.InlineKeyboardMarkup()
    # زر التحقق بعد الاشتراك فقط
    markup.add(types.InlineKeyboardButton("✅ تحقق بعد الاشتراك ✅", callback_data="check_mandatory_sub"))
    
    bot.send_message(
        user_id,
        message_text,
        reply_markup=markup,
        disable_web_page_preview=True # لضمان عدم ظهور معاينة الرابط
    )
    pending_mandatory_check[user_id] = True # وضع المستخدم في حالة انتظار التحقق

# --- معالجات الأوامر والرسائل ---

# معالجات الأوامر الخاصة بالمالك (مثل /v1, /v2)
@bot.message_handler(commands=['v1', 'v2'])
def set_upload_mode(message):
    if message.from_user.id == OWNER_ID:
        mode = message.text[1:]
        owner_upload_mode[message.from_user.id] = mode
        bot.reply_to(message, f"✅ سيتم حفظ الفيديوهات التالية في قسم {mode.upper()}.")
        # بعد ضبط وضع الرفع، نرسل له لوحة الأدمن الشفافة مرة أخرى
        bot.send_message(
            message.from_user.id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )


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
            # تحقق هنا مما إذا كان الاشتراك الإجباري مفعلاً
            if is_post_subscribe_check_enabled() and not is_mandatory_subscribed(user_id):
                # إذا كان التحقق مفعلاً ولم يكمل المستخدم الاشتراك الإجباري، ارسل رسالة القناة الأولى
                update_user_mandatory_progress(user_id, 0) # تأكد أن المستخدم يبدأ من القناة الأولى
                send_mandatory_subscription_message(user_id) 
            else:
                set_mandatory_subscribed(user_id) # اعتباره مشتركاً إذا كان التحقق معطلاً أو كان قد أكمله مسبقاً
                bot.send_message(user_id, "🎉 يمكنك الآن الوصول إلى فيديوهات1!", reply_markup=main_keyboard())
        elif not is_mandatory_subscribed(user_id) and is_post_subscribe_check_enabled(): # إذا كان لديه وصول ولكن لم يكمل الاشتراك الإجباري والتحقق مفعّل
            bot.send_message(user_id, "👍🏼 لديك وصول إلى فيديوهات1، ولكن يرجى إكمال الاشتراك الإجباري أولاً.")
            send_mandatory_subscription_message(user_id)
        elif not is_mandatory_subscribed(user_id) and not is_post_subscribe_check_enabled(): # لديه وصول ولكن لم يكمل الاشتراك الإجباري والتحقق معطل
            set_mandatory_subscribed(user_id) # اعتباره مشتركاً
            bot.send_message(user_id, "👍🏼 لديك وصول إلى فيديوهات1. التحقق الإجباري معطل حالياً.", reply_markup=main_keyboard())
        else: # لديه وصول وأكمل الاشتراك الإجباري
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

    requires_mandatory_check = is_post_subscribe_check_enabled()
    
    # يجب أن يكون المستخدم قد أتم الاشتراك الإجباري أو لا يتطلب الاشتراك الإجباري
    has_v1_access_and_mandatory_done = user_id in load_approved_users(approved_v1_col) and \
                                      (is_mandatory_subscribed(user_id) or not requires_mandatory_check)
    
    has_v2_access = user_id in load_approved_users(approved_v2_col)
    
    can_access_main_keyboard = has_v1_access_and_mandatory_done or has_v2_access

    if user_id == OWNER_ID:
        bot.send_message(
            user_id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
        bot.send_message(user_id, "✅ تم تحديث لوحة التحكم.", reply_markup=types.ReplyKeyboardRemove())
    elif can_access_main_keyboard: # إذا كان لديه أي وصول وتم الاشتراك الإجباري (لفيديوهات1) أو لا يتطلب الاشتراك الإجباري
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
    elif user_id in load_approved_users(approved_v1_col) and not is_mandatory_subscribed(user_id) and requires_mandatory_check:
        # المستخدم مفعل لـ فيديوهات1 ولكنه لم يكمل الاشتراك الإجباري والتحقق مفعّل
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
    channels = get_mandatory_channels()
    current_index = get_user_mandatory_progress(user_id)

    if current_index >= len(channels): # المستخدم أتم جميع الاشتراكات بالفعل
        set_mandatory_subscribed(user_id)
        # لا نرسل رسالة "تهانينا" هنا، بل بعد إعادة توجيه المستخدم إذا لزم الأمر
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None # إزالة الزر
        )
        bot.send_message(user_id, "✅ تهانينا! لقد أتممت الاشتراك الإجباري بنجاح!\nالآن يمكنك استخدام البوت والوصول إلى الأقسام المفعلة لك.", reply_markup=main_keyboard())
        pending_mandatory_check.pop(user_id, None)
        return

    # التحقق من القناة الحالية فقط
    channel_to_check = channels[current_index]
    try:
        member = bot.get_chat_member(channel_to_check["id"], user_id)
        if member.status in ["member", "administrator", "creator"]:
            # المستخدم مشترك في القناة الحالية
            next_index = current_index + 1
            update_user_mandatory_progress(user_id, next_index)
            
            if next_index < len(channels):
                # لا يزال هناك قنوات أخرى للاشتراك بها، أظهر القناة التالية
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"✅ رائع! لقد اشتركت في القناة الحالية. يرجى الاشتراك في القناة التالية.",
                    reply_markup=None # إزالة الزر القديم
                )
                send_mandatory_subscription_message(user_id) # أرسل القناة التالية
            else:
                # أتم جميع الاشتراكات
                set_mandatory_subscribed(user_id)
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ تهانينا! لقد أتممت الاشتراك الإجباري بنجاح!\nالآن يمكنك استخدام البوت والوصول إلى الأقسام المفعلة لك.",
                    reply_markup=None
                )
                bot.send_message(user_id, "اختر قسم الفيديوهات:", reply_markup=main_keyboard())
                pending_mandatory_check.pop(user_id, None)
        else:
            bot.send_message(user_id, "⚠️ لم يتم التحقق من اشتراكك في القناة الحالية. يرجى التأكد من الاشتراك ثم أعد المحاولة.", reply_markup=types.ReplyKeyboardRemove())
            send_mandatory_subscription_message(user_id) # أعد إرسال نفس القناة
    except apihelper.ApiTelegramException as e:
        print(f"Warning: Channel ID {channel_to_check['id']} or user {user_id} issue during check: {e}")
        bot.send_message(user_id, "⚠️ حدث خطأ أثناء التحقق من القناة. يرجى التأكد من أن البوت لديه صلاحية الوصول للقناة وأنك مشترك بها.", reply_markup=types.ReplyKeyboardRemove())
        send_mandatory_subscription_message(user_id)
    except Exception as e:
        print(f"An unexpected error occurred while checking subscription for {user_id} in {channel_to_check['id']}: {e}")
        bot.send_message(user_id, "⚠️ حدث خطأ غير متوقع أثناء التحقق. يرجى المحاولة مرة أخرى.", reply_markup=types.ReplyKeyboardRemove())
        send_mandatory_subscription_message(user_id)


# معالج لرسائل المستخدمين غير المفعلين والذين لم يكملوا الاشتراك الإجباري
@bot.message_handler(func=lambda m: m.from_user.id != OWNER_ID and \
                                     not (m.text and (ACTIVATION_PHRASE_V1 in m.text or ACTIVATION_PHRASE_V2 in m.text)) and \
                                     (m.text not in ["فيديوهات1", "فيديوهات2"]) and \
                                     (m.from_user.id in load_approved_users(approved_v1_col) and not is_mandatory_subscribed(m.from_user.id) and is_post_subscribe_check_enabled()))
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
        "🚫 مرحباً بك! للوصول إلى محتوى البوت، يرجى تفعيل **فيديوهات1** أولاً.\n"
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
    if user_id in load_approved_users(approved_v1_col) and (is_mandatory_subscribed(user_id) or not is_post_subscribe_check_enabled()):
        send_videos(user_id, "v1")
    elif user_id in load_approved_users(approved_v1_col) and not is_mandatory_subscribed(user_id) and is_post_subscribe_check_enabled():
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
            # بعد الحذف، نرسل له لوحة الأدمن الشفافة مرة أخرى
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

# --- معالجات الـ Inline Callback Query للمالك ---
@bot.callback_query_handler(func=lambda call: call.from_user.id == OWNER_ID)
def owner_callback_query_handler(call):
    bot.answer_callback_query(call.id) 
    user_id = call.from_user.id
    data = call.data

    # مسح أي حالات انتظار سابقة عند التنقل في القوائم الرئيسية
    owner_upload_mode.pop(user_id, None)
    waiting_for_delete.pop(user_id, None)
    waiting_for_broadcast.pop(user_id, None)
    owner_state.pop(user_id, None) # مسح حالة الإدخال الخاصة بالمالك

    # لا يوجد "main_admin_menu" مباشر هنا بعد حذف زر الإدارة، بل يتم إعادة عرض اللوحة الرئيسية
    if data == "main_admin_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
    
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

    # معالج زر الإذاعة الجديد يقود إلى قائمة فرعية
    elif data == "broadcast_menu": 
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="إدارة قسم الإذاعة:",
            reply_markup=broadcast_admin_keyboard()
        )
    elif data == "broadcast_photo":
        waiting_for_broadcast["photo"] = True
        bot.send_message(user_id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.")
    
    # --- معالجات الأزرار الجديدة لقسم الاشتراك الإجباري ---
    elif data == "mandatory_sub_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="إدارة قنوات الاشتراك الإجباري والرسالة:",
            reply_markup=mandatory_sub_admin_keyboard()
        )
    
    elif data == "set_mandatory_channel_by_link_start":
        bot.send_message(user_id, "الرجاء إرسال **رابط القناة** (مثال: `https://t.me/my_channel_link` أو `https://t.me/c/-1001234567890`).", parse_mode="Markdown")
        owner_state[user_id] = {"action": "await_mandatory_channel_link_only"}

    elif data == "delete_mandatory_channel_start":
        channels = get_mandatory_channels()
        if not channels:
            bot.send_message(user_id, "لا توجد قنوات إجبارية لإزالتها حالياً.")
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=mandatory_sub_admin_keyboard()
            )
            return
        
        text = "📋 قائمة القنوات الإجبارية:\n"
        for i, channel in enumerate(channels, 1):
            # استخدام channel.get('_id') لضمان وجوده
            text += f"{i}. ID: `{channel.get('id', 'N/A')}` - Link: {channel.get('link', 'غير محدد')}\n"
        text += "\nالرجاء إرسال رقم القناة التي تريد حذفها."
        bot.send_message(user_id, text, parse_mode="Markdown")
        owner_state[user_id] = {"action": "await_delete_mandatory_channel_index", "channels_list": channels}

    elif data == "set_mandatory_message_start":
        current_message = get_mandatory_message_text()
        bot.send_message(user_id, f"الرجاء إرسال نص رسالة الاشتراك الإجباري الجديدة.\n\nالرسالة الحالية:\n`{current_message}`", parse_mode="Markdown")
        owner_state[user_id] = {"action": "await_mandatory_message_text"}

    # --- إضافة معالجات أزرار تشغيل/إيقاف تحقق بعد الاشتراك ---
    elif data == "toggle_post_subscribe_check_on":
        post_subscribe_check_status_col.update_one({}, {"$set": {"enabled": True}}, upsert=True)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ تم تفعيل التحقق بعد الاشتراك.",
            reply_markup=mandatory_sub_admin_keyboard() # تحديث لوحة المفاتيح لعرض الحالة الجديدة
        )
    elif data == "toggle_post_subscribe_check_off":
        post_subscribe_check_status_col.update_one({}, {"$set": {"enabled": False}}, upsert=True)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ تم إيقاف التحقق بعد الاشتراك.",
            reply_markup=mandatory_sub_admin_keyboard() # تحديث لوحة المفاتيح لعرض الحالة الجديدة
        )
    
    # --- معالجات قسم الإحصائيات ---
    elif data == "statistics_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="إحصائيات وإدارة المستخدمين:",
            reply_markup=statistics_admin_keyboard()
        )
    elif data == "clear_approved_users_confirm": # معالج زر التأكيد
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("نعم، احذف 🗑️", callback_data="clear_approved_users_execute"))
        markup.add(types.InlineKeyboardButton("إلغاء ↩️", callback_data="statistics_menu")) # العودة لقائمة الإحصائيات
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚠️ هل أنت متأكد تمامًا من حذف جميع المستخدمين المقبولين؟ هذا سيؤدي إلى مسح جميع بياناتهم وسيحتاجون إلى إعادة التفعيل بالكامل.",
            reply_markup=markup
        )
    
    elif data == "clear_approved_users_execute": # معالج تنفيذ الحذف الفعلي
        approved_v1_col.delete_many({})
        approved_v2_col.delete_many({})
        notified_users_col.delete_many({})
        mandatory_subscribed_col.delete_many({})
        user_mandatory_progress_col.delete_many({}) # مسح تقدم الاشتراك الإجباري أيضاً

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ تم حذف جميع المستخدمين المقبولين بنجاح. سيحتاجون إلى إعادة التفعيل.",
            reply_markup=None
        )
        bot.send_message(
            user_id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )


# --- معالجات مدخلات المالك الخاصة بـ "الاشتراك الإجباري" ---

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and owner_state.get(m.from_user.id, {}).get("action") == "await_mandatory_channel_link_only")
def handle_await_mandatory_channel_link_only(message):
    user_id = message.from_user.id
    channel_link = message.text.strip()
    channel_id = None
    
    cleaned_link = channel_link.replace("https://t.me/", "").replace("t.me/", "")

    try:
        if cleaned_link.startswith("c/"):
            match = re.search(r'c/(-?\d+)', cleaned_link)
            if match:
                channel_id = int(match.group(1))
            else:
                raise ValueError("Could not extract ID from 'c/' link.")
        elif cleaned_link.startswith("+"):
            bot.send_message(user_id, "⚠️ لا يمكن إضافة القنوات الخاصة بروابط الدعوة (+) تلقائياً. الرجاء التأكد من أن القناة عامة (اسم مستخدم) أو قم بإضافة الـ ID يدوياً إذا كان البوت مسؤولاً فيها.")
            owner_state.pop(user_id, None)
            bot.send_message(
                user_id,
                "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
                reply_markup=owner_inline_keyboard()
            )
            return
        else:
            username = cleaned_link.split('/')[0]
            chat_obj = bot.get_chat(f"@{username}")
            channel_id = chat_obj.id

        if not isinstance(channel_id, int) or channel_id >= 0 or not str(channel_id).startswith("-100"):
            raise ValueError("Invalid channel ID extracted or not a supergroup/channel.")

        if mandatory_channels_col.find_one({"id": channel_id}):
            bot.send_message(user_id, "⚠️ هذه القناة موجودة بالفعل في قائمة القنوات الإجبارية.")
        else:
            mandatory_channels_col.insert_one({"id": channel_id, "link": channel_link})
            bot.send_message(user_id, f"✅ تم إضافة القناة `{channel_id}` بنجاح.", parse_mode="Markdown")
        
    except apihelper.ApiTelegramException as e:
        error_message = f"❌ خطأ في جلب معلومات القناة: {e}. قد تكون القناة غير موجودة، أو البوت ليس عضواً فيها، أو ليس لديه صلاحية الوصول. تأكد من أن الرابط صحيح وأن البوت مسؤول في القناة."
        bot.send_message(user_id, error_message)
    except ValueError as e:
        bot.send_message(user_id, f"❌ الرابط غير صالح أو لا يمكن استخراج معرف القناة منه: {e}. يرجى إرسال رابط قناة عامة (اسم مستخدم) أو رابط معرف قناة (يبدأ بـ `c/-100`).")
    except Exception as e:
        bot.send_message(user_id, f"❌ حدث خطأ غير متوقع: {e}. يرجى المحاولة مرة أخرى أو التحقق من الرابط.")
    
    owner_state.pop(user_id, None)
    bot.send_message(
        user_id,
        "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
        reply_markup=owner_inline_keyboard()
    )

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and owner_state.get(m.from_user.id, {}).get("action") == "await_delete_mandatory_channel_index")
def handle_await_delete_mandatory_channel_index(message):
    user_id = message.from_user.id
    channels_list = owner_state[user_id].get("channels_list")
    try:
        index_to_delete = int(message.text) - 1
        if 0 <= index_to_delete < len(channels_list):
            channel_to_delete = channels_list[index_to_delete]
            # التأكد من حذف باستخدام _id الخاص بـ MongoDB
            if "_id" in channel_to_delete:
                mandatory_channels_col.delete_one({"_id": channel_to_delete["_id"]})
                bot.send_message(user_id, f"✅ تم حذف القناة `{channel_to_delete.get('id', 'N/A')}` بنجاح.", parse_mode="Markdown")
            else:
                bot.send_message(user_id, "❌ خطأ: لا يمكن تحديد معرف القناة للحذف. يرجى المحاولة مرة أخرى.", reply_markup=types.ReplyKeyboardRemove())
        else:
            bot.send_message(user_id, "❌ رقم قناة غير صالح. يرجى إرسال رقم من القائمة.", reply_markup=types.ReplyKeyboardRemove())
            
    except ValueError:
        bot.send_message(user_id, "❌ يرجى إرسال رقم صالح من القائمة.", reply_markup=types.ReplyKeyboardRemove())
    
    # بعد أي عملية حذف أو خطأ، أعد المستخدم إلى القائمة الرئيسية
    owner_state.pop(user_id)
    bot.send_message(
        user_id,
        "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
        reply_markup=owner_inline_keyboard()
    )

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and owner_state.get(m.from_user.id, {}).get("action") == "await_mandatory_message_text")
def handle_await_mandatory_message_text(message):
    user_id = message.from_user.id
    new_message_text = message.text.strip()

    mandatory_message_col.update_one({}, {"$set": {"text": new_message_text}}, upsert=True)
    bot.send_message(user_id, "✅ تم تعيين رسالة الاشتراك الإجباري بنجاح.", reply_markup=types.ReplyKeyboardRemove())
    
    owner_state.pop(user_id)
    bot.send_message(
        user_id,
        "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
        reply_markup=owner_inline_keyboard()
    )

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
