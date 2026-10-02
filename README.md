import os
import re
import time
import json
import asyncio
import tempfile
import shutil
import subprocess
import threading
import aiohttp
import aiosqlite
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters)

# جلب التوكن وآيدي المالك من متغيرات البيئة تلقائياً
TOKEN    = os.environ.get("TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "1108903232"))
DB_PATH  = "xk_wm.db"
UA       = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "XK Bot is alive", 200

@flask_app.route("/health")
def health():
    return {"status": "ok"}, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def start_flask():
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()


async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, first_seen INTEGER, last_seen INTEGER, downloads INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, url TEXT, platform TEXT, created_at INTEGER)""")
        await db.commit()


async def db_upsert(u):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO users (user_id, username, first_name, first_seen, last_seen, downloads) VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen, downloads=downloads+1""", (u.id, u.username or "", u.first_name or "", now, now))
        await db.commit()


async def db_log(uid, url, platform):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, url, platform, created_at) VALUES (?, ?, ?, ?)", (uid, url, platform, int(time.time())))
        await db.commit()


async def db_get(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT downloads FROM users WHERE user_id=?", (uid,)) as c:
            row = await c.fetchone()
            return row[0] if row else 0


async def db_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM history") as c: total = (await c.fetchone())[0]
    return {"users": users, "total": total}


async def guard(update, context):
    u = update.effective_user
    if not u: return False, None
    await db_upsert(u)
    return True, u


def run_ytdlp_sync(url, tmpdir):
    out_tpl = os.path.join(tmpdir, "vid.%(ext)s")
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist", "--no-check-certificates", "-f", "bv*+ba/b[ext=mp4]/b", "--merge-output-format", "mp4", "-o", out_tpl, url]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)


async def tiktok_tikwm(session, url):
    apis = [f"https://www.tikwm.com/api/?url={url}&hd=1", f"https://tikwm.com/api/?url={url}&hd=1"]
    for api in apis:
        try:
            async with session.get(api, timeout=25, headers={"User-Agent": UA}) as r:
                if r.status != 200: continue
                data = await r.json(content_type=None)
                d = data.get("data") if isinstance(data, dict) else None
                if not d: continue
                vid = d.get("hdplay") or d.get("play") or d.get("wmplay")
                if not vid: continue
                tmpdir = tempfile.mkdtemp(prefix="xktk_")
                fp = os.path.join(tmpdir, "vid.mp4")
                headers_dl = {"User-Agent": UA, "Referer": "https://www.tiktok.com/", "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
                async with session.get(vid, timeout=120, headers=headers_dl, allow_redirects=True) as r2:
                    if r2.status not in (200, 206): continue
                    data_bytes = await r2.read()
                    if len(data_bytes) < 200_000: continue
                    if data_bytes[4:8] != b"ftyp":
                        continue
                    with open(fp, "wb") as f: f.write(data_bytes)
                    return {"path": fp, "tmpdir": tmpdir, "title": d.get("title", "")[:100], "platform": "tiktok"}
        except Exception:
            continue
    return None


async def tiktok_ytdlp(url):
    tmpdir = tempfile.mkdtemp(prefix="xktk_")
    loop = asyncio.get_event_loop()
    try:
        res = await loop.run_in_executor(None, run_ytdlp_sync, url, tmpdir)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    if res.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    best = None
    for f in os.listdir(tmpdir):
        fp = os.path.join(tmpdir, f)
        if os.path.isfile(fp) and os.path.getsize(fp) > 100_000:
            if fp.endswith(".mp4"):
                best = fp
                break
            if best is None: best = fp
    if not best:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    return {"path": best, "tmpdir": tmpdir, "title": "", "platform": "tiktok"}


async def process_url(session, url):
    result = await tiktok_tikwm(session, url)
    if result: return result
    return await tiktok_ytdlp(url)


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 TikTok", callback_data="menu_tiktok")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="my_stats")],
        [InlineKeyboardButton("❓ كيف أستخدم", callback_data="how_to")],
        [InlineKeyboardButton("👑 المالك", url=f"tg://user?id={OWNER_ID}")],
    ])


def tiktok_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 طريقة الاستخدام", callback_data="tt_how")],
        [InlineKeyboardButton("🔗 جرب رابط الآن", callback_data="tt_try")],
        [InlineKeyboardButton("◀ رجوع", callback_data="back_main")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀ رجوع", callback_data="back_main")]])


async def cmd_start(update, context):
    ok, u = await guard(update, context)
    if not ok: return
    downloads = await db_get(u.id)
    await update.message.reply_text(
        f"👋 أهلاً <b>{u.first_name}</b>!\n\n"
        f"🎬 <b>XK WM Remover</b>\n"
        f"عدد تحميلاتك: <b>{downloads}</b>\n\n"
        f"اختار من الأزرار تحت:",
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def cmd_help(update, context):
    ok, u = await guard(update, context)
    if not ok: return
    await update.message.reply_text(
        "📖 <b>الطريقة</b>\n\n"
        "1. اضغط زر <b>🎵 TikTok</b>\n"
        "2. اقرأ التعليمات\n"
        "3. ارجع وارسل الرابط\n\n"
        "البوت يرد بالفيديو نقي بدون علامة مائية.",
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def cmd_id(update, context):
    await update.message.reply_text(f"<code>{update.effective_user.id}</code>", parse_mode=ParseMode.HTML)


async def cmd_menu(update, context):
    ok, u = await guard(update, context)
    if not ok: return
    await update.message.reply_text("📋 <b>القائمة الرئيسية</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def cmd_stats(update, context):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 للمالك فقط."); return
    s = await db_stats()
    await update.message.reply_text(f"👑 <b>إحصائيات البوت</b>\nالمستخدمون: {s['users']}\nالتحميلات: {s['total']}", parse_mode=ParseMode.HTML)


async def cmd_broadcast(update, context):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 للمالك فقط."); return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("الاستخدام: /broadcast <نص>"); return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE is_banned=0") as c: users = await c.fetchall()
    sent, failed = 0, 0
    for (uid,) in users:
        try: await context.bot.send_message(uid, text, parse_mode=ParseMode.HTML); sent += 1; await asyncio.sleep(0.05)
        except: failed += 1
    await update.message.reply_text(f"📢 نجح: {sent} | فشل: {failed}")


async def cb_handler(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu_tiktok":
        await q.message.edit_text(
            "🎵 <b>TikTok</b>\n\n"
            "أرسل رابط الفيديو، وسأرجّعه لك بدون علامة مائية.\n\n"
            "<b>طريقة الحصول على الرابط:</b>\n"
            "1. افتح TikTok\n"
            "2. اختر الفيديو\n"
            "3. اضغط Share (سهم)\n"
            "4. اختر <b>Copy Link</b>\n"
            "5. ارجع هنا والصق الرابط",
            parse_mode=ParseMode.HTML, reply_markup=tiktok_menu_kb())

    elif data == "tt_how":
        await q.message.edit_text(
            "📖 <b>طريقة الاستخدام خطوة بخطوة</b>\n\n"
            "1. افتح تطبيق TikTok\n"
            "2. اذهب للفيديو\n"
            "3. اضغط أيقونة المشاركة (سهم)\n"
            "4. اختر Copy Link\n"
            "5. ارجع لتيليجرام والصق الرابط\n"
            "6. انتظر ثواني ويصلك الفيديو",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "tt_try":
        await q.message.edit_text(
            "🔗 <b>مثال على الرابط:</b>\n\n"
            "<code>https://vt.tiktok.com/ZSb5QJ6gn/</code>\n\n"
            "الصق رابطك في المحادثة الآن.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "my_stats":
        u = q.from_user
        downloads = await db_get(u.id)
        await q.message.edit_text(
            f"📊 <b>إحصائياتك</b>\n\n"
            f"الآيدي: <code>{u.id}</code>\n"
            f"عدد التحميلات: <b>{downloads}</b>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "how_to":
        await q.message.edit_text(
            "❓ <b>كيف تستخدم البوت</b>\n\n"
            "1. اضغط <b>🎵 TikTok</b>\n"
            "2. انسخ رابط الفيديو\n"
            "3. الصق الرابط في المحادثة",
            parse_mode=ParseMode.HTML, reply_markup=back_kb())

    elif data == "back_main":
        u = q.from_user
        downloads = await db_get(u.id)
        await q.message.edit_text(
            f"👋 أهلاً <b>{u.first_name}</b>!\n\n"
            f"🎬 <b>XK WM Remover</b>\n"
            f"عدد تحميلاتك: <b>{downloads}</b>\n\n"
            f"اختار من الأزرار:",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def handle_url(update, context):
    ok, u = await guard(update, context)
    if not ok: return
    url = update.message.text.strip()
    if "tiktok.com" not in url.lower():
        await update.message.reply_text("❌ أرسل رابط TikTok فقط.", reply_markup=main_menu_kb())
        return
    msg = await update.message.reply_text("⏳ جاري التحميل...")
    async with aiohttp.ClientSession() as session:
        try:
            result = await process_url(session, url)
        except Exception as e:
            await msg.edit_text(f"❌ خطأ: {str(e)[:300]}")
            return
    if not result:
        await msg.edit_text("❌ فشل التحميل. تأكد من أن الفيديو غير خاص أو أعد المحاولة بعد قليل.")
        return
    cap = "✅ TikTok"
    if result.get("title"): cap += f"\n{result['title'][:100]}"
    try:
        with open(result["path"], "rb") as f:
            await update.message.reply_video(video=InputFile(f, filename="xk.mp4"), caption=cap, supports_streaming=True, reply_markup=main_menu_kb())
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ خطأ إرسال: {str(e)[:300]}")
    finally:
        tmpdir = result.get("tmpdir")
        if tmpdir and os.path.isdir(tmpdir):
            try: shutil.rmtree(tmpdir, ignore_errors=True)
            except: pass
    await db_log(u.id, url, "tiktok")


async def post_init(app):
    await db_init()


def main():
    if not TOKEN:
        raise ValueError("TOKEN environment variable is missing!")
    start_flask()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
