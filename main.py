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
FINANCE_BOT_ID_V1 = 6626184534 # أضف معرف بوت التمويل هنا
ACTIVATION_PHRASE_V1 = "• لقد دخلت بنجاح عبر الرابط الذي قدمه صديقك كدعوة، ونتيجة لذلك، حصل صديقك على 2000 نقطة/نقاط كمكافأة ✨."
FINANCE_BOT_LINK_V1 = "https://t.me/yynnurybot?start=0006k43lft"

# --- إعدادات التفعيل لفيديوهات2 ---
FINANCE_BOT_USERNAME_V2 = "MHDN313bot"
FINANCE_BOT_ID_V2 = 6223173758 # أضف معرف بوت التمويل هنا (مثال فقط، قم بتحديثه)
ACTIVATION_PHRASE_V2 = "• لقد دخلت بنجاح عبر الرابط الذي قدمه صديقك كدعوة، ونتيجة لذلك، حصل صديقك على 1313 نقطة/نقاط كمكافأة ✨."
FINANCE_BOT_LINK_V2 = "https://t.me/MHDN313bot?start=0007mp2ekb"


# --- إعداد MongoDB ---
MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"]
approved_v2_col = db["approved_v2"]
notified_users_col = db["notified_users"]
mandatory_subscribed_col = db["mandatory_subscribed"] # لتتبع من أكملوا الاشتراك الإجباري مرة واحدة
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
    """
    Loads approved user IDs from a specific MongoDB collection.
    """
    return set(doc["user_id"] for doc in collection.find())

def add_approved_user(collection, user_id):
    """
    Adds a user ID to a specified MongoDB collection of approved users.
    """
    if not collection.find_one({"user_id": user_id}):
        collection.insert_one({"user_id": user_id})

def remove_approved_user(collection, user_id):
    """
    Removes a user ID from a specified MongoDB collection of approved users.
    """
    collection.delete_one({"user_id": user_id})

def has_notified(user_id):
    """
    Checks if a user has been notified.
    """
    return notified_users_col.find_one({"user_id": user_id}) is not None

def add_notified_user(user_id):
    """
    Adds a user to the notified users collection.
    """
    if not has_notified(user_id):
        notified_users_col.insert_one({"user_id": user_id})

def has_completed_mandatory_flow_in_db(user_id):
    """
    Checks if the user has completed mandatory subscription flow in the database.
    """
    return mandatory_subscribed_col.find_one({"user_id": user_id}) is not None

def set_mandatory_subscribed(user_id):
    """
    Records that the user has completed mandatory subscription.
    """
    if not has_completed_mandatory_flow_in_db(user_id):
        mandatory_subscribed_col.insert_one({"user_id": user_id, "timestamp": time.time()})
    # Clear user progress after completing all channels to ensure a fresh start if reset
    user_mandatory_progress_col.delete_one({"user_id": user_id})

def is_currently_subscribed_to_all_mandatory_channels(user_id):
    """
    Checks in real-time if the user is subscribed to all mandatory channels.
    """
    if not is_post_subscribe_check_enabled():
        return True # If check is disabled, consider them subscribed

    channels = get_mandatory_channels()
    if not channels:
        return True # No mandatory channels, so considered subscribed

    for channel in channels:
        try:
            member = bot.get_chat_member(channel["id"], user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False # User is not subscribed to at least one channel
        except apihelper.ApiTelegramException as e:
            # If the bot cannot access channel info (e.g., if not an admin)
            # or if the channel ID is invalid, consider them unsubscribed for safety.
            print(f"Error checking channel {channel.get('id', 'N/A')} for user {user_id}: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error checking channel {channel.get('id', 'N/A')} for user {user_id}: {e}")
            return False
    return True # User is subscribed to all channels

def main_keyboard():
    """
    Returns the main keyboard for regular users.
    """
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

# --- لوحة مفاتيح المالك الشفافة الجديدة ---
def owner_inline_keyboard():
    """
    Returns the inline keyboard for the owner/admin.
    """
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("فيديوهات1 ▶️", callback_data="manage_v1"),
        types.InlineKeyboardButton("فيديوهات2 ▶️", callback_data="manage_v2")
    )
    # Broadcast button leading to a submenu
    markup.add(types.InlineKeyboardButton("الإذاعة 📢", callback_data="broadcast_menu"))
    # Add mandatory subscription section
    markup.add(types.InlineKeyboardButton("الاشتراك الإجباري ✨", callback_data="mandatory_sub_menu"))
    # Add statistics section
    markup.add(types.InlineKeyboardButton("الإحصائيات 📊", callback_data="statistics_menu"))
    return markup

# --- لوحة مفاتيح قسم الإذاعة للمالك ---
def broadcast_admin_keyboard():
    """
    Returns the admin keyboard for the broadcast section.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("رسالة جماعية مع صورة 🖼️", callback_data="broadcast_photo"))
    markup.add(types.InlineKeyboardButton("العودة للقائمة الرئيسية ↩️", callback_data="main_admin_menu"))
    return markup

# --- لوحة مفاتيح قسم الاشتراك الإجباري للمالك ---
def mandatory_sub_admin_keyboard():
    """
    Returns the admin keyboard for the mandatory subscription section.
    """
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
    """
    Returns the admin keyboard for the statistics section.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("تنظيف المستخدمين المقبولين 🧹", callback_data="clear_approved_users_confirm")) # Add confirmation
    markup.add(types.InlineKeyboardButton("العودة للقائمة الرئيسية ↩️", callback_data="main_admin_menu"))
    return markup

# --- قوائم فرعية لإدارة الفيديوهات ---
def manage_videos_keyboard(category):
    """
    Returns the inline keyboard for managing videos in a specific category.
    """
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"إضافة فيديو لـ {category.upper()} ➕", callback_data=f"upload_video_{category}"),
        types.InlineKeyboardButton(f"حذف فيديو من {category.upper()} 🗑️", callback_data=f"delete_video_{category}")
    )
    markup.add(types.InlineKeyboardButton("العودة للقائمة الرئيسية ↩️", callback_data="main_admin_menu"))
    return markup

# --- لوحة مفاتيح رسالة التفعيل الأولية للمستخدمين غير المفعلين ---
def initial_activation_keyboard():
    """
    Returns the initial activation keyboard for unactivated users.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("لقد قمت بتفعيل البوت ✅", callback_data="activated_bot_check"))
    return markup


def get_total_approved_users():
    """
    Calculates the total number of approved users across both categories.
    """
    return len(load_approved_users(approved_v1_col).union(load_approved_users(approved_v2_col)))

def send_videos(user_id, category):
    """
    Sends videos from a specified category to the user.
    """
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
    """
    Fetches mandatory channels from MongoDB.
    """
    return list(mandatory_channels_col.find({}).sort("order", 1)) # Sort by an 'order' field if you add one, otherwise just get them

def get_mandatory_message_text():
    """
    Fetches the mandatory subscription message text from MongoDB or returns a default.
    """
    message_doc = mandatory_message_col.find_one({})
    if message_doc and "text" in message_doc:
        return message_doc["text"]
    return "⚠️ للوصول إلى محتوى البوت، يرجى الاشتراك في القنوات التالية أولاً:\n\nبعد الاشتراك في جميع القنوات، اضغط على زر 'تحقق بعد الاشتراك'." # Default message

def is_post_subscribe_check_enabled():
    """
    Fetches the status of the 'Check after subscription' button from MongoDB.
    """
    status_doc = post_subscribe_check_status_col.find_one({})
    # Default: enabled if not explicitly set to False
    return status_doc.get("enabled", True) if status_doc else True


def get_unsubscribed_mandatory_channels(user_id):
    """
    Checks which mandatory channels the user is NOT subscribed to.
    Returns a list of channel dictionaries (id, link) for unsubscribed channels.
    """
    unsubscribed_channels = []
    channels = get_mandatory_channels()
    for channel in channels:
        try:
            member = bot.get_chat_member(channel["id"], user_id)
            if member.status not in ["member", "administrator", "creator"]:
                unsubscribed_channels.append(channel)
        except apihelper.ApiTelegramException as e:
            # If bot can't access channel or channel ID is invalid, assume unsubscribed
            print(f"Error checking channel {channel.get('id', 'N/A')} for user {user_id}: {e}")
            unsubscribed_channels.append(channel)
        except Exception as e:
            print(f"Unexpected error checking channel {channel.get('id', 'N/A')} for user {user_id}: {e}")
            unsubscribed_channels.append(channel)
    return unsubscribed_channels

def send_mandatory_subscription_message(user_id):
    """
    Sends the mandatory subscription message with necessary buttons, showing only one unsubscribed channel at a time.
    """
    if not is_post_subscribe_check_enabled():
        print(f"Post-subscribe check is disabled for user {user_id}. Skipping mandatory message.")
        return

    channels = get_mandatory_channels()
    if not channels:
        set_mandatory_subscribed(user_id)
        bot.send_message(user_id, "✅ لا توجد قنوات إجبارية حالياً. يمكنك استخدام البوت.", reply_markup=main_keyboard())
        pending_mandatory_check.pop(user_id, None)
        return

    # Get user's current progress
    user_progress = user_mandatory_progress_col.find_one({"user_id": user_id})
    current_index = user_progress["current_channel_index"] if user_progress else 0

    # Find the next unsubscribed channel starting from current_index
    next_channel_to_subscribe = None
    for i in range(current_index, len(channels)):
        channel = channels[i]
        try:
            member = bot.get_chat_member(channel["id"], user_id)
            if member.status not in ["member", "administrator", "creator"]:
                next_channel_to_subscribe = channel
                current_index = i # Update index to this channel
                break
        except apihelper.ApiTelegramException as e:
            print(f"Error checking channel {channel.get('id', 'N/A')} for user {user_id}: {e}")
            next_channel_to_subscribe = channel
            current_index = i # Update index to this channel
            break
        except Exception as e:
            print(f"Unexpected error checking channel {channel.get('id', 'N/A')} for user {user_id}: {e}")
            next_channel_to_subscribe = channel
            current_index = i # Update index to this channel
            break

    if next_channel_to_subscribe:
        # Update user's progress in DB
        user_mandatory_progress_col.update_one(
            {"user_id": user_id},
            {"$set": {"current_channel_index": current_index}},
            upsert=True
        )

        message_text = (
            f"🚸| عذراً عزيزي..\n"
            f"🔰| عليك الاشتراك في القناة التالية لتتمكن من استخدام البوت:\n\n"
            f"القناة {current_index + 1} من {len(channels)}: {next_channel_to_subscribe['link']}\n\n"
            "‼️| بعد الاشتراك في القناة، اضغط على زر 'تحقق بعد الاشتراك'."
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ تحقق بعد الاشتراك ✅", callback_data="check_mandatory_sub"))

        bot.send_message(
            user_id,
            message_text,
            reply_markup=markup,
            disable_web_page_preview=True
        )
        pending_mandatory_check[user_id] = True
    else:
        # All channels are subscribed to
        set_mandatory_subscribed(user_id)
        bot.send_message(user_id, "✅ تهانينا! لقد أتممت الاشتراك الإجباري بنجاح!\nالآن يمكنك استخدام البوت والوصول إلى الأقسام المفعلة لك.", reply_markup=main_keyboard())
        pending_mandatory_check.pop(user_id, None)


# --- معالجات الأوامر والرسائل ---

# Owner-specific command handlers (e.g., /v1, /v2)
@bot.message_handler(commands=['v1', 'v2'])
def set_upload_mode(message):
    """
    Sets the video upload mode for the owner.
    """
    if message.from_user.id == OWNER_ID:
        mode = message.text[1:]
        owner_upload_mode[message.from_user.id] = mode
        bot.reply_to(message, f"✅ سيتم حفظ الفيديوهات التالية في قسم {mode.upper()}.")
        # After setting upload mode, send the owner inline admin keyboard again
        bot.send_message(
            message.from_user.id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )


# Activation message handler (V1 and V2)
@bot.message_handler(func=lambda m: m.forward_from or m.forward_from_chat) # Only forwarded messages
def handle_activation_messages(message):
    """
    Handles activation messages forwarded from finance bots.
    """
    user_id = message.from_user.id
    message_text = message.text if message.text else ""
    user_name = message.from_user.first_name if message.from_user.first_name else "لا يوجد اسم"
    user_username = f"@{message.from_user.username}" if message.from_user.username else "لا يوجد يوزر"


    # Check forwarding source
    source_bot_id = None
    if message.forward_from:
        source_bot_id = message.forward_from.id
    elif message.forward_from_chat and message.forward_from_chat.type == "bot":
        source_bot_id = message.forward_from_chat.id

    if not source_bot_id:
        # If not a forwarded message from a bot, ignore or send an error message
        bot.send_message(user_id, "⚠️ يرجى **إعادة توجيه** رسالة التفعيل مباشرة من بوت التمويل، وليس نسخها ولصقها.")
        return

    # Handle V1 activation
    if source_bot_id == FINANCE_BOT_ID_V1 and ACTIVATION_PHRASE_V1 in message_text:
        if user_id not in load_approved_users(approved_v1_col):
            add_approved_user(approved_v1_col, user_id)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ User {user_id} granted V1 access (pending mandatory sub).")
            bot.send_message(user_id, "✅ تم تفعيل وصولك إلى **فيديوهات1** بنجاح!")

            # Notification message for the owner when a new user is automatically accepted (V1)
            owner_notification_message = (
                "لقد تم قبول المستخدم تلقائيًا:\n\n"
                f"الاسم: {user_name}\n"
                f"اليوزر: {user_username}\n"
                f"الآيدي: `{user_id}`\n"
                "تم منحه وصولاً إلى: فيديوهات1"
            )
            bot.send_message(OWNER_ID, owner_notification_message, parse_mode="Markdown")

        # After activation, check mandatory subscription
        if is_post_subscribe_check_enabled() and not is_currently_subscribed_to_all_mandatory_channels(user_id):
            send_mandatory_subscription_message(user_id)
        else:
            set_mandatory_subscribed(user_id) # Consider them subscribed if check is disabled or already completed
            bot.send_message(user_id, "🎉 يمكنك الآن الوصول إلى فيديوهات1!", reply_markup=main_keyboard())
        return

    # Handle V2 activation
    elif source_bot_id == FINANCE_BOT_ID_V2 and ACTIVATION_PHRASE_V2 in message_text:
        if user_id not in load_approved_users(approved_v2_col):
            add_approved_user(approved_v2_col, user_id)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ User {user_id} granted V2 access.")
            bot.send_message(user_id, "✅ تم تفعيل وصولك إلى **فيديوهات2** بنجاح! يمكنك الآن الضغط على زر **فيديوهات2**.", reply_markup=main_keyboard())

            # Notification message for the owner when a new user is automatically accepted (V2)
            owner_notification_message = (
                "لقد تم قبول المستخدم تلقائيًا:\n\n"
                f"الاسم: {user_name}\n"
                f"اليوزر: {user_username}\n"
                f"الآيدي: `{user_id}`\n"
                "تم منحه وصولاً إلى: فيديوهات2"
            )
            bot.send_message(OWNER_ID, owner_notification_message, parse_mode="Markdown")

        else:
            bot.send_message(user_id, "👍🏼 لديك بالفعل وصول إلى فيديوهات2.", reply_markup=main_keyboard())
        return
    else:
        # Forwarded message is not from the required finance bot or does not contain the correct phrase
        bot.send_message(user_id, "⚠️ هذه ليست رسالة تفعيل صالحة من بوت التمويل المحدد. يرجى التأكد من إعادة توجيه الرسالة الصحيحة.")


# /start function (initial user interface)
@bot.message_handler(commands=['start'])
def start(message):
    """
    Handles the /start command, greeting the user and presenting options.
    """
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "لا يوجد اسم"

    requires_mandatory_check = is_post_subscribe_check_enabled()
    has_v1_access = user_id in load_approved_users(approved_v1_col)
    has_v2_access = user_id in load_approved_users(approved_v2_col)

    if user_id == OWNER_ID:
        bot.send_message(
            user_id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
        bot.send_message(user_id, "✅ تم تحديث لوحة التحكم.", reply_markup=types.ReplyKeyboardRemove())
    elif has_v1_access or has_v2_access: # User is activated (has access to either category)
        if requires_mandatory_check and not is_currently_subscribed_to_all_mandatory_channels(user_id):
            # If check is enabled and user is not subscribed to all mandatory channels
            send_mandatory_subscription_message(user_id)
        else:
            # User is activated and subscribed to all mandatory channels (or check is disabled)
            welcome_message = (
                f"🔞 مرحباً بك ( {first_name} ) 🏳‍🌈\n"
                "📂اختر قسم الفيديوهات من الأزرار بالأسفل!\n\n"
                "⚠️ المحتوى +18 - للكبار فقط!"
            )
            bot.send_message(user_id, welcome_message, reply_markup=main_keyboard())
    else: # User is not activated at all
        markup_for_unactivated = initial_activation_keyboard()
        activation_message_text = (
            "📢 مرحبًا عزيزي!\n\n"
            "للوصول إلى محتوى البوت، يجب أولًا تفعيل بوت التمويل.\n\n"
            "🔰 خطوات التفعيل:\n\n"
            "1️⃣ اضغط على الرابط في الأسفل للذهب إلى بوت التمويل.\n\n"
            "2️⃣ فعّل بوت التمويل واشترك في جميع القنوات المطلوبة❗️.\n\n"
            "3️⃣ بعد الاشتراك في جميع القنوات، ستصلك رسالة من بوت التمويل تؤكد تم التفعيل.\n\n"
            "4️⃣ قم بإعادة (تحويل) رسالة التفعيل إلى هنا – بدون نسخ أو تعديل.\n\n"
            "✅ بعد تحويل الرسالة سيتم قبولك تلقائيًا.\n\n"
            "👇 اضغط هنا لتفعيل بوت التمويل:\n"
            f"🔗 {FINANCE_BOT_LINK_V1}"
        )
        bot.send_message(
            user_id,
            activation_message_text,
            reply_markup=markup_for_unactivated,
            disable_web_page_preview=True
        )


# Handler for the mandatory subscription check button
@bot.callback_query_handler(func=lambda call: call.data == "check_mandatory_sub")
def handle_check_mandatory_sub(call):
    """
    Handles the 'check_mandatory_sub' callback to verify user subscription for the current channel.
    """
    bot.answer_callback_query(call.id, "جار التحقق من اشتراكك في القناة...")
    user_id = call.from_user.id

    channels = get_mandatory_channels()
    if not channels:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ لا توجد قنوات إجبارية حالياً. يمكنك استخدام البوت.",
            reply_markup=None
        )
        set_mandatory_subscribed(user_id)
        bot.send_message(user_id, "الآن يمكنك استخدام البوت.", reply_markup=main_keyboard())
        pending_mandatory_check.pop(user_id, None)
        return

    user_progress = user_mandatory_progress_col.find_one({"user_id": user_id})
    current_index = user_progress["current_channel_index"] if user_progress else 0

    if current_index < len(channels):
        current_channel = channels[current_index]
        try:
            member = bot.get_chat_member(current_channel["id"], user_id)
            if member.status in ["member", "administrator", "creator"]:
                # User subscribed to the current channel, move to next
                new_index = current_index + 1
                user_mandatory_progress_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"current_channel_index": new_index}},
                    upsert=True
                )
                # Removed the success message "✅ رائع! لقد اشتركت في القناة X."
                # Just edit the previous message to remove the button
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None
                )
                send_mandatory_subscription_message(user_id) # Send next channel or completion message
            else:
                # User not subscribed to the current channel
                # Removed the button from this message as well
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="⚠️ لم يتم التحقق من اشتراكك في القناة الحالية. يرجى التأكد من الاشتراك ثم أعد المحاولة.",
                    reply_markup=None # Removed the button here
                )
                # Re-send the link for the current channel with the check button
                message_text = (
                    f"🚸| عذراً عزيزي..\n"
                    f"🔰| عليك الاشتراك في القناة التالية لتتمكن من استخدام البوت:\n\n"
                    f"القناة {current_index + 1} من {len(channels)}: {current_channel['link']}\n\n"
                    "‼️| بعد الاشتراك في القناة، اضغط على زر 'تحقق بعد الاشتراك'."
                )
                bot.send_message(
                    user_id,
                    message_text,
                    reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ تحقق بعد الاشتراك ✅", callback_data="check_mandatory_sub")),
                    disable_web_page_preview=True
                )
        except apihelper.ApiTelegramException as e:
            print(f"Error checking channel {current_channel.get('id', 'N/A')} for user {user_id}: {e}")
            bot.send_message(user_id, "❌ حدث خطأ أثناء التحقق من القناة. يرجى التأكد من أن البوت لديه صلاحيات المسؤول في القناة أو أن المعرف صحيح.")
            send_mandatory_subscription_message(user_id) # Re-attempt sending the current channel
        except Exception as e:
            print(f"Unexpected error checking channel {current_channel.get('id', 'N/A')} for user {user_id}: {e}")
            bot.send_message(user_id, "❌ حدث خطأ غير متوقع أثناء التحقق. يرجى المحاولة مرة أخرى.")
            send_mandatory_subscription_message(user_id) # Re-attempt sending the current channel
    else:
        # Should not happen if send_mandatory_subscription_message is called correctly, but as a fallback
        set_mandatory_subscribed(user_id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ تهانينا! لقد أتممت الاشتراك الإجباري بنجاح!\nالآن يمكنك استخدام البوت والوصول إلى الأقسام المفعلة لك.",
            reply_markup=None
        )
        bot.send_message(user_id, "الآن يمكنك استخدام البوت.", reply_markup=main_keyboard())
        pending_mandatory_check.pop(user_id, None)


# Handler for unactivated users' messages and those who haven't completed mandatory subscription
@bot.message_handler(func=lambda m: m.from_user.id != OWNER_ID and \
                                     not (m.forward_from or m.forward_from_chat) and \
                                     (m.text not in ["فيديوهات1", "فيديوهات2"]) and \
                                     (m.from_user.id in load_approved_users(approved_v1_col) or m.from_user.id in load_approved_users(approved_v2_col)) and \
                                     is_post_subscribe_check_enabled() and \
                                     not is_currently_subscribed_to_all_mandatory_channels(m.from_user.id))
def handle_pending_mandatory_messages(message):
    """
    Handles messages from users who are approved but haven't completed mandatory subscription.
    """
    bot.send_message(message.chat.id, "⚠️ يرجى إكمال الاشتراك في القنوات الإجبارية أولاً للوصول إلى الأقسام.", reply_markup=types.ReplyKeyboardRemove())
    send_mandatory_subscription_message(message.chat.id)


# Handler for unactivated users' messages (not owner) who haven't done anything yet
@bot.message_handler(func=lambda m: m.from_user.id != OWNER_ID and \
                                     not (m.forward_from or m.forward_from_chat) and \
                                     (m.text not in ["فيديوهات1", "فيديوهات2"]) and \
                                     (m.from_user.id not in load_approved_users(approved_v1_col) and m.from_user.id not in load_approved_users(approved_v2_col)))
def handle_unactivated_user_messages(message):
    """
    Handles messages from completely unactivated users.
    """
    markup_for_unactivated = initial_activation_keyboard()
    # New activation message text with the link included directly
    activation_message_text = (
    "📢 مرحبًا عزيزي!\n\n"
    "للوصول إلى محتوى البوت، يجب أولًا تفعيل بوت التمويل.\n\n"
    "🔰 خطوات التفعيل:\n\n"
    "1️⃣ اضغط على الرابط في الأسفل للذهب إلى بوت التمويل.\n\n"
    "2️⃣ فعّل بوت التمويل واشترك في جميع القنوات المطلوبة❗️.\n\n"
    "3️⃣ بعد الاشتراك في جميع القنوات، ستصلك رسالة من بوت التمويل تؤكد تم التفعيل.\n\n"
    "4️⃣ قم بإعادة (تحويل) رسالة التفعيل إلى هنا – بدون نسخ أو تعديل.\n\n"
    "✅ بعد تحويل الرسالة سيتم قبولك تلقائيًا.\n\n"
    "👇 اضغط هنا لتفعيل بوت التمويل:\n"
    "🔗 https://t.me/yynnurybot?start=0006k43lft"
)
    bot.send_message(
        message.chat.id,
        activation_message_text, # Use the new text
        reply_markup=markup_for_unactivated,
        disable_web_page_preview=True
    )


# Video button handlers for regular users
@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    """
    Handles the 'Videos1' button.
    """
    user_id = message.from_user.id

    has_v1_access = user_id in load_approved_users(approved_v1_col)
    requires_mandatory_check = is_post_subscribe_check_enabled()

    if not has_v1_access:
        # If no access yet (directs to activate Videos1)
        markup_for_unactivated = initial_activation_keyboard()
        activation_message_text = (
            "📢 مرحبًا عزيزي!\n\n"
            "للوصول إلى محتوى البوت، يجب أولًا تفعيل بوت التمويل.\n\n"
            "🔰 خطوات التفعيل:\n\n"
            "1️⃣ اضغط على الرابط في الأسفل للذهب إلى بوت التمويل.\n\n"
            "2️⃣ فعّل بوت التمويل واشترك في جميع القنوات المطلوبة❗️.\n\n"
            "3️⃣ بعد الاشتراك في جميع القنوات، ستصلك رسالة من بوت التمويل تؤكد تم التفعيل.\n\n"
            "4️⃣ قم بإعادة (تحويل) رسالة التفعيل إلى هنا – بدون نسخ أو تعديل.\n\n"
            "✅ بعد تحويل الرسالة سيتم قبولك تلقائيًا.\n\n"
            "👇 اضغط هنا لتفعيل بوت التمويل:\n"
            f"🔗 {FINANCE_BOT_LINK_V1}"
        )
        bot.send_message(
            user_id,
            activation_message_text,
            reply_markup=markup_for_unactivated,
            disable_web_page_preview=True
        )
    elif requires_mandatory_check and not is_currently_subscribed_to_all_mandatory_channels(user_id):
        # Has V1 access but hasn't completed mandatory subscription and check is enabled
        bot.send_message(user_id, "⚠️ يرجى إكمال الاشتراك في القنوات الإجبارية أولاً للوصول إلى فيديوهات1.")
        send_mandatory_subscription_message(user_id)
    else:
        # Has V1 access and completed mandatory subscription (or check is disabled)
        send_videos(user_id, "v1")

@bot.message_handler(func=lambda m: m.text == "فيديوهات2")
def handle_v2(message):
    """
    Handles the 'Videos2' button, now including mandatory subscription check.
    """
    user_id = message.from_user.id

    has_v2_access = user_id in load_approved_users(approved_v2_col)
    requires_mandatory_check = is_post_subscribe_check_enabled()

    if not has_v2_access:
        # If no access, show activation message for V2
        markup_for_unactivated = initial_activation_keyboard()
        activation_message_text = (
            "📢 مرحبًا عزيزي!\n\n"
            "للوصول إلى محتوى البوت، يجب أولًا تفعيل بوت التمويل.\n\n"
            "🔰 خطوات التفعيل:\n\n"
            "1️⃣ اضغط على الرابط في الأسفل للذهب إلى بوت التمويل.\n\n"
            "2️⃣ فعّل بوت التمويل واشترك في جميع القنوات المطلوبة❗️.\n\n"
            "3️⃣ بعد الاشتراك في جميع القنوات، ستصلك رسالة من بوت التمويل تؤكد تم التفعيل.\n\n"
            "4️⃣ قم بإعادة (تحويل) رسالة التفعيل إلى هنا – بدون نسخ أو تعديل.\n\n"
            "✅ بعد تحويل الرسالة سيتم قبولك تلقائيًا.\n\n"
            "👇 اضغط هنا لتفعيل بوت التمويل:\n"
            f"🔗 {FINANCE_BOT_LINK_V2}" # Use V2 finance bot link
        )
        bot.send_message(
            user_id,
            activation_message_text,
            reply_markup=markup_for_unactivated,
            disable_web_page_preview=True
        )
    elif requires_mandatory_check and not is_currently_subscribed_to_all_mandatory_channels(user_id):
        # Has V2 access but mandatory subscription check is enabled and not completed
        bot.send_message(user_id, "⚠️ يرجى إكمال الاشتراك في القنوات الإجبارية أولاً للوصول إلى فيديوهات2.")
        send_mandatory_subscription_message(user_id)
    else:
        # Has V2 access and mandatory subscription is either complete or check is disabled
        send_videos(user_id, "v2")

# Video deletion handlers (owner-specific)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_delete.get(m.from_user.id))
def handle_delete_choice(message):
    """
    Handles the owner's choice to delete a video.
    """
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
            # After deletion, send the owner inline admin keyboard again
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

# Video upload handler (owner-specific)
@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    """
    Handles video uploads from the owner.
    """
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

# Broadcast message handler (owner-specific)
@bot.message_handler(func=lambda m: waiting_for_broadcast.get("photo") and m.from_user.id == OWNER_ID, content_types=['photo'])
def receive_broadcast_photo(message):
    """
    Receives the photo for a broadcast message.
    """
    waiting_for_broadcast["photo_file_id"] = message.photo[-1].file_id
    waiting_for_broadcast["photo"] = False
    waiting_for_broadcast["awaiting_text"] = True
    bot.send_message(message.chat.id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة.")

@bot.message_handler(func=lambda m: waiting_for_broadcast.get("awaiting_text") and m.from_user.id == OWNER_ID)
def receive_broadcast_text(message):
    """
    Receives the text for a broadcast message and sends it.
    """
    if waiting_for_broadcast.get("awaiting_text"):
        photo_id = waiting_for_broadcast.get("photo_file_id")
        text = message.text
        # Include users who have completed mandatory subscription as well
        users_to_broadcast = load_approved_users(approved_v1_col).union(load_approved_users(approved_v2_col)).union(set(doc["user_id"] for doc in mandatory_subscribed_col.find()))
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

# --- Owner's Inline Callback Query Handlers ---
@bot.callback_query_handler(func=lambda call: call.from_user.id == OWNER_ID)
def owner_callback_query_handler(call):
    """
    Handles inline callback queries from the owner/admin.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    data = call.data

    # Clear any previous waiting states when navigating main menus
    owner_upload_mode.pop(user_id, None)
    waiting_for_delete.pop(user_id, None)
    waiting_for_broadcast.pop(user_id, None)
    owner_state.pop(user_id, None) # Clear owner's input state

    # No direct "main_admin_menu" here after removing the manage button, instead re-display the main panel
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

    # New broadcast button handler leads to a submenu
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

    # --- New button handlers for Mandatory Subscription section ---
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

        text = "📋 قائمة القنوات الإجبارية (أرسل معرف القناة الذي تريد حذفه):\n"
        for channel in channels:
            # Use channel.get('_id') to ensure it exists
            text += f"**ID**: `{channel.get('id', 'N/A')}` - **الرابط**: {channel.get('link', 'غير محدد')}\n"
        text += "\nالرجاء إرسال **معرف القناة (Channel ID)** الذي تريد حذفه (مثال: `-1001234567890`)."
        bot.send_message(user_id, text, parse_mode="Markdown")
        owner_state[user_id] = {"action": "await_delete_mandatory_channel_id"} # Action changed here

    elif data == "set_mandatory_message_start":
        current_message = get_mandatory_message_text()
        bot.send_message(user_id, f"الرجاء إرسال نص رسالة الاشتراك الإجباري الجديدة.\n\nالرسالة الحالية:\n`{current_message}`", parse_mode="Markdown")
        owner_state[user_id] = {"action": "await_mandatory_message_text"}

    # --- Add handlers for toggle post-subscribe check buttons ---
    elif data == "toggle_post_subscribe_check_on":
        post_subscribe_check_status_col.update_one({}, {"$set": {"enabled": True}}, upsert=True)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="✅ تم تفعيل التحقق بعد الاشتراك.",
            reply_markup=mandatory_sub_admin_keyboard() # Update keyboard to show new status
        )
    elif data == "toggle_post_subscribe_check_off":
        post_subscribe_check_status_col.update_one({}, {"$set": {"enabled": False}}, upsert=True)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ تم إيقاف التحقق بعد الاشتراك.",
            reply_markup=mandatory_sub_admin_keyboard() # Update keyboard to show new status
        )

    # --- Statistics section handlers ---
    elif data == "statistics_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="إحصائيات وإدارة المستخدمين:",
            reply_markup=statistics_admin_keyboard()
        )
    elif data == "clear_approved_users_confirm": # Confirmation button handler
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("نعم، احذف 🗑️", callback_data="clear_approved_users_execute"))
        markup.add(types.InlineKeyboardButton("إلغاء ↩️", callback_data="statistics_menu")) # Return to statistics menu
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚠️ هل أنت متأكد تمامًا من حذف جميع المستخدمين المقبولين؟ هذا سيؤدي إلى مسح جميع بياناتهم وسيحتاجون إلى إعادة التفعيل بالكامل.",
            reply_markup=markup
        )

    elif data == "clear_approved_users_execute": # Actual deletion execution handler
        approved_v1_col.delete_many({})
        approved_v2_col.delete_many({})
        notified_users_col.delete_many({})
        mandatory_subscribed_col.delete_many({})
        user_mandatory_progress_col.delete_many({}) # Clear mandatory subscription progress as well

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

# --- New button handler "I have activated the bot" ---
@bot.callback_query_handler(func=lambda call: call.data == "activated_bot_check")
def handle_activated_bot_check_callback(call):
    """
    Handles the callback when a user claims they have activated the bot.
    """
    bot.answer_callback_query(call.id, "جار التحقق من تفعيلك...")
    user_id = call.from_user.id

    # Message to guide the user to forward the activation message
    bot.send_message(
        user_id,
        "لقبول تفعيلك، يرجى **إعادة توجيه** رسالة التفعيل التي استلمتها من بوت التمويل إليّ مباشرة. تأكد أنها الرسالة الأصلية وليست منسوخة.",
        parse_mode="Markdown"
    )
    # You can update the original message containing the button to prevent repeated presses
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None # Remove the button after pressing
    )


# --- Owner's input handlers for "Mandatory Subscription" ---

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and owner_state.get(m.from_user.id, {}).get("action") == "await_mandatory_channel_link_only")
def handle_await_mandatory_channel_link_only(message):
    """
    Handles adding a mandatory channel by link.
    """
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
            # Get the current count of mandatory channels to set the 'order'
            current_channels_count = mandatory_channels_col.count_documents({})
            mandatory_channels_col.insert_one({"id": channel_id, "link": channel_link, "order": current_channels_count})
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

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and owner_state.get(m.from_user.id, {}).get("action") == "await_delete_mandatory_channel_id")
def handle_await_delete_mandatory_channel_id(message):
    """
    Handles deleting a mandatory channel by its ID.
    """
    user_id = message.from_user.id
    channel_id_to_delete_str = message.text.strip()

    try:
        channel_id_to_delete = int(channel_id_to_delete_str) # Convert to integer

        # Search for the channel by the entered ID
        result = mandatory_channels_col.delete_one({"id": channel_id_to_delete})

        if result.deleted_count > 0:
            bot.send_message(user_id, f"✅ تم حذف القناة `{channel_id_to_delete}` بنجاح.", parse_mode="Markdown")
            # Re-order remaining channels
            channels = list(mandatory_channels_col.find({}).sort("order", 1))
            for i, channel in enumerate(channels):
                mandatory_channels_col.update_one({"_id": channel["_id"]}, {"$set": {"order": i}})
        else:
            bot.send_message(user_id, f"❌ لم يتم العثور على قناة بالمعرف `{channel_id_to_delete}`. يرجى التأكد من المعرف.", parse_mode="Markdown")

    except ValueError:
        bot.send_message(user_id, "❌ معرف القناة يجب أن يكون رقمًا. يرجى إدخال معرف رقمي صالح (مثال: -1001234567890).", reply_markup=types.ReplyKeyboardRemove())
    except Exception as e:
        bot.send_message(user_id, f"❌ حدث خطأ أثناء حذف القناة: {e}. يرجى المحاولة مرة أخرى.", reply_markup=types.ReplyKeyboardRemove())

    # After any deletion or error, return the user to the main menu
    owner_state.pop(user_id)
    bot.send_message(
        user_id,
        "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
        reply_markup=owner_inline_keyboard()
    )


@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and owner_state.get(m.from_user.id, {}).get("action") == "await_mandatory_message_text")
def handle_await_mandatory_message_text(message):
    """
    Handles setting the mandatory subscription message text.
    """
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

# --- Flask Web Server to run the bot on Render + UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    """
    Flask route for the home page.
    """
    return "Bot is running"

def run():
    """
    Runs the Flask application.
    """
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    """
    Starts a thread to keep the Flask application running.
    """
    t = Thread(target=run)
    t.start()

keep_alive()
bot.infinity_polling()
