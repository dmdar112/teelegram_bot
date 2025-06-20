# استيراد المكتبات اللازمة
import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient


# متغيرات البيئة (يجب تعيينها في بيئة النشر، مثل Render)
TOKEN = os.environ.get("TOKEN")  # توكن البوت الخاص بك من BotFather
bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622  # عدّل رقم آيدي التليجرام الخاص بك هنا ليصبح المالك

maintenance_mode = False # هذا المتغير يتحكم بوضع صيانة فيديوهات2 فقط (True = وضع صيانة مفعل، False = وضع صيانة غير مفعل)

# آيدي القناة الخاصة بفيديوهات1 (تُستخدم لرفع الفيديوهات)
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")
# آيدي القناة الخاصة بفيديوهات2 (تُستخدم لرفع الفيديوهات)
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")

# متغيرات لتتبع حالة المستخدمين في عمليات مختلفة (الحذف، إضافة/حذف القنوات، الرفع، الرسائل الجماعية)
waiting_for_delete = {} # {user_id: {"category": "v1", "videos": videos, "prompt_message_id": message_id, "context": "owner_main"}}
true_sub_pending = {}  # {user_id: step} - لتتبع تقدم المستخدم في الاشتراك الإجباري الحقيقي

# متغيرات جديدة لإدارة القنوات (القنوات الاختيارية + الإجبارية)
# الآن ستخزن أيضًا معرف الرسالة للسؤال وسياق العودة لتسهيل التنقل
waiting_for_channel_link = {} # {user_id: {"prompt_message_id": message_id, "channel_type": "true", "context": "true_sub_management"}}
waiting_for_channel_to_delete = {} # {user_id: {"channels": channels, "prompt_message_id": message_id, "channel_type": "true", "context": "true_sub_management"}}

# لم يعد يتم استخدام waiting_for_optional_link و waiting_for_optional_delete لـ فيديوهات1
# سيتم استخدامها فقط لـ فيديوهات2
waiting_for_optional_link = {} # {user_id: {"category": category, "prompt_message_id": message_id, "context": "fake_sub_management"}}
waiting_for_optional_delete = {} # {user_id: {"category": category, "channels": channels, "prompt_message_id": message_id, "context": "fake_sub_management"}}

# متغير جديد لحالة الاشتراك الوهمي العام - الآن لتعقب التقدم في القنوات
global_fake_sub_pending = {} # {user_id: step} - لتتبع تقدم المستخدم في الاشتراك الوهمي العام

MONGODB_URI = os.environ.get("MONGODB_URI") # رابط MongoDB Atlas الخاص بك

# إعداد MongoDB
client = MongoClient(MONGODB_URI)
db = client["telegram_bot_db"] # اسم قاعدة البيانات

# مجموعات (Collections) في قاعدة البيانات
users_col = db["users"] # لتخزين بيانات المستخدمين الأساسية (مثل حالة الانضمام)

# مجموعات لتخزين المستخدمين الموافق عليهم لكل قسم فيديوهات
approved_v1_col = db["approved_v1"]
approved_v2_col = db["approved_v2"]

# مجموعة جديدة للمستخدمين الموافق عليهم للاشتراك الوهمي العام
approved_global_dummy_sub_col = db["approved_global_dummy_sub"]

# لتخزين المستخدمين الذين تم إشعار المالك بهم (لمنع تكرار الإشعارات)
notified_users_col = db["notified_users"]

# المجموعة لقنوات الاشتراك الإجباري
true_subscribe_channels_col = db["true_subscribe_channels"]

# مجموعة جديدة لقنوات الاشتراك الوهمي العام
global_fake_subscribe_channels_col = db["global_fake_subscribe_channels"]


# مجموعات جديدة لقنوات الاشتراك الاختياري (فيديوهات1 و فيديوهات2)
# optional_subscribe_channels_v1_col لا تستخدم بعد الآن لتدفق المستخدم، ولكن يمكن الاحتفاظ بها في قاعدة البيانات.
optional_subscribe_channels_v1_col = db["optional_subscribe_channels_v1"]
optional_subscribe_channels_v2_col = db["optional_subscribe_channels_v2"]


# دوال لتحميل قنوات الاشتراك من قاعدة البيانات عند بدء البوت
def load_true_subscribe_links():
    """تحميل روابط قنوات الاشتراك الإجباري من قاعدة البيانات."""
    links = [doc["link"] for doc in true_subscribe_channels_col.find()]
    return links

def load_global_fake_subscribe_links():
    """تحميل روابط قنوات الاشتراك الوهمي العام من قاعدة البيانات."""
    links = [doc["link"] for doc in global_fake_subscribe_channels_col.find()]
    return links

def load_subscribe_links_v1():
    """
    تحميل روابط قنوات الاشتراك الاختياري لفيديوهات1 من قاعدة البيانات.
    (هذه الوظيفة لم تعد تستخدم لتدفق المستخدم في فيديوهات1 بعد الآن)
    """
    links = [doc["link"] for doc in optional_subscribe_channels_v1_col.find()]
    return links

def load_subscribe_links_v2():
    """تحميل روابط قنوات الاشتراك الاختياري لفيديوهات2 من قاعدة البيانات."""
    links = [doc["link"] for doc in optional_subscribe_channels_v2_col.find()]
    return links


# تحميل القوائم العالمية لقنوات الاشتراك عند بدء البوت لأول مرة
true_subscribe_links = load_true_subscribe_links()
global_fake_subscribe_links = load_global_fake_subscribe_links()
# subscribe_links_v1 لم تعد تستخدم في تدفق المستخدم لـ فيديوهات1، ولكن يمكن تركها إذا كانت هناك حاجة لها لأغراض أخرى
subscribe_links_v1 = load_subscribe_links_v1()
subscribe_links_v2 = load_subscribe_links_v2()

# متغيرات إضافية لتتبع حالة البوت
pending_check = {} # لتتبع تقدم المستخدم في الاشتراكات الاختيارية (فيديوهات2 فقط الآن)
owner_upload_mode = {} # {user_id: {"category": "v1", "prompt_message_id": message_id, "context": "owner_main"}} لتتبع وضع رفع الفيديوهات للمالك
waiting_for_broadcast = {} # {user_id: {"photo": True/False, "awaiting_text": True/False, "photo_file_id": file_id, "prompt_message_id": message_id, "context": "owner_main"}} لتتبع حالة الرسالة الجماعية

# دوال مساعدة لإدارة المستخدمين الموافق عليهم وإشعاراتهم
def load_approved_users(collection):
    """تحميل المستخدمين الموافق عليهم من مجموعة معينة في قاعدة البيانات."""
    return set(doc["user_id"] for doc in collection.find())

def add_approved_user(collection, user_id):
    """إضافة مستخدم موافق عليه إلى مجموعة معينة في قاعدة البيانات إذا لم يكن موجوداً."""
    if not collection.find_one({"user_id": user_id}):
        collection.insert_one({"user_id": user_id})

def remove_approved_user(collection, user_id):
    """إزالة مستخدم موافق عليه من مجموعة معينة في قاعدة البيانات."""
    collection.delete_one({"user_id": user_id})

def has_notified(user_id):
    """التحقق مما إذا كان المستخدم قد تم إبلاغ المالك به من قبل."""
    return notified_users_col.find_one({"user_id": user_id}) is not None

def add_notified_user(user_id):
    """إضافة مستخدم إلى قائمة المستخدمين الذين تم إبلاغ المالك بهم."""
    if not has_notified(user_id):
        notified_users_col.insert_one({"user_id": user_id})

# دوال لإنشاء لوحات المفاتيح (Keyboards)
def main_keyboard_with_videos():
    """إنشاء لوحة المفاتيح الرئيسية للمستخدم العادي بعد القبول الوهمي العام."""
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

def get_all_approved_users():
    """
    الحصول على جميع المستخدمين الذين أكملوا الاشتراك الإجباري
    وهم مؤهلون لتلقي الرسائل العامة.
    """
    return set(doc["user_id"] for doc in users_col.find({"joined": True}))

def send_videos(user_id, category):
    """إرسال الفيديوهات من قسم معين إلى المستخدم."""
    collection_name = f"videos_{category}"
    videos_collection = db[collection_name]
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
            time.sleep(1)  # تأخير لمنع الحظر أو التقييد من تيليجرام
        except Exception as e:
            print(f"❌ خطأ أثناء إرسال الفيديو للمستخدم {user_id}: {e}")

# معالج لزر "حذف فيديوهات1" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات1" and m.from_user.id == OWNER_ID)
def delete_videos_v1(message):
    """معالج لزر حذف فيديوهات1. يعرض قائمة بالفيديوهات للبدء في عملية الحذف."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    videos = list(db_videos_col.find().limit(20)) # عرض أول 20 فيديو

    # لوحة مفاتيح جديدة تحتوي على زر "رجوع"
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات1.", reply_markup=owner_keyboard())
        # إزالة حالة الانتظار إذا لم يكن هناك فيديوهات للحذف
        if user_id in waiting_for_delete:
            del waiting_for_delete[user_id]
        return

    text = "📋 قائمة فيديوهات1:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."

    # إرسال الرسالة مع لوحة المفاتيح الجديدة
    sent_message = bot.send_message(user_id, text, reply_markup=back_markup)
    # تحديث waiting_for_delete لتخزين message_id والسياق للعودة الصحيحة
    waiting_for_delete[user_id] = {"category": "v1", "videos": videos, "prompt_message_id": sent_message.message_id, "context": "owner_main"}

# معالج لزر "حذف فيديوهات2" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "حذف فيديوهات2" and m.from_user.id == OWNER_ID)
def delete_videos_v2(message):
    """معالج لزر حذف فيديوهات2. يعرض قائمة بالفيديوهات للبدء في عملية الحذف."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    videos = list(db_videos_col.find().limit(20))

    # لوحة مفاتيح جديدة تحتوي على زر "رجوع"
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))

    if not videos:
        bot.send_message(user_id, "لا يوجد فيديوهات في فيديوهات2.", reply_markup=owner_keyboard())
        # إزالة حالة الانتظار إذا لم يكن هناك فيديوهات للحذف
        if user_id in waiting_for_delete:
            del waiting_for_delete[user_id]
        return

    text = "📋 قائمة فيديوهات2:\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nأرسل رقم الفيديو الذي تريد حذفه."

    # إرسال الرسالة مع لوحة المفاتيح الجديدة
    sent_message = bot.send_message(user_id, text, reply_markup=back_markup)
    # تحديث waiting_for_delete لتخزين message_id والسياق للعودة الصحيحة
    waiting_for_delete[user_id] = {"category": "v2", "videos": videos, "prompt_message_id": sent_message.message_id, "context": "owner_main"}

# معالج لزر "رجوع" (يستخدم في حالات مختلفة للعودة للقائمة السابقة)
@bot.message_handler(func=lambda m: m.text == "رجوع" and (m.from_user.id in waiting_for_delete or \
                                                         m.from_user.id in waiting_for_channel_to_delete or \
                                                         m.from_user.id in waiting_for_channel_link or \
                                                         m.from_user.id in waiting_for_optional_link or \
                                                         m.from_user.id in waiting_for_optional_delete or \
                                                         m.from_user.id in owner_upload_mode or \
                                                         m.from_user.id in waiting_for_broadcast))
def handle_back_command(message):
    """معالج لزر الرجوع أثناء عملية الحذف أو إدارة القنوات أو الرفع أو الرسالة الجماعية (زر نصي)."""
    user_id = message.from_user.id
    prompt_message_id = None
    context = None # لتحديد القائمة التي يجب العودة إليها

    # التحقق من قوائم الانتظار وإزالة المستخدم وتحديد سياق العودة
    if user_id in waiting_for_delete:
        data = waiting_for_delete.pop(user_id)
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")
    elif user_id in waiting_for_channel_to_delete:
        data = waiting_for_channel_to_delete.pop(user_id)
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")
    elif user_id in waiting_for_channel_link:
        data = waiting_for_channel_link.pop(user_id)
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")
    elif user_id in waiting_for_optional_link:
        data = waiting_for_optional_link.pop(user_id)
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")
    elif user_id in waiting_for_optional_delete:
        data = waiting_for_optional_delete.pop(user_id)
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")
    elif user_id in owner_upload_mode: # معالجة الرجوع من وضع الرفع
        data = owner_upload_mode.pop(user_id)
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")
        bot.send_message(user_id, "تم إلغاء وضع الرفع.", reply_markup=owner_keyboard()) # إرسال لوحة المفاتيح فوراً لوضع الرفع
        
    elif user_id in waiting_for_broadcast: # معالجة الرجوع من وضع الرسالة الجماعية
        data = waiting_for_broadcast.pop(user_id)
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")
        bot.send_message(user_id, "تم إلغاء عملية الرسالة الجماعية.", reply_markup=owner_keyboard()) # إرسال لوحة المفاتيح فوراً للبث

    # حذف الرسالة السابقة التي تحتوي على السؤال (إذا كانت موجودة)
    if prompt_message_id:
        try:
            bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
        except Exception as e:
            print(f"خطأ في حذف رسالة الطلب: {e}")

    # العودة إلى القائمة الصحيحة بناءً على السياق المخزن
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
        # إعادة عرض قائمة إدارة قنوات الاشتراك الوهمي (فيديوهات2 فقط الآن)
        markup = types.InlineKeyboardMarkup(row_width=2)
        # تمت إزالة أزرار فيديوهات1
        markup.add(types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_v2"))
        markup.add(types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_v2"))
        markup.add(types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_v2"))
        markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي (فيديوهات2). اختر إجراءً:", reply_markup=markup)
    elif context == "global_fake_sub_management":
        # إعادة عرض قائمة إدارة قنوات الاشتراك الوهمي العام
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة قناة (وهمي عام)", callback_data="add_channel_global_fake"),
            types.InlineKeyboardButton("🗑️ حذف قناة (وهمي عام)", callback_data="delete_channel_global_fake"),
            types.InlineKeyboardButton("📺 عرض القنوات (وهمي عام)", callback_data="view_channels_global_fake")
        )
        markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي العام. اختر إجراءً:", reply_markup=markup)


# معالج لاختيار الفيديو المراد حذفه من قبل المالك
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.from_user.id in waiting_for_delete)
def handle_delete_choice(message):
    """معالج لاختيار الفيديو المراد حذفه من قبل المالك، ويقوم بحذف الفيديو من القناة وقاعدة البيانات."""
    user_id = message.from_user.id
    data = waiting_for_delete.get(user_id)
    if not data:
        # إذا لم تكن هناك بيانات انتظار، ربما انتهت الجلسة أو حدث خطأ
        bot.send_message(user_id, "حدث خطأ. يرجى البدء من جديد.", reply_markup=owner_keyboard())
        return

    # استخراج البيانات المطلوبة قبل إزالة حالة الانتظار
    category = data["category"]
    prompt_message_id = data.get("prompt_message_id")
    videos_to_process = data["videos"] # القائمة الأصلية التي عرضناها للمالك

    # حذف الرسالة السابقة التي تطلب الرقم (القائمة الأصلية)
    if prompt_message_id:
        try:
            bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
        except Exception as e:
            print(f"خطأ في حذف رسالة الطلب القديمة: {e}")

    try:
        choice = int(message.text)

        if 1 <= choice <= len(videos_to_process):
            video_to_delete = videos_to_process[choice - 1]
            chat_id = video_to_delete["chat_id"]
            message_id = video_to_delete["message_id"]

            try:
                # حذف الرسالة من القناة
                bot.delete_message(chat_id, message_id)
            except telebot.apihelper.ApiTelegramException as e:
                if "message to delete not found" in str(e):
                    print(f"تحذير: الرسالة {message_id} محذوفة بالفعل من القناة {chat_id}.")
                else:
                    raise e # أعد إثارة أي أخطاء أخرى
            
            # حذف السجل من قاعدة البيانات
            db_videos_col = db[f"videos_{category}"]
            db_videos_col.delete_one({"message_id": message_id})

            bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} بنجاح.")
            
            # إعادة جلب القائمة المحدثة من قاعدة البيانات
            updated_videos = list(db_videos_col.find().limit(20))

            if updated_videos:
                # إعادة عرض القائمة المحدثة للفيديوهات في نفس القسم
                text = f"📋 قائمة فيديوهات{category[-1].upper()} المتبقية:\n"
                for i, vid in enumerate(updated_videos, 1):
                    text += f"{i}. رسالة رقم: {vid['message_id']}\n"
                text += "\nأرسل رقم الفيديو التالي الذي تريد حذفه."
                
                back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                back_markup.add(types.KeyboardButton("رجوع"))
                
                sent_message = bot.send_message(user_id, text, reply_markup=back_markup)
                # إعادة ضبط حالة الانتظار للقائمة المحدثة
                waiting_for_delete[user_id] = {"category": category, "videos": updated_videos, "prompt_message_id": sent_message.message_id, "context": "owner_main"}
            else:
                bot.send_message(user_id, f"✅ تم حذف جميع الفيديوهات في قسم فيديوهات{category[-1].upper()}.", reply_markup=owner_keyboard())
                del waiting_for_delete[user_id] # إزالة من حالة الانتظار

        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.")
            # إعادة عرض القائمة الأصلية للسماح للمالك بالمحاولة مرة أخرى
            db_videos_col = db[f"videos_{category}"]
            current_videos = list(db_videos_col.find().limit(20))
            if current_videos:
                text = f"📋 قائمة فيديوهات{category[-1].upper()}:\n"
                for i, vid in enumerate(current_videos, 1):
                    text += f"{i}. رسالة رقم: {vid['message_id']}\n"
                text += "\nأرسل رقم الفيديو الذي تريد حذفه."
                back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                back_markup.add(types.KeyboardButton("رجوع"))
                sent_message = bot.send_message(user_id, text, reply_markup=back_markup)
                waiting_for_delete[user_id] = {"category": category, "videos": current_videos, "prompt_message_id": sent_message.message_id, "context": "owner_main"}
            else:
                bot.send_message(user_id, "لا توجد فيديوهات في هذا القسم.", reply_markup=owner_keyboard())
                del waiting_for_delete[user_id] # إزالة من حالة الانتظار

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.")
        # إعادة عرض القائمة الأصلية للسماح للمالك بالمحاولة مرة أخرى
        db_videos_col = db[f"videos_{category}"]
        current_videos = list(db_videos_col.find().limit(20))
        if current_videos:
            text = f"📋 قائمة فيديوهات{category[-1].upper()}:\n"
            for i, vid in enumerate(current_videos, 1):
                text += f"{i}. رسالة رقم: {vid['message_id']}\n"
            text += "\nأرسل رقم الفيديو الذي تريد حذفه."
            back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            back_markup.add(types.KeyboardButton("رجوع"))
            sent_message = bot.send_message(user_id, text, reply_markup=back_markup)
            waiting_for_delete[user_id] = {"category": category, "videos": current_videos, "prompt_message_id": sent_message.message_id, "context": "owner_main"}
        else:
            bot.send_message(user_id, "لا توجد فيديوهات في هذا القسم.", reply_markup=owner_keyboard())
            del waiting_for_delete[user_id] # إزالة من حالة الانتظار


# معالج زر "تنظيف فيديوهات1" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "تنظيف فيديوهات1" and m.from_user.id == OWNER_ID)
def clean_videos_v1_button(message):
    """معالج لزر تنظيف فيديوهات1. يقوم بحذف سجلات الفيديوهات من قاعدة البيانات إذا لم تعد موجودة في القناة."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v1"]
    channel_id = CHANNEL_ID_V1

    bot.send_message(user_id, "جاري تنظيف فيديوهات1... قد يستغرق هذا بعض الوقت.")

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            # نحاول توجيه الرسالة إلى المالك، إذا فشل يعني أن الرسالة محذوفة من القناة
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
        except Exception as e:
            # لو فشل، احذف الفيديو من قاعدة البيانات لأنه غير موجود بالقناة
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات1. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_keyboard())

# معالج زر "تنظيف فيديوهات2" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "تنظيف فيديوهات2" and m.from_user.id == OWNER_ID)
def clean_videos_v2_button(message):
    """معالج لزر تنظيف فيديوهات2. يقوم بحذف سجلات الفيديوهات من قاعدة البيانات إذا لم تعد موجودة في القناة."""
    user_id = message.from_user.id
    db_videos_col = db["videos_v2"]
    channel_id = CHANNEL_ID_V2

    bot.send_message(user_id, "جاري تنظيف فيديوهات2... قد يستغرق هذا بعض الوقت.")

    videos = list(db_videos_col.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            # نحاول توجيه الرسالة إلى المالك، إذا فشل يعني أن الرسالة محذوفة من القناة
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
        except Exception as e:
            # لو فشل، احذف الفيديو من قاعدة البيانات لأنه غير موجود بالقناة
            db_videos_col.delete_one({'_id': vid['_id']})
            removed_count += 1

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات2. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_keyboard())

def check_true_subscription(user_id, first_name):
    """
    يقوم بالتحقق من جميع قنوات الاشتراك الإجباري (true_subscribe_links) بشكل متسلسل.
    ويدفع المستخدم للاشتراك في القناة التالية إذا لم يكن مشتركًا.
    """
    global true_subscribe_links # تأكد من استخدام أحدث قائمة
    true_subscribe_links = load_true_subscribe_links() # إعادة تحميل القائمة في كل مرة للتحقق من التحديثات

    if not true_subscribe_links: # إذا لم تكن هناك قنوات اشتراك إجباري معرفة
        # إذا لا توجد قنوات إجبارية، يعتبر المستخدم كمن أتمها
        user_data_db = users_col.find_one({"user_id": user_id})
        if not user_data_db:
            users_col.insert_one({"user_id": user_id, "joined": True, "first_name": first_name})
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": True, "first_name": first_name}})
        
        # بعد الاشتراك الحقيقي، ننتقل للتحقق من الاشتراك الوهمي العام
        check_global_fake_subscription(user_id, first_name)
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
            # استخراج معرف القناة من الرابط
            channel_identifier = current_channel_link.split("t.me/")[-1]
            
            # في حال كانت القناة عامة (@username)
            if not channel_identifier.startswith('+'): # روابط الدعوة الخاصة تبدأ بـ '+'
                channel_username = f"@{channel_identifier}" if not channel_identifier.startswith('@') else channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    all_channels_subscribed = False
                    true_sub_pending[user_id] = index # احفظ الخطوة التي توقف عندها
                    text = (
                        "🚸| عذراً عزيزي .\n"
                        "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه\n\n"
                        f"- {current_channel_link}\n\n"
                        "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
                    )
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("✅ بعد الاشتراك، اضغط هنا للمتابعة ✅", callback_data="check_true_subscription"))
                    bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                    return # توقف هنا وانتظر تفاعل المستخدم
            else: # رابط دعوة خاص (يبدأ بـ +) - لا يمكن للبوت التحقق منه مباشرة
                # في هذه الحالة، نفترض أن المستخدم يحتاج للاشتراك ونطلب منه ذلك
                all_channels_subscribed = False
                true_sub_pending[user_id] = index # احفظ الخطوة
                text = (
                    "🚸| عذراً عزيزي .\n"
                    "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه\n\n"
                    f"- {current_channel_link}\n\n"
                    "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
                bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                return # توقف هنا وانتظر تفاعل المستخدم
            
            # إذا كان مشتركًا أو تم تجاوز فحص القناة الخاصة بنجاح، استمر في الحلقة
            true_sub_pending[user_id] = index + 1 # تحديث الخطوة للقناة التالية

        except Exception as e:
            print(f"❌ خطأ أثناء التحقق من القناة {current_channel_link} للمستخدم {user_id}: {e}")
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

        # NEW LOGIC: بعد الاشتراك الإجباري الحقيقي، ننتقل للتحقق من الاشتراك الوهمي العام
        check_global_fake_subscription(user_id, first_name)

    else:
        # إذا لم يكن مشتركاً في جميع القنوات بعد (رغم محاولة التحقق الكاملة)، نقوم بتحديث حالة joined إلى False
        user_data_db = users_col.find_one({"user_id": user_id})
        if user_data_db and user_data_db.get("joined", False):
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": False}})


def check_global_fake_subscription(user_id, first_name):
    """
    يتحقق من جميع قنوات الاشتراك الوهمي العام (global_fake_subscribe_links) بشكل متسلسل.
    ويدفع المستخدم للاشتراك في القناة التالية إذا لم يكن مشتركًا.
    """
    global global_fake_subscribe_links # تأكد من استخدام أحدث قائمة
    global_fake_subscribe_links = load_global_fake_subscribe_links() # إعادة تحميل القائمة في كل مرة للتحقق من التحديثات

    # إذا كان المستخدم موافق عليه بالفعل للاشتراك الوهمي العام (تم قبوله من المالك)
    if user_id in load_approved_users(approved_global_dummy_sub_col):
        send_start_welcome_message(user_id, first_name, show_videos=True)
        return

    # إذا لم تكن هناك قنوات اشتراك وهمي عام معرفة
    if not global_fake_subscribe_links:
        # إذا لا توجد قنوات وهمية عامة، نطلب الموافقة المباشرة من المالك
        notify_owner_for_global_dummy_approval(user_id, first_name, channel_based=False)
        bot.send_message(user_id, "لقد أكملت جميع المتطلبات! يرجى الانتظار حتى يوافق المالك على دخولك.", reply_markup=types.ReplyKeyboardRemove())
        # لا نحذف global_fake_sub_pending هنا، بل نتركه ليتم حذفه بعد موافقة المالك
        return


    # تهيئة الخطوة الحالية: إذا لم يكن المستخدم موجودًا في global_fake_sub_pending، ابدأ من 0
    step = global_fake_sub_pending.get(user_id, 0)

    # التأكد أن خطوة البداية لا تتجاوز عدد القنوات المتاحة
    if step >= len(global_fake_subscribe_links):
        step = 0 # أعد تعيينها لتبدأ من البداية إذا كان قد أكملها

    all_channels_subscribed = True
    for index in range(step, len(global_fake_subscribe_links)):
        current_channel_link = global_fake_subscribe_links[index]
        try:
            channel_identifier = current_channel_link.split("t.me/")[-1]
            if not channel_identifier.startswith('+'):
                channel_username = f"@{channel_identifier}" if not channel_identifier.startswith('@') else channel_identifier
                member = bot.get_chat_member(chat_id=channel_username, user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    all_channels_subscribed = False
                    global_fake_sub_pending[user_id] = index
                    text = (
                        "🚸| عذراً عزيزي .\n"
                        "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه (اشتراك وهمي عام)\n\n"
                        f"- {current_channel_link}\n\n"
                        "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
                    )
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("✅ بعد الاشتراك، اضغط هنا للمتابعة ✅", callback_data="check_global_fake_subscription"))
                    bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                    return
            else:
                all_channels_subscribed = False
                global_fake_sub_pending[user_id] = index
                text = (
                    "🚸| عذراً عزيزي .\n"
                    "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه (اشتراك وهمي عام)\n\n"
                    f"- {current_channel_link}\n\n"
                    "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_global_fake_subscription"))
                bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                return
            
            global_fake_sub_pending[user_id] = index + 1

        except Exception as e:
            print(f"❌ خطأ أثناء التحقق من القناة الوهمية العامة {current_channel_link} للمستخدم {user_id}: {e}")
            all_channels_subscribed = False
            global_fake_sub_pending[user_id] = index
            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة: {current_channel_link}.\n"
                "يرجى التأكد أنك مشترك وأن البوت مشرف في القناة (إذا كانت خاصة)، ثم حاول الضغط على الزر مرة أخرى."
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_global_fake_subscription"))
            bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
            return

    if all_channels_subscribed:
        if user_id in global_fake_sub_pending:
            del global_fake_sub_pending[user_id] # إزالة المستخدم بعد اكتمال التحقق من القنوات

        # بعد إكمال قنوات الاشتراك الوهمي العام، نرسل طلب الموافقة للمالك
        notify_owner_for_global_dummy_approval(user_id, first_name, channel_based=True)
        bot.send_message(user_id, "لقد أكملت جميع متطلبات الاشتراك! يرجى الانتظار حتى يوافق المالك على دخولك.", reply_markup=types.ReplyKeyboardRemove())
    else:
        # إذا لم يكن مشتركاً في جميع القنوات بعد (رغم محاولة التحقق الكاملة)، نقوم بتحديث حالة joined إلى False
        # (فقط إذا كانت false في users_col، وإلا لا نغيرها)
        pass # حالة joined تم تعيينها في check_true_subscription، لا نغيرها هنا.


# معالج لأمر /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    """معالج لأمر /start. يتحقق مما إذا كان المستخدم هو المالك أو يبدأ عملية التحقق من الاشتراك."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم جديد"

    # إذا كان المستخدم هو المالك، أظهر لوحة مفاتيح المالك مباشرة
    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحبا مالك البوت!", reply_markup=owner_keyboard())
        return

    # لكل المستخدمين الآخرين، ابدأ عملية التحقق من الاشتراك الإجباري
    bot.send_message(user_id, f"أهلاً بك/🔥 {first_name} 🇦🇱! يرجى إكمال الاشتراك في القنوات الإجبارية الحقيقية للوصول إلى البوت.", reply_markup=types.ReplyKeyboardRemove())
    
    check_true_subscription(user_id, first_name)


def send_start_welcome_message(user_id, first_name, show_videos=False):
    """
    المنطق الفعلي لدالة /start بعد التحقق من الاشتراك في القنوات الإجبارية.
    ترسل رسالة الترحيب وتُشعر المالك.
    تستخدم show_videos لتحديد ما إذا كان يجب عرض أزرار الفيديو مباشرة.
    """
    if show_videos:
        bot.send_message(user_id, "🤤🇺🇸🇸🇯اختر قسم الفيديوهات من الأزرار بالأسفل!", reply_markup=main_keyboard_with_videos())
    else:
        # رسالة أولية قبل الاشتراك الوهمي العام، ربما إزالة لوحة المفاتيح السابقة
        bot.send_message(user_id, f"أهلاً بك/🔥 {first_name} 🇦🇱! يرجى إكمال متطلبات الوصول التالية...", reply_markup=types.ReplyKeyboardRemove())


    # إشعار المالك بالمستخدم الجديد
    if not has_notified(user_id):
        total_users = len(get_all_approved_users())  # حساب إجمالي المستخدمين الموافق عليهم
        bot.send_message(OWNER_ID, f"""⚠️تم دخول شخص جديد إلى البوت⚠️

• الاسم : {first_name}
• الايدي : {user_id}
• عدد الأعضاء الكلي: {total_users}
""")
        add_notified_user(user_id)  # إضافة المستخدم لقائمة من تم إشعار المالك بهم

# معالج لـ callback_data "check_true_subscription"
@bot.callback_query_handler(func=lambda call: call.data == "check_true_subscription")
def handle_check_true_subscription_callback(call):
    """معالج لزر "لقد اشتركت، اضغط هنا للمتابعة" بعد الاشتراك الإجباري."""
    bot.answer_callback_query(call.id, "جاري التحقق من اشتراكك...") # إشعار للمستخدم بأن التحقق جارٍ
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم" # نحصل على الاسم من الكول باك
    check_true_subscription(user_id, first_name) # إعادة التحقق

# معالج لـ callback_data "check_global_fake_subscription"
@bot.callback_query_handler(func=lambda call: call.data == "check_global_fake_subscription")
def handle_check_global_fake_subscription_callback(call):
    """معالج لزر "لقد اشتركت، اضغط هنا للمتابعة" بعد الاشتراك الوهمي العام."""
    bot.answer_callback_query(call.id, "جاري التحقق من اشتراكك الوهمي العام...")
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم"
    check_global_fake_subscription(user_id, first_name)


# معالج لزر "مقاطع1"
@bot.message_handler(func=lambda m: m.text == "مقاطع1/🤤🫦🇸🇯")
def handle_v1(message):
    """
    معالج لزر مقاطع1.
    يتحقق من الاشتراك الإجباري، ثم من الاشتراك الوهمي العام، ثم يرسل الفيديوهات.
    """
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    # 1. التحقق من الاشتراك الإجباري الحقيقي
    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name)
        return

    # 2. التحقق من الاشتراك الوهمي العام
    if user_id not in load_approved_users(approved_global_dummy_sub_col):
        bot.send_message(user_id, "يرجى إكمال الاشتراك الوهمي العام أولاً والموافقة عليه من المالك.", reply_markup=types.ReplyKeyboardRemove())
        check_global_fake_subscription(user_id, first_name) # يدفع المستخدم لإكمال القنوات أو انتظار الموافقة
        return

    # إذا تم اجتياز الاشتراك الحقيقي والاشتراك الوهمي العام، يتم منح الوصول لـ فيديوهات1
    add_approved_user(approved_v1_col, user_id) # التأكد من أن المستخدم موافق عليه لـ فيديوهات1
    send_videos(user_id, "v1")


# معالج لزر "مقاطع2"
@bot.message_handler(func=lambda m: m.text == "مقاطع2/🤤🫦🇺🇸")
def handle_v2(message):
    """معالج لزر فيديوهات2. يتحقق من وضع الصيانة، حالة اشتراك المستخدم، ويرسل الفيديوهات أو يطلب الاشتراك الاختياري."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"

    # 1. التحقق من الاشتراك الإجباري الحقيقي
    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name)
        return

    # 2. التحقق من الاشتراك الوهمي العام
    if user_id not in load_approved_users(approved_global_dummy_sub_col):
        bot.send_message(user_id, "يرجى إكمال الاشتراك الوهمي العام أولاً والموافقة عليه من المالك.", reply_markup=types.ReplyKeyboardRemove())
        check_global_fake_subscription(user_id, first_name) # يدفع المستخدم لإكمال القنوات أو انتظار الموافقة
        return

    # التحقق من وضع الصيانة. المالك يتجاوز وضع الصيانة.
    global maintenance_mode # الوصول للمتغير العام
    if maintenance_mode and user_id != OWNER_ID:
        bot.send_message(user_id, "قريباً سيتم اضافة مقاطع في زر مقاطع/2‼️", reply_markup=main_keyboard_with_videos())
        return

    # 3. المتابعة بمنطق الاشتراك الوهمي الخاص بـ فيديوهات2 (المنطق الموجود مسبقًا)
    if user_id in load_approved_users(approved_v2_col): # إذا كان المستخدم موافق عليه لـ فيديوهات2
        send_videos(user_id, "v2")
    else:
        bot.send_message(user_id, "👋 أهلاً بك في قسم فيديوهات 2!\nللوصول إلى الفيديوهات، الرجاء الاشتراك في القنوات التالية:", reply_markup=types.ReplyKeyboardRemove())
        data = pending_check.get(user_id)
        if data and data["category"] == "v2":
            send_required_links(user_id, "v2")
        else:
            pending_check[user_id] = {"category": "v2", "step": 0}
            send_required_links(user_id, "v2")

def send_required_links(chat_id, category):
    """
    إرسال روابط الاشتراك الاختياري المطلوبة للمستخدم بشكل متسلسل.
    (هذه الوظيفة تستخدم الآن فقط لـ فيديوهات2)
    """
    if category == "v1":
        # هذا الفرع لن يتم الوصول إليه بعد الآن بسبب التغييرات في handle_v1
        # ولكن نتركه كاحتياط أو لتوضيح أن v1 لم تعد تستخدم هنا
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة (لا توجد قنوات اشتراك حالياً لهذا القسم). الرجاء الانتظار.", reply_markup=main_keyboard_with_videos())
        pending_check.pop(chat_id, None)
        return

    global subscribe_links_v2 # تأكد من استخدام أحدث قائمة
    subscribe_links_v2 = load_subscribe_links_v2() # إعادة تحميل لضمان التحديث

    data = pending_check.get(chat_id, {"category": category, "step": 0})
    step = data["step"]
    links = subscribe_links_v2 # الآن فقط لقنوات v2

    if not links: # إذا لم تكن هناك قنوات اشتراك اختيارية معرفة لهذا القسم
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة (لا توجد قنوات اشتراك حالياً لهذا القسم). الرجاء الانتظار.", reply_markup=main_keyboard_with_videos())
        pending_check.pop(chat_id, None) # إزالة من حالة الانتظار
        return

    if step >= len(links): # إذا أكمل المستخدم جميع القنوات
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة. الرجاء الانتظار.", reply_markup=main_keyboard_with_videos())
        pending_check.pop(chat_id, None)
        return

    link = links[step] # الحصول على رابط القناة الحالي

    text = (
    "🚸| عذراً عزيزي .\n"
    "🔰| عليك الاشتراك في قناة البوت لتتمكن من استخدامه\n\n"
    f"- {link}\n\n"
    "‼️| اشترك ثم اضغط /الزر أدناه للمتابعة ~"
)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ بعد الاشتراك، اضغط هنا للمتابعة ✅", callback_data=f"verify_{category}_{step}"))
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

    pending_check[chat_id] = {"category": category, "step": step} # حفظ حالة المستخدم الحالية

# معالج للتحقق من الاشتراك عبر الأزرار (بعد الضغط على "تحقق الآن")
@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    """
    معالج للتحقق من الاشتراك الاختياري عبر الأزرار.
    (هذه الوظيفة تستخدم الآن فقط لـ فيديوهات2)
    """
    bot.answer_callback_query(call.id)  # لحل مشكلة الزر المعلق

    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    step = int(step_str) + 1

    if category == "v1":
        # هذا الفرع لن يتم الوصول إليه بعد الآن
        # بدلاً من ذلك، ستقوم handle_v1 بتسجيل الدخول مباشرة
        # وهذا القسم لن يتم استدعاؤه لـ "v1" بعد التغيير.
        return

    links = load_subscribe_links_v2() # فقط لقنوات v2

    if step < len(links): # إذا كان لا يزال هناك قنوات للاشتراك فيها
        pending_check[user_id] = {"category": category, "step": step}
        send_required_links(user_id, category) # أرسل القناة التالية
    else: # إذا أكمل المستخدم جميع القنوات الاختيارية (لـ فيديوهات2)
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
        notify_owner_for_approval(user_id, call.from_user.first_name, category) # إشعار المالك بطلب الموافقة
        pending_check.pop(user_id, None) # إزالة المستخدم من حالة الانتظار

# إعادة إرسال روابط الاشتراك عند طلب المستخدم (إذا لم يكملها)
@bot.callback_query_handler(func=lambda call: call.data.startswith("resend_"))
def resend_links(call):
    """
    إعادة إرسال روابط الاشتراك الاختياري عند طلب المستخدم (عادة بعد فشل التحقق).
    (هذه الوظيفة تستخدم الآن فقط لـ فيديوهات2)
    """
    bot.answer_callback_query(call.id)  # لحل مشكلة الزر المعلق

    user_id = call.from_user.id
    category = call.data.split("_")[1]

    if category == "v1":
        # هذا الفرع لن يتم الوصول إليه بعد الآن
        bot.send_message(user_id, "لا توجد قنوات اشتراك اختيارية لـ مقاطع1 بعد الآن. يرجى التواصل مع الدعم إذا واجهت مشكلة.")
        return

    pending_check[user_id] = {"category": category, "step": 0} # إعادة تعيين الخطوة للبدء من جديد
    send_required_links(user_id, category)

def notify_owner_for_approval(user_id, name, category):
    """إرسال إشعار للمالك بطلب انضمام جديد لمراجعتها (لقبول أو رفض الوصول)."""
    # هذا الإشعار سيظل يُرسل لـ فيديوهات2، ولكن ليس لـ فيديوهات1 بعد الآن.
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("✅ قبول المستخدم (لفيديوهات2)", callback_data=f"approve_v2_{user_id}"),
        types.InlineKeyboardButton("❌ رفض المستخدم (لفيديوهات2)", callback_data=f"reject_v2_{user_id}")
    )
    message_text = (
        f"📥 طلب انضمام جديد (فيديوهات2)\n"
        f"👤 الاسم: {name}\n"
        f"🆔 الآيدي: {user_id}\n"
        f"📁 الفئة: فيديوهات {category[-1]}"
    )
    bot.send_message(OWNER_ID, message_text, reply_markup=keyboard)


def notify_owner_for_global_dummy_approval(user_id, name, channel_based=True):
    """إرسال إشعار للمالك بطلب انضمام وهمي عام جديد للمراجعة."""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("✅ قبول المستخدم (وهمي عام)", callback_data=f"approve_global_dummy_{user_id}"),
        types.InlineKeyboardButton("❌ رفض المستخدم (وهمي عام)", callback_data=f"reject_global_dummy_{user_id}")
    )
    
    if channel_based:
        message_text = (
            f"📥 طلب اشتراك وهمي عام جديد (أكمل القنوات)\n"
            f"👤 الاسم: {name}\n"
            f"🆔 الآيدي: {user_id}\n"
            f"✨ أكمل جميع قنوات الاشتراك الوهمي العام"
        )
    else: # إذا لم تكن هناك قنوات وهمية عامة، فقط طلب مباشر
        message_text = (
            f"📥 طلب اشتراك وهمي عام جديد (مباشر)\n"
            f"👤 الاسم: {name}\n"
            f"🆔 الآيدي: {user_id}\n"
            f"✨ جاهز للموافقة على الاشتراك الوهمي العام"
        )
    bot.send_message(OWNER_ID, message_text, reply_markup=keyboard)


# معالج لاستجابة المالك (قبول أو رفض المستخدم)
@bot.callback_query_handler(func=lambda call: call.data.startswith(("approve_", "reject_")))
def handle_owner_response(call):
    """معالج لاستجابة المالك (قبول أو رفض). يقوم بتحديث حالة المستخدم وإرسال إشعار له."""
    parts = call.data.split("_")
    action = parts[0] # approve or reject
    approval_type = parts[1] # global_dummy or v2
    user_id = int(parts[2])

    # التأكد أن من يضغط على الزر هو المالك
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🚫 غير مصرح لك بالقيام بهذا الإجراء.")
        return

    bot.answer_callback_query(call.id, f"تم {action} الطلب.") # إشعار للكول باك

    if approval_type == "global_dummy":
        if action == "approve":
            add_approved_user(approved_global_dummy_sub_col, user_id)
            # إزالة من حالة الانتظار للقنوات الوهمية العامة إذا وجدت
            if user_id in global_fake_sub_pending:
                del global_fake_sub_pending[user_id]
            
            first_name = call.from_user.first_name or "مستخدم" # الحصول على الاسم
            send_start_welcome_message(user_id, first_name, show_videos=True) # عرض أزرار الفيديو
            bot.send_message(user_id, "✅ تم قبول اشتراكك الوهمي العام! يمكنك الآن الوصول للمقاطع.")
            bot.edit_message_text("✅ تم قبول المستخدم للاشتراك الوهمي العام.", call.message.chat.id, call.message.message_id)
        else: # reject
            # السماح للمستخدم بالمحاولة مرة أخرى (إعادة توجيه لعملية الاشتراك الوهمي العام)
            if user_id in global_fake_sub_pending:
                del global_fake_sub_pending[user_id] # مسح التقدم لإعادة البدء
            
            first_name = call.from_user.first_name or "مستخدم" # الحصول على الاسم
            bot.send_message(user_id, "❌ لم يتم قبول اشتراكك الوهمي العام. يرجى المحاولة مرة أخرى.", reply_markup=types.ReplyKeyboardRemove())
            check_global_fake_subscription(user_id, first_name) # يدفع المستخدم لإعادة إكمال القنوات أو انتظار الموافقة
            bot.edit_message_text("❌ تم رفض المستخدم للاشتراك الوهمي العام.", call.message.chat.id, call.message.message_id)

    elif approval_type == "v2": # هذا هو الموافقة الخاصة بـ فيديوهات2 الموجودة مسبقًا
        if action == "approve":
            add_approved_user(approved_v2_col, user_id)
            bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة للوصول إلى مقاطع فيديوهات2!", reply_markup=main_keyboard_with_videos())
            bot.edit_message_text("✅ تم قبول المستخدم (لفيديوهات2).", call.message.chat.id, call.message.message_id)
        else: # reject
            # إعادة تعيين حالة التحقق المعلقة لـ فيديوهات2 إذا وجدت
            if user_id in pending_check and pending_check[user_id].get("category") == "v2":
                 del pending_check[user_id] # السماح للمستخدم بإعادة بدء الاشتراك الوهمي لـ فيديوهات2
            bot.send_message(user_id, "❌ لم يتم قبولك للوصول إلى مقاطع فيديوهات2. الرجاء التأكد من الاشتراك في جميع قنواتها.", reply_markup=main_keyboard_with_videos())
            bot.edit_message_text("❌ تم رفض المستخدم (لفيديوهات2).", call.message.chat.id, call.message.message_id)


# معالج لزر "رفع فيديوهات1" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات1" and m.from_user.id == OWNER_ID)
def set_upload_mode_v1_button(message):
    """تعيين وضع الرفع لقسم فيديوهات1. يطلب من المالك إرسال الفيديوهات."""
    user_id = message.from_user.id
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))
    sent_message = bot.reply_to(message, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات1.\nأرسل 'رجوع' للعودة.", reply_markup=back_markup)
    owner_upload_mode[user_id] = {'category': 'v1', 'prompt_message_id': sent_message.message_id, 'context': 'owner_main'}

# معالج لزر "رفع فيديوهات2" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "رفع فيديوهات2" and m.from_user.id == OWNER_ID)
def set_upload_mode_v2_button(message):
    """تعيين وضع الرفع لقسم فيديوهات2. يطلب من المالك إرسال الفيديوهات."""
    user_id = message.from_user.id
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))
    sent_message = bot.reply_to(message, "✅ سيتم حفظ الفيديوهات التالية في قسم فيديوهات2.\nأرسل 'رجوع' للعودة.", reply_markup=back_markup)
    owner_upload_mode[user_id] = {'category': 'v2', 'prompt_message_id': sent_message.message_id, 'context': 'owner_main'}

# معالج لرفع الفيديوهات من قبل المالك
@bot.message_handler(content_types=['video'])
def handle_video_upload(message):
    """معالج لاستقبال الفيديوهات التي يرفعها المالك وحفظها في القناة المخصصة وقاعدة البيانات."""
    user_id = message.from_user.id
    mode_data = owner_upload_mode.get(user_id)

    if user_id != OWNER_ID or not mode_data:
        return  # تجاهل أي فيديو من غير المالك أو إن لم يكن في وضع الرفع

    category = mode_data['category']
    prompt_message_id = mode_data.get('prompt_message_id')

    # حذف الرسالة السابقة التي تطلب الرفع
    if prompt_message_id:
        try:
            bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
        except Exception as e:
            print(f"خطأ في حذف رسالة الطلب: {e}")

    # رفع الفيديو إلى القناة الخاصة
    try:
        sent = bot.send_video(
            chat_id=os.environ.get(f"CHANNEL_ID_{category.upper()}"), # استخدام CHANNEL_ID_V1 أو CHANNEL_ID_V2
            video=message.video.file_id,
            caption=f"📥 فيديو جديد من المالك - قسم {category.upper()}", # كابشن اختياري
        )
        # تخزين تفاصيل الفيديو في قاعدة البيانات
        db[f"videos_{category}"].insert_one({
            "chat_id": sent.chat.id,
            "message_id": sent.message_id
        })

        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        sent_message = bot.reply_to(message, f"✅ تم حفظ الفيديو في قسم {category.upper()}.\nيمكنك إرسال فيديو آخر أو أرسل 'رجوع' للعودة.", reply_markup=back_markup)
        owner_upload_mode[user_id]['prompt_message_id'] = sent_message.message_id # تحديث معرف رسالة الطلب
        # لا نخرج من وضع الرفع هنا، بل نسمح له برفع المزيد من الفيديوهات

    except Exception as e:
        print(f"❌ خطأ في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ أثناء حفظ الفيديو.", reply_markup=owner_keyboard())
        owner_upload_mode.pop(user_id, None) # مسح وضع الرفع في حالة الخطأ

# معالج لزر "رسالة جماعية مع صورة" (خاص بالمالك)
@bot.message_handler(func=lambda m: m.text == "رسالة جماعية مع صورة" and m.from_user.id == OWNER_ID)
def ask_broadcast_photo(message):
    """طلب صورة لرسالة جماعية من المالك."""
    user_id = message.from_user.id
    back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    back_markup.add(types.KeyboardButton("رجوع"))
    sent_message = bot.send_message(user_id, "أرسل لي الصورة التي تريد إرسالها مع الرسالة.\nأو أرسل 'رجوع' للعودة.", reply_markup=back_markup)
    waiting_for_broadcast[user_id] = {"photo": True, "prompt_message_id": sent_message.message_id, "context": "owner_main"}

# معالج لاستقبال الصورة للرسالة الجماعية من المالك
@bot.message_handler(content_types=['photo'])
def receive_broadcast_photo(message):
    """استقبال الصورة للرسالة الجماعية من المالك، ثم طلب النص."""
    user_id = message.from_user.id
    if waiting_for_broadcast.get(user_id) and waiting_for_broadcast[user_id].get("photo") and user_id == OWNER_ID:
        
        # حذف رسالة الطلب السابقة
        prompt_message_id = waiting_for_broadcast[user_id].get("prompt_message_id")
        if prompt_message_id:
            try:
                bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
            except Exception as e:
                print(f"خطأ في حذف رسالة الطلب: {e}")

        waiting_for_broadcast[user_id]["photo_file_id"] = message.photo[-1].file_id # حفظ معرف ملف الصورة
        waiting_for_broadcast[user_id]["photo"] = False
        waiting_for_broadcast[user_id]["awaiting_text"] = True # تعيين حالة انتظار النص

        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        sent_message = bot.send_message(user_id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة.\nأو أرسل 'رجوع' للعودة.", reply_markup=back_markup)
        waiting_for_broadcast[user_id]["prompt_message_id"] = sent_message.message_id # تحديث معرف رسالة الطلب
    else:
        # إذا لم يكن في حالة انتظار الصورة للبث، تجاهل الصورة أو تعامل معها كصورة عادية إذا كان هناك معالج آخر
        pass

# معالج لاستقبال نص الرسالة الجماعية وإرسالها لجميع المستخدمين الموافق عليهم
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and waiting_for_broadcast.get(m.from_user.id) and waiting_for_broadcast[m.from_user.id].get("awaiting_text"))
def receive_broadcast_text(message):
    """استقبال نص الرسالة الجماعية وإرسالها لجميع المستخدمين الموافق عليهم."""
    user_id = message.from_user.id
    if waiting_for_broadcast.get(user_id) and waiting_for_broadcast[user_id].get("awaiting_text"):
        
        # حذف رسالة الطلب السابقة
        prompt_message_id = waiting_for_broadcast[user_id].get("prompt_message_id")
        if prompt_message_id:
            try:
                bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
            except Exception as e:
                print(f"خطأ في حذف رسالة الطلب: {e}")

        photo_id = waiting_for_broadcast[user_id].get("photo_file_id") # الحصول على معرف ملف الصورة
        text = message.text # الحصول على نص الرسالة
        users = get_all_approved_users() # جلب جميع المستخدمين الموافق عليهم
        sent_count = 0
        for uid in users: # التكرار عبر المستخدمين لإرسال الرسالة
            try:
                bot.send_photo(uid, photo_id, caption=text)
                sent_count += 1
            except Exception as e:
                print(f"خطأ في إرسال الرسالة الجماعية للمستخدم {uid}: {e}")
                pass # تجاهل الأخطاء ومتابعة الإرسال للمستخدمين الآخرين
        bot.send_message(OWNER_ID, f"تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.", reply_markup=owner_keyboard())
        waiting_for_broadcast.pop(user_id, None) # مسح حالة البث لهذا المستخدم

# --- إدارة القنوات الموحدة للمالك ---

# معالج لزر "إدارة قنوات الاشتراك" (الرئيسي للمالك)
@bot.message_handler(func=lambda m: m.text == "إدارة قنوات الاشتراك" and m.from_user.id == OWNER_ID)
def manage_all_subscription_channels_menu(message):
    """يعرض القائمة الرئيسية لإدارة قنوات الاشتراك (الاشتراك الإجباري والوهمي)."""
    user_id = message.from_user.id
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("اشتراك حقيقي إجباري", callback_data="manage_true_sub_channels"),
        types.InlineKeyboardButton("اشتراك وهمي عام", callback_data="manage_global_fake_sub_channels"), # زر جديد
        types.InlineKeyboardButton("اشتراك وهمي (فيديوهات 2 فقط)", callback_data="manage_fake_sub_channels")
    )
    # هذا هو زر الرجوع الجديد الذي طلبته للعودة للقائمة الرئيسية للمالك
    markup.add(types.InlineKeyboardButton("رجوع إلى القائمة الرئيسية", callback_data="back_to_owner_main_keyboard"))
    # نرسل رسالة جديدة دائمًا عند الدخول إلى هذه القائمة
    bot.send_message(user_id, "اختر نوع قنوات الاشتراك التي تريد إدارتها:", reply_markup=markup)

# معالج لزر "رجوع إلى القائمة الرئيسية" من قائمة إدارة قنوات الاشتراك الرئيسية
@bot.callback_query_handler(func=lambda call: call.data == "back_to_owner_main_keyboard")
def handle_back_to_owner_main_keyboard(call):
    """معالج زر 'رجوع إلى القائمة الرئيسية' من قائمة إدارة قنوات الاشتراك الرئيسية."""
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    # حذف الرسالة التي تحتوي على الأزرار المضمنة
    try:
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception as e:
        print(f"خطأ في حذف الرسالة عند الرجوع للقائمة الرئيسية للمالك: {e}")
    # إرسال لوحة مفاتيح المالك الرئيسية
    bot.send_message(user_id, "تم الرجوع إلى القائمة الرئيسية للمالك.", reply_markup=owner_keyboard())

# معالج لزر "اشتراك حقيقي إجباري"
@bot.callback_query_handler(func=lambda call: call.data == "manage_true_sub_channels")
def manage_true_sub_channels(call):
    """يعرض خيارات إدارة قنوات الاشتراك الإجباري (إضافة، حذف، عرض)."""
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("إضافة قناة", callback_data="add_channel_true"),
        types.InlineKeyboardButton("حذف قناة", callback_data="delete_channel_true"),
        types.InlineKeyboardButton("عرض القنوات", callback_data="view_channels_true")
    )
    markup.add(types.InlineKeyboardButton("رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
    bot.edit_message_text("أنت الآن في قسم إدارة قنوات الاشتراك الحقيقي الإجباري. اختر إجراءً:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

# معالج لزر "اشتراك وهمي عام" (جديد)
@bot.callback_query_handler(func=lambda call: call.data == "manage_global_fake_sub_channels")
def manage_global_fake_sub_channels(call):
    """يعرض خيارات إدارة قنوات الاشتراك الوهمي العام (إضافة، حذف، عرض)."""
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ إضافة قناة (وهمي عام)", callback_data="add_channel_global_fake"),
        types.InlineKeyboardButton("🗑️ حذف قناة (وهمي عام)", callback_data="delete_channel_global_fake"),
        types.InlineKeyboardButton("📺 عرض القنوات (وهمي عام)", callback_data="view_channels_global_fake")
    )
    markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
    bot.edit_message_text("أنت الآن في قسم إدارة قنوات الاشتراك الوهمي العام. اختر إجراءً:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)


# معالج لزر "اشتراك وهمي (فيديوهات 1 و 2)"
@bot.callback_query_handler(func=lambda call: call.data == "manage_fake_sub_channels")
def manage_fake_sub_channels(call):
    """
    يعرض خيارات إدارة قنوات الاشتراك الوهمي (إضافة، حذف، عرض)
    الآن فقط لـ فيديوهات2.
    """
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=2)

    # صف 1: إضافة فيديوهات2 فقط (تمت إزالة فيديوهات1)
    markup.add(
        types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_v2")
    )

    # صف 2: حذف فيديوهات2 فقط (تمت إزالة فيديوهات1)
    markup.add(
        types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_v2")
    )

    # صف 3: عرض قنوات فيديوهات2 فقط (تمت إزالة فيديوهات1)
    markup.add(
        types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_v2")
    )

    # زر العودة إلى القائمة الرئيسية لإدارة القنوات
    markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))

    bot.edit_message_text(
        "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي (فيديوهات2). اختر إجراءً:", # تم تعديل النص
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )

# معالج زر "رجوع إلى أقسام الاشتراك الإجباري" الذي يظهر في أقسام إدارة القنوات الفرعية
@bot.callback_query_handler(func=lambda call: call.data == "back_to_main_channel_management")
def back_to_main_channel_management(call):
    """معالج زر 'رجوع إلى أقسام الاشتراك الإجباري' الذي يعود إلى القائمة الرئيسية لإدارة القنوات."""
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    
    # نحذف الرسالة الحالية التي تحتوي على الأزرار المضمنة
    try:
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception as e:
        print(f"خطأ في حذف الرسالة عند الرجوع: {e}")
        # لا نوقف التنفيذ إذا فشل الحذف

    # الآن، نعيد إرسال القائمة الرئيسية لإدارة القنوات كرسالة جديدة
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("اشتراك حقيقي إجباري", callback_data="manage_true_sub_channels"),
        types.InlineKeyboardButton("اشتراك وهمي عام", callback_data="manage_global_fake_sub_channels"), # زر جديد
        types.InlineKeyboardButton("اشتراك وهمي (فيديوهات 2 فقط)", callback_data="manage_fake_sub_channels")
    )
    markup.add(types.InlineKeyboardButton("رجوع إلى القائمة الرئيسية", callback_data="back_to_owner_main_keyboard")) # إضافة زر الرجوع هنا أيضًا
    bot.send_message(user_id, "اختر نوع قنوات الاشتراك التي تريد إدارتها:", reply_markup=markup)

# معالج لجميع الـ Callbacks الخاصة بإضافة/حذف/عرض القنوات (إجباري واختياري)
@bot.callback_query_handler(func=lambda call: call.data.startswith(("add_channel_", "delete_channel_", "view_channels_")))
def handle_specific_channel_action(call):
    """معالج لـ Callbacks الخاصة بإضافة، حذف، أو عرض قنوات الاشتراك (الإجباري والاختياري)."""
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    parts = call.data.split("_")
    action_type = parts[0] # add, delete, view
    channel_category = parts[2] # true, v1, v2, global_fake

    # منع إضافة/حذف/عرض قنوات فيديوهات1 الوهمية
    if channel_category == "v1":
        bot.send_message(user_id, "⛔️ لا يمكن إدارة قنوات الاشتراك الوهمية لـ فيديوهات1. هذه الميزة تم إزالتها.")
        return

    # التعامل مع "إضافة قناة"
    if action_type == "add":
        # إضافة زر "رجوع" في الـ ReplyKeyboardMarkup
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        
        # إرسال الرسالة وتخزين الـ message_id وسياق العودة
        sent_message = bot.send_message(user_id, f"أرسل لي رابط القناة التي تريد إضافتها لـ {channel_category} (مثال: `https://t.me/CHANNEL_USERNAME` أو رابط دعوة).\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية.", parse_mode="Markdown", reply_markup=back_markup)
        
        if channel_category == "true":
            waiting_for_channel_link[user_id] = {"prompt_message_id": sent_message.message_id, "channel_type": "true", "context": "true_sub_management"}
        elif channel_category == "v2": # v2 فقط الآن
            waiting_for_optional_link[user_id] = {"category": channel_category, "prompt_message_id": sent_message.message_id, "context": "fake_sub_management"}
        elif channel_category == "global_fake": # جديد: لـ الاشتراك الوهمي العام
            waiting_for_optional_link[user_id] = {"category": channel_category, "prompt_message_id": sent_message.message_id, "context": "global_fake_sub_management"}


    # التعامل مع "حذف قناة"
    elif action_type == "delete":
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        
        channels = []
        collection = None
        if channel_category == "true":
            collection = true_subscribe_channels_col
        elif channel_category == "v2": # v2 فقط الآن
            collection = optional_subscribe_channels_v2_col
        elif channel_category == "global_fake": # جديد: لـ الاشتراك الوهمي العام
            collection = global_fake_subscribe_channels_col
        
        channels = list(collection.find())

        if not channels:
            # يجب أن نتحقق من هذا الشرط قبل إرسال الرسالة لتجنب تخزين message_id خاطئ
            bot.send_message(user_id, f"لا توجد قنوات {channel_category} لإزالتها.", reply_markup=owner_keyboard())
            return

        text = f"📋 قائمة قنوات {channel_category}:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
        
        # إرسال الرسالة وتخزين الـ message_id وسياق العودة
        sent_message = bot.send_message(user_id, text, reply_markup=back_markup, disable_web_page_preview=True) 

        if channel_category == "true":
            waiting_for_channel_to_delete[user_id] = {"channels": channels, "prompt_message_id": sent_message.message_id, "channel_type": "true", "context": "true_sub_management"}
        elif channel_category == "v2": # v2 فقط الآن
            waiting_for_optional_delete[user_id] = {"category": channel_category, "channels": channels, "prompt_message_id": sent_message.message_id, "context": "fake_sub_management"}
        elif channel_category == "global_fake": # جديد: لـ الاشتراك الوهمي العام
            waiting_for_optional_delete[user_id] = {"category": channel_category, "channels": channels, "prompt_message_id": sent_message.message_id, "context": "global_fake_sub_management"}

        
    # التعامل مع "عرض القنوات"
    elif action_type == "view":
        channels = []
        collection = None
        if channel_category == "true":
            collection = true_subscribe_channels_col
        elif channel_category == "v2": # v2 فقط الآن
            collection = optional_subscribe_channels_v2_col
        elif channel_category == "global_fake": # جديد: لـ الاشتراك الوهمي العام
            collection = global_fake_subscribe_channels_col
        
        channels = list(collection.find())

        if not channels:
            bot.send_message(user_id, f"لا توجد قنوات {channel_category} معرفة حالياً.")
            return
        text = f"📋 قنوات الاشتراك الحالية لـ {channel_category}:\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel['link']}\n"
        bot.send_message(user_id, text, disable_web_page_preview=True) 

# معالج جديد لإضافة قنوات الاشتراك الإجباري (الحقيقي)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.from_user.id in waiting_for_channel_link)
def handle_add_true_channel_link(message):
    """يتعامل مع إدخال رابط القناة لإضافتها إلى قنوات الاشتراك الإجباري."""
    user_id = message.from_user.id
    data = waiting_for_channel_link.get(user_id)
    if not data:
        return

    link = message.text.strip()
    prompt_message_id = data.get("prompt_message_id")
    context = data.get("context")

    # حذف الرسالة التي تطلب الرابط
    if prompt_message_id:
        try:
            bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
        except Exception as e:
            print(f"خطأ في حذف رسالة الطلب: {e}")

    # مسح حالة الانتظار أولاً، حيث أن هذا المعالج يعني استجابة (حتى لو غير صالحة)
    waiting_for_channel_link.pop(user_id) 

    if not (link.startswith("http") or link.startswith("t.me")):
        bot.send_message(user_id, "❌ الرابط غير صالح. يرجى إرسال رابط صحيح (يبدأ بـ http أو t.me).")
        # إعادة الدخول في حالة الانتظار إذا كان الرابط غير صالح
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        sent_message = bot.send_message(user_id, "أرسل لي رابط القناة التي تريد إضافتها.", reply_markup=back_markup)
        waiting_for_channel_link[user_id] = {"prompt_message_id": sent_message.message_id, "channel_type": "true", "context": context}
        return

    # التحقق مما إذا كانت القناة موجودة بالفعل
    if true_subscribe_channels_col.find_one({"link": link}):
        bot.send_message(user_id, "⚠️ هذه القناة موجودة بالفعل في قائمة الاشتراك الإجباري.")
    else:
        true_subscribe_channels_col.insert_one({"link": link})
        global true_subscribe_links
        true_subscribe_links = load_true_subscribe_links() # إعادة تحميل القائمة العالمية
        bot.send_message(user_id, "✅ تم إضافة القناة بنجاح إلى الاشتراك الإجباري.")
    
    # العودة إلى القائمة الصحيحة
    if context == "true_sub_management":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("إضافة قناة", callback_data="add_channel_true"),
            types.InlineKeyboardButton("حذف قناة", callback_data="delete_channel_true"),
            types.InlineKeyboardButton("عرض القنوات", callback_data="view_channels_true")
        )
        markup.add(types.InlineKeyboardButton("رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الحقيقي الإجباري. اختر إجراءً:", reply_markup=markup)
    else: # في حال فقدان السياق أو غير متوقع، العودة للوحة مفاتيح المالك
        bot.send_message(user_id, "تم إنجاز العملية.", reply_markup=owner_keyboard())
    
    # waiting_for_channel_link.pop(user_id) # تم مسحها بالفعل في الأعلى

# معالج جديد لإضافة قنوات الاشتراك الوهمي (فيديوهات1 و فيديوهات2 والوهمي العام)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.from_user.id in waiting_for_optional_link)
def handle_add_optional_channel_link(message):
    """
    يتعامل مع إدخال رابط القناة لإضافتها إلى قنوات الاشتراك الاختياري (فيديوهات2 والوهمي العام).
    """
    user_id = message.from_user.id
    data = waiting_for_optional_link.get(user_id)
    if not data:
        return

    link = message.text.strip()
    category = data.get("category")
    prompt_message_id = data.get("prompt_message_id")
    context = data.get("context")

    # منع إضافة قنوات لـ فيديوهات1 هنا
    if category == "v1":
        bot.send_message(user_id, "⛔️ لا يمكن إضافة قنوات اشتراك وهمية لـ فيديوهات1 عبر هذه الواجهة. هذه الميزة تم إزالتها.")
        # مسح حالة الانتظار
        waiting_for_optional_link.pop(user_id)
        # العودة إلى قائمة إدارة القنوات الوهمية
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("➕ إضافة قناة (وهمي عام)", callback_data="add_channel_global_fake"))
        markup.add(types.InlineKeyboardButton("🗑️ حذف قناة (وهمي عام)", callback_data="delete_channel_global_fake"))
        markup.add(types.InlineKeyboardButton("📺 عرض القنوات (وهمي عام)", callback_data="view_channels_global_fake"))
        markup.add(types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_v2"))
        markup.add(types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_v2"))
        markup.add(types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_v2"))
        markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي (فيديوهات2). اختر إجراءً:", reply_markup=markup)
        return

    # حذف الرسالة التي تطلب الرابط
    if prompt_message_id:
        try:
            bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
        except Exception as e:
            print(f"خطأ في حذف رسالة الطلب: {e}")
    
    # مسح حالة الانتظار أولاً، حيث أن هذا المعالج يعني استجابة (حتى لو غير صالحة)
    waiting_for_optional_link.pop(user_id) 

    if not (link.startswith("http") or link.startswith("t.me")):
        bot.send_message(user_id, "❌ الرابط غير صالح. يرجى إرسال رابط صحيح (يبدأ بـ http أو t.me).")
        # إعادة الدخول في حالة الانتظار إذا كان الرابط غير صالح
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        sent_message = bot.send_message(user_id, f"أرسل لي رابط القناة التي تريد إضافتها لـ {category}.", reply_markup=back_markup)
        waiting_for_optional_link[user_id] = {"category": category, "prompt_message_id": sent_message.message_id, "context": context}
        return

    collection = None
    if category == "v1":
        collection = db[f"optional_subscribe_channels_{category}"] # لن يتم الوصول إليه فعليًا
    elif category == "v2":
        collection = optional_subscribe_channels_v2_col
    elif category == "global_fake": # جديد
        collection = global_fake_subscribe_channels_col


    if collection.find_one({"link": link}):
        bot.send_message(user_id, f"⚠️ هذه القناة موجودة بالفعل في قائمة قنوات {category}.")
    else:
        collection.insert_one({"link": link})
        global subscribe_links_v1, subscribe_links_v2, global_fake_subscribe_links
        if category == "v1": # هذا لن يتم الوصول إليه فعليًا بعد التغييرات
            subscribe_links_v1 = load_subscribe_links_v1()
        elif category == "v2":
            subscribe_links_v2 = load_subscribe_links_v2()
        elif category == "global_fake": # جديد
            global_fake_subscribe_links = load_global_fake_subscribe_links()

        bot.send_message(user_id, f"✅ تم إضافة القناة بنجاح إلى قنوات {category}.")
    
    # العودة إلى القائمة الصحيحة (لوحة مفاتيح إدارة القنوات الوهمية)
    if context == "fake_sub_management":
        markup = types.InlineKeyboardMarkup(row_width=2)
        # أزرار فيديوهات1 محذوفة
        markup.add(types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_v2"))
        markup.add(types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_v2"))
        markup.add(types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_v2"))
        markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي (فيديوهات2). اختر إجراءً:", reply_markup=markup)
    elif context == "global_fake_sub_management": # جديد
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة قناة (وهمي عام)", callback_data="add_channel_global_fake"),
            types.InlineKeyboardButton("🗑️ حذف قناة (وهمي عام)", callback_data="delete_channel_global_fake"),
            types.InlineKeyboardButton("📺 عرض القنوات (وهمي عام)", callback_data="view_channels_global_fake")
        )
        markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
        bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي العام. اختر إجراءً:", reply_markup=markup)
    else:
        bot.send_message(user_id, "تم إنجاز العملية.", reply_markup=owner_keyboard())

    # waiting_for_optional_link.pop(user_id) # تم مسحها بالفعل في الأعلى

# معالج جديد لحذف قنوات الاشتراك الإجباري (الحقيقي)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.from_user.id in waiting_for_channel_to_delete)
def handle_delete_true_channel_choice(message):
    """يتعامل مع اختيار المالك لحذف قناة من قنوات الاشتراك الإجباري."""
    user_id = message.from_user.id
    data = waiting_for_channel_to_delete.get(user_id)
    if not data:
        return

    try:
        choice = int(message.text)
        channels_to_process = data["channels"]
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")

        # حذف الرسالة التي تطلب الرقم
        if prompt_message_id:
            try:
                bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
            except Exception as e:
                print(f"خطأ في حذف رسالة الطلب: {e}")

        # مسح حالة الانتظار أولاً، إلا إذا أعدنا الدخول إليها بسبب إدخال غير صالح
        waiting_for_channel_to_delete.pop(user_id)

        if 1 <= choice <= len(channels_to_process):
            channel_to_delete = channels_to_process[choice - 1]
            link = channel_to_delete["link"]
            
            true_subscribe_channels_col.delete_one({"link": link})
            global true_subscribe_links
            true_subscribe_links = load_true_subscribe_links() # إعادة تحميل القائمة العالمية بعد الحذف

            bot.send_message(user_id, f"✅ تم حذف القناة رقم {choice} بنجاح من الاشتراك الإجباري.")
        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.")
            # إعادة الدخول في حالة الانتظار إذا كان الاختيار غير صالح
            back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            back_markup.add(types.KeyboardButton("رجوع"))
            
            channels = list(true_subscribe_channels_col.find()) # جلب القائمة الحالية للقنوات
            if channels:
                text = "📋 قائمة قنوات true:\n"
                for i, channel in enumerate(channels, 1):
                    text += f"{i}. {channel['link']}\n"
                text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
                sent_message = bot.send_message(user_id, text, reply_markup=back_markup, disable_web_page_preview=True)
                waiting_for_channel_to_delete[user_id] = {"channels": channels, "prompt_message_id": sent_message.message_id, "channel_type": "true", "context": context}
                return # الخروج لمنع الانتقال إلى القائمة التالية فوراً
            else:
                bot.send_message(user_id, "لا توجد قنوات true لإزالتها.", reply_markup=owner_keyboard())

        
        # العودة إلى القائمة الصحيحة (إذا لم نعد ندخل في حالة الانتظار)
        if context == "true_sub_management":
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("إضافة قناة", callback_data="add_channel_true"),
                types.InlineKeyboardButton("حذف قناة", callback_data="delete_channel_true"),
                types.InlineKeyboardButton("عرض القنوات", callback_data="view_channels_true")
            )
            markup.add(types.InlineKeyboardButton("رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
            bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الحقيقي الإجباري. اختر إجراءً:", reply_markup=markup)
        else:
            bot.send_message(user_id, "تم إنجاز العملية.", reply_markup=owner_keyboard())

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.")
        # إعادة الدخول في حالة الانتظار إذا كان الإدخال غير صالح
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        
        channels = list(true_subscribe_channels_col.find()) # جلب القائمة الحالية للقنوات
        if channels:
            text = "📋 قائمة قنوات true:\n"
            for i, channel in enumerate(channels, 1):
                text += f"{i}. {channel['link']}\n"
            text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
            sent_message = bot.send_message(user_id, text, reply_markup=back_markup, disable_web_page_preview=True)
            waiting_for_channel_to_delete[user_id] = {"channels": channels, "prompt_message_id": sent_message.message_id, "channel_type": "true", "context": context}
            return # الخروج لمنع الانتقال إلى القائمة التالية فوراً
        else:
            bot.send_message(user_id, "لا توجد قنوات true لإزالتها.", reply_markup=owner_keyboard())

# معالج جديد لحذف قنوات الاشتراك الوهمي (فيديوهات1 وفيديوهات2 والوهمي العام)
@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.from_user.id in waiting_for_optional_delete)
def handle_delete_optional_channel_choice(message):
    """
    يتعامل مع اختيار المالك لحذف قناة من قنوات الاشتراك الاختياري (فيديوهات2 والوهمي العام).
    """
    user_id = message.from_user.id
    data = waiting_for_optional_delete.get(user_id)
    if not data:
        return

    try:
        choice = int(message.text)
        channels_to_process = data["channels"]
        category = data.get("category")
        prompt_message_id = data.get("prompt_message_id")
        context = data.get("context")

        # منع حذف قنوات لـ فيديوهات1 هنا
        if category == "v1":
            bot.send_message(user_id, "⛔️ لا يمكن حذف قنوات اشتراك وهمية لـ فيديوهات1 عبر هذه الواجهة. هذه الميزة تم إزالتها.")
            # مسح حالة الانتظار
            waiting_for_optional_delete.pop(user_id)
            # العودة إلى قائمة إدارة القنوات الوهمية
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("➕ إضافة قناة (وهمي عام)", callback_data="add_channel_global_fake"))
            markup.add(types.InlineKeyboardButton("🗑️ حذف قناة (وهمي عام)", callback_data="delete_channel_global_fake"))
            markup.add(types.InlineKeyboardButton("📺 عرض القنوات (وهمي عام)", callback_data="view_channels_global_fake"))
            markup.add(types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_v2"))
            markup.add(types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_v2"))
            markup.add(types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_v2"))
            markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
            bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي (فيديوهات2). اختر إجراءً:", reply_markup=markup)
            return

        # حذف الرسالة التي تطلب الرقم
        if prompt_message_id:
            try:
                bot.delete_message(chat_id=user_id, message_id=prompt_message_id)
            except Exception as e:
                print(f"خطأ في حذف رسالة الطلب: {e}")

        # مسح حالة الانتظار أولاً، إلا إذا أعدنا الدخول إليها بسبب إدخال غير صالح
        waiting_for_optional_delete.pop(user_id)

        if 1 <= choice <= len(channels_to_process):
            channel_to_delete = channels_to_process[choice - 1]
            link = channel_to_delete["link"]
            
            collection = None
            if category == "v1":
                collection = db[f"optional_subscribe_channels_{category}"]
            elif category == "v2":
                collection = optional_subscribe_channels_v2_col
            elif category == "global_fake": # جديد
                collection = global_fake_subscribe_channels_col

            collection.delete_one({"link": link})
            global subscribe_links_v1, subscribe_links_v2, global_fake_subscribe_links
            if category == "v1": # هذا لن يتم الوصول إليه فعليًا بعد التغييرات
                subscribe_links_v1 = load_subscribe_links_v1()
            elif category == "v2":
                subscribe_links_v2 = load_subscribe_links_v2()
            elif category == "global_fake": # جديد
                global_fake_subscribe_links = load_global_fake_subscribe_links()


            bot.send_message(user_id, f"✅ تم حذف القناة رقم {choice} بنجاح من قنوات {category}.")
        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح، حاول مرة أخرى.")
            # إعادة الدخول في حالة الانتظار إذا كان الاختيار غير صالح
            back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            back_markup.add(types.KeyboardButton("رجوع"))
            
            collection = None
            if category == "v1":
                collection = db[f"optional_subscribe_channels_{category}"]
            elif category == "v2":
                collection = optional_subscribe_channels_v2_col
            elif category == "global_fake":
                collection = global_fake_subscribe_channels_col

            channels = list(collection.find()) # جلب القائمة الحالية للقنوات
            if channels:
                text = f"📋 قائمة قنوات {category}:\n"
                for i, channel in enumerate(channels, 1):
                    text += f"{i}. {channel['link']}\n"
                text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
                sent_message = bot.send_message(user_id, text, reply_markup=back_markup, disable_web_page_preview=True)
                waiting_for_optional_delete[user_id] = {"category": category, "channels": channels, "prompt_message_id": sent_message.message_id, "context": context}
                return # الخروج لمنع الانتقال إلى القائمة التالية فوراً
            else:
                bot.send_message(user_id, f"لا توجد قنوات {category} لإزالتها.", reply_markup=owner_keyboard())

        # العودة إلى القائمة الصحيحة (لوحة مفاتيح إدارة القنوات الوهمية) (إذا لم نعد ندخل في حالة الانتظار)
        if context == "fake_sub_management":
            markup = types.InlineKeyboardMarkup(row_width=2)
            # أزرار فيديوهات1 محذوفة
            markup.add(types.InlineKeyboardButton("➕ إضافة قناة (فيديوهات2)", callback_data="add_channel_v2"))
            markup.add(types.InlineKeyboardButton("🗑️ حذف قناة (فيديوهات2)", callback_data="delete_channel_v2"))
            markup.add(types.InlineKeyboardButton("📺 عرض القنوات (فيديوهات2)", callback_data="view_channels_v2"))
            markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
            bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي (فيديوهات2). اختر إجراءً:", reply_markup=markup)
        elif context == "global_fake_sub_management": # جديد
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("➕ إضافة قناة (وهمي عام)", callback_data="add_channel_global_fake"),
                types.InlineKeyboardButton("🗑️ حذف قناة (وهمي عام)", callback_data="delete_channel_global_fake"),
                types.InlineKeyboardButton("📺 عرض القنوات (وهمي عام)", callback_data="view_channels_global_fake")
            )
            markup.add(types.InlineKeyboardButton("🔙 رجوع إلى أقسام الاشتراك الإجباري", callback_data="back_to_main_channel_management"))
            bot.send_message(user_id, "أنت الآن في قسم إدارة قنوات الاشتراك الوهمي العام. اختر إجراءً:", reply_markup=markup)
        else:
            bot.send_message(user_id, "تم إنجاز العملية.", reply_markup=owner_keyboard())

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح.")
        # إعادة الدخول في حالة الانتظار إذا كان الإدخال غير صالح
        back_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(types.KeyboardButton("رجوع"))
        
        collection = None
        if category == "v1":
            collection = db[f"optional_subscribe_channels_{category}"]
        elif category == "v2":
            collection = optional_subscribe_channels_v2_col
        elif category == "global_fake":
            collection = global_fake_subscribe_channels_col

        channels = list(collection.find()) # جلب القائمة الحالية للقنوات
        if channels:
            text = f"📋 قائمة قنوات {category}:\n"
            for i, channel in enumerate(channels, 1):
                text += f"{i}. {channel['link']}\n"
            text += "\nأرسل رقم القناة التي تريد حذفها.\n\nأو أرسل 'رجوع' للعودة للقائمة الرئيسية."
            sent_message = bot.send_message(user_id, text, reply_markup=back_markup, disable_web_page_preview=True)
            waiting_for_optional_delete[user_id] = {"category": category, "channels": channels, "prompt_message_id": sent_message.message_id, "context": context}
            return # الخروج لمنع الانتقال إلى القائمة التالية فوراً
        else:
            bot.send_message(user_id, f"لا توجد قنوات {category} لإزالتها.", reply_markup=owner_keyboard())

# معالجات جديدة لأزرار وضع الصيانة
@bot.message_handler(func=lambda m: m.text == "تفعيل صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def enable_maintenance_v2(message):
    """معالج لزر تفعيل صيانة فيديوهات2. يُفعل وضع الصيانة."""
    global maintenance_mode
    maintenance_mode = True
    bot.send_message(message.from_user.id, "✅ تم تفعيل وضع صيانة فيديوهات2.", reply_markup=owner_keyboard())

@bot.message_handler(func=lambda m: m.text == "إيقاف صيانة فيديوهات2" and m.from_user.id == OWNER_ID)
def disable_maintenance_v2(message):
    """معالج لزر إيقاف صيانة فيديوهات2. يُعطل وضع الصيانة."""
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
