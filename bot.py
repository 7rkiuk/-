"""
Discord Bot — Single File Monolith
إدارة، إشراف، أدوات، كشف IP، ذكاء اصطناعي، موسيقى، وألعاب.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import random
import time
from datetime import timedelta
from pathlib import Path

import aiohttp
import discord
import psutil
import yt_dlp
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import AsyncOpenAI

# ---------------------------------------------------------------------------
# 1. الإعدادات وقراءة المتغيرات
# ---------------------------------------------------------------------------

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PREFIX = os.getenv("PREFIX", "!")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

COLOR_OK = 0x2ECC71
COLOR_ERR = 0xE74C3C
COLOR_INFO = 0x3498DB
COLOR_WARN = 0xF1C40F

DATA_DIR = Path("data")
WARN_FILE = DATA_DIR / "warnings.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")

if not TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN غير مضبوط في متغيرات البيئة")

DATA_DIR.mkdir(exist_ok=True)
if not WARN_FILE.exists():
    WARN_FILE.write_text("{}")

# ---------------------------------------------------------------------------
# 2. إعدادات الصلاحيات والبوت الأساسية
# ---------------------------------------------------------------------------

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.guilds = True
INTENTS.voice_states = True
INTENTS.moderation = True


class ArabicBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=PREFIX,
            intents=INTENTS,
            help_command=None,
            case_insensitive=True,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )
        self.started_at = time.time()
        self.ai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None
        self.music_queues: dict[int, list[dict]] = {}
        self.ytdl = yt_dlp.YoutubeDL(
            {
                "format": "bestaudio/best",
                "noplaylist": True,
                "quiet": True,
                "default_search": "auto",
                "source_address": "0.0.0.0",
            }
        )

    async def setup_hook(self) -> None:
        synced = await self.tree.sync()
        log.info("synced %d slash commands", len(synced))

    async def on_ready(self) -> None:
        log.info("logged as %s (%s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{PREFIX}مساعدة | {len(self.guilds)} سيرفر",
            )
        )

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"❌ ناقص argument: `{error.param.name}`", mention_author=False)
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ ما عندك صلاحية لهذا الأمر.", mention_author=False)
            return
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.reply("❌ البوت ما عنده صلاحية كافية.", mention_author=False)
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏱️ استنى {error.retry_after:.1f} ثانية.", mention_author=False)
            return
        log.exception("command error", exc_info=error)
        await ctx.reply(f"❌ خطأ: `{type(error).__name__}`", mention_author=False)


bot = ArabicBot()

# ---------------------------------------------------------------------------
# 3. الدوال المساعدة (IP + Warns + AI)
# ---------------------------------------------------------------------------


async def lookup_ip(ip: str) -> dict:
    url = (
        f"http://ip-api.com/json/{ip}?fields=status,message,country,"
        "countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
    )
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
        async with s.get(url) as r:
            data = await r.json()
    if data.get("status") != "success":
        raise ValueError(data.get("message", "فشل الاستعلام"))
    return data


def load_warns() -> dict:
    return json.loads(WARN_FILE.read_text())


def save_warns(data: dict) -> None:
    WARN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


async def ask_ai(prompt: str, system: str = "أنت مساعد ذكي تجيب بالعربية بشكل موجز ومفيد.") -> str:
    if not bot.ai_client:
        raise RuntimeError("OPENAI_API_KEY غير مضبوط")
    r = await bot.ai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=800,
        temperature=0.7,
    )
    return r.choices[0].message.content or "(رد فارغ)"

# ---------------------------------------------------------------------------
# 4. أوامر الإدارة (طرد، حظر، كتم، رتب، مسح)
# ---------------------------------------------------------------------------


@bot.command(name="طرد", aliases=["kick"])
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick_cmd(ctx: commands.Context, member: discord.Member, *, reason: str = "بدون سبب"):
    await member.kick(reason=f"{ctx.author} | {reason}")
    e = discord.Embed(title="👢 تم الطرد", color=COLOR_OK)
    e.add_field(name="العضو", value=f"{member.mention} (`{member.id}`)", inline=False)
    e.add_field(name="السبب", value=reason, inline=False)
    e.add_field(name="المشرف", value=ctx.author.mention, inline=False)
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="حظر", aliases=["ban"])
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban_cmd(ctx: commands.Context, member: discord.Member, *, reason: str = "بدون سبب"):
    await member.ban(reason=f"{ctx.author} | {reason}", delete_message_days=1)
    e = discord.Embed(title="🔨 تم الحظر", color=COLOR_ERR)
    e.add_field(name="العضو", value=f"{member.mention} (`{member.id}`)")
    e.add_field(name="السبب", value=reason)
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="رفع_حظر", aliases=["unban"])
@commands.has_permissions(ban_members=True)
async def unban_cmd(ctx: commands.Context, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
    except discord.NotFound:
        return await ctx.reply("❌ المستخدم ما محظور أو ما موجود.", mention_author=False)
    await ctx.reply(f"✅ تم رفع الحظر عن {user.mention}", mention_author=False)


@bot.command(name="كتم", aliases=["mute", "timeout"])
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def timeout_cmd(ctx: commands.Context, member: discord.Member, minutes: int = 10, *, reason: str = "بدون سبب"):
    until = discord.utils.utcnow() + timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    await ctx.reply(f"🔇 {member.mention} مكتوم {minutes} دقيقة. السبب: {reason}", mention_author=False)


@bot.command(name="فك_كتم", aliases=["unmute"])
@commands.has_permissions(moderate_members=True)
async def untimeout_cmd(ctx: commands.Context, member: discord.Member):
    await member.timeout(None)
    await ctx.reply(f"🔊 تم فك الكتم عن {member.mention}", mention_author=False)


@bot.command(name="مسح", aliases=["clear", "purge"])
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def purge_cmd(ctx: commands.Context, amount: int = 10):
    if amount < 1 or amount > 500:
        return await ctx.reply("❌ العدد لازم بين 1 و 500.", mention_author=False)
    deleted = await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"🧹 تم مسح {len(deleted) - 1} رسالة.")
    await msg.delete(delay=4)


@bot.command(name="اعطاء_رتبة", aliases=["addrole", "role_add"])
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def add_role_cmd(ctx: commands.Context, member: discord.Member, *, role: discord.Role):
    if role >= ctx.guild.me.top_role:
        return await ctx.reply("❌ الرتبة أعلى من رتبة البوت.", mention_author=False)
    if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        return await ctx.reply("❌ الرتبة أعلى من رتبتك.", mention_author=False)
    await member.add_roles(role, reason=f"بواسطة {ctx.author}")
    await ctx.reply(f"✅ تم إعطاء {role.mention} إلى {member.mention}", mention_author=False)


@bot.command(name="سحب_رتبة", aliases=["removerole", "role_remove"])
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def remove_role_cmd(ctx: commands.Context, member: discord.Member, *, role: discord.Role):
    if role >= ctx.guild.me.top_role:
        return await ctx.reply("❌ الرتبة أعلى من رتبة البوت.", mention_author=False)
    await member.remove_roles(role, reason=f"بواسطة {ctx.author}")
    await ctx.reply(f"✅ تم سحب {role.mention} من {member.mention}", mention_author=False)


@bot.command(name="انشاء_رتبة", aliases=["createrole"])
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def create_role_cmd(ctx: commands.Context, *, name: str):
    role = await ctx.guild.create_role(name=name, reason=f"بواسطة {ctx.author}")
    await ctx.reply(f"✅ تم إنشاء الرتبة {role.mention}", mention_author=False)


@bot.command(name="اعلان", aliases=["announce"])
@commands.has_permissions(manage_guild=True)
async def announce_cmd(ctx: commands.Context, channel: discord.TextChannel, *, message: str):
    e = discord.Embed(title="📢 إعلان", description=message, color=COLOR_INFO)
    e.set_footer(text=f"من {ctx.author}")
    await channel.send(embed=e)
    await ctx.reply(f"✅ تم الإرسال إلى {channel.mention}", mention_author=False)

# ---------------------------------------------------------------------------
# 5. أوامر الإشراف والسجلات والترحيب
# ---------------------------------------------------------------------------


@bot.command(name="تحذير", aliases=["warn"])
@commands.has_permissions(manage_messages=True)
async def warn_cmd(ctx: commands.Context, member: discord.Member, *, reason: str = "بدون سبب"):
    data = load_warns()
    gid, uid = str(ctx.guild.id), str(member.id)
    data.setdefault(gid, {}).setdefault(uid, [])
    data[gid][uid].append(
        {"reason": reason, "by": str(ctx.author), "ts": str(discord.utils.utcnow())}
    )
    save_warns(data)

    count = len(data[gid][uid])
    e = discord.Embed(title="⚠️ تحذير", color=COLOR_WARN)
    e.add_field(name="العضو", value=member.mention)
    e.add_field(name="السبب", value=reason)
    e.add_field(name="عدد التحذيرات", value=str(count))
    await ctx.reply(embed=e, mention_author=False)

    if count >= 3:
        try:
            await member.ban(reason="3 تحذيرات تلقائية", delete_message_days=1)
            await ctx.send(f"🔨 {member.mention} انحظر تلقائياً بعد 3 تحذيرات.")
        except discord.Forbidden:
            pass


@bot.command(name="تحذيرات", aliases=["warnings"])
async def warnings_cmd(ctx: commands.Context, member: discord.Member):
    data = load_warns()
    warns = data.get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not warns:
        return await ctx.reply(f"✅ {member.mention} ما عنده تحذيرات.", mention_author=False)
    e = discord.Embed(title=f"تحذيرات {member.display_name}", color=COLOR_WARN)
    for i, w in enumerate(warns, 1):
        e.add_field(name=f"#{i}", value=f"{w['reason']} — {w['by']}", inline=False)
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="مسح_تحذيرات", aliases=["clearwarns"])
@commands.has_permissions(administrator=True)
async def clear_warns_cmd(ctx: commands.Context, member: discord.Member):
    data = load_warns()
    data.get(str(ctx.guild.id), {}).pop(str(member.id), None)
    save_warns(data)
    await ctx.reply(f"✅ تم مسح تحذيرات {member.mention}", mention_author=False)


@bot.event
async def on_message_delete(message: discord.Message) -> None:
    if message.author.bot or not message.guild:
        return
    log_ch = discord.utils.get(message.guild.text_channels, name="سجل-الحذف")
    if not log_ch:
        return
    e = discord.Embed(title="🗑️ رسالة محذوفة", color=COLOR_ERR, timestamp=discord.utils.utcnow())
    e.add_field(name="الكاتب", value=message.author.mention)
    e.add_field(name="القناة", value=message.channel.mention)
    e.add_field(name="المحتوى", value=(message.content or "*مرفق/صورة*")[:1000], inline=False)
    await log_ch.send(embed=e)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    ch = discord.utils.get(member.guild.text_channels, name="الترحيب")
    if ch:
        e = discord.Embed(
            title="🎉 عضو جديد",
            description=f"أهلاً {member.mention} في **{member.guild.name}**",
            color=COLOR_OK,
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"عضو رقم {member.guild.member_count}")
        await ch.send(embed=e)

# ---------------------------------------------------------------------------
# 6. الأدوات والمعلومات وكشف الـ IP
# ---------------------------------------------------------------------------


@bot.command(name="كشف_ip", aliases=["ip", "iplookup"])
@commands.cooldown(2, 10.0, commands.BucketType.user)
async def ip_cmd(ctx: commands.Context, ip: str):
    await ctx.typing()
    try:
        data = await lookup_ip(ip)
    except Exception as e:
        return await ctx.reply(f"❌ فشل: `{e}`", mention_author=False)

    e = discord.Embed(title=f"🌐 معلومات IP: {data['query']}", color=COLOR_INFO)
    e.add_field(name="الدولة", value=f"{data['country']} ({data.get('countryCode', '?')})", inline=True)
    e.add_field(name="المدينة", value=data.get("city") or "-", inline=True)
    e.add_field(name="المنطقة", value=data.get("regionName") or "-", inline=True)
    e.add_field(name="مزود الخدمة", value=data.get("isp") or "-", inline=False)
    e.add_field(name="AS", value=data.get("as") or "-", inline=False)
    e.add_field(name="الإحداثيات", value=f"{data['lat']}, {data['lon']}", inline=True)
    e.add_field(name="التوقيت", value=data.get("timezone") or "-", inline=True)
    e.set_footer(text="المصدر: ip-api.com")
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="معلومات_عضو", aliases=["userinfo", "whois"])
async def user_info_cmd(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    e = discord.Embed(title=f"👤 {member}", color=member.color if member.color.value else COLOR_INFO)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="الاسم", value=str(member), inline=True)
    e.add_field(name="المعرف", value=str(member.id), inline=True)
    e.add_field(name="بوت؟", value="نعم" if member.bot else "لا", inline=True)
    e.add_field(
        name="انضم",
        value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "-",
        inline=True,
    )
    e.add_field(name="أنشأ الحساب", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    e.add_field(name=f"الرتب ({len(roles)})", value=", ".join(roles[:15]) or "لا شيء", inline=False)
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="معلومات_سيرفر", aliases=["serverinfo"])
async def server_info_cmd(ctx: commands.Context):
    g = ctx.guild
    e = discord.Embed(title=f"🏠 {g.name}", color=COLOR_INFO)
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    e.add_field(name="المالك", value=g.owner.mention if g.owner else "-")
    e.add_field(name="الأعضاء", value=str(g.member_count))
    e.add_field(name="القنوات", value=str(len(g.channels)))
    e.add_field(name="الرتب", value=str(len(g.roles)))
    e.add_field(name="أنشئ", value=discord.utils.format_dt(g.created_at, "R"))
    e.add_field(name="Boosts", value=f"{g.premium_subscription_count} (مستوى {g.premium_tier})")
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="بينج", aliases=["ping"])
async def ping_cmd(ctx: commands.Context):
    ws = round(bot.latency * 1000)
    await ctx.reply(f"🏓 البينق: **{ws}ms**", mention_author=False)


@bot.command(name="معلومات_البوت", aliases=["botinfo"])
async def bot_info_cmd(ctx: commands.Context):
    uptime = int(time.time() - bot.started_at)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    mem = psutil.Process().memory_info().rss / 1024 / 1024
    e = discord.Embed(title="🤖 معلومات البوت", color=COLOR_OK)
    e.add_field(name="الاسم", value=str(bot.user))
    e.add_field(name="السيرفرات", value=str(len(bot.guilds)))
    e.add_field(name="الأعضاء", value=str(sum(g.member_count for g in bot.guilds)))
    e.add_field(name="Uptime", value=f"{h}س {m}د {s}ث")
    e.add_field(name="الذاكرة", value=f"{mem:.1f} MB")
    e.add_field(name="Python", value=platform.python_version())
    e.add_field(name="discord.py", value=discord.__version__)
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="avatar", aliases=["صورة"])
async def avatar_cmd(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    e = discord.Embed(title=f"صورة {member.display_name}", color=COLOR_INFO)
    e.set_image(url=member.display_avatar.with_size(1024).url)
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="مساعدة", aliases=["help", "اوامر"])
async def help_cmd(ctx: commands.Context):
    e = discord.Embed(title="📖 قائمة الأوامر", color=COLOR_INFO)
    e.add_field(
        name="🛡️ إدارة",
        value="`طرد` `حظر` `رفع_حظر` `كتم` `فك_كتم` `مسح`\n`اعطاء_رتبة` `سحب_رتبة` `انشاء_رتبة` `اعلان`",
        inline=False,
    )
    e.add_field(name="⚠️ إشراف", value="`تحذير` `تحذيرات` `مسح_تحذيرات`", inline=False)
    e.add_field(
        name="🔧 أدوات",
        value="`كشف_ip` `معلومات_عضو` `معلومات_سيرفر` `معلومات_البوت` `بينج` `avatar`",
        inline=False,
    )
    e.add_field(
        name="🤖 ذكاء اصطناعي",
        value="`ذكاء <سؤال>` `ترجم <نص>` `لخص <نص>` `اقترح <موضوع>`",
        inline=False,
    )
    e.add_field(name="🎵 موسيقى", value="`شغل <رابط>` `وقف` `استمر` `تخطي` `قائمة` `اترك`", inline=False)
    e.add_field(name="🎮 ألعاب", value="`نرد` `عملة` `حظ` `تخمين`", inline=False)
    e.set_footer(text=f"البادئة: {ctx.prefix}")
    await ctx.reply(embed=e, mention_author=False)

# ---------------------------------------------------------------------------
# 7. أوامر الذكاء الاصطناعي (OpenAI)
# ---------------------------------------------------------------------------


@bot.command(name="ذكاء", aliases=["ai", "gpt"])
@commands.cooldown(3, 30.0, commands.BucketType.user)
async def ai_cmd(ctx: commands.Context, *, question: str):
    async with ctx.typing():
        try:
            answer = await ask_ai(question)
        except Exception as e:
            return await ctx.reply(f"❌ فشل: `{e}`", mention_author=False)
    e = discord.Embed(title="🤖 رد الذكاء الاصطناعي", description=answer[:4000], color=COLOR_INFO)
    e.set_footer(text=f"سأل: {ctx.author.display_name}")
    await ctx.reply(embed=e, mention_author=False)


@bot.command(name="ترجم", aliases=["translate"])
@commands.cooldown(3, 30.0, commands.BucketType.user)
async def translate_cmd(ctx: commands.Context, *, text: str):
    async with ctx.typing():
        try:
            out = await ask_ai(
                f"ترجم النص التالي إلى الإنجليزية إن كان عربياً، وإلى العربية إن كان إنجليزياً. "
                f"أعد الترجمة فقط بدون شرح:\n\n{text}",
                system="أنت مترجم محترف. أعد الترجمة فقط.",
            )
        except Exception as e:
            return await ctx.reply(f"❌ فشل: `{e}`", mention_author=False)
    await ctx.reply(out[:2000], mention_author=False)


@bot.command(name="لخص", aliases=["summarize"])
@commands.cooldown(3, 30.0, commands.BucketType.user)
async def summarize_cmd(ctx: commands.Context, *, text: str):
    async with ctx.typing():
        try:
            out = await ask_ai(
                f"لخص النص التالي في نقاط مختصرة بالعربية:\n\n{text}",
                system="أنت مساعد يلخص بوضوح.",
            )
        except Exception as e:
            return await ctx.reply(f"❌ فشل: `{e}`", mention_author=False)
    await ctx.reply(out[:2000], mention_author=False)


@bot.command(name="اقترح", aliases=["suggest"])
@commands.cooldown(3, 30.0, commands.BucketType.user)
async def suggest_cmd(ctx: commands.Context, *, topic: str):
    async with ctx.typing():
        try:
            out = await ask_ai(
                f"اقترح 5 أفكار إبداعية عن: {topic}. نقاط مختصرة بالعربية.",
                system="أنت مساعد إبداعي.",
            )
        except Exception as e:
            return await ctx.reply(f"❌ فشل: `{e}`", mention_author=False)
    await ctx.reply(out[:2000], mention_author=False)

# ---------------------------------------------------------------------------
# 8. أوامر الموسيقى والرومات الصوتية
# ---------------------------------------------------------------------------

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


def _extract_track(query: str) -> dict:
    info = bot.ytdl.extract_info(query, download=False)
    if "entries" in info:
        info = info["entries"][0]
    return {
        "url": info["url"],
        "title": info.get("title", "?"),
        "web": info.get("webpage_url", ""),
    }


async def _ensure_voice(ctx: commands.Context) -> discord.VoiceClient:
    if not ctx.author.voice:
        raise commands.CommandError("لازم تكون في روم صوتي.")
    ch = ctx.author.voice.channel
    vc = ctx.voice_client
    if vc and vc.channel != ch:
        await vc.move_to(ch)
    elif not vc:
        vc = await ch.connect()
    return vc


def _play_next(ctx: commands.Context) -> None:
    q = bot.music_queues.get(ctx.guild.id, [])
    if not q:
        return
    track = q.pop(0)
    src = discord.FFmpegPCMAudio(track["url"], **FFMPEG_OPTS)
    vc = ctx.voice_client
    vc.play(src, after=lambda _e: bot.loop.call_soon_threadsafe(_play_next, ctx))

    async def announce():
        await ctx.send(f"🎶 يشتغل الآن: **{track['title']}**")

    asyncio.run_coroutine_threadsafe(announce(), bot.loop)


@bot.command(name="شغل", aliases=["play", "p"])
async def play_cmd(ctx: commands.Context, *, query: str):
    vc = await _ensure_voice(ctx)
    async with ctx.typing():
        try:
            track = await asyncio.to_thread(_extract_track, query)
        except Exception as e:
            return await ctx.reply(f"❌ فشل الجلب: `{e}`", mention_author=False)
    bot.music_queues.setdefault(ctx.guild.id, []).append(track)
    if not vc.is_playing():
        _play_next(ctx)
    else:
        await ctx.reply(f"➕ أضيف للقائمة: **{track['title']}**", mention_author=False)


@bot.command(name="وقف", aliases=["pause"])
async def pause_cmd(ctx: commands.Context):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.reply("⏸️ تم الإيقاف المؤقت.", mention_author=False)


@bot.command(name="استمر", aliases=["resume"])
async def resume_cmd(ctx: commands.Context):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.reply("▶️ تم الاستمرار.", mention_author=False)


@bot.command(name="تخطي", aliases=["skip"])
async def skip_cmd(ctx: commands.Context):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.reply("⏭️ تم التخطي.", mention_author=False)


@bot.command(name="اترك", aliases=["leave", "disconnect"])
async def leave_cmd(ctx: commands.Context):
    if ctx.voice_client:
        bot.music_queues.pop(ctx.guild.id, None)
        await ctx.voice_client.disconnect()
        await ctx.reply("👋 طلعت من الروم.", mention_author=False)


@bot.command(name="قائمة", aliases=["queue"])
async def queue_cmd(ctx: commands.Context):
    q = bot.music_queues.get(ctx.guild.id, [])
    if not q:
        return await ctx.reply("📭 القائمة فاضية.", mention_author=False)
    txt = "\n".join(f"{i + 1}. {t['title']}" for i, t in enumerate(q[:20]))
    await ctx.reply(f"🎵 القائمة:\n{txt}", mention_author=False)

# ---------------------------------------------------------------------------
# 9. الألعاب والتسلية
# ---------------------------------------------------------------------------


@bot.command(name="نرد", aliases=["dice", "roll"])
async def dice_cmd(ctx: commands.Context, sides: int = 6):
    if sides < 2 or sides > 1000:
        return await ctx.reply("❌ العدد لازم بين 2 و 1000.", mention_author=False)
    await ctx.reply(f"🎲 طلع: **{random.randint(1, sides)}**", mention_author=False)


@bot.command(name="عملة", aliases=["coin", "flip"])
async def coin_cmd(ctx: commands.Context):
    await ctx.reply(f"🪙 {random.choice(['صورة', 'كتابة'])}", mention_author=False)


@bot.command(name="حظ", aliases=["8ball"])
async def luck_cmd(ctx: commands.Context, *, question: str):
    answers = [
        "أكيد.", "ممكن.", "ما أتوقع.", "لا.", "نعم بلا شك.",
        "اسأل مرة ثانية.", "غامض، جرب لاحقاً.", "الأفضل ما تسأل.",
    ]
    await ctx.reply(f"🎱 {random.choice(answers)}", mention_author=False)


@bot.command(name="تخمين", aliases=["guess"])
async def guess_cmd(ctx: commands.Context):
    n = random.randint(1, 100)
    await ctx.reply("🎯 خمنت رقم من 1 إلى 100. اكتب تخمينك (عندك 5 محاولات).", mention_author=False)
    for _ in range(5):
        try:
            msg = await bot.wait_for(
                "message",
                check=lambda m: (
                    m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            return await ctx.reply(f"⌛ انتهى الوقت. الرقم كان {n}.", mention_author=False)
        g = int(msg.content)
        if g == n:
            return await ctx.reply(f"✅ صح! الرقم كان {n}.", mention_author=False)
        await ctx.reply("⬆️ أعلى" if g < n else "⬇️ أقل", mention_author=False)
    await ctx.reply(f"❌ خلصت المحاولات. الرقم كان {n}.", mention_author=False)

# ---------------------------------------------------------------------------
# 10. أوامر السلاش (Slash Commands)
# ---------------------------------------------------------------------------


@bot.tree.command(name="طرد", description="طرد عضو من السيرفر")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 تم طرد {member.mention}")


@bot.tree.command(name="حظر", description="حظر عضو من السيرفر")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 تم حظر {member.mention}")


@bot.tree.command(name="اعطاء_رتبة", description="أعطي رتبة لعضو")
@app_commands.default_permissions(manage_roles=True)
async def slash_addrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("❌ الرتبة أعلى من رتبة البوت.", ephemeral=True)
    await member.add_roles(role)
    await interaction.response.send_message(f"✅ تم إعطاء {role.mention} لـ {member.mention}")


@bot.tree.command(name="سحب_رتبة", description="اسحب رتبة من عضو")
@app_commands.default_permissions(manage_roles=True)
async def slash_removerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await interaction.response.send_message(f"✅ تم سحب {role.mention} من {member.mention}")


@bot.tree.command(name="كشف_ip", description="كشف معلومات عنوان IP")
async def slash_ip(interaction: discord.Interaction, ip: str):
    await interaction.response.defer()
    try:
        data = await lookup_ip(ip)
    except Exception as e:
        return await interaction.followup.send(f"❌ فشل: `{e}`")
    e = discord.Embed(title=f"🌐 {data['query']}", color=COLOR_INFO)
    e.add_field(name="الدولة", value=f"{data['country']} ({data.get('countryCode', '?')})")
    e.add_field(name="المدينة", value=data.get("city") or "-")
    e.add_field(name="ISP", value=data.get("isp") or "-")
    e.add_field(name="AS", value=data.get("as") or "-")
    e.add_field(name="الموقع", value=f"{data['lat']}, {data['lon']}")
    await interaction.followup.send(embed=e)


@bot.tree.command(name="ذكاء", description="اسأل الذكاء الاصطناعي")
async def slash_ai(interaction: discord.Interaction, سؤال: str):
    await interaction.response.defer()
    try:
        answer = await ask_ai(سؤال)
    except Exception as e:
        return await interaction.followup.send(f"❌ فشل: `{e}`")
    await interaction.followup.send(answer[:2000])

# ---------------------------------------------------------------------------
# 11. تشغيل البوت
# ---------------------------------------------------------------------------


async def main() -> None:
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("stopped")
