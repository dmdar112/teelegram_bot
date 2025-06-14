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
BOT_USERNAME = "znjopabot"  # *** مهم جداً: تأكد أن هذا مطابق لاسم بوتك بدون @ ***

maintenance_mode = False # هذا المتغير يتحكم بوضع صيانة فيديوهات2 فقط

# آيدي القناة الخاصة بفيديوهات1
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")
# آيدي القناة الخاصة بفيديوهات2
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")

waiting_for_delete = {}
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
            channel_identifier = current_channel_link.split("t.me/")[-1]
            is_subscribed = False

            # محاولة التحقق من الاشتراك
            # نتحقق فقط للقنوات العامة التي تبدأ بـ @ أو لا تحتوي على '+'
            if not channel_identifier.startswith('+'): 
                channel_username = f"@{channel_identifier}" if not channel_identifier.startswith('@') else channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    is_subscribed = True
            else: 
                # للقنوات الخاصة (روابط الدعوة +)، نفترض أنه غير مشترك ونطلب منه الاشتراك
                # لا يمكن التحقق التلقائي من روابط الدعوة بسهولة بدون أن يكون البوت مشرفاً فيها
                # وحتى لو كان مشرفاً، فإن get_chat_member لا يعمل مع الروابط نفسها.
                pass 

            if not is_subscribed:
                # إذا لم يكن مشتركًا في القناة الحالية، اطلب منه الاشتراك
                # وسنجعل /start رابطًا قابلاً للضغط
                
                # بناء النص مع /start كـ URL
                start_button_text = telebot.formatting.escape_markdown('/start')
                start_link_url = f"tg://resolve?domain={BOT_USERNAME}&start="
                
                # تهريب جميع الرموز الخاصة في النص العادي باستخدام escape_markdown
                escaped_channel_link = telebot.formatting.escape_markdown(current_channel_link)
                
                text = (
                    "🔔 لطفاً اشترك في القناة التالية\\:\n" # تهريب ":"
                    f"📮\\: {escaped_channel_link}\n\n" # تهريب ":"
                    f"⚠️ بعد الاشتراك، اضغط [{start_button_text}]({start_link_url}) للمتابعة\\." # تهريب "."
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
            
            escaped_channel_link = telebot.formatting.escape_markdown(current_channel_link)

            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة\\: {escaped_channel_link}\\.\n" # تهريب ":" و "."
                "يرجى التأكد أنك مشترك وأن البوت مشرف في القناة إذا كانت عامة، ثم اضغط "
                f"[{start_button_text}]({start_link_url})\\." # تهريب "."
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

    # إذا كان المستخدم هو المالك، أظهر لوحة مفاتيح المالك مباشرة
    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
        return

    # لكل المستخدمين الآخرين، ابدأ عملية التحقق من الاشتراك الإجباري
    check_true_subscription(user_id, first_name)


def send_start_welcome_message(user_id, first_name):
    """المنطق الفعلي لدالة /start بعد التحقق من الاشتراك في القنوات الإجبارية."""
    # تأكدنا بالفعل من أن المستخدم ليس المالك في handle_start
    bot.send_message(user_id, f"""🔞 مرحباً بك \\( {telebot.formatting.escape_markdown(first_name)} \\) 🏳‍🌈
📂اختر قسم الفيديوهات من الأزرار بالأسفل\\!

⚠️ المحتوى \\+18 \\- للكبار فقط\\!""", reply_markup=main_keyboard(), parse_mode='MarkdownV2') # تم إضافة parse_mode هنا أيضاً

    if not has_notified(user_id):
        total_users = len(get_all_approved_users())
        # تهريب النص لرسالة المالك أيضاً
        escaped_first_name = telebot.formatting.escape_markdown(first_name)
        escaped_user_id = telebot.formatting.escape_markdown(str(user_id))
        escaped_total_users = telebot.formatting.escape_markdown(str(total_users))

        bot.send_message(OWNER_ID, f"""👾 تم دخول شخص جديد إلى البوت الخاص بك

• الاسم \\: {escaped_first_name}
• الايدي \\: {escaped_user_id}
• عدد الأعضاء الكلي\\: {escaped_total_users}
""", parse_mode='MarkdownV2')
        add_notified_user(user_id)


# --- لا يوجد معالج callback_query_handler لـ "check_true_subscription" في هذه الطريقة ---


@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    """معالج لزر فيديوهات1."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    # قبل السماح بالوصول إلى فيديوهات1، يجب أن يكون المستخدم قد اجتاز التحقق الإجباري
    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        # تم تهريب النص هنا أيضاً
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً\\. اضغط /start للمتابعة\\.", parse_mode='MarkdownV2')
        check_true_subscription(user_id, first_name) # نعيد توجيهه لإكمال الاشتراك الإجباري
        return

    if user_id in load_approved_users(approved_v1_col):
        send_videos(user_id, "v1")
    else:
        # تم تهريب النص هنا أيضاً
        bot.send_message(user_id, "👋 أهلاً بك في قسم فيديوهات 1\\!\nللوصول إلى المحتوى، الرجاء الاشتراك في القنوات التالية\\:", parse_mode='MarkdownV2')
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
        # تم تهريب النص هنا أيضاً
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً\\. اضغط /start للمتابعة\\.", parse_mode='MarkdownV2')
        check_true_subscription(user_id, first_name) # نعيد توجيهه لإكمال الاشتراك الإجباري
        return

    if maintenance_mode and user_id != OWNER_ID:
        # تم تهريب النص هنا أيضاً
        bot.send_message(user_id, "⚙️ زر فيديوهات 2️⃣ حالياً في وضع صيانة\\. الرجاء المحاولة لاحقاً\\.", parse_mode='MarkdownV2')
        return

    if user_id in load_approved_users(approved_v2_col):
        send_videos(user_id, "v2")
    else:
        # تم تهريب النص هنا أيضاً
        bot.send_message(user_id, "👋 أهلاً بك في قسم فيديوهات 2\\!\nللوصول إلى الفيديوهات، الرجاء الاشتراك في القنوات التالية\\:", parse_mode='MarkdownV2')
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
        notify_owner_for_approval(chat_id, "مستخدم", category)
        # تم تهريب النص هنا أيضاً
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة\\. الرجاء الانتظار\\.", reply_markup=main_keyboard(), parse_mode='MarkdownV2')
        pending_check.pop(chat_id, None)
        return

    link = links[step]

    # هنا نستخدم زر Inline برابط مباشر (هذا لقنوات فيديوهات1/2)
    markup = types.InlineKeyboardMarkup()
    channel_name = link.split('/')[-1]
    # التأكد من تهريب channel_name في زر الـ Inline أيضاً
    escaped_channel_name = telebot.formatting.escape_markdown(channel_name)
    if channel_name.startswith('+'):
        # تهريب الرقم
        escaped_step = telebot.formatting.escape_markdown(str(step + 1))
        markup.add(types.InlineKeyboardButton(f"اشترك في القناة الخاصة {escaped_step}", url=link))
    else:
        markup.add(types.InlineKeyboardButton(f"اشترك في {escaped_channel_name}", url=link)) # تم تهريب هنا
    
    text = f"""- لطفاً اشترك بالقناة واضغط على الزر أدناه للمتابعة \\.
- قناة البوت 👾\\.👇🏻
""" # تم تهريب "." و ":"
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True, parse_mode='MarkdownV2') # تم إضافة parse_mode هنا

    pending_check[chat_id] = {"category": category, "step": step}

@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    """معالج للتحقق من الاشتراك عبر الأزرار."""
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
        # تهريب النص في زر الـ Inline أيضاً
        markup.add(
            types.InlineKeyboardButton(telebot.formatting.escape_markdown("🚸إذا كنت غير مشترك، اشترك الآن🚸"), callback_data=f"resend_{category}")
        )
        # تهريب النص هنا أيضاً
        bot.send_message(
            user_id,
            "⏳ يرجى الانتظار قليلاً حتى نتحقق من اشتراكك في جميع القنوات\\.\n"
            "إذا كنت مشتركًا سيتم قبولك تلقائيًا، وإذا كنت غير مشترك لا يمكنك استخدام البوت ⚠️",
            reply_markup=markup,
            parse_mode='MarkdownV2' # تم إضافة parse_mode هنا
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
    # تهريب النص هنا أيضاً
    escaped_name = telebot.formatting.escape_markdown(name)
    escaped_user_id = telebot.formatting.escape_markdown(str(user_id))
    escaped_category_last_char = telebot.formatting.escape_markdown(str(category[-1]))

    message_text = (
        f"📥 طلب انضمام جديد\n"
        f"👤 الاسم\\: {escaped_name}\n"
        f"🆔 الآيدي\\: {escaped_user_id}\n"
        f"📁 الفئة\\: فيديوهات {escaped_category_last_char}"
    )
    bot.send_message(OWNER_ID, message_text, reply_markup=keyboard, parse_mode='MarkdownV2') # تم إضافة parse_mode هنا

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
        # تهريب النص هنا أيضاً
        bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة\\! يمكنك الآن استخدام البوت بكل المزايا\\.", parse_mode='MarkdownV2')
        bot.edit_message_text("✅ تم قبول المستخدم\\.", call.message.chat.id, call.message.message_id, parse_mode='MarkdownV2') # تهريب النص هنا
    else:
        # تهريب النص هنا أيضاً
        bot.send_message(user_id, "❌ لم يتم قبولك\\. الرجاء الاشتراك في جميع قنوات البوت ثم أرسل /start مرة أخرى\\.", parse_mode='MarkdownV2')
        bot.edit_message_text("❌ تم رفض المستخدم\\.", call.message.chat.id, call.message.message_id, parse_mode='MarkdownV2') # تهريب النص هنا


@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات1" and m.from_user.id == OWNER_ID)
def set_upload_mode_v1_button(message):
    """تعيين وضع الرفع لقسم فيديوهات1."""
    owner_upload_mode[message.from_user.id] = 'v1'
    # تهريب النص هنا أيضاً
    bot.reply_to(message, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات1\\.", parse_mode='MarkdownV2')

@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات2" and m.from_user.id == OWNER_ID)
def set_upload_mode_v2_button(message):
    """تعيين وضع الرفع لقسم فيديوهات2."""
    owner_upload_mode[message.from_user.id] = 'v2'
    # تهريب النص هنا أيضاً
    bot.reply_to(message, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات2\\.", parse_mode='MarkdownV2')

# معالج زر تفعيل وضع صيانة فيديوهات2
@bot.message_handler(func=lambda m: m.text == "تفعيل صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def enable_maintenance_button(message):
    global maintenance_mode
    maintenance_mode = True
    # تهريب النص هنا أيضاً
    bot.reply_to(message, "✅ تم تفعيل وضع الصيانة لـ فيديوهات2\\. البوت الآن في وضع الصيانة لهذا القسم\\.", parse_mode='MarkdownV2')

# معالج لزر إيقاف وضع صيانة فيديوهات2
@bot.message_handler(func=lambda m: m.text == "إيقاف صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def disable_maintenance_button(message):
    global maintenance_mode
    maintenance_mode = False
    # تهريب النص هنا أيضاً
    bot.reply_to(message, "✅ تم إيقاف وضع الصيانة لـ فيديوهات2\\. البوت عاد للعمل في هذا القسم\\.", parse_mode='MarkdownV2')

@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    """معالج لرفع الفيديوهات من قبل المالك."""
    user_id = message.from_user.id
    mode = owner_upload_mode.get(user_id)

    if user_id != OWNER_ID or not mode:
        return  # تجاهل أي فيديو من غير المالك أو إن لم يحدد القسم

    # رفع الفيديو إلى القناة الخاصة
    try:
        # تهريب الكابتن هنا
        caption_text = f"📥 فيديو جديد من المالك \\- قسم {telebot.formatting.escape_markdown(mode.upper())}"
        sent = bot.send_video(
            chat_id=os.environ.get(f"CHANNEL_ID_{mode.upper()}"),
            video=message.video.file_id,
            caption=caption_text,
            parse_mode='MarkdownV2' # تم إضافة parse_mode هنا
        )
        # تخزين في قاعدة البيانات
        db[f"videos_{mode}"].insert_one({
            "chat_id": sent.chat.id,
            "message_id": sent.message_id
        })

        # تهريب النص هنا أيضاً
        bot.reply_to(message, f"✅ تم حفظ الفيديو في قسم {telebot.formatting.escape_markdown(mode.upper())}\\.", parse_mode='MarkdownV2')

    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        # تهريب النص هنا أيضاً
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو\\.", parse_mode='MarkdownV2')

@bot.message_handler(func=lambda m: m.text == "رسالة جماعية مع صورة" and m.from_user.id == OWNER_ID)
def ask_broadcast_photo(message):
    """طلب صورة لرسالة جماعية."""
    # تهريب النص هنا أيضاً
    bot.send_message(message.chat.id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة\\.", parse_mode='MarkdownV2')
    waiting_for_broadcast["photo"] = True

@bot.message_handler(content_types=['photo'])
def receive_broadcast_photo(message):
    """استقبال الصورة للرسالة الجماعية."""
    if waiting_for_broadcast.get("photo") and message.from_user.id == OWNER_ID:
        waiting_for_broadcast["photo_file_id"] = message.photo[-1].file_id
        waiting_for_broadcast["photo"] = False
        waiting_for_broadcast["awaiting_text"] = True
        # تهريب النص هنا أيضاً
        bot.send_message(message.chat.id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة\\.", parse_mode='MarkdownV2')

@bot.message_handler(func=lambda m: waiting_for_broadcast.get("awaiting_text") and m.from_user.id == OWNER_ID)
def receive_broadcast_text(message):
    """استقبال نص الرسالة الجماعية وإرسالها."""
    if waiting_for_broadcast.get("awaiting_text"):
        photo_id = waiting_for_broadcast.get("photo_file_id")
        text = message.text # النص الذي أرسله المالك
        
        # تهريب نص الرسالة الجماعية قبل إرساله للمستخدمين
        escaped_text_for_broadcast = telebot.formatting.escape_markdown(text)
        
        users = get_all_approved_users()
        sent_count = 0
        for user_id in users:
            try:
                bot.send_photo(user_id, photo_id, caption=escaped_text_for_broadcast, parse_mode='MarkdownV2') # تم إضافة parse_mode هنا
                sent_count += 1
            except Exception as e:
                print(f"Error sending broadcast to {user_id}: {e}")
                pass
        # تهريب النص هنا أيضاً
        bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم\\.", parse_mode='MarkdownV2')
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
