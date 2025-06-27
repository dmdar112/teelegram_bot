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


# --- إعداد MongoDB ---
MONGODB_URI = os.environ.get("MONGODB_URI")
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"] 
approved_v2_col = db["approved_v2"] 
notified_users_col = db["notified_users"]


# --- الحالات المؤقتة ---
owner_upload_mode = {}
waiting_for_broadcast = {}
waiting_for_delete = {}
# هذه المتغيرات لم تعد بحاجة لأن تكون عامة، سيتم تمريرها كـ user_data في Inline Keyboard
# waiting_for_v2_add_id = {}


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
    # هذه هي لوحة المفاتيح للمستخدمين العاديين
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

# --- لوحة مفاتيح المالك الشفافة الجديدة ---
def owner_inline_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    # قسم إدارة الفيديوهات
    markup.add(types.InlineKeyboardButton("الإدارة 📂", callback_data="admin_menu"))
    markup.add(
        types.InlineKeyboardButton("فيديوهات1 ▶️", callback_data="manage_v1"),
        types.InlineKeyboardButton("فيديوهات2 ▶️", callback_data="manage_v2")
    )
    # قسم إدارة الإذاعة
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


# --- معالجات الأوامر والرسائل ---

# معالج رسائل التفعيل (V1 و V2)
@bot.message_handler(func=lambda m: (m.text and ACTIVATION_PHRASE_V1 in m.text) or (m.text and ACTIVATION_PHRASE_V2 in m.text))
def handle_activation_messages(message):
    user_id = message.from_user.id
    message_text = message.text if message.text else ""

    if ACTIVATION_PHRASE_V1 in message_text:
        if user_id not in load_approved_users(approved_v1_col):
            add_approved_user(approved_v1_col, user_id) 
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✅ User {user_id} granted V1 access.")
            bot.send_message(user_id, "✅ تم تفعيل وصولك إلى **فيديوهات1** بنجاح! يمكنك الآن الضغط على زر **فيديوهات1**.", reply_markup=main_keyboard())
        else:
            bot.send_message(user_id, "👍🏼 لديك بالفعل وصول إلى فيديوهات1.", reply_markup=main_keyboard())
        return

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

    has_any_access = user_id in load_approved_users(approved_v1_col) or user_id in load_approved_users(approved_v2_col)

    if user_id == OWNER_ID:
        # للمالك، نرسل لوحة التحكم الشفافة
        bot.send_message(
            user_id,
            "أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
        # إزالة لوحة المفاتيح السفلية إذا كانت موجودة
        bot.send_message(user_id, "✅ تم تحديث لوحة التحكم.", reply_markup=types.ReplyKeyboardRemove())
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
        bot.send_message(
            user_id,
            "🚫 مرحباً بك! للوصول إلى محتوى البوت، يرجى تفعيل **فيديوهات1** أولاً.\n"
            f"للتفعيل، يرجى الدخول إلى بوت التمويل الخاص بنا عبر هذا الرابط:\n{FINANCE_BOT_LINK_V1}\n\n"
            "ثم أكمل عملية الدخول وقم بإعادة توجيه رسالة التفعيل التي ستصلك إليّ.\n"
            f"✅ يجب أن تحتوي رسالة التفعيل على العبارة: '{ACTIVATION_PHRASE_V1}'.",
            reply_markup=types.ReplyKeyboardRemove(),
            disable_web_page_preview=True
        )


# معالج لرسائل المستخدمين غير المفعلين (غير المالك)
@bot.message_handler(func=lambda m: m.from_user.id != OWNER_ID and not (m.text and (ACTIVATION_PHRASE_V1 in m.text or ACTIVATION_PHRASE_V2 in m.text)) and not (m.text == "فيديوهات1" or m.text == "فيديوهات2"))
def handle_unactivated_user_messages(message):
    user_id = message.from_user.id
    has_any_access = user_id in load_approved_users(approved_v1_col) or user_id in load_approved_users(approved_v2_col)

    if not has_any_access:
        bot.send_message(
            user_id,
            "🚫 يرجى تفعيل البوت أولاً للوصول إلى المحتوى.\n"
            f"للتفعيل، يرجى الدخول إلى بوت التمويل الخاص بنا عبر هذا الرابط:\n{FINANCE_BOT_LINK_V1}\n\n"
            "ثم أكمل عملية الدخول وقم بإعادة توجيه رسالة التفعيل التي ستصلك إليّ.\n"
            f"✅ يجب أن تحتوي رسالة التفعيل على العبارة: '{ACTIVATION_PHRASE_V1}'.",
            reply_markup=types.ReplyKeyboardRemove(),
            disable_web_page_preview=True
        )
    else:
        # إذا كان مفعلاً ولكن أرسل شيئاً غير الأزرار
        bot.send_message(user_id, "لم أفهم طلبك. الرجاء استخدام الأزرار في الأسفل.", reply_markup=main_keyboard())


# معالجات أزرار الفيديوهات للمستخدمين العاديين (لم تتغير)
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

# --- معالجات الـ Inline Callback Query للمالك ---
@bot.callback_query_handler(func=lambda call: call.from_user.id == OWNER_ID)
def owner_callback_query_handler(call):
    bot.answer_callback_query(call.id) # إخفاء رسالة "جار التحميل"

    user_id = call.from_user.id
    data = call.data

    if data == "main_admin_menu":
        # العودة إلى القائمة الرئيسية للأدمن
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="أهلاً بك في لوحة الأدمن الخاصة بالبوت 🤖\n\n- يمكنك التحكم في البوت الخاص بك من هنا",
            reply_markup=owner_inline_keyboard()
        )
        # مسح أي حالات انتظار خاصة بالمالك
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
        # لا نعدل الرسالة الأصلية هنا لأننا نطلب ملف

    elif data.startswith("delete_video_"):
        category = data.split("_")[2]
        db_videos_col = db[f"videos_{category}"]
        videos = list(db_videos_col.find().limit(20)) # عرض أول 20 فيديو للحذف

        if not videos:
            bot.send_message(user_id, f"لا يوجد فيديوهات حالياً في قسم {category.upper()} لحذفها.")
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=manage_videos_keyboard(category)
            ) # لإعادة إظهار الأزرار بعد الرسالة
            return
        
        text = f"📋 قائمة فيديوهات {category.upper()}:\n"
        for i, vid in enumerate(videos, 1):
            text += f"{i}. رسالة رقم: {vid['message_id']}\n"
        text += "\nأرسل رقم الفيديو الذي تريد حذفه."
        bot.send_message(user_id, text)
        waiting_for_delete[user_id] = {"category": category, "videos": videos}
        # لا نعدل الرسالة الأصلية هنا لأننا نطلب رقم

    elif data == "broadcast_photo":
        waiting_for_broadcast["photo"] = True
        bot.send_message(user_id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.")


# معالجات حذف الفيديوهات (الآن تستقبل الأرقام من المالك بعد الضغط على الزر الشفاف)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_delete.get(m.from_user.id))
def handle_delete_choice(message):
    user_id = message.from_user.id
    data = waiting_for_delete.get(user_id)
    if not data: return # يجب أن يكون هناك بيانات حذف معلقة
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
        owner_upload_mode.pop(user_id) # مسح حالة الرفع بعد الانتهاء
        # بعد الرفع، نرسل له لوحة الأدمن الشفافة مرة أخرى
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
        for user_id_to_send in users_to_broadcast: # changed variable name to avoid conflict with `user_id` from message
            try:
                bot.send_photo(user_id_to_send, photo_id, caption=text)
                sent_count += 1
            except Exception as e:
                print(f"Failed to send broadcast to {user_id_to_send}: {e}")
                pass # تجاهل المستخدمين الذين لا يمكن إرسال رسالة إليهم
        bot.send_message(OWNER_ID, f"✅ تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.", reply_markup=types.ReplyKeyboardRemove())
        waiting_for_broadcast.clear()
        # بعد الإذاعة، نرسل له لوحة الأدمن الشفافة مرة أخرى
        bot.send_message(
            OWNER_ID,
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
