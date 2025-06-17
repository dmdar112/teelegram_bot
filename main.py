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

waiting_for_delete = {} # لتتبع الفيديوهات المعروضة للحذف
true_sub_pending = {}  # {user_id: step} - لتتبع تقدم المستخدم في الاشتراك الإجباري الحقيقي

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

# هذه هي قنوات الاشتراك الإجباري الحقيقي التي يجب على المستخدم الاشتراك بها أولاً
true_subscribe_links = [
    "https://t.me/BLACK_ROOT1",
    "https://t.me/SNOKER_VIP",
    "https://t.me/R2M199"
]

pending_check = {} # لتتبع تقدم المستخدم في الاشتراكات الاختيارية (فيديوهات1/2)
owner_upload_mode = {} # لتحديد القسم الذي يرفع فيه المالك الفيديوهات
waiting_for_broadcast = {} # لتتبع حالة إرسال الرسائل الجماعية

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
    """إنشاء لوحة المفاتيح الرئيسية للمستخدم العادي (Reply Keyboard)."""
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

def owner_inline_keyboard():
    """إنشاء لوحة مفاتيح المالك بأزرار تحكم شفافة (Inline Keyboard)."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("عرض فيديوهات1", callback_data="owner_action_view_v1"),
        types.InlineKeyboardButton("عرض فيديوهات2", callback_data="owner_action_view_v2"),
        types.InlineKeyboardButton("حذف فيديوهات1", callback_data="owner_action_delete_menu_v1"),
        types.InlineKeyboardButton("حذف فيديوهات2", callback_data="owner_action_delete_menu_v2"),
        types.InlineKeyboardButton("رفع لـ فيديوهات1", callback_data="owner_action_upload_mode_v1"),
        types.InlineKeyboardButton("رفع لـ فيديوهات2", callback_data="owner_action_upload_mode_v2"),
        types.InlineKeyboardButton("تنظيف فيديوهات1", callback_data="owner_action_clean_v1"),
        types.InlineKeyboardButton("تنظيف فيديوهات2", callback_data="owner_action_clean_v2"),
        types.InlineKeyboardButton("تفعيل صيانة فيديوهات2", callback_data="owner_action_maintenance_on_v2"),
        types.InlineKeyboardButton("إيقاف صيانة فيديوهات2", callback_data="owner_action_maintenance_off_v2"),
        types.InlineKeyboardButton("رسالة جماعية مع صورة", callback_data="owner_action_broadcast_photo")
    )
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
            time.sleep(0.5)  # لمنع الحظر أو التقييد
        except Exception as e:
            print(f"❌ خطأ أثناء إرسال الفيديو للمستخدم {user_id}: {e}")
            # يمكن إضافة منطق لإزالة الفيديو من DB إذا لم يعد موجوداً في القناة
            pass

# --- دوال وإجراءات المالك باستخدام Inline Keyboard ---

def send_delete_menu_inline(user_id, category):
    """إرسال قائمة الفيديوهات للحذف للمالك باستخدام Inline Keyboard."""
    db_videos_col = db[f"videos_{category}"]
    videos = list(db_videos_col.find().limit(20)) # عرض 20 فيديو كحد أقصى

    if not videos:
        bot.send_message(user_id, f"لا يوجد فيديوهات في فيديوهات{category[-1]} للحذف.", reply_markup=owner_inline_keyboard())
        return

    text = f"📋 قائمة فيديوهات{category[-1]} للحذف (أرسل رقم الفيديو):\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nالرجاء إرسال رقم الفيديو الذي تريد حذفه."

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="owner_action_main_menu"))

    bot.send_message(user_id, text, reply_markup=markup)
    waiting_for_delete[user_id] = {"category": category, "videos": videos}

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.text.isdigit() and m.from_user.id in waiting_for_delete)
def handle_delete_choice_inline(message):
    """معالج لاختيار الفيديو المراد حذفه من قبل المالك (بعد استخدام Inline Keyboard)."""
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

            try:
                # حذف الرسالة من القناة
                bot.delete_message(chat_id, message_id)
                # حذف السجل من قاعدة البيانات
                db_videos_col = db[f"videos_{category}"]
                db_videos_col.delete_one({"message_id": message_id})
                bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} بنجاح.", reply_markup=owner_inline_keyboard())
            except Exception as e:
                bot.send_message(user_id, f"❌ فشل حذف الفيديو من القناة. قد يكون الفيديو غير موجود: {e}", reply_markup=owner_inline_keyboard())
            finally:
                waiting_for_delete.pop(user_id)

        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.")

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.", reply_markup=owner_inline_keyboard()) # نُعيد الأزرار الرئيسية في حال خطأ


# معالج زر "تنظيف فيديوهات1" (يمكن إعادة استخدامه، سيتم استدعاؤه من الكولباك)
def clean_videos_v1_action(user_id):
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

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات1. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_inline_keyboard())

# معالج زر "تنظيف فيديوهات2" (يمكن إعادة استخدامه، سيتم استدعاؤه من الكولباك)
def clean_videos_v2_action(user_id):
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

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات2. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_inline_keyboard())


# --- معالج Callbacks للمالك ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("owner_action_") and call.from_user.id == OWNER_ID)
def handle_owner_inline_actions(call):
    bot.answer_callback_query(call.id) # يزيل حالة التحميل من الزر في واجهة المستخدم
    user_id = call.from_user.id
    action = call.data.replace("owner_action_", "")

    if action == "view_v1":
        send_videos(user_id, "v1")
        bot.send_message(user_id, "أنت الآن في قسم فيديوهات1. اختر إجراء آخر:", reply_markup=owner_inline_keyboard())
    elif action == "view_v2":
        send_videos(user_id, "v2")
        bot.send_message(user_id, "أنت الآن في قسم فيديوهات2. اختر إجراء آخر:", reply_markup=owner_inline_keyboard())
    elif action == "delete_menu_v1":
        send_delete_menu_inline(user_id, "v1")
    elif action == "delete_menu_v2":
        send_delete_menu_inline(user_id, "v2")
    elif action == "upload_mode_v1":
        owner_upload_mode[user_id] = 'v1'
        bot.send_message(user_id, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات1. أرسل الفيديو الآن.")
    elif action == "upload_mode_v2":
        owner_upload_mode[user_id] = 'v2'
        bot.send_message(user_id, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات2. أرسل الفيديو الآن.")
    elif action == "clean_v1":
        clean_videos_v1_action(user_id)
    elif action == "clean_v2":
        clean_videos_v2_action(user_id)
    elif action == "maintenance_on_v2":
        global maintenance_mode
        maintenance_mode = True
        bot.send_message(user_id, "✅ تم تفعيل وضع الصيانة لـ فيديوهات2.", reply_markup=owner_inline_keyboard())
    elif action == "maintenance_off_v2":
        global maintenance_mode
        maintenance_mode = False
        bot.send_message(user_id, "✅ تم إيقاف وضع الصيانة لـ فيديوهات2.", reply_markup=owner_inline_keyboard())
    elif action == "broadcast_photo":
        bot.send_message(user_id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.")
        waiting_for_broadcast["photo"] = True
    elif action == "main_menu": # للعودة من قوائم فرعية
        if user_id in waiting_for_delete:
            waiting_for_delete.pop(user_id)
        bot.send_message(user_id, "تم الرجوع إلى القائمة الرئيسية للمالك:", reply_markup=owner_inline_keyboard())


def check_true_subscription(user_id, first_name):
    """
    يقوم بالتحقق من جميع قنوات true_subscribe_links بشكل متسلسل
    ويدفع المستخدم للاشتراك في القناة التالية إذا لم يكن مشتركًا.
    """
    step = true_sub_pending.get(user_id, 0)
    
    # التأكد أن خطوة البداية لا تتجاوز عدد القنوات المتاحة
    if step >= len(true_subscribe_links):
        step = 0

    all_channels_subscribed = True
    for index in range(step, len(true_subscribe_links)):
        current_channel_link = true_subscribe_links[index]
        try:
            channel_identifier = current_channel_link.split("t.me/")[-1]
            
            if not channel_identifier.startswith('+'): # قناة عامة @username
                channel_username = f"@{channel_identifier}" if not channel_identifier.startswith('@') else channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    all_channels_subscribed = False
                    true_sub_pending[user_id] = index # احفظ الخطوة التي توقف عندها
                    text = (
                        "🔔 لطفاً اشترك في القناة التالية واضغط على الزر أدناه للمتابعة:\n"
                        f"📮: {current_channel_link}"
                    )
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
                    bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                    return
            else: # رابط دعوة خاص (يبدأ بـ +)
                # لا يمكن التحقق من الاشتراك في الروابط الخاصة إلا إذا كان البوت مشرفًا
                # سنعتبر أن المستخدم يجب أن يضغط على الرابط ثم يعود ليتحقق عبر الزر.
                all_channels_subscribed = False
                true_sub_pending[user_id] = index
                text = (
                    "🔔 لطفاً اشترك في القناة التالية واضغط على الزر أدناه للمتابعة:\n"
                    f"📮: {current_channel_link}"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
                bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                return
            
            true_sub_pending[user_id] = index + 1

        except Exception as e:
            print(f"❌ Error checking channel {current_channel_link} for user {user_id}: {e}")
            all_channels_subscribed = False
            true_sub_pending[user_id] = index
            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة: {current_channel_link}.\n"
                "يرجى التأكد أنك مشترك وأن البوت مشرف في القناة، ثم حاول الضغط على الزر مرة أخرى."
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
            bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
            return

    if all_channels_subscribed:
        if user_id in true_sub_pending:
            del true_sub_pending[user_id]
        
        user_data_db = users_col.find_one({"user_id": user_id})
        if not user_data_db:
            users_col.insert_one({"user_id": user_id, "joined": True, "first_name": first_name})
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": True, "first_name": first_name}})

        send_start_welcome_message(user_id, first_name)
    else:
        user_data_db = users_col.find_one({"user_id": user_id})
        if user_data_db and user_data_db.get("joined", False):
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": False}})


@bot.message_handler(commands=['start'])
def handle_start(message):
    """معالج لأمر /start للتحقق من الاشتراك."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم جديد"

    # إذا كان المستخدم هو المالك، أظهر لوحة مفاتيح المالك الشفافة مباشرة
    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحباً مالك البوت، اختر الإجراء:", reply_markup=owner_inline_keyboard())
        return

    # لكل المستخدمين الآخرين، ابدأ عملية التحقق من الاشتراك الإجباري
    bot.send_message(user_id, "أهلاً بك! يرجى إكمال الاشتراك في القنوات الإجبارية للوصول إلى البوت.", reply_markup=types.ReplyKeyboardRemove())
    check_true_subscription(user_id, first_name)


def send_start_welcome_message(user_id, first_name):
    """المنطق الفعلي لدالة /start بعد التحقق من الاشتراك في القنوات الإجبارية."""
    bot.send_message(user_id, f"""🔞 مرحباً بك ( {first_name} ) 🏳‍🌈
📂اختر قسم الفيديوهات من الأزرار بالأسفل!

⚠️ المحتوى +18 - للكبار فقط!""", reply_markup=main_keyboard())

    if not has_notified(user_id):
        total_users = users_col.count_documents({"joined": True}) # عدّ فقط المستخدمين الذين اجتازوا الاشتراك الإجباري
        bot.send_message(OWNER_ID, f"""👾 تم دخول شخص جديد إلى البوت الخاص بك

• الاسم : {first_name}
• الايدي : {user_id}
• عدد الأعضاء الكلي: {total_users}
""")
        add_notified_user(user_id)


@bot.callback_query_handler(func=lambda call: call.data == "check_true_subscription")
def handle_check_true_subscription_callback(call):
    """
    معالج لـ callback_data "check_true_subscription"
    التي تُرسل عند الضغط على زر "لقد اشتركت، اضغط هنا للمتابعة".
    """
    bot.answer_callback_query(call.id, "جاري التحقق من اشتراكك...")
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم"
    check_true_subscription(user_id, first_name)


@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    """معالج لزر فيديوهات1."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name)
        return

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

@bot.message_handler(func=lambda m: m.text == "فيديوهات2")
def handle_v2(message):
    """معالج لزر فيديوهات2 مع التحقق من وضع الصيانة."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name)
        return

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
    """إرسال روابط الاشتراك المطلوبة."""
    data = pending_check.get(chat_id, {"category": category, "step": 0})
    step = data["step"]
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    if step >= len(links):
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة. الرجاء الانتظار.", reply_markup=main_keyboard())
        pending_check.pop(chat_id, None)
        return

    link = links[step]

    text = f"""- لطفاً اشترك بالقناة واضغط على الزر أدناه للمتابعة .
- قناة البوت 👾.👇🏻
📬:  {link}
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👾 تحقق الانْ بعد الاشتراك 👾", callback_data=f"verify_{category}_{step}"))
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

    pending_check[chat_id] = {"category": category, "step": step}

@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    """معالج للتحقق من الاشتراك عبر الأزرار."""
    bot.answer_callback_query(call.id)

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
    """إعادة إرسال روابط الاشتراك عند طلب المستخدم."""
    bot.answer_callback_query(call.id)

    user_id = call.from_user.id
    category = call.data.split("_")[1]
    pending_check[user_id] = {"category": category, "step": 0}
    send_required_links(user_id, category)

def notify_owner_for_approval(user_id, name, category):
    """إرسال إشعار للمالك بطلب انضمام جديد."""
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
    """معالج لاستجابة المالك (قبول أو رفض)."""
    parts = call.data.split("_")
    action, category, user_id = parts[0], parts[1], int(parts[2])

    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🚫 غير مصرح لك بالقيام بهذا الإجراء.")
        return

    bot.answer_callback_query(call.id) # إخفاء حالة التحميل من الزر

    if action == "approve":
        if category == "v1":
            add_approved_user(approved_v1_col, user_id)
        else:
            add_approved_user(approved_v2_col, user_id)
        bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة! يمكنك الآن استخدام البوت بكل المزايا.", reply_markup=main_keyboard())
        bot.edit_message_text("✅ تم قبول المستخدم.", call.message.chat.id, call.message.message_id)
    else:
        bot.send_message(user_id, "❌ لم يتم قبولك. الرجاء الاشتراك في جميع قنوات البوت ثم أرسل /start مرة أخرى.", reply_markup=types.ReplyKeyboardRemove())
        bot.edit_message_text("❌ تم رفض المستخدم.", call.message.chat.id, call.message.message_id)


@bot.message_handler(content_types=['video'], func=lambda m: m.from_user.id == OWNER_ID and owner_upload_mode.get(m.from_user.id))
def handle_video_upload(message):
    """معالج لرفع الفيديوهات من قبل المالك."""
    user_id = message.from_user.id
    mode = owner_upload_mode.get(user_id)

    if not mode: # للتأكد، بالرغم من أن الـ func تضمن ذلك
        return

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

        bot.reply_to(message, f"✅ تم حفظ الفيديو في قسم {mode.upper()}.", reply_markup=owner_inline_keyboard())
        owner_upload_mode.pop(user_id) # إنهاء وضع الرفع بعد الفيديو
    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو.", reply_markup=owner_inline_keyboard())
        owner_upload_mode.pop(user_id, None)

@bot.message_handler(content_types=['photo'], func=lambda m: waiting_for_broadcast.get("photo") and m.from_user.id == OWNER_ID)
def receive_broadcast_photo(message):
    """استقبال الصورة للرسالة الجماعية."""
    waiting_for_broadcast["photo_file_id"] = message.photo[-1].file_id
    waiting_for_broadcast["photo"] = False
    waiting_for_broadcast["awaiting_text"] = True
    bot.send_message(message.chat.id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة.")

@bot.message_handler(func=lambda m: waiting_for_broadcast.get("awaiting_text") and m.from_user.id == OWNER_ID)
def receive_broadcast_text(message):
    """استقبال نص الرسالة الجماعية وإرسالها."""
    photo_id = waiting_for_broadcast.get("photo_file_id")
    text = message.text
    users = get_all_approved_users() # إرسال للكل، ليس فقط الموافق عليهم للاقسام
    sent_count = 0
    for user_id in users:
        try:
            bot.send_photo(user_id, photo_id, caption=text)
            sent_count += 1
            time.sleep(0.1) # تأخير بسيط لتجنب التقييد
        except Exception as e:
            print(f"Error sending broadcast to {user_id}: {e}")
            pass
    bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.", reply_markup=owner_inline_keyboard())
    waiting_for_broadcast.clear()


# --- Flask Web Server لتشغيل البوت على Render + UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    """المسار الرئيسي للخادم الويب."""
    return "Bot is running"

def run():
    """تشغيل خادم الويب."""
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    """تشغيل الخادم في موضوع منفصل."""
    t = Thread(target=run)
    t.start()

keep_alive()
bot.infinity_polling()

