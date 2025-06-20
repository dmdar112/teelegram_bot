# استيراد المكتبات اللازمة
import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient

# --- متغيرات البيئة والثوابت (يجب تعيينها في بيئة النشر، مثل Render) ---
# توكن البوت الخاص بك من BotFather
TOKEN = os.environ.get("TOKEN")
# رقم آيدي التليجرام الخاص بالمالك (عدّله هنا)
OWNER_ID = 7054294622  # Replace with your actual owner ID

# آيدي القناة الخاصة بفيديوهات1 (تُستخدم لرفع الفيديوهات)
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")
# آيدي القناة الخاصة بفيديوهات2 (تُستخدم لرفع الفيديوهات)
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")

# رابط MongoDB Atlas الخاص بك
MONGODB_URI = os.environ.get("MONGODB_URI")

# اسم قاعدة البيانات
DB_NAME = "telegram_bot_db"

# --- متغيرات البوت العامة ---
bot = telebot.TeleBot(TOKEN)
maintenance_mode = False # هذا المتغير يتحكم بوضع صيانة فيديوهات2 فقط (True = وضع صيانة مفعل، False = وضع صيانة غير مفعل)

# قاموس مركزي لتتبع حالة المستخدمين في عمليات مختلفة
# {user_id: {"state_type": "delete_videos", "category": "v1", "videos": videos, "prompt_message_id": message_id, "context": "owner_main"}}
user_states = {}

# إعداد MongoDB
client = MongoClient(MONGODB_URI)
db = client[DB_NAME]

# مجموعات (Collections) في قاعدة البيانات
USERS_COL = db["users"] # لتخزين بيانات المستخدمين الأساسية (مثل حالة الانضمام)
APPROVED_V1_COL = db["approved_v1"] # لتخزين المستخدمين الموافق عليهم لقسم فيديوهات1
APPROVED_V2_COL = db["approved_v2"] # لتخزين المستخدمين الموافق عليهم لقسم فيديوهات2
NOTIFIED_USERS_COL = db["notified_users"] # لتخزين المستخدمين الذين تم إشعار المالك بهم
TRUE_SUBSCRIBE_CHANNELS_COL = db["true_subscribe_channels"] # المجموعة لقنوات الاشتراك الإجباري
OPTIONAL_SUBSCRIBE_CHANNELS_V1_COL = db["optional_subscribe_channels_v1"] # مجموعة قنوات الاشتراك الاختياري لفيديوهات1
OPTIONAL_SUBSCRIBE_CHANNELS_V2_COL = db["optional_subscribe_channels_v2"] # مجموعة قنوات الاشتراك الاختياري لفيديوهات2
NEW_FAKE_SUBSCRIBE_CHANNELS_COL = db["new_fake_subscribe_channels"] # مجموعة قنوات الاشتراك الوهمي الجديدة (مقترح)

# --- دوال مساعدة لتعامل مع قاعدة البيانات والقوائم ---

def get_collection_by_category(category):
    """
    يحصل على مجموعة MongoDB الصحيحة بناءً على الفئة.
    المدخلات: category (str) - فئة الفيديو (مثال: 'v1', 'v2') أو نوع القناة (مثال: 'true').
    المخرجات: pymongo.collection.Collection - مجموعة MongoDB.
    """
    if category == "v1":
        return db["videos_v1"]
    elif category == "v2":
        return db["videos_v2"]
    elif category == "true":
        return TRUE_SUBSCRIBE_CHANNELS_COL
    elif category == "optional_v1":
        return OPTIONAL_SUBSCRIBE_CHANNELS_V1_COL
    elif category == "optional_v2":
        return OPTIONAL_SUBSCRIBE_CHANNELS_V2_COL
    elif category == "new_fake": # للفئة الجديدة المقترحة
        return NEW_FAKE_SUBSCRIBE_CHANNELS_COL
    return None

def load_channel_links(collection):
    """
    تحميل روابط قنوات الاشتراك من مجموعة معينة في قاعدة البيانات.
    المدخلات: collection (pymongo.collection.Collection) - مجموعة القنوات.
    المخرجات: list - قائمة بالروابط.
    """
    return [doc["link"] for doc in collection.find()]

# تحميل القوائم العالمية لقنوات الاشتراك عند بدء البوت لأول مرة
# (سيتم تحديثها ديناميكيا عند الإضافة/الحذف)
true_subscribe_links = load_channel_links(TRUE_SUBSCRIBE_CHANNELS_COL)
subscribe_links_v1 = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V1_COL)
subscribe_links_v2 = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V2_COL)
# تحميل روابط القنوات الوهمية الجديدة
new_fake_subscribe_links = load_channel_links(NEW_FAKE_SUBSCRIBE_CHANNELS_COL)


def load_approved_users(collection):
    """
    تحميل المستخدمين الموافق عليهم من مجموعة معينة في قاعدة البيانات.
    المدخلات: collection (pymongo.collection.Collection) - مجموعة المستخدمين الموافق عليهم.
    المخرجات: set - مجموعة بمعرفات المستخدمين.
    """
    return set(doc["user_id"] for doc in collection.find())

def add_approved_user(collection, user_id):
    """
    إضافة مستخدم موافق عليه إلى مجموعة معينة في قاعدة البيانات إذا لم يكن موجوداً.
    المدخلات:
        collection (pymongo.collection.Collection) - مجموعة المستخدمين الموافق عليهم.
        user_id (int) - معرف المستخدم.
    """
    if not collection.find_one({"user_id": user_id}):
        collection.insert_one({"user_id": user_id})

def remove_approved_user(collection, user_id):
    """
    إزالة مستخدم موافق عليه من مجموعة معينة في قاعدة البيانات.
    المدخلات:
        collection (pymongo.collection.Collection) - مجموعة المستخدمين الموافق عليهم.
        user_id (int) - معرف المستخدم.
    """
    collection.delete_one({"user_id": user_id})

def has_notified(user_id):
    """
    التحقق مما إذا كان المستخدم قد تم إبلاغ المالك به من قبل.
    المدخلات: user_id (int) - معرف المستخدم.
    المخرجات: bool - صحيح إذا تم إبلاغ المالك، خطأ خلاف ذلك.
    """
    return NOTIFIED_USERS_COL.find_one({"user_id": user_id}) is not None

def add_notified_user(user_id):
    """
    إضافة مستخدم إلى قائمة المستخدمين الذين تم إبلاغ المالك بهم.
    المدخلات: user_id (int) - معرف المستخدم.
    """
    if not has_notified(user_id):
        NOTIFIED_USERS_COL.insert_one({"user_id": user_id})

def get_all_approved_users():
    """
    الحصول على جميع المستخدمين الموافق عليهم من كلا القسمين (فيديوهات1 و فيديوهات2).
    المخرجات: set - مجموعة بمعرفات جميع المستخدمين الموافق عليهم.
    """
    return load_approved_users(APPROVED_V1_COL).union(load_approved_users(APPROVED_V2_COL))

def delete_prompt_message(user_id):
    """
    يحذف رسالة الطلب السابقة إذا كانت موجودة في حالة المستخدم.
    المدخلات: user_id (int) - معرف المستخدم.
    """
    state_data = user_states.get(user_id)
    if state_data and "prompt_message_id" in state_data:
        try:
            bot.delete_message(chat_id=user_id, message_id=state_data["prompt_message_id"])
        except Exception as e:
            print(f"خطأ في حذف رسالة الطلب: {e}")
        state_data.pop("prompt_message_id", None) # إزالة معرف الرسالة بعد الحذف

# --- دوال لإنشاء لوحات المفاتيح (Keyboards) ---
def main_keyboard():
    """إنشاء لوحة المفاتيح الرئيسية للمستخدم العادي."""
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("مقاطع1/🤤🫦🇸🇯"), types.KeyboardButton("مقاطع2/🤤🫦🇺🇸")
    )

def owner_keyboard():
    """إنشاء لوحة مفاتيح المالك مع أزرار التحكم المختلفة."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("إدارة قنوات الاشتراك") # زر موحد لإدارة كل من الاختياري والإجباري
    markup.row("حذف فيديوهات1", "حذف فيديوهات2")
    markup.row("رفع فيديوهات1", "رفع فيديوهات2")
    markup.row("تنظيف فيديوهات1", "تنظيف فيديوهات2")
    markup.row("تفعيل صيانة فيديوهات2", "إيقاف صيانة فيديوهات2")
    markup.row("رسالة جماعية مع صورة")
    return markup

def get_back_markup():
    """ينشئ لوحة مفاتيح بسيطة بزر "رجوع"."""
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))
    return back_markup

def send_videos(user_id, category):
    """
    إرسال الفيديوهات من قسم معين إلى المستخدم.
    المدخلات:
        user_id (int) - معرف المستخدم.
        category (str) - فئة الفيديو ('v1' أو 'v2').
    """
    videos_collection = get_collection_by_category(category)
    videos = list(videos_collection.find()) # جلب جميع الفيديوهات من المجموعة المحددة

    if not videos:
        bot.send_message(user_id, "❌ لا توجد فيديوهات حالياً في هذا القسم.")
        return

    for video in videos:
        try:
            # استخدام copy_message بدلاً من send_video للحفاظ على جودة الفيديو الأصلي
            bot.copy_message(
                chat_id=user_id,
                from_chat_id=video["chat_id"],
                message_id=video["message_id"],
                caption="", # إزالة الكابشن الأصلي
                caption_entities=None # إزالة الكابشن الأصلي
            )
            time.sleep(0.5)  # تأخير لمنع الحظر أو التقييد من تيليجرام
        except Exception as e:
            print(f"❌ خطأ أثناء إرسال الفيديو للمستخدم {user_id}: {e}")

# --- معالجات الأوامر والرسائل (Handlers) ---

# معالج لزر "حذف فيديوهات1" و "حذف فيديوهات2" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text in ["حذف فيديوهات1", "حذف فيديوهات2"] and m.from_user.id == OWNER_ID)
def delete_videos_button_handler(message):
    """
    معالج لزر حذف فيديوهات1 أو فيديوهات2. يعرض قائمة بالفيديوهات للبدء في عملية الحذف.
    """
    user_id = message.from_user.id
    category = "v1" if message.text == "حذف فيديوهات1" else "v2"
    
    db_videos_col = get_collection_by_category(category)
    videos = list(db_videos_col.find().limit(20)) # عرض أول 20 فيديو

    if not videos:
        bot.send_message(user_id, f"لا يوجد فيديوهات في فيديوهات{category[-1].upper()}.", reply_markup=owner_keyboard())
        user_states.pop(user_id, None) # إزالة حالة الانتظار إذا لم يكن هناك فيديوهات للحذف
        return

    text = f"📋 قائمة فيديوهات{category[-1].upper()}:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."

    # إرسال الرسالة مع لوحة المفاتيح الجديدة
    sent_message = bot.send_message(user_id, text, reply_markup=get_back_markup())
    # تحديث user_states لتخزين message_id والسياق للعودة الصحيحة
    user_states[user_id] = {
        "state_type": "delete_videos",
        "category": category,
        "videos": videos,
        "prompt_message_id": sent_message.message_id,
        "context": "owner_main"
    }

# معالج لزر "رجوع" (يستخدم في حالات مختلفة للعودة للقائمة السابقة)
@bot.message_handler(func=lambda m: m.text == "رجوع" and m.from_user.id in user_states)
def handle_back_command(message):
    """
    معالج لزر الرجوع أثناء عملية الحذف أو إدارة القنوات أو الرفع أو الرسالة الجماعية.
    """
    user_id = message.from_user.id
    state_data = user_states.pop(user_id, None)

    if not state_data:
        bot.send_message(user_id, "لا توجد عملية جارية للرجوع منها.", reply_markup=owner_keyboard())
        return

    # حذف الرسالة السابقة التي تحتوي على السؤال (إذا كانت موجودة)
    delete_prompt_message(user_id)

    context = state_data.get("context")
    
    if context == "owner_main":
        bot.send_message(user_id, "تم الرجوع إلى القائمة الرئيسية", reply_markup=owner_keyboard())
    elif context == "true_sub_management":
        # إعادة عرض قائمة إدارة قنوات الاشتراك الحقيقي الإجباري
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("إضافة قناة", callback_data="add_channel_true"),
            types.InlineKeyboardButton("حذف قناة", callback_data="delete_channel_true"),
            types.InlineKeyboardButton("عرض القنوات", callback_data="view_channels_true")
        )
        markup.add(types.InlineKeyboardButton("رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الحقيقي الإجباري. اختر إجراءً:", reply_markup=markup)
    elif context == "fake_sub_management":
        # إعادة عرض قائمة إدارة قنوات الاشتراك الوهمي
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات1)", callback_data="add_channel_optional_v1"),
            types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_optional_v2")
        )
        markup.add(
            types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات1)", callback_data="delete_channel_optional_v1"),
            types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_optional_v2")
        )
        markup.add(
            types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات1)", callback_data="view_channels_optional_v1"),
            types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_optional_v2")
        )
        markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي. اختر إجراءً:", reply_markup=markup)
    else:
        bot.send_message(user_id, "تم إلغاء العملية.", reply_markup=owner_keyboard())


# معالج لاختيار الفيديو المراد حذفه من قبل المالك
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and user_states.get(m.from_user.id, {}).get("state_type") == "delete_videos")
def handle_delete_choice(message):
    """
    معالج لاختيار الفيديو المراد حذفه من قبل المالك، ويقوم بحذف الفيديو من القناة وقاعدة البيانات.
    """
    user_id = message.from_user.id
    state_data = user_states.get(user_id)

    # حذف الرسالة السابقة التي تطلب الرقم (القائمة الأصلية)
    delete_prompt_message(user_id)

    category = state_data["category"]
    videos_to_process = state_data["videos"] # القائمة الأصلية التي عرضناها للمالك
    
    try:
        choice = int(message.text)
        if not (1 <= choice <= len(videos_to_process)):
            raise ValueError("الرقم غير صحيح.")

        video_to_delete = videos_to_process[choice - 1]
        chat_id = video_to_delete["chat_id"]
        message_id = video_to_delete["message_id"]

        try:
            bot.delete_message(chat_id, message_id)
        except telebot.apihelper.ApiTelegramException as e:
            if "message to delete not found" in str(e):
                print(f"تحذير: الرسالة {message_id} محذوفة بالفعل من القناة {chat_id}.")
            else:
                raise e # أعد إثارة أي أخطاء أخرى
        
        # حذف السجل من قاعدة البيانات
        db_videos_col = get_collection_by_category(category)
        db_videos_col.delete_one({"message_id": message_id})

        bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} بنجاح.")
        
        # إعادة جلب القائمة المحدثة من قاعدة البيانات
        updated_videos = list(db_videos_col.find().limit(20))

        if updated_videos:
            text = f"📋 قائمة فيديوهات{category[-1].upper()} المتبقية:\n"
            for i, vid in enumerate(updated_videos, 1):
                text += f"{i}. رسالة رقم: {vid['message_id']}\n"
            text += "\nأرسل رقم الفيديو التالي الذي تريد حذفه."
            
            sent_message = bot.send_message(user_id, text, reply_markup=get_back_markup())
            user_states[user_id].update({
                "videos": updated_videos,
                "prompt_message_id": sent_message.message_id
            })
        else:
            bot.send_message(user_id, f"✅ تم حذف جميع الفيديوهات في قسم فيديوهات{category[-1].upper()}.", reply_markup=owner_keyboard())
            user_states.pop(user_id) # إزالة من حالة الانتظار

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح أو رقم غير صحيح، حاول مرة أخرى.")
        # إعادة عرض القائمة للسماح بالمحاولة مرة أخرى
        db_videos_col = get_collection_by_category(category)
        current_videos = list(db_videos_col.find().limit(20))
        if current_videos:
            text = f"📋 قائمة فيديوهات{category[-1].upper()}:\n"
            for i, vid in enumerate(current_videos, 1):
                text += f"{i}. رسالة رقم: {vid['message_id']}\n"
            text += "\nأرسل رقم الفيديو الذي تريد حذفه."
            sent_message = bot.send_message(user_id, text, reply_markup=get_back_markup())
            user_states[user_id].update({
                "videos": current_videos,
                "prompt_message_id": sent_message.message_id
            })
        else:
            bot.send_message(user_id, "لا توجد فيديوهات في هذا القسم.", reply_markup=owner_keyboard())
            user_states.pop(user_id) # إزالة من حالة الانتظار

# معالج زر "تنظيف فيديوهات1" و "تنظيف فيديوهات2" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text in ["تنظيف فيديوهات1", "تنظيف فيديوهات2"] and m.from_user.id == OWNER_ID)
def clean_videos_button_handler(message):
    """
    معالج لزر تنظيف فيديوهات1 أو فيديوهات2. يقوم بحذف سجلات الفيديوهات من قاعدة البيانات إذا لم تعد موجودة في القناة.
    """
    user_id = message.from_user.id
    category = "v1" if message.text == "تنظيف فيديوهات1" else "v2"
    
    db_videos_col = get_collection_by_category(category)
    channel_id = CHANNEL_ID_V1 if category == "v1" else CHANNEL_ID_V2

    bot.send_message(user_id, f"جاري تنظيف فيديوهات{category[-1].upper()}... قد يستغرق هذا بعض الوقت.")

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            # نحاول توجيه الرسالة إلى المالك، إذا فشل يعني أن الرسالة محذوفة من القناة
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
            # نحذف الرسالة التي تم توجيهها للمالك لتنظيف الدردشة
            bot.delete_message(chat_id=user_id, message_id=bot.last_message_id) # هذا قد لا يعمل في كل الحالات
        except Exception as e:
            # لو فشل، احذف الفيديو من قاعدة البيانات لأنه غير موجود بالقناة
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات{category[-1].upper()}. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_keyboard())

def check_true_subscription(user_id, first_name):
    """
    يقوم بالتحقق من جميع قنوات الاشتراك الإجباري (true_subscribe_links) بشكل متسلسل.
    ويدفع المستخدم للاشتراك في القناة التالية إذا لم يكن مشتركًا.
    بعد الانتهاء، يستدعي دالة prompt_new_fake_subscription.
    المدخلات:
        user_id (int) - معرف المستخدم.
        first_name (str) - الاسم الأول للمستخدم.
    المخرجات: bool - صحيح إذا أكمل المستخدم جميع الاشتراكات الإجبارية، خطأ خلاف ذلك.
    """
    global true_subscribe_links # تأكد من استخدام أحدث قائمة
    true_subscribe_links = load_channel_links(TRUE_SUBSCRIBE_CHANNELS_COL) # إعادة تحميل القائمة في كل مرة للتحقق من التحديثات

    if not true_subscribe_links: # إذا لم تكن هناك قنوات اشتراك إجباري معرفة
        prompt_new_fake_subscription(user_id, first_name)
        return True
    
    # تهيئة الخطوة الحالية: إذا لم يكن المستخدم موجودًا في user_states أو كانت حالته ليست true_sub_pending
    state_data = user_states.get(user_id)
    step = state_data.get("step", 0) if state_data and state_data.get("state_type") == "true_sub_pending" else 0
    
    all_channels_subscribed = True
    for index in range(step, len(true_subscribe_links)):
        current_channel_link = true_subscribe_links[index]
        try:
            channel_identifier = current_channel_link.split("t.me/")[-1]
            
            # التحقق فقط للقنوات العامة التي تبدأ بـ @
            if not channel_identifier.startswith('+'):
                channel_username = f"@{channel_identifier}" if not channel_identifier.startswith('@') else channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    all_channels_subscribed = False
                    user_states[user_id] = {"state_type": "true_sub_pending", "step": index} # احفظ الخطوة
                    text = (
                        "🚸| عذراً عزيزي .\n"
                        "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه\n\n"
                        f"- {current_channel_link}\n\n"
                        "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
                    )
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("✅ بعد الاشتراك، اضغط هنا للمتابعة ✅", callback_data="check_true_subscription"))
                    bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                    return False
            else: # رابط دعوة خاص (يبدأ بـ +) - لا يمكن للبوت التحقق منه مباشرة
                # في هذه الحالة، نفترض أن المستخدم يحتاج للاشتراك ونطلب منه ذلك
                all_channels_subscribed = False
                user_states[user_id] = {"state_type": "true_sub_pending", "step": index} # احفظ الخطوة
                text = (
                    "🚸| عذراً عزيزي .\n"
                    "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه\n\n"
                    f"- {current_channel_link}\n\n"
                    "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
                bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                return False
            
            # إذا كان مشتركًا أو تم تجاوز فحص القناة الخاصة بنجاح، استمر في الحلقة
            user_states[user_id] = {"state_type": "true_sub_pending", "step": index + 1} # تحديث الخطوة للقناة التالية

        except Exception as e:
            print(f"❌ خطأ أثناء التحقق من القناة {current_channel_link} للمستخدم {user_id}: {e}")
            all_channels_subscribed = False
            user_states[user_id] = {"state_type": "true_sub_pending", "step": index} # ابقَ على نفس الخطوة ليحاول مرة أخرى
            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة: {current_channel_link}.\n"
                "يرجى التأكد أنك مشترك وأن البوت مشرف في القناة (إذا كانت خاصة)، ثم حاول الضغط على الزر مرة أخرى."
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
            bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
            return False

    # إذا وصل الكود إلى هنا، فهذا يعني أن المستخدم مشترك في جميع القنوات بنجاح
    if all_channels_subscribed:
        user_states.pop(user_id, None) # إزالة المستخدم بعد اكتمال التحقق
        
        # تحديث حالة الاشتراك في قاعدة البيانات
        user_data_db = USERS_COL.find_one({"user_id": user_id})
        if not user_data_db:
            USERS_COL.insert_one({"user_id": user_id, "joined": True, "first_name": first_name})
        else:
            USERS_COL.update_one({"user_id": user_id}, {"$set": {"joined": True, "first_name": first_name}})

        # بعد اكتمال الاشتراك الإجباري، ننتقل إلى الاشتراك الوهمي الجديد.
        prompt_new_fake_subscription(user_id, first_name)
        return True
    else:
        # إذا لم يكن مشتركاً في جميع القنوات بعد، نقوم بتحديث حالة joined إلى False
        user_data_db = USERS_COL.find_one({"user_id": user_id})
        if user_data_db and user_data_db.get("joined", False):
            USERS_COL.update_one({"user_id": user_id}, {"$set": {"joined": False}})
        return False

def prompt_new_fake_subscription(user_id, first_name):
    """
    تعرض رسالة الاشتراك الوهمي الاختياري بعد إكمال المستخدم للاشتراك الإجباري الحقيقي.
    ملاحظة: هذه الروابط يجب أن تُدار من خلال لوحة تحكم المالك أيضاً، بدلاً من أن تكون مكتوبة يدوياً.
    المدخلات:
        user_id (int) - معرف المستخدم.
        first_name (str) - الاسم الأول للمستخدم.
    """
    global new_fake_subscribe_links
    new_fake_subscribe_links = load_channel_links(NEW_FAKE_SUBSCRIBE_CHANNELS_COL) # تحميل الروابط من القاعدة

    if not new_fake_subscribe_links:
        send_start_welcome_message(user_id, first_name)
        return

    text = (
        "✅ تهانينا! لقد أكملت اشتراكك الإجباري.\n"
        "للوصول إلى جميع الميزات، يرجى الانضمام إلى هذه القنوات الإضافية (اختياري).\n\n"
        "يرجى الاشتراك في القنوات التالية:\n"
    )
    markup = types.InlineKeyboardMarkup()
    for link in new_fake_subscribe_links:
        text += f"- {link}\n"

    markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة ✅", callback_data=f"check_final_fake_sub_{user_id}"))
    bot.send_message(user_id, text, reply_markup=markup, disable_web_page_preview=True)


# معالج لأمر /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    """
    معالج لأمر /start. يتحقق مما إذا كان المستخدم هو المالك أو يبدأ عملية التحقق من الاشتراك.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم جديد"

    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
        user_states.pop(user_id, None) # إزالة أي حالة سابقة للمالك
        return

    bot.send_message(user_id, f"أهلاً بك/🔥 {first_name} 🇦🇱! يرجى إكمال الاشتراك في القنوات الإجبارية للوصول إلى البوت.", reply_markup=types.ReplyKeyboardRemove())
    
    check_true_subscription(user_id, first_name) # بدء عملية الاشتراك الإجباري والوهمي الجديد

def send_start_welcome_message(user_id, first_name):
    """
    المنطق الفعلي لدالة /start بعد التحقق من الاشتراك في القنوات الإجبارية. ترسل رسالة الترحيب وتُشعر المالك.
    المدخلات:
        user_id (int) - معرف المستخدم.
        first_name (str) - الاسم الأول للمستخدم.
    """
    bot.send_message(user_id, "🤤🇺🇸🇸🇯اختر قسم الفيديوهات من الأزرار بالأسفل!", reply_markup=main_keyboard())

    # إشعار المالك بالمستخدم الجديد
    if not has_notified(user_id):
        total_users = len(get_all_approved_users())
        bot.send_message(OWNER_ID, f"""⚠️تم دخول شخص جديد إلى البوت⚠️

• الاسم : {first_name}
• الايدي : {user_id}
• عدد الأعضاء الكلي: {total_users}
""")
        add_notified_user(user_id)

# معالج لـ callback_data "check_true_subscription"
@bot.callback_query_handler(func=lambda call: call.data == "check_true_subscription")
def handle_check_true_subscription_callback(call):
    """
    معالج لزر "لقد اشتركت، اضغط هنا للمتابعة" بعد الاشتراك الإجباري.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id, "جاري التحقق من اشتراكك...")
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم"
    check_true_subscription(user_id, first_name) # إعادة التحقق

# معالج لـ callback_data "check_final_fake_sub_"
@bot.callback_query_handler(func=lambda call: call.data.startswith("check_final_fake_sub_"))
def handle_final_fake_sub_check(call):
    """
    معالج لزر "لقد اشتركت، اضغط هنا للمتابعة" بعد الاشتراك الوهمي الجديد.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id, "جاري التحقق والموافقة...")
    user_id = call.from_user.id

    # بدلاً من التحقق الفعلي من الاشتراك (الذي قد يكون معقدًا للقنوات الخاصة)،
    # سنرسل إشعارًا للمالك للموافقة يدوياً.
    notify_owner_for_approval(user_id, call.from_user.first_name, "post_true_sub_fake") # فئة جديدة للموافقة
    bot.edit_message_text(
        "⏳ تم إرسال طلبك للموافقة. يرجى الانتظار قليلاً.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

# معالج لزر "مقاطع1/🤤🫦🇸🇯"
@bot.message_handler(func=lambda m: m.text == "مقاطع1/🤤🫦🇸🇯")
def handle_v1(message):
    """
    معالج لزر فيديوهات1. يتحقق من حالة اشتراك المستخدم ويرسل الفيديوهات.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    user_data_db = USERS_COL.find_one({"user_id": user_id})
    # التحقق من أن المستخدم قد أكمل الاشتراك الإجباري وقبل المالك اشتراكه الوهمي الجديد
    if not user_data_db or not user_data_db.get("joined", False) or user_id not in load_approved_users(APPROVED_V1_COL):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات المطلوبة أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name)
        return

    send_videos(user_id, "v1")

# معالج لزر "مقاطع2/🤤🫦🇺🇸"
@bot.message_handler(func=lambda m: m.text == "مقاطع2/🤤🫦🇺🇸")
def handle_v2(message):
    """
    معالج لزر فيديوهات2. يتحقق من وضع الصيانة، حالة اشتراك المستخدم، ويرسل الفيديوهات أو يطلب الاشتراك الاختياري.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    user_data_db = USERS_COL.find_one({"user_id": user_id})
    # التحقق من أن المستخدم قد أكمل الاشتراك الإجباري (وتمت الموافقة عليه للاشتراك الوهمي الجديد)
    if not user_data_db or not user_data_db.get("joined", False) or user_id not in load_approved_users(APPROVED_V1_COL):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات المطلوبة أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name)
        return

    global maintenance_mode
    if maintenance_mode and user_id != OWNER_ID:
        bot.send_message(user_id, "قريباً سيتم اضافة مقاطع في زر مقاطع/2‼️")
        return

    if user_id in load_approved_users(APPROVED_V2_COL):
        send_videos(user_id, "v2")
    else:
        bot.send_message(user_id, "👋 أهلاً بك في قسم فيديوهات 2!\nللوصول إلى الفيديوهات، الرجاء الاشتراك في القنوات التالية:")
        user_states[user_id] = {"state_type": "optional_check", "category": "v2", "step": 0}
        send_required_links(user_id, "v2")

def send_required_links(chat_id, category):
    """
    إرسال روابط الاشتراك الاختياري المطلوبة للمستخدم بشكل متسلسل.
    ملاحظة: هذه الدالة الآن مخصصة فقط لقنوات فيديوهات2 الاختيارية (حسب منطق المستخدم).
    المدخلات:
        chat_id (int) - معرف الدردشة.
        category (str) - فئة الفيديو ('v2' فقط هنا).
    """
    global subscribe_links_v2
    subscribe_links_v2 = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V2_COL)

    state_data = user_states.get(chat_id, {"state_type": "optional_check", "category": category, "step": 0})
    step = state_data["step"]
    links = subscribe_links_v2

    if not links:
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة (لا توجد قنوات اشتراك حالياً لهذا القسم). الرجاء الانتظار.", reply_markup=main_keyboard())
        user_states.pop(chat_id, None)
        return

    if step >= len(links):
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة. الرجاء الانتظار.", reply_markup=main_keyboard())
        user_states.pop(chat_id, None)
        return

    link = links[step]

    text = (
    "🚸| عذراً عزيزي .\n"
    "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه\n\n"
    f"- {link}\n\n"
    "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ بعد الاشتراك، اضغط هنا للمتابعة ✅", callback_data=f"verify_{category}_{step}"))
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

    user_states[chat_id] = {"state_type": "optional_check", "category": category, "step": step}

# معالج للتحقق من الاشتراك عبر الأزرار (بعد الضغط على "تحقق الآن")
@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    """
    معالج للتحقق من الاشتراك الاختياري عبر الأزرار. ينقل المستخدم للقناة التالية أو يطلب الموافقة.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)

    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    step = int(step_str) + 1
    
    links = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V2_COL)

    if step < len(links):
        user_states[user_id] = {"state_type": "optional_check", "category": category, "step": step}
        send_required_links(user_id, category)
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔴 إذا كنت غير مشترك، اضغط هنا 🔴", callback_data=f"resend_{category}")
        )
        bot.send_message(
            user_id,
            "⏳ يرجى الانتظار قليلاً حتى نتحقق من اشتراكك في جميع القنوات.\n"
            "إذا كنت مشتركًا سيتم قبولك تلقائيًا، وإذا كنت غير مشترك سيتم رفضك ولا يمكنك الوصول للمقاطع ‼️",
            reply_markup=markup
        )
        notify_owner_for_approval(user_id, call.from_user.first_name, category)
        user_states.pop(user_id, None)

# إعادة إرسال روابط الاشتراك عند طلب المستخدم (إذا لم يكملها)
@bot.callback_query_handler(func=lambda call: call.data.startswith("resend_"))
def resend_links(call):
    """
    إعادة إرسال روابط الاشتراك الاختياري عند طلب المستخدم (عادة بعد فشل التحقق).
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)

    user_id = call.from_user.id
    category = call.data.split("_")[1]
    
    user_states[user_id] = {"state_type": "optional_check", "category": category, "step": 0}
    send_required_links(user_id, category)

def notify_owner_for_approval(user_id, name, category):
    """
    إرسال إشعار للمالك بطلب انضمام جديد لمراجعتها (لقبول أو رفض الوصول).
    الفئات الممكنة: "v2" (للاشتراك الوهمي الخاص بمقاطع2)، "post_true_sub_fake" (للاشتراك الوهمي الجديد بعد الإجباري).
    المدخلات:
        user_id (int) - معرف المستخدم.
        name (str) - اسم المستخدم.
        category (str) - فئة الموافقة المطلوبة.
    """
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("✅ قبول المستخدم", callback_data=f"approve_{category}_{user_id}"),
        types.InlineKeyboardButton("❌ رفض المستخدم", callback_data=f"reject_{category}_{user_id}")
    )
    message_text = (
        f"📥 طلب انضمام جديد\n"
        f"👤 الاسم: {name}\n"
        f"🆔 الآيدي: {user_id}\n"
        f"📁 الفئة: {category}"
    )
    bot.send_message(OWNER_ID, message_text, reply_markup=keyboard)

# معالج لاستجابة المالك (قبول أو رفض المستخدم)
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_owner_response(call):
    """
    معالج لاستجابة المالك (قبول أو رفض). يقوم بتحديث حالة المستخدم وإرسال إشعار له.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    parts = call.data.split("_", 2)
    action, category, user_id_str = parts[0], parts[1], parts[2]
    user_id = int(user_id_str)

    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🚫 غير مصرح لك بالقيام بهذا الإجراء.")
        return

    if action == "approve":
        if category == "v2":
            add_approved_user(APPROVED_V2_COL, user_id)
            bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة! يمكنك الآن الوصول إلى قسم مقاطع2.")
        elif category == "post_true_sub_fake":
            add_approved_user(APPROVED_V1_COL, user_id)
            bot.send_message(user_id, "🤤🇺🇸🇸🇯اختر قسم الفيديوهات من الأزرار بالأسفل!", reply_markup=main_keyboard())
            if not has_notified(user_id):
                total_users = len(get_all_approved_users())
                bot.send_message(OWNER_ID, f"""⚠️تم دخول شخص جديد إلى البوت⚠️\n\n• الاسم : {call.from_user.first_name}\n• الايدي : {user_id}\n• عدد الأعضاء الكلي: {total_users}\n""")
                add_notified_user(user_id)
        
        bot.edit_message_text("✅ تم قبول المستخدم.", call.message.chat.id, call.message.message_id)
    else: # action == "reject"
        bot.send_message(user_id, "❌ لم يتم قبولك. الرجاء الاشتراك في جميع قنوات البوت ثم أرسل /start مرة أخرى.")
        bot.edit_message_text("❌ تم رفض المستخدم.", call.message.chat.id, call.message.message_id)

# معالج لزر "رفع فيديوهات1" و "رفع فيديوهات2" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text in ["رفع فيديوهات1", "رفع فيديوهات2"] and m.from_user.id == OWNER_ID)
def set_upload_mode_button_handler(message):
    """
    تعيين وضع الرفع لقسم فيديوهات1 أو فيديوهات2. يطلب من المالك إرسال الفيديوهات.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    category = "v1" if message.text == "رفع فيديوهات1" else "v2"
    
    sent_message = bot.reply_to(message, f"✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات{category[-1].upper()}.\nأرسل 'رجوع' للعودة.", reply_markup=get_back_markup())
    user_states[user_id] = {
        'state_type': 'owner_upload_mode',
        'category': category,
        'prompt_message_id': sent_message.message_id,
        'context': 'owner_main'
    }

# معالج لرفع الفيديوهات من قبل المالك
@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    """
    معالج لاستقبال الفيديوهات التي يرفعها المالك وحفظها في القناة المخصصة وقاعدة البيانات.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    mode_data = user_states.get(user_id)

    if user_id != OWNER_ID or not (mode_data and mode_data.get("state_type") == "owner_upload_mode"):
        return

    category = mode_data['category']
    delete_prompt_message(user_id) # حذف رسالة الطلب السابقة

    try:
        channel_id = CHANNEL_ID_V1 if category == "v1" else CHANNEL_ID_V2
        sent = bot.send_video(
            chat_id=channel_id,
            video=message.video.file_id,
            caption=f"📥 فيديو جديد من المالك - قسم {category.upper()}",
        )
        # تخزين تفاصيل الفيديو في قاعدة البيانات
        get_collection_by_category(category).insert_one({
            "chat_id": sent.chat.id,
            "message_id": sent.message_id
        })

        sent_message = bot.reply_to(message, f"✅ تم حفظ الفيديو في قسم {category.upper()}.\nيمكنك إرسال فيديو آخر أو أرسل 'رجوع' للعودة.", reply_markup=get_back_markup())
        user_states[user_id]['prompt_message_id'] = sent_message.message_id
        # لا نخرج من وضع الرفع هنا، بل نسمح له برفع المزيد من الفيديوهات

    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو.", reply_markup=owner_keyboard())
        user_states.pop(user_id, None)

# معالج لزر "رسالة جماعية مع صورة" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "رسالة جماعية مع صورة" and m.from_user.id == OWNER_ID)
def ask_broadcast_photo(message):
    """
    طلب صورة لرسالة جماعية من المالك.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    sent_message = bot.send_message(user_id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.\nأو أرسل 'رجوع' للعودة.", reply_markup=get_back_markup())
    user_states[user_id] = {
        "state_type": "broadcast_photo",
        "awaiting_photo": True,
        "prompt_message_id": sent_message.message_id,
        "context": "owner_main"
    }

# معالج لاستقبال الصورة للرسالة الجماعية من المالك
@bot.message_handler(content_types=['photo'])
def receive_broadcast_photo(message):
    """
    استقبال الصورة للرسالة الجماعية من المالك، ثم طلب النص.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    state_data = user_states.get(user_id)

    if user_id == OWNER_ID and state_data and state_data.get("state_type") == "broadcast_photo" and state_data.get("awaiting_photo"):
        delete_prompt_message(user_id)

        user_states[user_id].update({
            "photo_file_id": message.photo[-1].file_id,
            "awaiting_photo": False,
            "awaiting_text": True
        })

        sent_message = bot.send_message(user_id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة.\nأو أرسل 'رجوع' للعودة.", reply_markup=get_back_markup())
        user_states[user_id]["prompt_message_id"] = sent_message.message_id
    else:
        # إذا لم يكن في حالة انتظار الصورة للبث، تجاهل الصورة
        pass

# معالج لاستقبال نص الرسالة الجماعية وإرسالها لجميع المستخدمين الموافق عليهم
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and user_states.get(m.from_user.id, {}).get("state_type") == "broadcast_photo" and user_states[m.from_user.id].get("awaiting_text"))
def receive_broadcast_text(message):
    """
    استقبال نص الرسالة الجماعية وإرسالها لجميع المستخدمين الموافق عليهم.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    state_data = user_states.get(user_id)

    if state_data and state_data.get("awaiting_text"):
        delete_prompt_message(user_id)

        photo_id = state_data.get("photo_file_id")
        text = message.text
        users = get_all_approved_users()
        sent_count = 0
        for uid in users:
            try:
                bot.send_photo(uid, photo_id, caption=text)
                sent_count += 1
                time.sleep(0.1) # لتجنب تجاوز حدود معدل تيليجرام
            except Exception as e:
                print(f"خطأ في إرسال الرسالة الجماعية للمستخدم {uid}: {e}")
                pass
        bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.", reply_markup=owner_keyboard())
        user_states.pop(user_id, None)

# --- إدارة القنوات الموحدة للمالك ---

# معالج لزر "إدارة قنوات الاشتراك" (الرئيسي للمالك)
@bot.message_handler(func=lambda m: m.text == "إدارة قنوات الاشتراك" and m.from_user.id == OWNER_ID)
def manage_all_subscription_channels_menu(message):
    """
    يعرض القائمة الرئيسية لإدارة قنوات الاشتراك (الاشتراك الإجباري والوهمي).
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("اشتراك حقيقي إجباري", callback_data="manage_true_sub_channels"),
        types.InlineKeyboardButton("اشتراك وهمي (فيديوهات 1 و 2)", callback_data="manage_fake_sub_channels")
    )
    markup.add(types.InlineKeyboardButton("إدارة قنوات الاشتراك الوهمي الجديدة", callback_data="manage_new_fake_sub_channels")) # زر جديد
    markup.add(types.InlineKeyboardButton("رجوع إلى القائمة الرئيسية", callback_data="back_to_owner_main_keyboard"))
    bot.send_message(user_id, "اختر نوع قنوات الاشتراك التي تريد إدارتها:", reply_markup=markup)

# معالج لزر "رجوع إلى القائمة الرئيسية" من قائمة إدارة قنوات الاشتراك الرئيسية
@bot.callback_query_handler(func=lambda call: call.data == "back_to_owner_main_keyboard")
def handle_back_to_owner_main_keyboard(call):
    """
    معالج زر 'رجوع إلى القائمة الرئيسية' من قائمة إدارة قنوات الاشتراك الرئيسية.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    try:
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception as e:
        print(f"خطأ في حذف الرسالة عند الرجوع للقائمة الرئيسية للمالك: {e}")
    bot.send_message(user_id, "تم الرجوع إلى القائمة الرئيسية للمالك.", reply_markup=owner_keyboard())

# معالج لزر "اشتراك حقيقي إجباري"
@bot.callback_query_handler(func=lambda call: call.data == "manage_true_sub_channels")
def manage_true_sub_channels(call):
    """
    يعرض خيارات إدارة قنوات الاشتراك الإجباري (إضافة، حذف، عرض).
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("إضافة قناة", callback_data="add_channel_true"),
        types.InlineKeyboardButton("حذف قناة", callback_data="delete_channel_true"),
        types.InlineKeyboardButton("عرض القنوات", callback_data="view_channels_true")
    )
    markup.add(types.InlineKeyboardButton("رجوع إلى أقسام الاشتراك", callback_data="back_to_main_channel_management"))
    bot.edit_message_text("أنت الآن في قسم إدارة قنوات الاشتراك الحقيقي الإجباري. اختر إجراءً:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

# معالج لزر "اشتراك وهمي (فيديوهات 1 و 2)"
@bot.callback_query_handler(func=lambda call: call.data == "manage_fake_sub_channels")
def manage_fake_sub_channels(call):
    """
    يعرض خيارات إدارة قنوات الاشتراك الوهمي (إضافة، حذف، عرض) لكل من فيديوهات1 و فيديوهات2.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=2)

    markup.add(
        types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات1)", callback_data="add_channel_optional_v1"),
        types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_optional_v2")
    )
    markup.add(
        types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات1)", callback_data="delete_channel_optional_v1"),
        types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_optional_v2")
    )
    markup.add(
        types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات1)", callback_data="view_channels_optional_v1"),
        types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_optional_v2")
    )
    markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك", callback_data="back_to_main_channel_management"))

    bot.edit_message_text(
        "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي. اختر إجراءً:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )

# معالج لزر "إدارة قنوات الاشتراك الوهمي الجديدة"
@bot.callback_query_handler(func=lambda call: call.data == "manage_new_fake_sub_channels")
def manage_new_fake_sub_channels(call):
    """
    يعرض خيارات إدارة قنوات الاشتراك الوهمي الجديدة.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("إضافة قناة", callback_data="add_channel_new_fake"),
        types.InlineKeyboardButton("حذف قناة", callback_data="delete_channel_new_fake"),
        types.InlineKeyboardButton("عرض القنوات", callback_data="view_channels_new_fake")
    )
    markup.add(types.InlineKeyboardButton("رجوع إلى أقسام الاشتراك", callback_data="back_to_main_channel_management"))
    bot.edit_message_text("أنت الآن في قسم إدارة قنوات الاشتراك الوهمي الجديدة. اختر إجراءً:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

# معالج زر "رجوع إلى أقسام الاشتراك" الذي يظهر في أقسام إدارة القنوات الفرعية
@bot.callback_query_handler(func=lambda call: call.data == "back_to_main_channel_management")
def back_to_main_channel_management(call):
    """
    معالج زر 'رجوع إلى أقسام الاشتراك' الذي يعود إلى القائمة الرئيسية لإدارة القنوات.
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    
    try:
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception as e:
        print(f"خطأ في حذف الرسالة عند الرجوع: {e}")

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("اشتراك حقيقي إجباري", callback_data="manage_true_sub_channels"),
        types.InlineKeyboardButton("اشتراك وهمي (فيديوهات 1 و 2)", callback_data="manage_fake_sub_channels")
    )
    markup.add(types.InlineKeyboardButton("إدارة قنوات الاشتراك الوهمي الجديدة", callback_data="manage_new_fake_sub_channels"))
    markup.add(types.InlineKeyboardButton("رجوع إلى القائمة الرئيسية", callback_data="back_to_owner_main_keyboard"))
    bot.send_message(user_id, "اختر نوع قنوات الاشتراك التي تريد إدارتها:", reply_markup=markup)

# معالج لجميع الـ Callbacks الخاصة بإضافة/حذف/عرض القنوات (إجباري واختياري والجديدة)
@bot.callback_query_handler(func=lambda call: call.data.startswith(("add_channel_", "delete_channel_", "view_channels_")))
def handle_specific_channel_action(call):
    """
    معالج لـ Callbacks الخاصة بإضافة، حذف، أو عرض قنوات الاشتراك (الإجباري والاختياري والجديدة).
    المدخلات: call (telebot.types.CallbackQuery) - كائن الكول باك.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    parts = call.data.split("_")
    action_type = parts[0]
    
    # تحديد نوع القناة بناءً على الاسم في الكول باك
    channel_type = "_".join(parts[2:]) # يمكن أن يكون 'true', 'optional_v1', 'optional_v2', 'new_fake'

    # تحديد السياق للعودة الصحيحة
    context_map = {
        "true": "true_sub_management",
        "optional_v1": "fake_sub_management",
        "optional_v2": "fake_sub_management",
        "new_fake": "new_fake_sub_management" # سياق جديد
    }
    current_context = context_map.get(channel_type, "owner_main")

    # التعامل مع "إضافة قناة"
    if action_type == "add":
        sent_message = bot.send_message(user_id, f"أرسل لي رابط القناة التي تريد إضافتها لـ {channel_type} (مثال: `https://t.me/CHANNEL_USERNAME` أو رابط دعوة).\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية.", parse_mode="Markdown", reply_markup=get_back_markup())
        user_states[user_id] = {
            "state_type": "add_channel_link",
            "channel_type": channel_type,
            "prompt_message_id": sent_message.message_id,
            "context": current_context
        }

    # التعامل مع "حذف قناة"
    elif action_type == "delete":
        collection = get_collection_by_category(channel_type)
        if not collection:
            bot.send_message(user_id, "خطأ: فئة قناة غير معروفة.", reply_markup=owner_keyboard())
            return
        
        channels = list(collection.find())

        if not channels:
            bot.send_message(user_id, f"لا توجد قنوات {channel_type} لإزالتها.", reply_markup=owner_keyboard())
            user_states.pop(user_id, None)
            return

        text = f"📋 قائمة قنوات {channel_type}:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
        
        sent_message = bot.send_message(user_id, text, reply_markup=get_back_markup(), disable_web_page_preview=True) 

        user_states[user_id] = {
            "state_type": "delete_channel_choice",
            "channel_type": channel_type,
            "channels": channels,
            "prompt_message_id": sent_message.message_id,
            "context": current_context
        }
        
    # التعامل مع "عرض القنوات"
    elif action_type == "view":
        collection = get_collection_by_category(channel_type)
        if not collection:
            bot.send_message(user_id, "خطأ: فئة قناة غير معروفة.")
            return
        
        channels = list(collection.find())

        if not channels:
            bot.send_message(user_id, f"لا توجد قنوات {channel_type} معرفة حالياً.")
            return
        text = f"📋 قنوات الاشتراك الحالية لـ {channel_type}:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        bot.send_message(user_id, text, disable_web_page_preview=True) 

# معالج لإضافة قنوات الاشتراك (الإجباري والوهمي والجديدة)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and user_states.get(m.from_user.id, {}).get("state_type") == "add_channel_link")
def handle_add_channel_link(message):
    """
    يتعامل مع إدخال رابط القناة لإضافتها إلى قنوات الاشتراك.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    state_data = user_states.get(user_id)
    if not state_data:
        return

    link = message.text.strip()
    channel_type = state_data.get("channel_type")
    context = state_data.get("context")

    delete_prompt_message(user_id)
    user_states.pop(user_id, None) # إزالة حالة الانتظار مبدئيًا

    if not (link.startswith("http") or link.startswith("t.me")):
        bot.send_message(user_id, "❌ الرابط غير صالح. يرجى إرسال رابط صحيح (يبدأ بـ http أو t.me).")
        sent_message = bot.send_message(user_id, f"أرسل لي رابط القناة التي تريد إضافتها لـ {channel_type}.", reply_markup=get_back_markup())
        user_states[user_id] = {
            "state_type": "add_channel_link",
            "channel_type": channel_type,
            "prompt_message_id": sent_message.message_id,
            "context": context
        }
        return

    collection = get_collection_by_category(channel_type)
    if not collection:
        bot.send_message(user_id, "خطأ: فئة قناة غير معروفة للإضافة.", reply_markup=owner_keyboard())
        return

    if collection.find_one({"link": link}):
        bot.send_message(user_id, f"⚠️ هذه القناة موجودة بالفعل في قائمة قنوات {channel_type}.")
    else:
        collection.insert_one({"link": link})
        # تحديث القوائم العالمية بعد الإضافة
        global true_subscribe_links, subscribe_links_v1, subscribe_links_v2, new_fake_subscribe_links
        if channel_type == "true":
            true_subscribe_links = load_channel_links(TRUE_SUBSCRIBE_CHANNELS_COL)
        elif channel_type == "optional_v1":
            subscribe_links_v1 = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V1_COL)
        elif channel_type == "optional_v2":
            subscribe_links_v2 = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V2_COL)
        elif channel_type == "new_fake":
            new_fake_subscribe_links = load_channel_links(NEW_FAKE_SUBSCRIBE_CHANNELS_COL)

        bot.send_message(user_id, f"✅ تم إضافة القناة بنجاح إلى قنوات {channel_type}.")
    
    # العودة إلى القائمة الصحيحة
    if context == "true_sub_management":
        manage_true_sub_channels(types.CallbackQuery(id='dummy', from_user=message.from_user, message=message, data="manage_true_sub_channels"))
    elif context == "fake_sub_management":
        manage_fake_sub_channels(types.CallbackQuery(id='dummy', from_user=message.from_user, message=message, data="manage_fake_sub_channels"))
    elif context == "new_fake_sub_management":
        manage_new_fake_sub_channels(types.CallbackQuery(id='dummy', from_user=message.from_user, message=message, data="manage_new_fake_sub_channels"))
    else:
        bot.send_message(user_id, "تم إنجاز العملية.", reply_markup=owner_keyboard())

# معالج لحذف قنوات الاشتراك (الإجباري والوهمي والجديدة)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and user_states.get(m.from_user.id, {}).get("state_type") == "delete_channel_choice")
def handle_delete_channel_choice(message):
    """
    يتعامل مع اختيار المالك لحذف قناة من قنوات الاشتراك.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    user_id = message.from_user.id
    state_data = user_states.get(user_id)
    if not state_data:
        return

    delete_prompt_message(user_id) # حذف الرسالة التي تطلب الرقم

    channels_to_process = state_data["channels"]
    channel_type = state_data.get("channel_type")
    context = state_data.get("context")

    try:
        choice = int(message.text)
        if not (1 <= choice <= len(channels_to_process)):
            raise ValueError("الرقم غير صحيح.")

        channel_to_delete = channels_to_process[choice - 1]
        link = channel_to_delete["link"]
        
        collection = get_collection_by_category(channel_type)
        if not collection:
            bot.send_message(user_id, "خطأ: فئة قناة غير معروفة للحذف.", reply_markup=owner_keyboard())
            user_states.pop(user_id, None)
            return

        collection.delete_one({"link": link})
        # تحديث القوائم العالمية بعد الحذف
        global true_subscribe_links, subscribe_links_v1, subscribe_links_v2, new_fake_subscribe_links
        if channel_type == "true":
            true_subscribe_links = load_channel_links(TRUE_SUBSCRIBE_CHANNELS_COL)
        elif channel_type == "optional_v1":
            subscribe_links_v1 = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V1_COL)
        elif channel_type == "optional_v2":
            subscribe_links_v2 = load_channel_links(OPTIONAL_SUBSCRIBE_CHANNELS_V2_COL)
        elif channel_type == "new_fake":
            new_fake_subscribe_links = load_channel_links(NEW_FAKE_SUBSCRIBE_CHANNELS_COL)

        bot.send_message(user_id, f"✅ تم حذف القناة رقم {choice} بنجاح من قنوات {channel_type}.")

        # إعادة عرض القائمة المحدثة أو العودة للقائمة الرئيسية
        updated_channels = list(collection.find())
        if updated_channels:
            text = f"📋 قائمة قنوات {channel_type}:\n"
            for i, channel in enumerate(updated_channels, 1):
                text += f"{i}. {channel['link']}\n"
            text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
            sent_message = bot.send_message(user_id, text, reply_markup=get_back_markup(), disable_web_page_preview=True)
            user_states[user_id] = {
                "state_type": "delete_channel_choice",
                "channel_type": channel_type,
                "channels": updated_channels,
                "prompt_message_id": sent_message.message_id,
                "context": context
            }
        else:
            bot.send_message(user_id, f"لا توجد قنوات {channel_type} لإزالتها.", reply_markup=owner_keyboard())
            user_states.pop(user_id, None)

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.")
        # إعادة الدخول في حالة الانتظار إذا كان الإدخال غير صالح
        collection = get_collection_by_category(channel_type)
        channels = list(collection.find())
        if channels:
            text = f"📋 قائمة قنوات {channel_type}:\n"
            for i, channel in enumerate(channels, 1):
                text += f"{i}. {channel['link']}\n"
            text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
            sent_message = bot.send_message(user_id, text, reply_markup=get_back_markup(), disable_web_page_preview=True)
            user_states[user_id] = {
                "state_type": "delete_channel_choice",
                "channel_type": channel_type,
                "channels": channels,
                "prompt_message_id": sent_message.message_id,
                "context": context
            }
        else:
            bot.send_message(user_id, f"لا توجد قنوات {channel_type} لإزالتها.", reply_markup=owner_keyboard())
            user_states.pop(user_id, None)

# معالجات جديدة لأزرار وضع الصيانة
@bot.message_handler(func=lambda m: m.text == "تفعيل صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def enable_maintenance_v2(message):
    """
    معالج لزر تفعيل صيانة فيديوهات2. يُفعل وضع الصيانة.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    global maintenance_mode
    maintenance_mode = True
    bot.send_message(message.from_user.id, "✅ تم تفعيل وضع صيانة فيديوهات2.", reply_markup=owner_keyboard())

@bot.message_handler(func=lambda m: m.text == "إيقاف صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def disable_maintenance_v2(message):
    """
    معالج لزر إيقاف صيانة فيديوهات2. يُعطل وضع الصيانة.
    المدخلات: message (telebot.types.Message) - كائن الرسالة.
    """
    global maintenance_mode
    maintenance_mode = False
    bot.send_message(message.from_user.id, "✅ تم إيقاف وضع صيانة فيديوهات2.", reply_markup=owner_keyboard())

# --- Flask Web Server لتشغيل البوت على Render + UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    """المسار الرئيسي للخادم الويب. يعيد رسالة بسيطة."""
    return "Bot is running"

def run():
    """تشغيل خادم الويب على المنفذ 3000."""
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    """تشغيل الخادم في موضوع منفصل للحفاظ على البوت نشطاً."""
    t = Thread(target=run)
    t.start()

# بدء تشغيل خادم الويب والبوت
keep_alive()
bot.infinity_polling()

