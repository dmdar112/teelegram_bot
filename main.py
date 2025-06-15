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
if not TOKEN:
    print("❌ خطأ: متغير البيئة TOKEN غير موجود. يرجى تعيينه.")
    exit(1)
bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622  # عدّل رقمك هنا
# تأكد أن هذا مطابق لاسم بوتك بدون @ (مهم جداً للروابط القابلة للنقر)
BOT_USERNAME = "znjopabot"  

maintenance_mode = False # هذا المتغير يتحكم بوضع صيانة فيديوهات2 فقط

# آيدي القناة الخاصة بفيديوهات1
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")
# آيدي القناة الخاصة بفيديوهات2
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")

if not CHANNEL_ID_V1 or not CHANNEL_ID_V2:
    print("❌ خطأ: متغيرات البيئة CHANNEL_ID_V1 أو CHANNEL_ID_V2 غير موجودة. يرجى تعيينها.")
    exit(1)

waiting_for_delete = {}
# {user_id: step} - لتتبع تقدم المستخدم في الاشتراك الإجباري الحقيقي
true_sub_pending = {}  

MONGODB_URI = os.environ.get("MONGODB_URI")
if not MONGODB_URI:
    print("❌ خطأ: متغير البيئة MONGODB_URI غير موجود. يرجى تعيينه.")
    exit(1)

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
owner_upload_mode = {}
waiting_for_broadcast = {}

# --- دالة مساعدة لتهريب النص لـ MarkdownV2 ---
def escape_markdown_v2(text):
    """
    يهرب الأحرف الخاصة في النص لاستخدامها مع parse_mode='MarkdownV2'.
    """
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return "".join(["\\" + char if char in escape_chars else char for char in text])

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
    # استخدام set.union لتجميع المستخدمين الفريدين من كلتا المجموعتين
    approved_v1_users = set(user["user_id"] for user in approved_v1_col.find({}, {"user_id": 1}))
    approved_v2_users = set(user["user_id"] for user in approved_v2_col.find({}, {"user_id": 1}))
    return approved_v1_users.union(approved_v2_users)

def send_videos(user_id, category):
    """إرسال الفيديوهات من قسم معين إلى المستخدم."""
    collection_name = f"videos_{category}"
    videos_collection = db[collection_name]
    videos = list(videos_collection.find())

    if not videos:
        bot.send_message(user_id, escape_markdown_v2("❌ لا توجد فيديوهات حالياً في هذا القسم."), parse_mode='MarkdownV2')
        return

    for video in videos:
        try:
            bot.copy_message(
                chat_id=user_id,
                from_chat_id=video["chat_id"],
                message_id=video["message_id"],
                caption="", # الكابشن يتم نسخه كما هو، لا يحتاج لتهريب هنا
                caption_entities=None
            )
            time.sleep(0.5)  # تقليل التأخير قليلاً
        except Exception as e:
            print(f"❌ خطأ أثناء إرسال الفيديو: {e} إلى المستخدم {user_id}")
            # يمكن إضافة رسالة للمستخدم هنا إذا أردت
            # bot.send_message(user_id, escape_markdown_v2("❌ حدث خطأ أثناء إرسال الفيديو. يرجى المحاولة لاحقاً."), parse_mode='MarkdownV2')

@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات1" and m.from_user.id == OWNER_ID)
def delete_videos_v1(message):
    """معالج لزر حذف فيديوهات1."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    videos = list(db_videos_col.find().limit(20)) # عرض أول 20 فيديو فقط

    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, escape_markdown_v2("لا يوجد فيديوهات في فيديوهات1."), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')
        return

    text = escape_markdown_v2("📋 قائمة فيديوهات1:\n")
    for i, vid in enumerate(videos, 1):
        text += escape_markdown_v2(f"{i}. رسالة رقم: {vid['message_id']}\n")
    text += escape_markdown_v2("\nأرسل رقم الفيديو الذي تريد حذفه.")

    bot.send_message(user_id, text, reply_markup=back_markup, parse_mode='MarkdownV2')
    waiting_for_delete[user_id] = {"category": "v1", "videos": videos}

@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات2" and m.from_user.id == OWNER_ID)
def delete_videos_v2(message):
    """معالج لزر حذف فيديوهات2."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    videos = list(db_videos_col.find().limit(20)) # عرض أول 20 فيديو فقط

    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, escape_markdown_v2("لا يوجد فيديوهات في فيديوهات2."), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')
        return

    text = escape_markdown_v2("📋 قائمة فيديوهات2:\n")
    for i, vid in enumerate(videos, 1):
        text += escape_markdown_v2(f"{i}. رسالة رقم: {vid['message_id']}\n")
    text += escape_markdown_v2("\nأرسل رقم الفيديو الذي تريد حذفه.")

    bot.send_message(user_id, text, reply_markup=back_markup, parse_mode='MarkdownV2')
    waiting_for_delete[user_id] = {"category": "v2", "videos": videos}

@bot.message_handler(func=lambda m: m.text == "رجوع" and m.from_user.id in waiting_for_delete)
def handle_back_command(message):
    """معالج لزر الرجوع أثناء عملية الحذف."""
    user_id = message.from_user.id

    if user_id in waiting_for_delete:
        waiting_for_delete.pop(user_id)
    # إزالة المستخدم من وضع الرفع إذا كان فيه
    if user_id in owner_upload_mode:
        owner_upload_mode.pop(user_id)
    if user_id in waiting_for_broadcast:
        waiting_for_broadcast.clear()

    bot.send_message(user_id, escape_markdown_v2("تم الرجوع إلى القائمة الرئيسية"), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_delete.get(m.from_user.id) and m.text != "رجوع")
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
            chat_id_to_delete_from = os.environ.get(f"CHANNEL_ID_{category.upper()}")
            message_id = video_to_delete["message_id"]

            try:
                # حذف الرسالة من القناة
                bot.delete_message(chat_id_to_delete_from, message_id)
                # حذف السجل من قاعدة البيانات
                db_videos_col = db[f"videos_{category}"]
                db_videos_col.delete_one({"message_id": message_id})
                bot.send_message(user_id, escape_markdown_v2(f"✅ تم حذف الفيديو رقم {choice} بنجاح."), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')
                waiting_for_delete.pop(user_id)
            except Exception as e:
                bot.send_message(user_id, escape_markdown_v2(f"❌ حدث خطأ أثناء حذف الرسالة من القناة: {e}. يرجى التحقق يدوياً."), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')
                waiting_for_delete.pop(user_id)


        else:
            bot.send_message(user_id, escape_markdown_v2("❌ الرقم غير صحيح، حاول مرة أخرى."), parse_mode='MarkdownV2')

    except ValueError:
        bot.send_message(user_id, escape_markdown_v2("❌ من فضلك أرسل رقم صالح."), parse_mode='MarkdownV2')

# معالج زر "تنظيف فيديوهات1"
@bot.message_handler(func=lambda m: m.text == "تنظيف فيديوهات1" and m.from_user.id == OWNER_ID)
def clean_videos_v1_button(message):
    """معالج لزر تنظيف فيديوهات1."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    channel_id = CHANNEL_ID_V1

    bot.send_message(user_id, escape_markdown_v2("جاري تنظيف فيديوهات1... قد يستغرق هذا بعض الوقت."), parse_mode='MarkdownV2')

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            # نجرب نرسل رسالة توجيهية لنفسنا (المالك) من القناة، للتأكد من وجود الرسالة
            # لو الرسالة غير موجودة، هذا الأمر سيفشل
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
            time.sleep(0.1) # تقليل الضغط على API
        except Exception as e:
            # لو فشل، احذف الفيديو من قاعدة البيانات لأنه غير موجود بالقناة
            print(f"Video {message_id} in channel {channel_id} not found, removing from DB: {e}")
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, escape_markdown_v2(f"✅ تم تنظيف فيديوهات1. عدد الفيديوهات المحذوفة: {removed_count}"), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')

# معالج زر "تنظيف فيديوهات2"
@bot.message_handler(func=lambda m: m.text == "تنظيف فيديوهات2" and m.from_user.id == OWNER_ID)
def clean_videos_v2_button(message):
    """معالج لزر تنظيف فيديوهات2."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    channel_id = CHANNEL_ID_V2

    bot.send_message(user_id, escape_markdown_v2("جاري تنظيف فيديوهات2... قد يستغرق هذا بعض الوقت."), parse_mode='MarkdownV2')

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
            time.sleep(0.1) # تقليل الضغط على API
        except Exception as e:
            print(f"Video {message_id} in channel {channel_id} not found, removing from DB: {e}")
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, escape_markdown_v2(f"✅ تم تنظيف فيديوهات2. عدد الفيديوهات المحذوفة: {removed_count}"), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')


def check_true_subscription(user_id, first_name):
    """
    يقوم بالتحقق من جميع قنوات true_subscribe_links بشكل متسلسل
    ويدفع المستخدم للاشتراك في القناة التالية إذا لم يكن مشتركًا.
    """
    # تهيئة الخطوة الحالية: إذا لم يكن المستخدم موجودًا في true_sub_pending، ابدأ من 0
    step = true_sub_pending.get(user_id, 0)
    
    # حلقة للتحقق من الاشتراكات المتسلسلة
    while step < len(true_subscribe_links):
        current_channel_link = true_subscribe_links[step]
        try:
            # استخراج المعرّف من الرابط (سواء @username أو رابط دعوة)
            channel_identifier = current_channel_link.split("t.me/")[-1]
            is_subscribed = False

            # للروابط التي تبدأ بـ '@' (قنوات عامة)
            if channel_identifier.startswith('@'):
                channel_username = channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    is_subscribed = True
            # للروابط التي لا تبدأ بـ '@' (روابط دعوة للقنوات العامة أو الخاصة)
            else:
                # هنا يجب أن نكون حذرين. get_chat_member لا يعمل مع روابط الدعوة مباشرة.
                # الطريقة الوحيدة للتحقق من قنوات الدعوة هي أن يكون البوت عضواً فيها
                # ويجب على المطور استخراج chat_id للقناة الخاصة إذا كان البوت عضواً.
                # لتبسيط الأمر، إذا كان الرابط رابط دعوة، نفترض أنه غير مشترك ونطلب منه الاشتراك
                # وننتظر منه إعادة إرسال /start
                # الحل الأفضل يتطلب أن يكون البوت مشرفًا في القناة الخاصة للحصول على chat_id
                # والتحقق منه عبر get_chat_member.
                # في هذه الحالة، إذا كان رابط دعوة، لن نتمكن من التحقق تلقائيًا.
                # سنعاملها كقناة لم يتم الاشتراك فيها.
                pass # لا يمكن التحقق التلقائي من روابط الدعوة هنا.

            if not is_subscribed:
                # إذا لم يكن مشتركًا في القناة الحالية، اطلب منه الاشتراك
                # وسنجعل /start رابطًا قابلاً للضغط
                
                # بناء النص مع /start كـ URL
                # استخدم telebot.formatting.escape_markdown لتهريب النص داخل الرابط
                start_button_text = telebot.formatting.escape_markdown('/start')
                # تأكد أن BOT_USERNAME صحيح
                start_link_url = f"tg://resolve?domain={BOT_USERNAME}&start="
                
                # تهريب جميع الرموز الخاصة في النص العادي باستخدام دالتنا المخصصة
                escaped_channel_link = escape_markdown_v2(current_channel_link)
                
                text = (
                    f"🔔 لطفًا اشترك في القناة التالية:\n"
                    f"📮: {escaped_channel_link}\n\n"
                    f"⚠️ بعد الاشتراك، اضغط [{start_button_text}]({start_link_url}) للمتابعة."
                )
                bot.send_message(user_id, text, disable_web_page_preview=True, parse_mode='MarkdownV2')
                true_sub_pending[user_id] = step # حفظ الخطوة الحالية
                return # توقف هنا وانتظر من المستخدم أن يرسل /start مرة أخرى

            # إذا كان مشتركًا (أو تجاوزنا فحص القناة الخاصة بنجاح)، انتقل للخطوة التالية
            step += 1
            true_sub_pending[user_id] = step # تحديث الخطوة للقناة التالية

        except Exception as e:
            print(f"❌ Error checking channel {current_channel_link} for user {user_id}: {e}")
            # في حالة الخطأ، نطلب من المستخدم المحاولة مرة أخرى عند /start
            
            # بناء النص مع /start كـ URL
            start_button_text = telebot.formatting.escape_markdown('/start')
            start_link_url = f"tg://resolve?domain={BOT_USERNAME}&start="
            
            escaped_channel_link = escape_markdown_v2(current_channel_link)

            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة: {escaped_channel_link}.\n"
                "يرجى التأكد أنك مشترك وأن البوت مشرف في القناة إذا كانت عامة، ثم اضغط "
                f"[{start_button_text}]({start_link_url})."
            )
            bot.send_message(user_id, text, disable_web_page_preview=True, parse_mode='MarkdownV2')
            true_sub_pending[user_id] = step # ابقَ على نفس الخطوة ليحاول مرة أخرى
            return # توقف هنا وانتظر تفاعل المستخدم

    # إذا وصل الكود إلى هنا، فهذا يعني أن المستخدم مشترك في جميع القنوات بنجاح
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


@bot.message_handler(commands=['start'])
def handle_start(message):
    """معالج لأمر /start للتحقق من الاشتراك."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم جديد"

    # مسح أي حالات انتظار سابقة عند /start
    if user_id in waiting_for_delete:
        del waiting_for_delete[user_id]
    if user_id in owner_upload_mode:
        del owner_upload_mode[user_id]
    if user_id in waiting_for_broadcast:
        waiting_for_broadcast.clear()
    if user_id in pending_check:
        del pending_check[user_id]


    # إذا كان المستخدم هو المالك، أظهر لوحة مفاتيح المالك مباشرة
    if user_id == OWNER_ID:
        bot.send_message(user_id, escape_markdown_v2("مرحبا مالك البوت!"), reply_markup=owner_keyboard(), parse_mode='MarkdownV2')
        return

    # لكل المستخدمين الآخرين، ابدأ عملية التحقق من الاشتراك الإجباري
    check_true_subscription(user_id, first_name)


def send_start_welcome_message(user_id, first_name):
    """المنطق الفعلي لدالة /start بعد التحقق من الاشتراك في القنوات الإجبارية."""
    # تأكدنا بالفعل من أن المستخدم ليس المالك في handle_start
    bot.send_message(user_id, escape_markdown_v2(f"""🔞 مرحباً بك ({first_name}) 🏳‍🌈
📂اختر قسم الفيديوهات من الأزرار بالأسفل!

⚠️ المحتوى +18 - للكبار فقط!"""), reply_markup=main_keyboard(), parse_mode='MarkdownV2')

    if not has_notified(user_id):
        # التأكد من عدد المستخدمين الجدد بشكل صحيح
        total_users = users_col.count_documents({}) # عدد جميع المستخدمين في قاعدة البيانات
        # تهريب النص لرسالة المالك أيضاً
        escaped_first_name = escape_markdown_v2(first_name)
        escaped_user_id = escape_markdown_v2(str(user_id))
        escaped_total_users = escape_markdown_v2(str(total_users))

        bot.send_message(OWNER_ID, f"""👾 تم دخول شخص جديد إلى البوت الخاص بك

• الاسم : {escaped_first_name}
• الايدي : {escaped_user_id}
• عدد الأعضاء الكلي: {escaped_total_users}
""", parse_mode='MarkdownV2')
        add_notified_user(user_id)


@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    """معالج لزر فيديوهات1."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    # قبل السماح بالوصول إلى فيديوهات1، يجب أن يكون المستخدم قد اجتاز التحقق الإجباري
    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, escape_markdown_v2("⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة."), parse_mode='MarkdownV2')
        check_true_subscription(user_id, first_name) # نعيد توجيهه لإكمال الاشتراك الإجباري
        return

    if user_id in load_approved_users(approved_v1_col):
        send_videos(user_id, "v1")
    else:
        bot.send_message(user_id, escape_markdown_v2("👋 أهلاً بك في قسم فيديوهات 1!\nللوصول إلى المحتوى، الرجاء الاشتراك في القنوات التالية:"), parse_mode='MarkdownV2')
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

    # قبل السماح بالوصول إلى فيديوهات2، يجب أن يكون المستخدم قد اجتاز التحقق الإجباري
    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, escape_markdown_v2("⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة."), parse_mode='MarkdownV2')
        check_true_subscription(user_id, first_name) # نعيد توجيهه لإكمال الاشتراك الإجباري
        return

    if maintenance_mode and user_id != OWNER_ID:
        bot.send_message(user_id, escape_markdown_v2("⚙️ زر فيديوهات 2 حالياً في وضع صيانة. الرجاء المحاولة لاحقاً."), parse_mode='MarkdownV2')
        return

    if user_id in load_approved_users(approved_v2_col):
        send_videos(user_id, "v2")
    else:
        bot.send_message(user_id, escape_markdown_v2("👋 أهلاً بك في قسم فيديوهات 2!\nللوصول إلى الفيديوهات، الرجاء الاشتراك في القنوات التالية:"), parse_mode='MarkdownV2')
        data = pending_check.get(user_id)
        if data and data["category"] == "v2":
            send_required_links(user_id, "v2")
        else:
            pending_check[user_id] = {"category": "v2", "step": 0}
            send_required_links(user_id, "v2")

def send_required_links(chat_id, category):
    """إرسال روابط الاشتراك المطلوبة (للاشتراكات الاختيارية)."""
    data = pending_check.get(chat_id, {"category": category, "step": 0})
    step = data["step"]
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    if step >= len(links):
        notify_owner_for_approval(chat_id, bot.get_chat(chat_id).first_name, category)
        bot.send_message(chat_id, escape_markdown_v2("تم إرسال طلبك للموافقة. الرجاء الانتظار."), reply_markup=main_keyboard(), parse_mode='MarkdownV2')
        pending_check.pop(chat_id, None)
        return

    link = links[step]

    markup = types.InlineKeyboardMarkup()
    # لتجنب الأخطاء إذا كان الرابط لا يحتوي على اسم قناة واضح
    channel_display_name = link.split('/')[-1] if link.split('/')[-1] else f"القناة {step + 1}"
    
    if '+' in channel_display_name: # إذا كان رابط دعوة خاص
        button_text = escape_markdown_v2(f"اشترك في القناة الخاصة {step + 1}")
    else: # روابط القنوات العامة
        button_text = escape_markdown_v2(f"اشترك في @{channel_display_name}")

    markup.add(types.InlineKeyboardButton(button_text, url=link))
    
    # إضافة زر "تم الاشتراك" للانتقال للرابط التالي
    markup.add(types.InlineKeyboardButton(escape_markdown_v2("✅ تم الاشتراك"), callback_data=f"verify_{category}_{step}"))

    text = escape_markdown_v2(f"""- لطفاً اشترك بالقناة واضغط على الزر أدناه للمتابعة.
- قناة البوت 👾.👇🏻
""")
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True, parse_mode='MarkdownV2')

    pending_check[chat_id] = {"category": category, "step": step}

@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    """معالج للتحقق من الاشتراك عبر الأزرار."""
    bot.answer_callback_query(call.id, text=escape_markdown_v2("جاري التحقق..."), show_alert=False)

    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    current_step = int(step_str) # الخطوة التي تم الضغط عليها (0-indexed)
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    # التحقق من الاشتراك في القناة الحالية
    current_channel_link = links[current_step]
    is_subscribed_to_current = False
    
    try:
        channel_identifier = current_channel_link.split("t.me/")[-1]
        if channel_identifier.startswith('@'):
            channel_username = channel_identifier
            member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
            if member.status in ['member', 'administrator', 'creator']:
                is_subscribed_to_current = True
        else:
            # لقنوات الدعوة الخاصة، لا يمكن التحقق التلقائي هنا
            # إذا ضغط المستخدم "تم الاشتراك" على رابط دعوة، سنفترض أنه اشترك ونقدم له الخطوة التالية
            is_subscribed_to_current = True
            
    except Exception as e:
        print(f"Error verifying optional channel {current_channel_link} for user {user_id}: {e}")
        bot.send_message(user_id, escape_markdown_v2("❌ حدث خطأ أثناء التحقق من القناة. يرجى التأكد من الاشتراك وإعادة المحاولة."), parse_mode='MarkdownV2')
        return

    if is_subscribed_to_current:
        next_step = current_step + 1
        if next_step < len(links):
            pending_check[user_id] = {"category": category, "step": next_step}
            send_required_links(user_id, category)
        else:
            # تم الانتهاء من جميع الاشتراكات الاختيارية
            notify_owner_for_approval(user_id, call.from_user.first_name, category)
            bot.send_message(user_id, escape_markdown_v2("تم إرسال طلبك للموافقة. الرجاء الانتظار."), reply_markup=main_keyboard(), parse_mode='MarkdownV2')
            pending_check.pop(user_id, None)
    else:
        # إذا لم يكن مشتركًا في القناة الحالية
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(escape_markdown_v2("🚸 إذا كنت غير مشترك، اشترك الآن 🚸"), url=current_channel_link)
        )
        markup.add(
            types.InlineKeyboardButton(escape_markdown_v2("✅ لقد اشتركت"), callback_data=f"verify_{category}_{current_step}")
        )
        bot.send_message(
            user_id,
            escape_markdown_v2("⚠️ يبدو أنك لم تشترك في القناة الحالية بعد. الرجاء الاشتراك ثم اضغط 'لقد اشتركت'."),
            reply_markup=markup,
            parse_mode='MarkdownV2'
        )
        
        # لا نغير حالة pending_check هنا، يبقى عند نفس الخطوة
        pending_check[user_id] = {"category": category, "step": current_step}


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
    
    escaped_name = escape_markdown_v2(name)
    escaped_user_id = escape_markdown_v2(str(user_id))
    # للتأكد من أن "فيديوهات 1" أو "فيديوهات 2" تظهر بشكل صحيح
    display_category = "1" if category == "v1" else "2"
    escaped_category_display = escape_markdown_v2(display_category)

    message_text = (
        f"📥 طلب انضمام جديد\n"
        f"👤 الاسم: {escaped_name}\n"
        f"🆔 الآيدي: {escaped_user_id}\n"
        f"📁 الفئة: فيديوهات {escaped_category_display}"
    )
    bot.send_message(OWNER_ID, message_text, reply_markup=keyboard, parse_mode='MarkdownV2')

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_owner_response(call):
    """معالج لاستجابة المالك (قبول أو رفض)."""
    bot.answer_callback_query(call.id) # لإغلاق إشعار التحميل للزر

    parts = call.data.split("_")
    action, category, user_id = parts[0], parts[1], int(parts[2])

    if call.from_user.id != OWNER_ID:
        bot.send_message(call.from_user.id, escape_markdown_v2("🚫 غير مصرح لك بالقيام بهذا الإجراء."), parse_mode='MarkdownV2')
        return

    if action == "approve":
        target_collection = approved_v1_col if category == "v1" else approved_v2_col
        add_approved_user(target_collection, user_id)
        
        bot.send_message(user_id, escape_markdown_v2("✅ تم قبولك من قبل الإدارة! يمكنك الآن استخدام البوت بكل المزايا."), parse_mode='MarkdownV2')
        bot.edit_message_text(escape_markdown_v2("✅ تم قبول المستخدم."), call.message.chat.id, call.message.message_id, parse_mode='MarkdownV2')
    else:
        bot.send_message(user_id, escape_markdown_v2("❌ لم يتم قبولك. الرجاء الاشتراك في جميع قنوات البوت ثم أرسل /start مرة أخرى."), parse_mode='MarkdownV2')
        bot.edit_message_text(escape_markdown_v2("❌ تم رفض المستخدم."), call.message.chat.id, call.message.message_id, parse_mode='MarkdownV2')


@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات1" and m.from_user.id == OWNER_ID)
def set_upload_mode_v1_button(message):
    """تعيين وضع الرفع لقسم فيديوهات1."""
    owner_upload_mode[message.from_user.id] = 'v1'
    bot.reply_to(message, escape_markdown_v2("✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات1."), parse_mode='MarkdownV2')

@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات2" and m.from_user.id == OWNER_ID)
def set_upload_mode_v2_button(message):
    """تعيين وضع الرفع لقسم فيديوهات2."""
    owner_upload_mode[message.from_user.id] = 'v2'
    bot.reply_to(message, escape_markdown_v2("✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات2."), parse_mode='MarkdownV2')

# معالج زر تفعيل وضع صيانة فيديوهات2
@bot.message_handler(func=lambda m: m.text == "تفعيل صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def enable_maintenance_button(message):
    global maintenance_mode
    maintenance_mode = True
    bot.reply_to(message, escape_markdown_v2("✅ تم تفعيل وضع الصيانة لـ فيديوهات2. البوت الآن في وضع الصيانة لهذا القسم."), parse_mode='MarkdownV2')

# معالج لزر إيقاف وضع صيانة فيديوهات2
@bot.message_handler(func=lambda m: m.text == "إيقاف صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def disable_maintenance_button(message):
    global maintenance_mode
    maintenance_mode = False
    bot.reply_to(message, escape_markdown_v2("✅ تم إيقاف وضع الصيانة لـ فيديوهات2. البوت عاد للعمل في هذا القسم."), parse_mode='MarkdownV2')

@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    """معالج لرفع الفيديوهات من قبل المالك."""
    user_id = message.from_user.id
    mode = owner_upload_mode.get(user_id)

    if user_id != OWNER_ID or not mode:
        return

    channel_id_to_send = os.environ.get(f"CHANNEL_ID_{mode.upper()}")
    if not channel_id_to_send:
        bot.reply_to(message, escape_markdown_v2("❌ خطأ: لم يتم تحديد CHANNEL_ID لهذا القسم."), parse_mode='MarkdownV2')
        return

    try:
        # الكابشن هنا سيكون ثابت من البوت، لذا نهربه يدوياً
        caption_text = escape_markdown_v2(f"📥 فيديو جديد من المالك - قسم {mode.upper()}")
        sent = bot.send_video(
            chat_id=channel_id_to_send,
            video=message.video.file_id,
            caption=caption_text,
            parse_mode='MarkdownV2'
        )
        # تخزين في قاعدة البيانات
        db[f"videos_{mode}"].insert_one({
            "chat_id": sent.chat.id,
            "message_id": sent.message_id
        })

        bot.reply_to(message, escape_markdown_v2(f"✅ تم حفظ الفيديو في قسم {mode.upper()}."), parse_mode='MarkdownV2')
        # بعد الرفع، نخرج من وضع الرفع تلقائياً
        owner_upload_mode.pop(user_id, None) 

    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, escape_markdown_v2("❌ حدث خطأ أثناء حفظ الفيديو."), parse_mode='MarkdownV2')

@bot.message_handler(func=lambda m: m.text == "رسالة جماعية مع صورة" and m.from_user.id == OWNER_ID)
def ask_broadcast_photo(message):
    """طلب صورة لرسالة جماعية."""
    waiting_for_broadcast.clear() # مسح أي حالات سابقة
    waiting_for_broadcast["photo_pending"] = True
    bot.send_message(message.chat.id, escape_markdown_v2("أرسل لي الصورة التي تريد إرسالها مع الرسالة."), parse_mode='MarkdownV2')

@bot.message_handler(content_types=['photo'])
def receive_broadcast_photo(message):
    """استقبال الصورة للرسالة الجماعية."""
    if waiting_for_broadcast.get("photo_pending") and message.from_user.id == OWNER_ID:
        waiting_for_broadcast["photo_file_id"] = message.photo[-1].file_id
        waiting_for_broadcast.pop("photo_pending")
        waiting_for_broadcast["awaiting_text"] = True
        bot.send_message(message.chat.id, escape_markdown_v2("الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة."), parse_mode='MarkdownV2')
    # إذا لم يكن في وضع انتظار الصورة، تجاهل الصورة
    elif message.from_user.id == OWNER_ID and not waiting_for_broadcast.get("photo_pending"):
        bot.reply_to(message, escape_markdown_v2("يرجى الضغط على 'رسالة جماعية مع صورة' أولاً لبدء عملية الإرسال الجماعي."), parse_mode='MarkdownV2')


@bot.message_handler(func=lambda m: waiting_for_broadcast.get("awaiting_text") and m.from_user.id == OWNER_ID)
def receive_broadcast_text(message):
    """استقبال نص الرسالة الجماعية وإرسالها."""
    if waiting_for_broadcast.get("awaiting_text"):
        photo_id = waiting_for_broadcast.get("photo_file_id")
        text_from_owner = message.text # النص الذي أرسله المالك
        
        # تهريب نص الرسالة الجماعية قبل إرساله للمستخدمين
        escaped_text_for_broadcast = escape_markdown_v2(text_from_owner)
        
        users = get_all_approved_users()
        sent_count = 0
        failed_count = 0
        
        # إرسال رسالة للمالك بأن العملية بدأت
        bot.send_message(OWNER_ID, escape_markdown_v2("جاري إرسال الرسالة الجماعية... قد يستغرق هذا بعض الوقت."), parse_mode='MarkdownV2')

        for user_id in users:
            try:
                bot.send_photo(user_id, photo_id, caption=escaped_text_for_broadcast, parse_mode='MarkdownV2')
                sent_count += 1
                time.sleep(0.1) # لتجنب التقييد
            except Exception as e:
                print(f"Error sending broadcast to {user_id}: {e}")
                failed_count += 1
                pass
        
        bot.send_message(OWNER_ID, escape_markdown_v2(f"✅ تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.\n❌ فشل الإرسال إلى {failed_count} مستخدم."), parse_mode='MarkdownV2')
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

# --- بدء تشغيل البوت والخادم ---
if __name__ == '__main__':
    keep_alive()
    print("Bot is starting...")
    bot.infinity_polling()
