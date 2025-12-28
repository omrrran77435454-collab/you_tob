import os
import re
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.types import Message, ChatMemberUpdated, ChatPermissions
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv


# ===================== إعدادات =====================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WELCOME_PHOTO_URL = os.getenv("WELCOME_PHOTO_URL", "").strip()
MUTE_SECONDS = int(os.getenv("MUTE_SECONDS", "300"))

# ✅ آيديات الأدمن
ADMIN_IDS = {5559869840}

# ✅ رسالة التحذير تُحذف بعد كم ثانية؟
WARNING_DELETE_AFTER = 10

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in .env or Render Environment Variables")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("spam-guard-bot")

dp = Dispatcher()

LINK_REGEX = re.compile(r"(?i)\b((?:https?://|www\.)\S+|t\.me/\S+|telegram\.me/\S+)")

# ✅ نخزن من تم الترحيب بهم
welcomed_users = set()


# ===================== أدوات مساعدة =====================

def safe_text(s: str) -> str:
    if not s:
        return ""
    return s.replace("<", "").replace(">", "")


def now_str_utc() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")


def message_has_link(message: Message) -> bool:
    text = message.text or message.caption or ""
    entities = (message.entities or []) + (message.caption_entities or [])
    for ent in entities:
        if ent.type in ("url", "text_link"):
            return True
    return bool(LINK_REGEX.search(text))


async def is_admin_by_role(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def is_allowed_sender(bot: Bot, message: Message) -> bool:
    # ✅ منشورات القناة داخل التعليقات نتركها
    if message.sender_chat is not None:
        return True

    if message.from_user and message.from_user.id in ADMIN_IDS:
        return True

    if message.from_user:
        try:
            return await is_admin_by_role(bot, message.chat.id, message.from_user.id)
        except TelegramBadRequest:
            return False

    return False


async def restrict_user(bot: Bot, chat_id: int, user_id: int, seconds: int):
    until_date = int(datetime.now(timezone.utc).timestamp()) + seconds
    perms = ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )
    await bot.restrict_chat_member(chat_id, user_id, perms, until_date=until_date)


async def unrestrict_user(bot: Bot, chat_id: int, user_id: int):
    perms = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
    )
    await bot.restrict_chat_member(chat_id, user_id, perms)


async def delete_after_delay(msg: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass


async def send_welcome(bot: Bot, chat_id: int, user_id: int, full_name: str, username: str | None):
    key = (chat_id, user_id)
    if key in welcomed_users:
        return

    welcomed_users.add(key)

    join_time = now_str_utc()
    username_text = f"@{username}" if username else "لا يوجد"

    text = (
        f"👋 <b>مرحباً بك في المجموعة</b>\n\n"
        f"👤 <b>الاسم:</b> {safe_text(full_name)}\n"
        f"🆔 <b>الآيدي:</b> <code>{user_id}</code>\n"
        f"🔗 <b>المعرف:</b> <code>{username_text}</code>\n"
        f"📌 <b>التاريخ/الوقت:</b> <code>{join_time}</code>\n\n"
        f"📖 <b>قوانين المجموعة:</b>\n"
        f"• يمنع إرسال الروابط من غير الإدارة.\n"
        f"• يمنع السبام والإزعاج.\n"
        f"• احترام الجميع.\n\n"
        f"✨ نتمنى لك إقامة طيبة معنا."
    )

    try:
        if WELCOME_PHOTO_URL:
            await bot.send_photo(chat_id, photo=WELCOME_PHOTO_URL, caption=text)
        else:
            await bot.send_message(chat_id, text)
    except TelegramBadRequest:
        pass


# ===================== ترحيب عند الانضمام =====================

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=(ChatMemberStatus.LEFT, ChatMemberStatus.MEMBER)))
async def on_user_join(event: ChatMemberUpdated, bot: Bot):
    if event.chat.type not in ("group", "supergroup"):
        return

    user = event.new_chat_member.user
    await send_welcome(
        bot=bot,
        chat_id=event.chat.id,
        user_id=user.id,
        full_name=user.full_name,
        username=user.username
    )


# ===================== ترحيب عند أول رسالة + منع الروابط =====================

@dp.message()
async def on_message(message: Message, bot: Bot):
    if message.chat.type not in ("group", "supergroup"):
        return

    # ✅ لا نرحب لمن يرسل باسم قناة
    if message.sender_chat is not None:
        return

    # ✅ إذا أول مرة يكتب: نرحب به
    if message.from_user:
        await send_welcome(
            bot=bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username
        )

    # ✅ منع الروابط
    if not message_has_link(message):
        return

    if await is_allowed_sender(bot, message):
        return

    # حذف رسالة الرابط
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    if not message.from_user:
        return

    # تقييد
    try:
        await restrict_user(bot, message.chat.id, message.from_user.id, MUTE_SECONDS)
    except TelegramBadRequest:
        return

    warn_text = (
        f"⚠️ <b>تنبيه:</b> يمنع إرسال الروابط لغير الإدارة.\n"
        f"تم تقييد <b>{safe_text(message.from_user.full_name)}</b> لمدة <code>{MUTE_SECONDS//60}</code> دقائق."
    )

    try:
        warn_msg = await bot.send_message(message.chat.id, warn_text)
        asyncio.create_task(delete_after_delay(warn_msg, WARNING_DELETE_AFTER))
    except TelegramBadRequest:
        pass

    async def lift_later():
        await asyncio.sleep(MUTE_SECONDS)
        try:
            await unrestrict_user(bot, message.chat.id, message.from_user.id)
        except TelegramBadRequest:
            pass

    asyncio.create_task(lift_later())


# ===================== تشغيل =====================

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    log.info("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
