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

MONGODB_URI = os.environ.get("MONGODB_URI")

# إعداد MongoDB
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"]

# مجموعات (Collections)
users_col = db["users"] # ستخزن هنا بيانات المستخدمين وحالة اشتراكهم الإجباري

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
    
    # التأكد أن خطوة البداية لا تتجاوز عدد القنوات المتاحة
    if step >= len(true_subscribe_links):
        step = 0 # أعد تعيينها لتبدأ من البداية إذا كان قد أكملها

    all_channels_subscribed = True # علم للتحقق مما إذا كان المستخدم مشتركًا في كل القنوات
    
    for index in range(len(true_subscribe_links)): # التحقق من كل القنوات دائمًا
        current_channel_link = true_subscribe_links[index]
        try:
            channel_identifier = current_channel_link.split("t.me/")[-1]
            
            is_subscribed = False
            # في حال كانت القناة عامة (@username)
            if not channel_identifier.startswith('+'):
                channel_username = f"@{channel_identifier}" if not channel_identifier.startswith('@') else channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    is_subscribed = True
            else: # رابط دعوة خاص (يبدأ بـ +)
                # للروابط الخاصة، لا يمكن التحقق التلقائي بدون أن يكون البوت مشرفًا
                # الأفضل هنا هو مطالبة المستخدم بالضغط على الرابط ثم التحقق يدوياً
                # لذا، سنعتبر أنه لم يشترك حتى يضغط على الزر
                pass # سنترك is_subscribed كـ False وندفع المستخدم للضغط على الزر

            if not is_subscribed:
                all_channels_subscribed = False # المستخدم ليس مشتركًا في كل القنوات
                true_sub_pending[user_id] = index # احفظ الخطوة التي توقف عندها
                text = (
                    "🔔 لطفاً اشترك في القناة التالية واضغط على الزر أدناه للمتابعة:\n"
                    f"📮: {current_channel_link}"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
                bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                return # توقف هنا وانتظر تفاعل المستخدم
            
        except Exception as e:
            # يمكن أن يحدث خطأ إذا كانت القناة غير موجودة، أو البوت ليس مشرفًا، أو مشكلة في API
            print(f"❌ Error checking channel {current_channel_link} for user {user_id}: {e}")
            all_channels_subscribed = False # حدث خطأ، لذا لا يمكننا اعتبار المستخدم مشتركًا
            true_sub_pending[user_id] = index # ابقَ على نفس الخطوة ليحاول مرة أخرى
            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة: {current_channel_link}.\n"
                "يرجى التأكد أنك مشترك وأن البوت مشرف في القناة، ثم حاول الضغط على الزر مرة أخرى."
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
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"joined_true_subs": True, "first_name": first_name}},
            upsert=True
        )
        
        # استدعاء المنطق الفعلي بعد التحقق
        send_start_welcome_message(user_id, first_name)
    else:
        # إذا لم يكن مشتركًا في كل القنوات بعد التحقق، أعد توجيهه للخطوة الأولى
        true_sub_pending[user_id] = 0
        check_true_subscription(user_id, first_name)


---

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
    # هذه الخطوة تضمن أنه يمر بالتحقق في كل مرة يرسل /start
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


---

@bot.callback_query_handler(func=lambda call: call.data == "check_true_subscription")
def handle_check_true_subscription_callback(call):
    """
    معالج لـ callback_data "check_true_subscription"
    التي تُرسل عند الضغط على زر "لقد اشتركت، اضغط هنا للمتابعة".
    """
    bot.answer_callback_query(call.id, "جاري التحقق من اشتراكك...")
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم" # نحصل على الاسم من الكول باك
    check_true_subscription(user_id, first_name) # أعد التحقق من جميع القنوات الإجبارية


---

def check_user_true_subscription_status(user_id, first_name):
    """
    يقوم بالتحقق مما إذا كان المستخدم لا يزال مشتركًا في جميع قنوات الاشتراك الإجباري الحقيقي.
    """
    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined_true_subs", False):
        # لم يكن مشتركًا أبدًا أو فقد حالة الاشتراك، أعد توجيهه
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة.", reply_markup=main_keyboard())
        check_true_subscription(user_id, first_name)
        return False

    # تحقق من كل قناة إجبارية
    for channel_link in true_subscribe_links:
        try:
            channel_identifier = channel_link.split("t.me/")[-1]
            is_subscribed = False

            if not channel_identifier.startswith('+'): # قناة عامة
                channel_username = f"@{channel_identifier}" if not channel_identifier.startswith('@') else channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    is_subscribed = True
            else: # رابط دعوة خاص، نفترض أنه مشترك إذا كان قد اجتاز التحقق الأولي
                  # لكن لجعلها قوية، يجب أن يكون البوت مشرفًا في القناة الخاصة ليتحقق
                  # أو نعتمد على أن المستخدم يجب أن يعيد الضغط على زر التحقق
                # في هذه الحالة، إذا كان رابط خاص ولم يكن البوت مشرفًا، لا يمكننا التحقق بشكل موثوق
                # لذا، كحل بديل، إذا لم يكن البوت مشرفًا، سنطلب من المستخدم إعادة التحقق.
                # ولكن لغرض هذا المثال، سنفترض أن البوت يستطيع التحقق.
                # الأفضل هنا: ألا تعتمد على روابط الدعوة الخاصة للتحقق الإجباري
                pass # سنتركها كـ False ونجبر المستخدم على إعادة الاشتراك عبر check_true_subscription
            
            if not is_subscribed:
                # إذا لم يكن مشتركًا في أي قناة، قم بتحديث حالته في قاعدة البيانات وأعد توجيهه
                users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"joined_true_subs": False}}
                )
                bot.send_message(user_id, "⚠️ يبدو أنك ألغيت اشتراكك في إحدى القنوات الإجبارية. الرجاء إعادة الاشتراك والضغط على /start للمتابعة.", reply_markup=main_keyboard())
                check_true_subscription(user_id, first_name)
                return False
        except Exception as e:
            print(f"Error checking true subscription for user {user_id} in channel {channel_link}: {e}")
            # في حال وجود خطأ (القناة غير موجودة، البوت ليس مشرفًا، إلخ)، اعتبر أنه غير مشترك
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"joined_true_subs": False}}
            )
            bot.send_message(user_id, "⚠️ حدث خطأ أثناء التحقق من اشتراكك في القنوات الإجبارية. الرجاء الضغط على /start للمتابعة.", reply_markup=main_keyboard())
            check_true_subscription(user_id, first_name)
            return False
            
    # إذا وصل إلى هنا، فالمستخدم مشترك في جميع القنوات الإجبارية
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"joined_true_subs": True}}
    )
    return True


---

@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    """معالج لزر فيديوهات1."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    # التحقق من الاشتراك الإجباري أولاً
    if not check_user_true_subscription_status(user_id, first_name):
        return # إذا لم يكن مشتركًا أو حدث خطأ، الدالة check_user_true_subscription_status ستتعامل معه

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

    # التحقق من الاشتراك الإجباري أولاً
    if not check_user_true_subscription_status(user_id, first_name):
        return # إذا لم يكن مشتركًا أو حدث خطأ، الدالة check_user_true_subscription_status ستتعامل معه

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
    bot.answer_callback_query(call.id)  # لحل مشكلة الزر المعلق

    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    step = int(step_str) + 1
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    # هنا تحتاج إلى تنفيذ التحقق الفعلي من الاشتراك في القناة الحالية
    # يمكنك استخدام get_chat_member هنا لروابط القنوات التي يمكن التحقق منها
    # أو ببساطة المضي قدمًا إذا كانت هي الخطوة الأخيرة في سلسلة الاشتراك الاختياري

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
        
        # للحصول على جميع المستخدمين الذين اجتازوا الاشتراك الإجباري،
        # نستخدم users_col ونبحث عن joined_true_subs: True
        users_to_notify = users_col.find({"joined_true_subs": True})
        
        sent_count = 0
        for user_data in users_to_notify:
            user_id = user_data["user_id"]
            try:
                bot.send_photo(user_id, photo_id, caption=text)
                sent_count += 1
            except Exception as e:
                print(f"Error sending broadcast to {user_id}: {e}")
                # هنا يمكنك إضافة منطق لإزالة المستخدمين غير النشطين أو المحظورين
                pass
        bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.")
        waiting_for_broadcast.clear()

# --- Flask Web Server لتشغيل البوت على Render + UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    """المسار الرئيسي للخادم الويب."""
    return "Bot is running"

def run():
    """تشغيل خادم الويب."""
    # هذا هو التعديل المحتمل للخطأ على Render
    # Render يعين منفذًا عشوائيًا عبر متغير البيئة PORT
    port = int(os.environ.get("PORT", 3000)) 
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    """تشغيل الخادم في موضوع منفصل."""
    t = Thread(target=run)
    t.start()

keep_alive()
bot.infinity_polling()
