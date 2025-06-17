import os
import time
import json
from flask import Flask
from threading import Thread

import telebot
from telebot import types

from pymongo import MongoClient

# ====================================================================
#                      ! ! ! مـهـم جـداً ! ! !
# ====================================================================
# قبل تشغيل البوت، تأكد من إعداد متغيرات البيئة التالية:
# 1. TOKEN: توكن بوت تيليجرام الخاص بك.
# 2. CHANNEL_ID_V1: آيدي القناة التي ستُرفع إليها فيديوهات قسم "فيديوهات1".
# 3. CHANNEL_ID_V2: آيدي القناة التي ستُرفع إليها فيديوهات قسم "فيديوهات2".
# 4. MONGODB_URI: رابط اتصال قاعدة بيانات MongoDB الخاصة بك.

# يجب أن يكون البوت:
# - مشرفًا في جميع قنوات الاشتراك الإجباري (true_subscribe_links) مع صلاحية "دعوة المستخدمين عبر الرابط"
#   و "الحصول على معلومات حول المشتركين" للتحقق من الاشتراك.
# - مشرفًا في CHANNEL_ID_V1 و CHANNEL_ID_V2 مع صلاحية "نشر الرسائل" و "حذف الرسائل"
#   و "دعوة المستخدمين عبر الرابط" (للسماح برفع الفيديوهات والتنظيف والحذف).
# ====================================================================


# متغيرات البيئة
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    print("❌ خطأ: متغير البيئة 'TOKEN' غير موجود.")
    exit(1) # يوقف البوت إذا لم يتم توفير التوكن

bot = telebot.TeleBot(TOKEN)
OWNER_ID = 7054294622  # عدّل رقمك هنا، هو آيدي تيليجرام الخاص بك

maintenance_mode = False # هذا المتغير يتحكم بوضع صيانة فيديوهات2 فقط

# آيدي القناة الخاصة بفيديوهات1 (تأكد من إعداده كمتغير بيئة)
CHANNEL_ID_V1 = os.environ.get("CHANNEL_ID_V1")
# آيدي القناة الخاصة بفيديوهات2 (تأكد من إعداده كمتغير بيئة)
CHANNEL_ID_V2 = os.environ.get("CHANNEL_ID_V2")

if not CHANNEL_ID_V1 or not CHANNEL_ID_V2:
    print("❌ خطأ: متغيرات البيئة 'CHANNEL_ID_V1' أو 'CHANNEL_ID_V2' غير موجودة.")
    exit(1)

# تحويل آيدي القنوات إلى أعداد صحيحة
try:
    CHANNEL_ID_V1 = int(CHANNEL_ID_V1)
    CHANNEL_ID_V2 = int(CHANNEL_ID_V2)
except ValueError:
    print("❌ خطأ: CHANNEL_ID_V1 أو CHANNEL_ID_V2 يجب أن يكون رقمًا صحيحًا.")
    exit(1)

waiting_for_delete = {} # {user_id: {"category": "v1/v2", "videos": [video_docs]}}
true_sub_pending = {}  # {user_id: step} - لتتبع تقدم المستخدم في الاشتراك الإجباري الحقيقي

MONGODB_URI = os.environ.get("MONGODB_URI")
if not MONGODB_URI:
    print("❌ خطأ: متغير البيئة 'MONGODB_URI' غير موجود.")
    exit(1)

# إعداد MongoDB
try:
    client = MongoClient(MONGODB_URI)
    db = client["telegram_bot_db"]
    # اختبار الاتصال بقاعدة البيانات
    client.admin.command('ping')
    print("✅ تم الاتصال بقاعدة بيانات MongoDB بنجاح!")
except Exception as e:
    print(f"❌ فشل الاتصال بقاعدة بيانات MongoDB: {e}")
    exit(1)

users_col = db["users"]

# مجموعات (Collections)
approved_v1_col = db["approved_v1"]
approved_v2_col = db["approved_v2"]
notified_users_col = db["notified_users"]
videos_v1_col = db["videos_v1"]
videos_v2_col = db["videos_v2"]


# روابط قنوات الاشتراك الاختياري لقسم فيديوهات1
subscribe_links_v1 = [
    "https://t.me/+2L5KrXuCDUA5ZWIy",
    "https://t.me/+SPTrcs3tJqhlMDVi",
    "https://t.me/+W2KuzsUu_zcyODIy",
    "https://t.me/+CFA6qHiV0zw1NjRk",
]

# روابط قنوات الاشتراك الاختياري لقسم فيديوهات2
subscribe_links_v2 = [
    "https://t.me/R2M199",
    "https://t.me/SNOKER_VIP",
]

# هذه هي قنوات الاشتراك الإجباري الحقيقي التي يجب على المستخدم الاشتراك بها أولاً
# يجب أن يكون البوت مشرفًا في هذه القنوات ليتمكن من التحقق من الاشتراك.
true_subscribe_links = [
    "https://t.me/BLACK_ROOT1",
    "https://t.me/SNOKER_VIP",
    "https://t.me/R2M199"
]

pending_check = {} # {user_id: {"category": "v1/v2", "step": 0}} - لتتبع تقدم المستخدم في الاشتراكات الاختيارية
owner_upload_mode = {} # {user_id: "v1/v2"} - لتحديد القسم الذي يرفع فيه المالك الفيديوهات
waiting_for_broadcast = {} # {"photo": True/False, "photo_file_id": "...", "awaiting_text": True/False}


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
    # تستخدم أزرار لوحة المفاتيح العادية للمستخدمين
    return types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True).add(
        types.KeyboardButton("فيديوهات1"), types.KeyboardButton("فيديوهات2")
    )

def owner_inline_keyboard():
    """
    إنشاء لوحة مفاتيح المالك بأزرار تحكم شفافة (Inline Keyboard).
    تسمح بالتحكم في البوت مباشرة من الرسالة.
    """
    markup = types.InlineKeyboardMarkup(row_width=2) # يمكن تعديل row_width حسب الحاجة
    markup.add(
        types.InlineKeyboardButton("عرض فيديوهات1 🎬", callback_data="owner_action_view_v1"),
        types.InlineKeyboardButton("عرض فيديوهات2 🎬", callback_data="owner_action_view_v2"),
        types.InlineKeyboardButton("رفع لـ فيديوهات1 ⬆️", callback_data="owner_action_upload_mode_v1"),
        types.InlineKeyboardButton("رفع لـ فيديوهات2 ⬆️", callback_data="owner_action_upload_mode_v2"),
        types.InlineKeyboardButton("حذف فيديوهات1 🗑️", callback_data="owner_action_delete_menu_v1"),
        types.InlineKeyboardButton("حذف فيديوهات2 🗑️", callback_data="owner_action_delete_menu_v2"),
        types.InlineKeyboardButton("تنظيف فيديوهات1 🧹", callback_data="owner_action_clean_v1"),
        types.InlineKeyboardButton("تنظيف فيديوهات2 🧹", callback_data="owner_action_clean_v2"),
        types.InlineKeyboardButton("تفعيل صيانة ⚙️", callback_data="owner_action_maintenance_on_v2"),
        types.InlineKeyboardButton("إيقاف صيانة ✅", callback_data="owner_action_maintenance_off_v2"),
        types.InlineKeyboardButton("رسالة جماعية مع صورة 📢", callback_data="owner_action_broadcast_photo")
    )
    return markup

def get_all_approved_users():
    """الحصول على جميع المستخدمين الذين تم قبولهم في أي من القسمين."""
    return set(
        user["user_id"] for user in approved_v1_col.find()
    ).union(
        user["user_id"] for user in approved_v2_col.find()
    )

def send_videos(user_id, category):
    """
    إرسال الفيديوهات من قسم معين إلى المستخدم.
    يقوم بالنسخ من القناة المحددة.
    """
    collection = videos_v1_col if category == "v1" else videos_v2_col
    videos = list(collection.find())

    if not videos:
        bot.send_message(user_id, "❌ لا توجد فيديوهات حالياً في هذا القسم.")
        return

    bot.send_message(user_id, f"جاري إرسال فيديوهات قسم {category[-1]}... يرجى الانتظار.")
    for video in videos:
        try:
            bot.copy_message(
                chat_id=user_id,
                from_chat_id=video["chat_id"],
                message_id=video["message_id"],
                caption="", # إزالة الكابشن الأصلي
                caption_entities=None
            )
            time.sleep(0.5)  # تأخير لمنع الحظر أو التقييد من تيليجرام
        except telebot.apihelper.ApiTelegramException as e:
            print(f"❌ خطأ Telegram API أثناء إرسال الفيديو {video['message_id']} للمستخدم {user_id}: {e}")
            if "Too Many Requests" in str(e):
                print("⚠️ تجاوز حد الطلبات، سأحاول الانتظار.")
                time.sleep(5) # انتظار أطول
            elif "message not found" in str(e).lower() or "not exists" in str(e).lower():
                print(f"⚠️ الفيديو {video['message_id']} غير موجود في القناة الأصلية، سيتم إزالته من DB.")
                collection.delete_one({"_id": video["_id"]})
            else:
                pass # تجاهل أخطاء أخرى للمضي قدماً
        except Exception as e:
            print(f"❌ خطأ عام أثناء إرسال الفيديو {video['message_id']} للمستخدم {user_id}: {e}")


# --- دوال وإجراءات المالك باستخدام Inline Keyboard ---

def send_delete_menu_inline(user_id, category):
    """
    يرسل قائمة بالفيديوهات المتاحة للحذف للمالك.
    يطلب من المالك إرسال رقم الفيديو المراد حذفه.
    """
    collection = videos_v1_col if category == "v1" else videos_v2_col
    videos = list(collection.find().limit(20)) # عرض 20 فيديو كحد أقصى للحذف

    if not videos:
        bot.send_message(user_id, f"لا يوجد فيديوهات في قسم فيديوهات{category[-1]} للحذف حالياً.", reply_markup=owner_inline_keyboard())
        return

    text = f"📋 قائمة فيديوهات{category[-1]} للحذف (أرسل رقم الفيديو):\n"
    for i, vid in enumerate(videos, 1):
        text += f"{i}. رسالة رقم: {vid['message_id']}\n"
    text += "\nالرجاء إرسال رقم الفيديو الذي تريد حذفه من هذه القائمة.\n" \
            "أو أرسل 'إلغاء' للعودة إلى القائمة الرئيسية للمالك."

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="owner_action_main_menu"))

    bot.send_message(user_id, text, reply_markup=markup)
    waiting_for_delete[user_id] = {"category": category, "videos": videos}
    print(f"Debug: {user_id} دخل وضع حذف الفيديو لـ {category}.")


@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID and m.from_user.id in waiting_for_delete)
def handle_delete_choice_text_input(message):
    """
    معالج للمالك عندما يرسل رقم فيديو للحذف أو كلمة "إلغاء".
    يعمل فقط إذا كان المالك في حالة 'waiting_for_delete'.
    """
    user_id = message.from_user.id
    data = waiting_for_delete.get(user_id)

    if not data:
        # هذه الحالة لا ينبغي أن تحدث إذا كان المعالج يعمل بشكل صحيح
        # ولكن كاحتياط، نرسل لوحة مفاتيح المالك.
        bot.send_message(user_id, "⚠️ خطأ في حالة الحذف. يرجى البدء من جديد.", reply_markup=owner_inline_keyboard())
        return

    if message.text == "إلغاء":
        waiting_for_delete.pop(user_id)
        bot.send_message(user_id, "تم إلغاء عملية الحذف. تم الرجوع إلى القائمة الرئيسية للمالك:", reply_markup=owner_inline_keyboard())
        print(f"Debug: {user_id} ألغى عملية الحذف.")
        return

    try:
        choice = int(message.text)
        videos = data["videos"]
        category = data["category"]
        channel_id_to_delete_from = CHANNEL_ID_V1 if category == "v1" else CHANNEL_ID_V2
        collection = videos_v1_col if category == "v1" else videos_v2_col


        if 1 <= choice <= len(videos):
            video_to_delete = videos[choice - 1]
            message_id = video_to_delete["message_id"]

            try:
                # محاولة حذف الرسالة من القناة أولاً
                bot.delete_message(channel_id_to_delete_from, message_id)
                print(f"Debug: تم حذف الرسالة {message_id} من القناة {channel_id_to_delete_from}.")

                # حذف السجل من قاعدة البيانات بعد نجاح الحذف من القناة
                collection.delete_one({"message_id": message_id})
                bot.send_message(user_id, f"✅ تم حذف الفيديو رقم {choice} بنجاح من البوت والقناة.", reply_markup=owner_inline_keyboard())
                print(f"Debug: تم حذف السجل للفيديو {message_id} من DB.")

            except telebot.apihelper.ApiTelegramException as e:
                # إذا كانت الرسالة غير موجودة في القناة (تم حذفها يدويًا مثلاً)، نقوم بحذفها من DB فقط
                if "message not found" in str(e).lower() or "message to delete not found" in str(e).lower():
                    collection.delete_one({"message_id": message_id})
                    bot.send_message(user_id, f"⚠️ الفيديو رقم {choice} غير موجود في القناة. تم حذفه من قاعدة بيانات البوت فقط.", reply_markup=owner_inline_keyboard())
                    print(f"Debug: الفيديو {message_id} غير موجود في القناة. تم حذفه من DB.")
                else:
                    bot.send_message(user_id, f"❌ حدث خطأ أثناء حذف الفيديو من القناة: {e}", reply_markup=owner_inline_keyboard())
                    print(f"❌ خطأ API أثناء حذف الفيديو {message_id} من القناة: {e}")
            except Exception as e:
                bot.send_message(user_id, f"❌ حدث خطأ غير متوقع أثناء الحذف: {e}", reply_markup=owner_inline_keyboard())
                print(f"❌ خطأ غير متوقع أثناء حذف الفيديو {message_id}: {e}")
            finally:
                waiting_for_delete.pop(user_id) # إنهاء حالة الانتظار
                print(f"Debug: {user_id} خرج من وضع حذف الفيديو.")

        else:
            bot.send_message(user_id, "❌ الرقم غير صحيح. الرجاء إرسال رقم صحيح من القائمة.", reply_markup=types.ForceReply(selective=True))
            print(f"Debug: {user_id} أرسل رقمًا غير صالح للحذف: {message.text}.")

    except ValueError:
        bot.send_message(user_id, "❌ من فضلك أرسل رقم صالح أو كلمة 'إلغاء'.", reply_markup=types.ForceReply(selective=True))
        print(f"Debug: {user_id} أرسل إدخالًا غير رقمي للحذف: {message.text}.")


def clean_videos_action(user_id, category):
    """
    تقوم بتنظيف قاعدة البيانات من سجلات الفيديوهات التي لم تعد موجودة في القناة.
    """
    collection = videos_v1_col if category == "v1" else videos_v2_col
    channel_id = CHANNEL_ID_V1 if category == "v1" else CHANNEL_ID_V2

    bot.send_message(user_id, f"جاري تنظيف فيديوهات{category[-1]}... قد يستغرق هذا بعض الوقت.")
    print(f"Debug: بدأ تنظيف فيديوهات{category[-1]} بواسطة {user_id}.")

    videos = list(collection.find())
    removed_count = 0

    for vid in videos:
        message_id = vid['message_id']
        try:
            # محاولة توجيه الرسالة للتأكد من وجودها.
            # إذا فشلت، فهذا يعني أن الرسالة غير موجودة في القناة.
            bot.forward_message(chat_id=user_id, from_chat_id=channel_id, message_id=message_id)
            # إذا نجحت، نحذف الرسالة التي تم توجيهها لتجنب إزعاج المالك
            bot.delete_message(user_id, bot.send_message(user_id, "TEMP").message_id)
            print(f"Debug: تم التحقق من وجود الفيديو {message_id} في القناة.")
        except telebot.apihelper.ApiTelegramException as e:
            if "message not found" in str(e).lower() or "message to forward not found" in str(e).lower():
                # لو فشل، احذف الفيديو من قاعدة البيانات لأنه غير موجود بالقناة
                collection.delete_one({'_id': vid['_id']})
                removed_count += 1
                print(f"Debug: الفيديو {message_id} غير موجود في القناة. تم حذفه من DB.")
            else:
                print(f"❌ خطأ API أثناء التحقق من الفيديو {message_id}: {e}")
        except Exception as e:
            print(f"❌ خطأ عام أثناء التحقق من الفيديو {message_id}: {e}")

    bot.send_message(user_id, f"✅ تم تنظيف فيديوهات{category[-1]}. عدد الفيديوهات المحذوفة: {removed_count}", reply_markup=owner_inline_keyboard())
    print(f"Debug: انتهى تنظيف فيديوهات{category[-1]}.")


# --- معالج Callbacks للمالك ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("owner_action_") and call.from_user.id == OWNER_ID)
def handle_owner_inline_actions(call):
    bot.answer_callback_query(call.id) # يزيل حالة التحميل من الزر في واجهة المستخدم
    user_id = call.from_user.id
    action = call.data.replace("owner_action_", "")
    print(f"Debug: المالك {user_id} ضغط على الزر: {action}")

    if action == "view_v1":
        send_videos(user_id, "v1")
        # لا نرسل لوحة مفاتيح جديدة هنا، فدالة send_videos سترسل فيديوهات ثم سينتهي الأمر
    elif action == "view_v2":
        send_videos(user_id, "v2")
        # لا نرسل لوحة مفاتيح جديدة هنا
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
        clean_videos_action(user_id, "v1")
    elif action == "clean_v2":
        clean_videos_action(user_id, "v2")
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
    elif action == "main_menu": # للعودة من قوائم فرعية (مثل قائمة الحذف)
        if user_id in waiting_for_delete:
            waiting_for_delete.pop(user_id) # مسح حالة الانتظار للحذف
        bot.send_message(user_id, "تم الرجوع إلى القائمة الرئيسية للمالك:", reply_markup=owner_inline_keyboard())
    
    # بعد كل إجراء، نرسل لوحة المفاتيح الشفافة للمالك مرة أخرى
    # هذا يضمن أن الأزرار متاحة دائمًا للمالك بعد أي عملية
    # باستثناء حالات مثل رفع الفيديو حيث ننتظر إرسال الفيديو نفسه.
    if action not in ["upload_mode_v1", "upload_mode_v2", "broadcast_photo", "delete_menu_v1", "delete_menu_v2"]:
        # لا نرسلها إذا كنا بانتظار إدخال من المالك
        bot.send_message(user_id, "اختر إجراء آخر من أزرار التحكم:", reply_markup=owner_inline_keyboard())


def check_true_subscription(user_id, first_name):
    """
    يقوم بالتحقق من جميع قنوات true_subscribe_links بشكل متسلسل.
    إذا لم يكن المستخدم مشتركًا في قناة، يطلب منه الاشتراك فيها.
    ملاحظة: لكي يعمل التحقق مع قنوات الروابط الخاصة (+link)، يجب أن يكون البوت مشرفًا في تلك القنوات.
    """
    step = true_sub_pending.get(user_id, 0)
    
    # التأكد أن خطوة البداية لا تتجاوز عدد القنوات المتاحة
    if step >= len(true_subscribe_links):
        step = 0 # أعد تعيينها لتبدأ من البداية إذا كان قد أكملها

    all_channels_subscribed = True
    for index in range(step, len(true_subscribe_links)):
        current_channel_link = true_subscribe_links[index]
        print(f"Debug: التحقق من اشتراك المستخدم {user_id} في القناة: {current_channel_link}")
        
        try:
            channel_identifier = current_channel_link.split("t.me/")[-1]
            
            if not channel_identifier.startswith('+'): # قناة عامة (@username)
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
                    print(f"Debug: المستخدم {user_id} غير مشترك في {current_channel_link} (عامة).")
                    return # توقف هنا وانتظر تفاعل المستخدم
            else: # رابط دعوة خاص (يبدأ بـ +)
                # للروابط الخاصة، التحقق عبر get_chat_member يتطلب أن يكون البوت مشرفًا في القناة.
                # إذا لم يكن البوت مشرفًا، سيحدث خطأ. الأفضل هو توجيه المستخدم للضغط على الزر فقط.
                # سنعتبر أن المستخدم يجب أن يضغط على الرابط ثم يعود ليتحقق عبر الزر.
                # يجب أن يكون البوت مشرفًا في هذه القناة.
                chat_id_from_link = None
                try:
                    # محاولة استخراج chat_id من رابط الدعوة إذا أمكن
                    # هذه الطريقة ليست مضمونة وتعتمد على تنسيق الرابط وإعدادات تيليجرام
                    # الأفضل أن يكون لديك الـ chat_id الحقيقي للقنوات الخاصة إذا كنت ستستخدم get_chat_member
                    # For simplicity, we'll assume the link is directly usable or bot is admin.
                    # A more robust solution might involve hardcoding chat_ids for private channels.
                    
                    # محاولة الحصول على معلومات القناة من الرابط (يعمل فقط إذا كان البوت مشتركًا أو لديه حق الوصول)
                    # هذا الجزء قد يفشل إذا لم يكن البوت مشرفًا في القناة الخاصة.
                    # member = bot.get_chat_member(chat_id=current_channel_link, user_id=user_id)
                    # if member.status not in ['member', 'administrator', 'creator']:
                    #    all_channels_subscribed = False
                    #    true_sub_pending[user_id] = index
                    #    ... (نفس منطق رسالة الخطأ أدناه)
                    
                    # بما أن التحقق من get_chat_member لروابط الدعوة الخاصة معقد،
                    # سنعتمد على أن المستخدم سيضغط على الرابط ثم يعود ليؤكد بنفسه.
                    # إذا لم يكن البوت مشرفًا، قد يفشل التحقق لاحقًا.
                    pass
                except Exception as ex_inner:
                    print(f"WARNING: Could not check private channel {current_channel_link} directly for {user_id}: {ex_inner}. Bot likely not admin.")
                
                all_channels_subscribed = False
                true_sub_pending[user_id] = index # احفظ الخطوة
                text = (
                    "🔔 لطفاً اشترك في القناة التالية واضغط على الزر أدناه للمتابعة:\n"
                    f"📮: {current_channel_link}"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ لقد اشتركت، اضغط هنا للمتابعة", callback_data="check_true_subscription"))
                bot.send_message(user_id, text, disable_web_page_preview=True, reply_markup=markup)
                print(f"Debug: المستخدم {user_id} غير مشترك في {current_channel_link} (خاصة).")
                return # توقف هنا وانتظر تفاعل المستخدم
            
            # إذا كان مشتركًا أو تم تجاوز فحص القناة الخاصة بنجاح، استمر في الحلقة
            true_sub_pending[user_id] = index + 1 # تحديث الخطوة للقناة التالية

        except telebot.apihelper.ApiTelegramException as e:
            # يمكن أن يحدث خطأ إذا كانت القناة غير موجودة، أو البوت ليس مشرفًا (خاصة في القنوات الخاصة)، أو مشكلة في API
            print(f"❌ خطأ Telegram API أثناء التحقق من القناة {current_channel_link} للمستخدم {user_id}: {e}")
            all_channels_subscribed = False
            true_sub_pending[user_id] = index # ابقَ على نفس الخطوة ليحاول مرة أخرى
            error_message = ""
            if "chat not found" in str(e).lower() or "not a member" in str(e).lower():
                error_message = "قد لا يكون البوت مشرفًا في هذه القناة أو القناة غير موجودة."
            text = (
                f"⚠️ حدث خطأ أثناء التحقق من الاشتراك في القناة: {current_channel_link}.\n"
                f"{error_message} يرجى التأكد أنك مشترك وأن البوت مشرف في القناة، ثم حاول الضغط على الزر مرة أخرى."
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
            print(f"Debug: المستخدم {user_id} أضيف كـ 'joined'.")
        else:
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": True, "first_name": first_name}})
            print(f"Debug: حالة المستخدم {user_id} حدثت إلى 'joined'.")

        # استدعاء المنطق الفعلي بعد التحقق
        send_start_welcome_message(user_id, first_name)
    else:
        # إذا لم يكن مشتركًا في كل القنوات بعد، تأكد من إخفاء الكيبورد
        user_data_db = users_col.find_one({"user_id": user_id})
        if user_data_db and user_data_db.get("joined", False):
            users_col.update_one({"user_id": user_id}, {"$set": {"joined": False}})
            print(f"Debug: حالة المستخدم {user_id} حدثت إلى 'not joined'.")


@bot.message_handler(commands=['start'])
def handle_start(message):
    """معالج لأمر /start. يوجه المستخدمين العاديين للتحقق من الاشتراك والمالك للقائمة الرئيسية."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم جديد"

    # إذا كان المستخدم هو المالك، أظهر لوحة مفاتيح المالك الشفافة مباشرة
    if user_id == OWNER_ID:
        bot.send_message(user_id, "مرحباً مالك البوت، اختر الإجراء:", reply_markup=owner_inline_keyboard())
        print(f"Debug: المالك {user_id} استخدم /start.")
        return

    # لكل المستخدمين الآخرين، ابدأ عملية التحقق من الاشتراك الإجباري
    bot.send_message(user_id, "أهلاً بك! يرجى إكمال الاشتراك في القنوات الإجبارية للوصول إلى البوت.", reply_markup=types.ReplyKeyboardRemove())
    print(f"Debug: المستخدم {user_id} استخدم /start وبدأ التحقق من الاشتراك الإجباري.")
    check_true_subscription(user_id, first_name)


def send_start_welcome_message(user_id, first_name):
    """المنطق الفعلي لدالة /start بعد التحقق من الاشتراك في القنوات الإجبارية."""
    bot.send_message(user_id, f"""🔞 مرحباً بك ( {first_name} ) 🏳‍🌈
📂اختر قسم الفيديوهات من الأزرار بالأسفل!

⚠️ المحتوى +18 - للكبار فقط!""", reply_markup=main_keyboard())
    print(f"Debug: المستخدم {user_id} تلقى رسالة الترحيب الرئيسية.")

    if not has_notified(user_id):
        # نقوم بعدّ المستخدمين الذين تم التأكد من اشتراكهم الإجباري
        total_users = users_col.count_documents({"joined": True})
        bot.send_message(OWNER_ID, f"""👾 تم دخول شخص جديد إلى البوت الخاص بك

• الاسم : {first_name}
• الايدي : {user_id}
• عدد الأعضاء الكلي: {total_users}
""")
        add_notified_user(user_id)
        print(f"Debug: إشعار دخول مستخدم جديد {user_id} أُرسل للمالك.")


@bot.callback_query_handler(func=lambda call: call.data == "check_true_subscription")
def handle_check_true_subscription_callback(call):
    """معالج لـ callback_data "check_true_subscription" لإعادة التحقق من الاشتراك الإجباري."""
    bot.answer_callback_query(call.id, "جاري التحقق من اشتراكك...")
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "مستخدم"
    print(f"Debug: المستخدم {user_id} ضغط زر 'check_true_subscription'.")
    check_true_subscription(user_id, first_name)


@bot.message_handler(func=lambda m: m.text == "فيديوهات1")
def handle_v1(message):
    """معالج لزر فيديوهات1 (Reply Keyboard)."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"
    print(f"Debug: المستخدم {user_id} ضغط 'فيديوهات1'.")

    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name) # نعيد توجيهه لإكمال الاشتراك الإجباري
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
    """معالج لزر فيديوهات2 (Reply Keyboard) مع التحقق من وضع الصيانة."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "مستخدم"
    print(f"Debug: المستخدم {user_id} ضغط 'فيديوهات2'.")

    user_data_db = users_col.find_one({"user_id": user_id})
    if not user_data_db or not user_data_db.get("joined", False):
        bot.send_message(user_id, "⚠️ يجب عليك إكمال الاشتراك في القنوات الإجبارية أولاً. اضغط /start للمتابعة.", reply_markup=types.ReplyKeyboardRemove())
        check_true_subscription(user_id, first_name) # نعيد توجيهه لإكمال الاشتراك الإجباري
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
    """إرسال روابط الاشتراك الاختياري المطلوبة."""
    data = pending_check.get(chat_id, {"category": category, "step": 0})
    step = data["step"]
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2

    if step >= len(links):
        notify_owner_for_approval(chat_id, "مستخدم", category)
        bot.send_message(chat_id, "تم إرسال طلبك للموافقة. الرجاء الانتظار.", reply_markup=main_keyboard())
        pending_check.pop(chat_id, None)
        print(f"Debug: المستخدم {chat_id} أكمل روابط {category} الاختيارية. تم إرسال طلب للمالك.")
        return

    link = links[step]

    text = f"""- لطفاً اشترك بالقناة واضغط على الزر أدناه للمتابعة .
- قناة البوت 👾.👇🏻
📬:  {link}
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👾 تحقق الانْ بعد الاشتراك 👾", callback_data=f"verify_{category}_{step}"))
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
    print(f"Debug: المستخدم {chat_id} تلقى رابط الاشتراك الاختياري {step+1}/{len(links)} لـ {category}.")

    pending_check[chat_id] = {"category": category, "step": step}

@bot.callback_query_handler(func=lambda call: call.data.startswith("verify_"))
def verify_subscription_callback(call):
    """معالج للتحقق من الاشتراك الاختياري عبر الأزرار."""
    bot.answer_callback_query(call.id) # لإخفاء حالة التحميل من الزر

    user_id = call.from_user.id
    _, category, step_str = call.data.split("_")
    step = int(step_str) + 1 # الخطوة التالية التي يجب التحقق منها
    links = subscribe_links_v1 if category == "v1" else subscribe_links_v2
    print(f"Debug: المستخدم {user_id} ضغط زر 'verify_{category}_{step_str}'.")

    # يمكن إضافة منطق التحقق الفعلي هنا إذا لزم الأمر، لكن في هذا السيناريو
    # نفترض أن المستخدم قد اشترك إذا ضغط على الزر والمضي قدماً في السلسلة.

    if step < len(links):
        pending_check[user_id] = {"category": category, "step": step}
        send_required_links(user_id, category)
    else:
        # إذا أكمل جميع الروابط الاختيارية، أرسل للمالك للموافقة النهائية
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
        pending_check.pop(user_id, None) # مسح حالة الانتظار بعد إرسال الطلب للمالك
        print(f"Debug: المستخدم {user_id} أكمل جميع روابط {category} الاختيارية. تم إرسال طلب موافقة للمالك.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("resend_"))
def resend_links(call):
    """إعادة إرسال روابط الاشتراك الاختياري عند طلب المستخدم."""
    bot.answer_callback_query(call.id) # إخفاء حالة التحميل من الزر

    user_id = call.from_user.id
    category = call.data.split("_")[1]
    pending_check[user_id] = {"category": category, "step": 0}
    send_required_links(user_id, category)
    print(f"Debug: المستخدم {user_id} طلب إعادة إرسال روابط {category} الاختيارية.")

def notify_owner_for_approval(user_id, name, category):
    """إرسال إشعار للمالك بطلب انضمام جديد لقسم اختياري."""
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
    print(f"Debug: إشعار طلب الموافقة لـ {user_id} في قسم {category} أُرسل للمالك.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_owner_response(call):
    """معالج لاستجابة المالك (قبول أو رفض) لطلب انضمام مستخدم لقسم اختياري."""
    parts = call.data.split("_")
    action, category, user_id = parts[0], parts[1], int(parts[2])

    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🚫 غير مصرح لك بالقيام بهذا الإجراء.")
        print(f"Debug: محاولة غير مصرح بها للتعامل مع الموافقة من {call.from_user.id}.")
        return

    bot.answer_callback_query(call.id) # إخفاء حالة التحميل من الزر

    if action == "approve":
        if category == "v1":
            add_approved_user(approved_v1_col, user_id)
        else:
            add_approved_user(approved_v2_col, user_id)
        bot.send_message(user_id, "✅ تم قبولك من قبل الإدارة! يمكنك الآن استخدام البوت بكل المزايا.", reply_markup=main_keyboard())
        bot.edit_message_text(f"✅ تم قبول المستخدم {user_id} في قسم فيديوهات {category[-1]}.", call.message.chat.id, call.message.message_id)
        print(f"Debug: المالك {OWNER_ID} وافق على {user_id} في قسم {category}.")
    else:
        # إذا تم الرفض، نعيد المستخدم لعملية الاشتراك الإجباري كاحتياط
        # أو يمكن توجيهه إلى رسالة رفض بسيطة.
        bot.send_message(user_id, "❌ لم يتم قبولك. يرجى التأكد من الاشتراك في جميع القنوات وإعادة المحاولة. أرسل /start.", reply_markup=types.ReplyKeyboardRemove())
        bot.edit_message_text(f"❌ تم رفض المستخدم {user_id} في قسم فيديوهات {category[-1]}.", call.message.chat.id, call.message.message_id)
        print(f"Debug: المالك {OWNER_ID} رفض {user_id} في قسم {category}.")


@bot.message_handler(content_types=['video'], func=lambda m: m.from_user.id == OWNER_ID and m.from_user.id in owner_upload_mode)
def handle_video_upload(message):
    """
    معالج لرفع الفيديوهات من قبل المالك.
    يتم استدعاؤه فقط عندما يكون المالك في وضع رفع محدد (owner_upload_mode).
    """
    user_id = message.from_user.id
    mode = owner_upload_mode.get(user_id) # 'v1' أو 'v2'

    if not mode: # هذا الفحص إضافي حيث أن الـ func تضمن وجود المود
        return

    collection = videos_v1_col if mode == "v1" else videos_v2_col
    channel_id = CHANNEL_ID_V1 if mode == "v1" else CHANNEL_ID_V2

    try:
        sent = bot.send_video(
            chat_id=channel_id,
            video=message.video.file_id,
            caption=f"📥 فيديو جديد من المالك - قسم {mode.upper()}",
        )
        # تخزين معلومات الفيديو في قاعدة البيانات
        collection.insert_one({
            "chat_id": sent.chat.id,
            "message_id": sent.message_id,
            "file_id": message.video.file_id # يمكن حفظ file_id الأصلي أيضاً
        })

        bot.reply_to(message, f"✅ تم حفظ الفيديو في قسم {mode.upper()}.", reply_markup=owner_inline_keyboard())
        owner_upload_mode.pop(user_id) # إنهاء وضع الرفع بعد الفيديو
        print(f"Debug: الفيديو {message.video.file_id} حُفظ في {mode.upper()} بواسطة {user_id}.")

    except telebot.apihelper.ApiTelegramException as e:
        print(f"❌ خطأ Telegram API في رفع الفيديو: {e}")
        bot.reply_to(message, f"❌ حدث خطأ أثناء حفظ الفيديو في القناة: {e}", reply_markup=owner_inline_keyboard())
        owner_upload_mode.pop(user_id, None)
    except Exception as e:
        print(f"❌ خطأ عام في رفع الفيديو: {e}")
        bot.reply_to(message, "❌ حدث خطأ غير متوقع أثناء حفظ الفيديو.", reply_markup=owner_inline_keyboard())
        owner_upload_mode.pop(user_id, None)


@bot.message_handler(content_types=['photo'], func=lambda m: waiting_for_broadcast.get("photo") and m.from_user.id == OWNER_ID)
def receive_broadcast_photo(message):
    """استقبال الصورة للرسالة الجماعية من المالك."""
    waiting_for_broadcast["photo_file_id"] = message.photo[-1].file_id
    waiting_for_broadcast["photo"] = False
    waiting_for_broadcast["awaiting_text"] = True
    bot.send_message(message.chat.id, "الآن أرسل لي نص الرسالة التي تريد إرسالها مع الصورة.")
    print(f"Debug: المالك {message.from_user.id} أرسل صورة للبث.")

@bot.message_handler(func=lambda m: waiting_for_broadcast.get("awaiting_text") and m.from_user.id == OWNER_ID)
def receive_broadcast_text(message):
    """استقبال نص الرسالة الجماعية وإرسالها لجميع المستخدمين الموافق عليهم."""
    photo_id = waiting_for_broadcast.get("photo_file_id")
    text = message.text
    # نرسل لجميع المستخدمين الذين سجلوا في البوت (بغض النظر عن أقسامهم)
    all_users = users_col.find({"joined": True})
    sent_count = 0
    failed_count = 0

    bot.send_message(OWNER_ID, "جاري إرسال الرسالة الجماعية... قد يستغرق هذا بعض الوقت.")
    print(f"Debug: بدأ إرسال رسالة جماعية من المالك {OWNER_ID}.")

    for user_doc in all_users:
        user_id = user_doc["user_id"]
        try:
            bot.send_photo(user_id, photo_id, caption=text)
            sent_count += 1
            time.sleep(0.1) # تأخير بسيط لتجنب التقييد من تيليجرام
        except telebot.apihelper.ApiTelegramException as e:
            # يمكن أن يحدث خطأ إذا قام المستخدم بحظر البوت
            print(f"❌ فشل إرسال رسالة بث إلى المستخدم {user_id}: {e}")
            failed_count += 1
            if "bot was blocked by the user" in str(e).lower():
                print(f"Debug: المستخدم {user_id} حظر البوت. يمكن إزالته من قائمة المستخدمين إذا لزم الأمر.")
        except Exception as e:
            print(f"❌ خطأ عام أثناء إرسال رسالة بث إلى المستخدم {user_id}: {e}")
            failed_count += 1
            pass # استمر في الإرسال للمستخدمين الآخرين

    bot.send_message(OWNER_ID, f"✅ تم إرسال الرسالة مع الصورة إلى {sent_count} مستخدم.\n"
                                f"❌ فشل الإرسال إلى {failed_count} مستخدم.", reply_markup=owner_inline_keyboard())
    waiting_for_broadcast.clear()
    print(f"Debug: انتهى إرسال الرسالة الجماعية. أُرسل لـ {sent_count}، فشل لـ {failed_count}.")

# --- Flask Web Server لتشغيل البوت على Render + UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    """المسار الرئيسي للخادم الويب. يعرض رسالة لتأكيد أن البوت يعمل."""
    return "Bot is running"

def run():
    """تشغيل خادم الويب على المنفذ 3000."""
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    """تشغيل الخادم في موضوع منفصل للحفاظ على البوت نشطًا."""
    t = Thread(target=run)
    t.start()

# بدء تشغيل الخادم والبدء في استقصاء رسائل تيليجرام
if __name__ == '__main__':
    keep_alive()
    print("✅ بدأ تشغيل البوت...")
    bot.infinity_polling(timeout=10, long_polling_timeout=10) # أضف timeout لتجنب مشاكل الاتصال

