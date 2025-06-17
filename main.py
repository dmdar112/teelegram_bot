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
true_sub_pending = {}  # {user_id: step} - لتتبع تقدم المستخدم في الاشتراك الإجباري الحقيقي

# متغيرات جديدة لإدارة القنوات (القنوات الاختيارية + الإجبارية)
waiting_for_channel_link = {} # يستخدم لإضافة قنوات الاشتراك الإجباري
waiting_for_channel_to_delete = {} # يستخدم لحذف قنوات الاشتراك الإجباري

waiting_for_optional_link = {} # {user_id: category} - لإضافة قنوات فيديوهات1/2
waiting_for_optional_delete = {} # {user_id: category} - لحذف قنوات فيديوهات1/2


MONGODB_URI = os.environ.get("MONGODB_URI")

# إعداد MongoDB
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

users_col = db["users"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"]
approved_v2_col = db["approved_v2"]
notified_users_col = db["notified_users"]
true_subscribe_channels_col = db["true_subscribe_channels"] # المجموعة لقنوات الاشتراك الإجباري

# مجموعات جديدة لقنوات الاشتراك الاختياري (فيديوهات1 و فيديوهات2)
optional_subscribe_channels_v1_col = db["optional_subscribe_channels_v1"]
optional_subscribe_channels_v2_col = db["optional_subscribe_channels_v2"]


# تحميل قنوات الاشتراك الإجباري من قاعدة البيانات عند بدء البوت
def load_true_subscribe_links():
    """تحميل روابط قنوات الاشتراك الإجباري من قاعدة البيانات."""
    links = [doc["link"] for doc in true_subscribe_channels_col.find()]
    return links

# تحميل قنوات الاشتراك الاختياري لفيديوهات1 من قاعدة البيانات
def load_subscribe_links_v1():
    """تحميل روابط قنوات الاشتراك الاختياري لفيديوهات1 من قاعدة البيانات."""
    links = [doc["link"] for doc in optional_subscribe_channels_v1_col.find()]
    return links

# تحميل قنوات الاشتراك الاختياري لفيديوهات2 من قاعدة البيانات
def load_subscribe_links_v2():
    """تحميل روابط قنوات الاشتراك الاختياري لفيديوهات2 من قاعدة البيانات."""
    links = [doc["link"] for doc in optional_subscribe_channels_v2_col.find()]
    return links


true_subscribe_links = load_true_subscribe_links() # قم بتحميلها هنا عند بدء البوت
subscribe_links_v1 = load_subscribe_links_v1()
subscribe_links_v2 = load_subscribe_links_v2()


pending_check = {} # لتتبع تقدم المستخدم في الاشتراكات الاختيارية (فيديوهات1/2)
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
    """إنشاء لوحة مفاتيح المالك مع أزرار التحكم."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("فيديوهات1", "فيديوهات2") # هذه الأزرار ستعرض قائمة إدارة للمالك الآن
    markup.row("حذف فيديوهات1", "حذف فيديوهات2")
    markup.row("رفع فيديوهات1", "رفع فيديوهات2")
    markup.row("تنظيف فيديوهات1", "تنظيف فيديوهات2")
    markup.row("تفعيل صيانة فيديوهات2", "إيقاف صيانة فيديوهات2")
    markup.row("رسالة جماعية مع صورة")
    markup.row("إدارة قنوات الاشتراك الإجباري") # زر واحد لإدارة قنوات true_subscribe_links
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


@bot.message_handler(func=lambda m: m.text == "رجوع" and (m.from_user.id in waiting_for_delete or \
                                                         m.from_user.id in waiting_for_channel_to_delete or \
                                                         m.from_user.id in waiting_for_channel_link or \
                                                         m.from_user.id in waiting_for_optional_link or \
                                                         m.from_user.id in waiting_for_optional_delete))
def handle_back_command(message):
    """معالج لزر الرجوع أثناء عملية الحذف أو إدارة القنوات."""
    user_id = message.from_user.id

    # إزالة المستخدم من قوائم الانتظار المختلفة
    if user_id in waiting_for_delete:
        waiting_for_delete.pop(user_id)
    if user_id in waiting_for_channel_to_delete:
        waiting_for_channel_to_delete.pop(user_id)
    if user_id in waiting_for_channel_link:
        waiting_for_channel_link.pop(user_id)
    if user_id in waiting_for_optional_link:
        waiting_for_optional_link.pop(user_id)
    if user_id in waiting_for_optional_delete:
        waiting_for_optional_delete.pop(user_id)

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

def check_true_subscription(user_id, first_name):
    """
    يقوم بالتحقق من جميع قنوات true_subscribe_links بشكل متسلسل
    ويدفع المستخدم للاشتراك في القناة التالية إذا لم يكن مشتركًا.
    """
    global true_subscribe_links # تأكد من استخدام أحدث قائمة
    true_subscribe_links = load_true_subscribe_links() # إعادة تحميل في كل مرة للتحقق من التحديثات

    if not true_subscribe_links: # إذا لم تكن هناك قنوات اشتراك إجباري معرفة
        send_start_welcome_message(user_id, first_name)
        return

    # تهيئة الخطوة الحالية: إذا لم يكن المستخدم موجودًا في true_sub_pending، ابدأ من 0
    step = true_sub_pending.get(user_id, 0)
    
    # التأكد أن خطوة البداية لا تتجاوز عدد القنوات المتاحة
    if step >= len(true_subscribe_links):
        step = 0 # أعد تعيينها لتبدأ من البداية إذا كان قد أكملها

    all_channels_subscribed = True
    for index in range(step, len(true_subscribe_links)):
        current_channel_link = true_subscribe_links[index]
        try:
            channel_identifier = current_channel_link.split("t.me/")[-1]
            
            # في حال كانت القناة عامة (@username)
            if not channel_identifier.startswith('+'):
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
                    return # توقف هنا وانتظر تفاعل المستخدم
            else: # رابط دعوة خاص (يبدأ بـ +)
                all_channels_subscribed = False
                true_sub_pending[user_id] = index # احفظ الخطوة
                text = (
                    "🔔 لطفاً اشترك في القناة التالية واضغط على الزر أدناه للمتابعة:\n"
                    f"📮: {current_channel_link}"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
                bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                return # توقف هنا وانتظر تفاعل المستخدم
            
            # إذا كان مشتركًا أو تم تجاوز فحص القناة الخاصة بنجاح، استمر في الحلقة
            true_sub_pending[user_id] = index + 1 # تحديث الخطوة للقناة التالية

        except Exception as e:
            print(f"❌ Error checking channel {current_channel_link} for user {user_id}: {e}")
            all_channels_subscribed = False
            true_sub_pending[user_id] = index # ابقَ على نفس الخطوة ليحاول مرة أخرى
            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة: {current_channel_link}.\n"
                "يرجى التأكد أنك مشترك وأن البوت مشرف في القناة (إذا كانت خاصة)، ثم حاول الضغط على الزر مرة أخرى."
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
            bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
            return # توقف هنا

    # إذا وصل الكود إلى هنا، فهذا يعني أن المستخدم مشترك في جميع القنوات بنجاح
    if all_channels_subscribed:
        if user_id in true_sub_pending:
            del true_sub_pending[user_id] # إزالة المستخدم بعد اكتمال التحقق
        
        # تحديث حالة الاشتراك في قاعدة البيانات
        user_data_db = users_col.find_one({"user_id": user_id})
        if not user_data_db:
            users_col.insert_one({"user_id": user_id, "joined": True, "first_name": first_name})
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": True, "first_name": first_name}})

        # استدعاء المنطق الفعلي بعد التحقق
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

    # إذا كان المستخدم هو المالك، أظهر لوحة مفاتيح المالك مباشرة
    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
        return

    # لكل المستخدمين الآخرين، ابدأ عملية التحقق من الاشتراك الإجباري
    bot.send_message(user_id, "أهلاً بك! يرجى إكمال الاشتراك في القنوات الإجبارية للوصول إلى البوت.", reply_markup=types.ReplyKeyboardRemove())
    check_true_subscription(user_id, first_name)


def send_start_welcome_message(user_id, first_name):
    """المنطق الفعلي لدالة /start بعد التحقق من الاشتراك في القنوات الإجبارية."""
    # تأكدنا بالفعل من أن المستخدم ليس المالك في handle_start
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


@bot.callback_query_handler(func=lambda call: call.data == "check_true_subscription")
def handle_check_true_subscription_callback(call):
    """
    معالج لـ callback_data "check_true_subscription"
    التي تُرسل عند الضغط على زر "لقد اشتركت، اضغط هنا للمتابعة".
    """
    bot.answer_callback_query(call.id, "جاري التحقق من اشتراكك...")
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم" # نحصل على الاسم من الكول باك
    check_true_subscription(user_id, first_name)


@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    """معالج لزر فيديوهات1."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    # لو المالك ضغط على زر فيديوهات1، اعرض له قائمة إدارة القنوات الخاصة بفيديوهات1
    if user_id == OWNER_ID:
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("إضافة قناة", callback_data="manage_optional_v1_add"),
            types.InlineKeyboardButton("حذف قناة", callback_data="manage_optional_v1_delete")
        )
        markup.row(
            types.InlineKeyboardButton("عرض القنوات", callback_data="manage_optional_v1_view"),
            types.InlineKeyboardButton("عرض الفيديوهات", callback_data="manage_optional_v1_show_videos")
        )
        bot.send_message(user_id, "أنت المالك. اختر إجراءً لإدارة قنوات فيديوهات1:", reply_markup=markup)
        return

    # للمستخدمين العاديين، استمر بالمنطق الحالي
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

    # لو المالك ضغط على زر فيديوهات2، اعرض له قائمة إدارة القنوات الخاصة بفيديوهات2
    if user_id == OWNER_ID:
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("إضافة قناة", callback_data="manage_optional_v2_add"),
            types.InlineKeyboardButton("حذف قناة", callback_data="manage_optional_v2_delete")
        )
        markup.row(
            types.InlineKeyboardButton("عرض القنوات", callback_data="manage_optional_v2_view"),
            types.InlineKeyboardButton("عرض الفيديوهات", callback_data="manage_optional_v2_show_videos")
        )
        bot.send_message(user_id, "أنت المالك. اختر إجراءً لإدارة قنوات فيديوهات2:", reply_markup=markup)
        return

    # للمستخدمين العاديين، استمر بالمنطق الحالي
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
    global subscribe_links_v1, subscribe_links_v2 # تأكد من استخدام أحدث قائمة
    subscribe_links_v1 = load_subscribe_links_v1()
    subscribe_links_v2 = load_subscribe_links_v2()

    data = pending_check.get(chat_id, {"category": category, "step": 0})
    step = data["step"]
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    if not links: # إذا لم تكن هناك قنوات اشتراك اختيارية معرفة
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة (لا توجد قنوات اشتراك حالياً لهذا القسم). الرجاء الانتظار.", reply_markup=main_keyboard())
        pending_check.pop(chat_id, None)
        return


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
    bot.answer_callback_query(call.id)  # لحل مشكلة الزر المعلق

    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    step = int(step_str) + 1
    links = load_subscribe_links_v1() if category == "v1" else load_subscribe_links_v2()

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
    bot.answer_callback_query(call.id)  # لحل مشكلة الزر المعلق

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


@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات1" and m.from_user.id == OWNER_ID)
def set_upload_mode_v1_button(message):
    """تعيين وضع الرفع لقسم فيديوهات1."""
    owner_upload_mode[message.from_user.id] = 'v1'
    bot.reply_to(message, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات1.")

@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات2" and m.from_user.id == OWNER_ID)
def set_upload_mode_v2_button(message):
    """تعيين وضع الرفع لقسم فيديوهات2."""
    owner_upload_mode[message.from_user.id] = 'v2'
    bot.reply_to(message, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات2.")

# معالج زر تفعيل وضع صيانة فيديوهات2
@bot.message_handler(func=lambda m: m.text == "تفعيل صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def enable_maintenance_button(message):
    global maintenance_mode
    maintenance_mode = True
    bot.reply_to(message, "✅ تم تفعيل وضع الصيانة لـ فيديوهات2. البوت الآن في وضع الصيانة لهذا القسم.")

# معالج لزر إيقاف وضع صيانة فيديوهات2
@bot.message_handler(func=lambda m: m.text == "إيقاف صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def disable_maintenance_button(message):
    global maintenance_mode
    maintenance_mode = False
    bot.reply_to(message, "✅ تم إيقاف وضع الصيانة لـ فيديوهات2. البوت عاد للعمل في هذا القسم.")

@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    """معالج لرفع الفيديوهات من قبل المالك."""
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

    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو.")

@bot.message_handler(func=lambda m: m.text == "رسالة جماعية مع صورة" and m.from_user.id == OWNER_ID)
def ask_broadcast_photo(message):
    """طلب صورة لرسالة جماعية."""
    bot.send_message(message.chat.id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.")
    waiting_for_broadcast["photo"] = True

@bot.message_handler(content_types=['photo'])
def receive_broadcast_photo(message):
    """استقبال الصورة للرسالة الجماعية."""
    if waiting_for_broadcast.get("photo") and message.from_user.id == OWNER_ID:
        waiting_for_broadcast["photo_file_id"] = message.photo[-1].file_id
        waiting_for_broadcast["photo"] = False
        waiting_for_broadcast["awaiting_text"] = True
        bot.send_message(message.chat.id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة.")

@bot.message_handler(func=lambda m: waiting_for_broadcast.get("awaiting_text") and m.from_user.id == OWNER_ID)
def receive_broadcast_text(message):
    """استقبال نص الرسالة الجماعية وإرسالها."""
    if waiting_for_broadcast.get("awaiting_text"):
        photo_id = waiting_for_broadcast.get("photo_file_id")
        text = message.text
        users = get_all_approved_users()
        sent_count = 0
        for user_id in users:
            try:
                bot.send_photo(user_id, photo_id, caption=text)
                sent_count += 1
            except Exception as e:
                print(f"Error sending broadcast to {user_id}: {e}")
                pass
        bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.")
        waiting_for_broadcast.clear()

# --- معالجات قنوات الاشتراك الإجباري (true_subscribe_links) من خلال زر "إدارة قنوات الاشتراك الإجباري" ---

@bot.message_handler(func=lambda m: m.text == "إدارة قنوات الاشتراك الإجباري" and m.from_user.id == OWNER_ID)
def manage_true_subscribe_channels_button(message):
    """يعرض قائمة إدارة لقنوات الاشتراك الإجباري."""
    user_id = message.from_user.id
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("إضافة قناة إجباري", callback_data="true_add_channel"),
        types.InlineKeyboardButton("حذف قناة إجباري", callback_data="true_delete_channel")
    )
    markup.row(
        types.InlineKeyboardButton("عرض القنوات الإجبارية", callback_data="true_view_channels")
    )
    bot.send_message(user_id, "اختر إجراءً لإدارة قنوات الاشتراك الإجباري:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("true_"))
def handle_true_channel_management_callback(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    action = call.data.split("_")[1] # add, delete, view

    if action == "add":
        bot.send_message(user_id, "أرسل لي رابط القناة التي تريد إضافتها كقناة اشتراك إجباري (مثل: `https://t.me/CHANNEL_USERNAME` أو رابط دعوة).\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية.", parse_mode="Markdown")
        waiting_for_channel_link[user_id] = True
    elif action == "delete":
        channels = list(true_subscribe_channels_col.find())
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        if not channels:
            bot.send_message(user_id, "لا توجد قنوات اشتراك إجباري لإزالتها.", reply_markup=owner_keyboard())
            return

        text = "📋 قائمة قنوات الاشتراك الإجباري:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
        bot.send_message(user_id, text, reply_markup=back_markup)
        waiting_for_channel_to_delete[user_id] = {"channels": channels}
    elif action == "view":
        channels = list(true_subscribe_channels_col.find())
        if not channels:
            bot.send_message(user_id, "لا توجد قنوات اشتراك إجباري معرفة حالياً.")
            return
        text = "📋 قنوات الاشتراك الإجباري الحالية:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        bot.send_message(user_id, text)

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_channel_link.get(m.from_user.id))
def add_channel_link(message):
    """يستقبل رابط القناة الإجبارية ويضيفه إلى قاعدة البيانات."""
    user_id = message.from_user.id
    link = message.text.strip()

    if link == "رجوع":
        handle_back_command(message)
        return

    if link.startswith("http://") or link.startswith("https://"):
        if not true_subscribe_channels_col.find_one({"link": link}):
            true_subscribe_channels_col.insert_one({"link": link})
            global true_subscribe_links
            true_subscribe_links = load_true_subscribe_links()
            bot.send_message(user_id, f"✅ تم إضافة القناة: `{link}` بنجاح.", parse_mode="Markdown", reply_markup=owner_keyboard())
        else:
            bot.send_message(user_id, "هذه القناة موجودة بالفعل في قائمة قنوات الاشتراك الإجباري.", reply_markup=owner_keyboard())
        waiting_for_channel_link.pop(user_id)
    else:
        bot.send_message(user_id, "❌ الرابط غير صالح. يرجى إرسال رابط URL يبدأ بـ `http://` أو `https://`.", reply_markup=owner_keyboard())
        waiting_for_channel_link.pop(user_id)


@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_channel_to_delete.get(m.from_user.id))
def delete_channel_link(message):
    """يستقبل رقم القناة الإجبارية المراد حذفها ويقوم بحذفها من قاعدة البيانات."""
    user_id = message.from_user.id
    data = waiting_for_channel_to_delete.get(user_id)

    if message.text == "رجوع":
        handle_back_command(message)
        return

    try:
        choice = int(message.text)
        channels = data["channels"]

        if 1 <= choice <= len(channels):
            channel_to_delete = channels[choice - 1]
            true_subscribe_channels_col.delete_one({"_id": channel_to_delete["_id"]})
            global true_subscribe_links
            true_subscribe_links = load_true_subscribe_links()
            bot.send_message(user_id, f"✅ تم حذف القناة رقم {choice} بنجاح.", reply_markup=owner_keyboard())
            waiting_for_channel_to_delete.pop(user_id)
        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.", reply_markup=owner_keyboard())
            waiting_for_channel_to_delete.pop(user_id)
    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.", reply_markup=owner_keyboard())
        waiting_for_channel_to_delete.pop(user_id)


# --- معالجات إدارة القنوات الاختيارية (فيديوهات1 و فيديوهات2) ---

@bot.callback_query_handler(func=lambda call: call.data.startswith("manage_optional_"))
def handle_optional_channel_management_callback(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    _, _, category_prefix, action = call.data.split("_") # manage_optional_v1_add

    category = category_prefix # v1 أو v2
    
    if action == "add":
        bot.send_message(user_id, f"أرسل لي رابط القناة التي تريد إضافتها لقسم فيديوهات {category[-1]} (مثال: `https://t.me/CHANNEL_USERNAME` أو رابط دعوة).\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية.", parse_mode="Markdown")
        waiting_for_optional_link[user_id] = category
    elif action == "delete":
        col = optional_subscribe_channels_v1_col if category == "v1" else optional_subscribe_channels_v2_col
        channels = list(col.find())
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))

        if not channels:
            bot.send_message(user_id, f"لا توجد قنوات اشتراك لإزالتها في قسم فيديوهات {category[-1]}.", reply_markup=owner_keyboard())
            return

        text = f"📋 قائمة قنوات فيديوهات {category[-1]}:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
        bot.send_message(user_id, text, reply_markup=back_markup)
        waiting_for_optional_delete[user_id] = {"category": category, "channels": channels}
    elif action == "view":
        col = optional_subscribe_channels_v1_col if category == "v1" else optional_subscribe_channels_v2_col
        channels = list(col.find())
        if not channels:
            bot.send_message(user_id, f"لا توجد قنوات اشتراك معرفة حالياً لقسم فيديوهات {category[-1]}.")
            return
        text = f"📋 قنوات الاشتراك الحالية لقسم فيديوهات {category[-1]}:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        bot.send_message(user_id, text)
    elif action == "show_videos":
        # هذه الحالة تعيد المالك إلى وظيفته الأصلية لعرض الفيديوهات لهذا القسم
        send_videos(user_id, category)


@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_optional_link.get(m.from_user.id))
def add_optional_channel_link(message):
    """يستقبل رابط القناة الاختيارية ويضيفه إلى قاعدة البيانات."""
    user_id = message.from_user.id
    category = waiting_for_optional_link.get(user_id)
    link = message.text.strip()

    if link == "رجوع":
        handle_back_command(message)
        return

    if link.startswith("http://") or link.startswith("https://"):
        col = optional_subscribe_channels_v1_col if category == "v1" else optional_subscribe_channels_v2_col
        if not col.find_one({"link": link}):
            col.insert_one({"link": link})
            global subscribe_links_v1, subscribe_links_v2
            subscribe_links_v1 = load_subscribe_links_v1() # تحديث القوائم في الذاكرة
            subscribe_links_v2 = load_subscribe_links_v2()
            bot.send_message(user_id, f"✅ تم إضافة القناة لقسم فيديوهات {category[-1]}: `{link}` بنجاح.", parse_mode="Markdown", reply_markup=owner_keyboard())
        else:
            bot.send_message(user_id, f"هذه القناة موجودة بالفعل في قائمة قنوات فيديوهات {category[-1]}.", reply_markup=owner_keyboard())
        waiting_for_optional_link.pop(user_id)
    else:
        bot.send_message(user_id, "❌ الرابط غير صالح. يرجى إرسال رابط URL يبدأ بـ `http://` أو `https://`.", reply_markup=owner_keyboard())
        waiting_for_optional_link.pop(user_id)


@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_optional_delete.get(m.from_user.id))
def delete_optional_channel_link(message):
    """يستقبل رقم القناة الاختيارية المراد حذفها ويقوم بحذفها من قاعدة البيانات."""
    user_id = message.from_user.id
    data = waiting_for_optional_delete.get(user_id)
    category = data["category"]

    if message.text == "رجوع":
        handle_back_command(message)
        return

    try:
        choice = int(message.text)
        channels = data["channels"]

        if 1 <= choice <= len(channels):
            channel_to_delete = channels[choice - 1]
            col = optional_subscribe_channels_v1_col if category == "v1" else optional_subscribe_channels_v2_col
            col.delete_one({"_id": channel_to_delete["_id"]})
            global subscribe_links_v1, subscribe_links_v2
            subscribe_links_v1 = load_subscribe_links_v1() # تحديث القوائم في الذاكرة
            subscribe_links_v2 = load_subscribe_links_v2()
            bot.send_message(user_id, f"✅ تم حذف القناة رقم {choice} من قسم فيديوهات {category[-1]} بنجاح.", reply_markup=owner_keyboard())
            waiting_for_optional_delete.pop(user_id)
        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.", reply_markup=owner_keyboard())
            waiting_for_optional_delete.pop(user_id)
    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.", reply_markup=owner_keyboard())
        waiting_for_optional_delete.pop(user_id)


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
