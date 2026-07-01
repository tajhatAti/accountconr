import os
import asyncio
import threading
import time
import re
import base64
import urllib.parse
import random
from http.server import HTTPServer, BaseHTTPRequestHandler

# Telethon & Third-party Imports
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from deep_translator import GoogleTranslator

# --- এনভায়রনমেন্ট কনফিগারেশন ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RAW_SESSIONS = os.environ.get("STRING_SESSIONS", "")

USER_STATES = {} 
bot_client = None  # ফিক্স: গ্লোবালি ইনিশিয়ালাইজ করা যাবে না, লুপের জন্য None রাখা হলো
start_time = time.time()
login_temp = {"phone": None, "client": None}

# --- ওয়েব সার্ভার (রেন্ডার/হিরোকু আপটাইম এর জন্য) ---
class RenderServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"HyperEngine Bot Online - Running Multi-Sessions")
    def log_message(self, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), RenderServer).serve_forever()

# --- টেক্সট স্টাইলিং ও ম্যাপ ডিকশনারি ---
MORSE_CODE = {'A':'.-', 'B':'-...', 'C':'-.-.', 'D':'-..', 'E':'.', 'F':'..-.', 'G':'--.', 'H':'....', 'I':'..', 'J':'.---', 'K':'-.-', 'L':'.-..', 'M':'--', 'N':'-.', 'O':'---', 'P':'.--.', 'Q':'--.-', 'R':'.-.', 'S':'...', 'T':'-', 'U':'..-', 'V':'...-', 'W':'.--', 'X':'-..-', 'Y':'-.--', 'Z':'--..'}

# ==========================================
#  🤖 কন্ট্রোলার বটের প্যানেল ফিচারস (মাস্টার কমান্ড)
# ==========================================

def setup_bot_handlers(client):
    @client.on(events.NewMessage(pattern='/start'))
    async def b_start(event):
        if event.sender_id != OWNER_ID: return
        await event.reply("⚙️ **মেগা ডুয়াল ইউজারবট প্যানেল সচল!**\n\n💬 নতুন আইডি যোগ করতে সরাসরি আন্তর্জাতিক নাম্বারে মেসেজ দে (যেমন: `+88017...`)\n💬 বটের সব কমান্ড দেখতে কমান্ড কর: `/bothelp`")

    @client.on(events.NewMessage(pattern='/bothelp'))
    async def b_help(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(
            "🤖 **বট কন্ট্রোল কমান্ডস:**\n"
            "1. `/start` - প্যানেল বুট\n2. `/bothelp` - এই মেনু\n3. `/list` - সব আইডির লাইভ স্ট্যাটাস\n"
            "4. `/reset` - লগইন স্টেট ক্লিয়ার\n5. `/broadcast [লেখা]` - সব আইডি থেকে একসাথে মেসেজ\n"
            "6. `/afk_all [কারণ]` - এক ক্লিকে সব আইডি AFK করা\n7. `/unafk_all` - সব আইডি একসাথে অনলাইন করা\n"
            "8. `/bio_all [লেখা]` - সব আইডির বায়ো একসাথে চেঞ্জ\n9. `/name_all [নাম]` - সব আইডির ফার্স্ট নেম চেঞ্জ\n"
            "10. `/ping_all` - সব আইডির স্পিড চেক\n11. `/stats` - সার্ভার ও মেমোরি কন্ডিশন\n"
            "12. `/clean_cache` - ইন্টারনাল ডাটা ফ্লাশ\n13. `/session_count` - মোট সেশন সংখ্যা\n"
            "14. `/backup_sessions` - সব সেশনের টেক্সট ফাইল ব্যাকআপ\n15. `/terminate_all` - সব আইডি ডিসকানেক্ট করা\n"
            "16. `/uptime` - বটের আপটাইম\n17. `/myid` - তোর টেলিগ্রাম আইডি"
        )

    @client.on(events.NewMessage(pattern='/list'))
    async def b_list(event):
        if event.sender_id != OWNER_ID: return
        if not USER_STATES: return await event.reply("❌ কোনো একাউন্ট কানেক্টেড নেই।")
        msg = "📋 **সংযুক্ত অ্যাকাউন্টসমূহ:**\n\n"
        for idx, (uid, data) in enumerate(USER_STATES.items(), 1):
            st = "💤 AFK" if data["is_afk"] else "🟢 অনলাইন"
            msg += f"{idx}. 👤 **{data['name']}** (`{uid}`) - স্ট্যাটাস: {st}\n"
        await event.reply(msg)

    @client.on(events.NewMessage(pattern='/reset'))
    async def b_reset(event):
        if event.sender_id != OWNER_ID: return
        login_temp["phone"] = None
        if login_temp["client"]: await login_temp["client"].disconnect()
        await event.reply("🔄 লগইন মেমোরি রিসেট সফল।")

    @client.on(events.NewMessage(pattern=r'/broadcast (.*)'))
    async def b_spammer(event):
        if event.sender_id != OWNER_ID: return
        txt = event.pattern_match.group(1)
        for uid, data in USER_STATES.items():
            try: await data["client"].send_message("me", f"📢 **[Bot Broadcast]:** {txt}")
            except: pass
        await event.reply("✅ সব আইডির Saved Messages-এ ব্রডকাস্ট পাঠানো হয়েছে।")

    @client.on(events.NewMessage(pattern=r'/afk_all (.*)'))
    async def b_afk_all(event):
        if event.sender_id != OWNER_ID: return
        r = event.pattern_match.group(1)
        for uid in USER_STATES:
            USER_STATES[uid]["is_afk"] = True
            USER_STATES[uid]["reason"] = r
        await event.reply(f"🔒 সব আইডিকে AFK করা হয়েছে। কারণ: {r}")

    @client.on(events.NewMessage(pattern='/unafk_all'))
    async def b_unafk_all(event):
        if event.sender_id != OWNER_ID: return
        for uid in USER_STATES: USER_STATES[uid]["is_afk"] = False
        await event.reply("🔓 সব আইডির AFK মোড অফ করা হয়েছে।")

    @client.on(events.NewMessage(pattern=r'/bio_all (.*)'))
    async def b_bio_all(event):
        if event.sender_id != OWNER_ID: return
        bi = event.pattern_match.group(1)
        for uid, data in USER_STATES.items():
            try: await data["client"](UpdateProfileRequest(about=bi))
            except: pass
        await event.reply("📝 সব আইডির বায়ো সাকসেসফুলি চেঞ্জ করা হয়েছে।")

    @client.on(events.NewMessage(pattern=r'/name_all (.*)'))
    async def b_name_all(event):
        if event.sender_id != OWNER_ID: return
        n = event.pattern_match.group(1)
        for uid, data in USER_STATES.items():
            try: await data["client"](UpdateProfileRequest(first_name=n))
            except: pass
        await event.reply(f"✅ সবার নাম পরিবর্তন করে '{n}' রাখা হয়েছে।")

    @client.on(events.NewMessage(pattern='/session_count'))
    async def b_sess_count(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(f"📊 **মোট অ্যাকটিভ সেশন:** `{len(USER_STATES)}` টি")

    @client.on(events.NewMessage(pattern='/backup_sessions'))
    async def b_backup(event):
        if event.sender_id != OWNER_ID: return
        if not USER_STATES: return await event.reply("❌ কোনো সেশন অ্যাকটিভ নেই।")
        
        backup_text = ""
        for uid, data in USER_STATES.items():
            backup_text += f"{data['client'].session.save()}\n"
        
        filename = f"TOTAL_{len(USER_STATES)}_SESSIONS_BACKUP.txt"
        with open(filename, "w") as f:
            f.write(backup_text)
        
        await event.reply("✅ সেশন ব্যাকআপ জেনারেট হয়েছে! ফাইলটি ডাউনলোড করে সুরক্ষিত রাখো।", file=filename)
        os.remove(filename)

    @client.on(events.NewMessage(pattern='/ping_all'))
    async def b_ping_all(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(f"⚡ **সিস্টেম রানিং!**\nবর্তমানে {len(USER_STATES)} টি অ্যাকাউন্ট কানেক্টেড আছে।")

    @client.on(events.NewMessage(pattern='/uptime'))
    async def b_uptime(event):
        if event.sender_id != OWNER_ID: return
        up = int(time.time() - start_time)
        m, s = divmod(up, 60)
        h, m = divmod(m, 60)
        await event.reply(f"⏱️ **বট আপটাইম:** `{h}h {m}m {s}s`")

    @client.on(events.NewMessage(pattern='/myid'))
    async def b_myid(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(f"👤 **তোর ওনার আইডি:** `{event.sender_id}`")

    @client.on(events.NewMessage(pattern='/clean_cache'))
    async def b_clean_cache(event):
        if event.sender_id != OWNER_ID: return
        await event.reply("🧹 **ইন্টারনাল ক্যাশ ক্লিয়ার করা হয়েছে।**")

    @client.on(events.NewMessage(pattern='/terminate_all'))
    async def b_terminate(event):
        if event.sender_id != OWNER_ID: return
        count = len(USER_STATES)
        for uid, data in USER_STATES.items():
            try: await data["client"].disconnect()
            except: pass
        USER_STATES.clear()
        await event.reply(f"⚠️ **সতর্কতা:** {count} টি সেশন ফোরসফুলি ডিসকানেক্ট করা হয়েছে!")

    # 🔒 ওটিপি এবং পাসওয়ার্ড সহ সেশন জেনারেশন হ্যান্ডলার
    @client.on(events.NewMessage)
    async def b_login_engine(event):
        if event.sender_id != OWNER_ID or event.text.startswith('/'): return
        text = event.text.strip()

        if text.startswith('+') and login_temp["phone"] is None:
            login_temp["phone"] = text
            await event.reply("⏳ ওটিপি কোড রিকোয়েস্ট পাঠানো হচ্ছে...")
            try:
                login_temp["client"] = TelegramClient(StringSession(), API_ID, API_HASH)
                await login_temp["client"].connect()
                await login_temp["client"].send_code_request(login_temp["phone"])
                await event.reply("📩 কোড গেছে। এভাবে রিপ্লাই দে: `code 12345`")
            except Exception as e:
                login_temp["phone"] = None
                await event.reply(f"❌ এরর: {e}")

        elif text.startswith('code ') and login_temp["phone"] is not None:
            c = text.split(' ')[1]
            try:
                await login_temp["client"].sign_in(login_temp["phone"], c)
                await finalize_login(event)
            except SessionPasswordNeededError:
                await event.reply("🔐 2FA অন আছে। পাসওয়ার্ড এভাবে পাঠা: `pass তোর_পাসওয়ার্ড`")
            except Exception as e:
                login_temp["phone"] = None
                await event.reply(f"❌ লগইন ফেইলড: {e}")

        elif text.startswith('pass ') and login_temp["phone"] is not None:
            p = text.replace('pass ', '').strip()
            try:
                await login_temp["client"].sign_in(password=p)
                await finalize_login(event)
            except Exception as e:
                await event.reply(f"❌ পাসওয়ার্ড ভুল: {e}")

async def finalize_login(event):
    me = await login_temp["client"].get_me()
    ss = login_temp["client"].session.save()
    register_userbot_handlers(login_temp["client"], me)
    
    existing = RAW_SESSIONS + "," if RAW_SESSIONS else ""
    combined_string = f"{existing}{ss}"
    
    await event.reply(
        f"🎉 **{me.first_name}** অনলাইন হয়েছে!\n\n"
        f"⚠️ **রেন্ডার আপডেটেড এনভায়রনমেন্ট ভেরিয়েবল:**\n"
        f"রেন্ডার ড্যাশবোর্ডে গিয়ে `STRING_SESSIONS` এর মান মুছে সম্পূর্ণ নিচের টেক্সটটি পেস্ট করে দে (তাহলে আর রিস্টার্টে আইডি হারাবে না):\n\n"
        f"`{combined_string}`"
    )
    login_temp["phone"] = None

# ==========================================
#  👤 ইউজারবট ইঞ্জিন (পার্সোনাল অ্যাকাউন্টের জন্য)
# ==========================================

def register_userbot_handlers(client, me):
    uid = me.id
    USER_STATES[uid] = {"is_afk": False, "reason": "", "client": client, "name": me.first_name}

    # --- কোর ফিচারসমূহ ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.help'))
    async def u_help(event):
        await event.edit(
            f"👑 **[ {me.first_name} ] ইউজারবট প্যানেল:**\n\n"
            "🔹 **কোর:** `.alive` | `.ping` | `.id` | `.myinfo` | `.userinfo` (Reply)\n"
            "🔹 **প্রোফাইল:** `.bio [txt]` | `.name [txt]` | `.lastname [txt]` | `.username [txt]` | `.delpfp`\n"
            "🔹 **অটোমেশন:** `.afk [কারণ]` | `.purge` (Reply) | `.tagall` (Group)\n"
            "🔹 **চ্যাট:** `.del` | `.pin` | `.unpin` | `.read` | `.echo [txt]` | `.frwd [@user]`\n"
            "🔹 **অ্যানিমেশন:** `.type [txt]` | `.loading` | `.clock` | `.heart`\n"
            "🔹 **ইউটিলিটি:** `.calc [অংক]` | `.save` (Reply) | `.tr [bn/en]` | `.count`\n"
            "🔹 **ফান:** `.dice` | `.coin` | `.8ball` | `.stinfo` (স্টিকার/ফাইল ইনফো)\n"
            "🔹 **মডারেশন:** `.kick` | `.ban` | `.mute` | `.unban` | `.unmute` (Reply)\n"
            "🔹 **স্টাইল:** `.bold` | `.italic` | `.mono` | `.strike` | `.underline` | `.rev` | `.upper` | `.lower` | `.mock` | `.binary` | `.hex` | `.base64` | `.morse` | `.vapor` (Reply)"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.alive'))
    async def u_alive(event):
        await event.edit(f"⚡ **[ {me.first_name} ] হাইব্রিড সেশন অনলাইন!**\n⏱️ আপটাইম: `{int(time.time() - start_time)}s`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.ping'))
    async def u_ping(event):
        t = time.time()
        await event.edit("`🏓 Pinging...`")
        await event.edit(f"🎯 **Pong!**\n⏱️ `{(time.time() - t)*1000:.2f}ms`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.id'))
    async def u_id(event):
        await event.edit(f"👤 **ইউজার আইডি:** `{uid}`\n📍 **চ্যাট আইডি:** `{event.chat_id}`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.afk(?: |$)(.*)'))
    async def u_afk(event):
        reason = event.pattern_match.group(1) or "ব্যস্ত আছি, পরে নক দাও।"
        USER_STATES[uid]["is_afk"] = True
        USER_STATES[uid]["reason"] = reason
        await event.edit(f"💤 **AFK মোড সক্রিয় করা হলো!**\n📝 কারণ: {reason}")

    # --- প্রোফাইল ও ইনফো ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.bio (.*)'))
    async def u_bio(event):
        try:
            await client(UpdateProfileRequest(about=event.pattern_match.group(1)))
            await event.edit("✅ বায়ো পরিবর্তন সফল।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.name (.*)'))
    async def u_name(event):
        try:
            await client(UpdateProfileRequest(first_name=event.pattern_match.group(1)))
            await event.edit("✅ ফার্স্ট নেম আপডেট সফল।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.lastname (.*)'))
    async def u_lastname(event):
        try:
            await client(UpdateProfileRequest(last_name=event.pattern_match.group(1)))
            await event.edit("✅ লাস্ট নেম আপডেট সফল।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.username (.*)'))
    async def u_username(event):
        try:
            await client(UpdateUsernameRequest(event.pattern_match.group(1)))
            await event.edit("✅ ইউজারনেম আপডেট সফল।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.delpfp'))
    async def u_delpfp(event):
        try:
            p = await client.get_profile_photos("me")
            if p: await client.delete_profile_photos(p[0])
            await event.edit("🗑️ প্রোফাইল পিকচার ডিলিট করা হয়েছে।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.myinfo'))
    async def u_myinfo(event):
        await event.edit(f"👤 **আমার ইনফো:**\nনাম: {me.first_name}\nআইডি: `{uid}`\nইউজারনেম: @{me.username}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.userinfo'))
    async def u_userinfo(event):
        if not event.is_reply: return await event.edit("❌ রিপ্লাই করো।")
        r = await event.get_reply_message()
        u = await client.get_entity(r.sender_id)
        await event.edit(f"👤 **ইউজার ইনফো:**\nনাম: {u.first_name}\nআইডি: `{u.id}`")

    # --- চ্যাট অ্যাকশন ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.del$'))
    async def u_del(event):
        if event.is_reply:
            r = await event.get_reply_message()
            await r.delete()
            await event.delete()

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.pin$'))
    async def u_pin(event):
        if event.is_reply:
            r = await event.get_reply_message()
            await client.pin_message(event.chat_id, r.id)
            await event.edit("📌 মেসেজ পিন করা হয়েছে।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.unpin$'))
    async def u_unpin(event):
        if event.is_reply:
            r = await event.get_reply_message()
            await client.unpin_message(event.chat_id, r.id)
            await event.edit("📌 মেসেজ আনপিন করা হয়েছে।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.read$'))
    async def u_read(event):
        await client.send_read_acknowledge(event.chat_id)
        await event.edit("👁️ মেসেজ রিড মার্ক করা হয়েছে।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.echo (.*)'))
    async def u_echo(event):
        txt = event.pattern_match.group(1)
        await event.delete()
        await client.send_message(event.chat_id, txt)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.frwd (.*)'))
    async def u_frwd(event):
        if not event.is_reply: return await event.edit("❌ রিপ্লাই করো।")
        r = await event.get_reply_message()
        target = event.pattern_match.group(1)
        try:
            await client.forward_messages(target, r)
            await event.edit(f"✅ মেসেজ {target} এ ফরোয়ার্ড করা হয়েছে।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    # --- অ্যানিমেশন ও ইউটিলিটি ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.type (.*)'))
    async def u_type(event):
        t = event.pattern_match.group(1)
        s = ""
        for char in t:
            s += char
            await event.edit(s + "▒")
            await asyncio.sleep(0.1)
        await event.edit(s)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.loading'))
    async def u_loading(event):
        for pct in [10, 30, 55, 85, 100]:
            await event.edit(f"⏳ **Loading:** `[{'■'*(pct//10)}{' '*(10-(pct//10))}] {pct}%`")
            await asyncio.sleep(0.2)
        await event.edit("✅ **ডাউনলোড সম্পন্ন!**")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.clock'))
    async def u_clock(event):
        for emoji in ["🕐", "🕒", "🕔", "🕖", "🕘", "🕚", "🕛"]:
            await event.edit(emoji)
            await asyncio.sleep(0.2)
        await event.edit("⌛ সময় শেষ!")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.heart'))
    async def u_heart(event):
        for h in ["❤️", "💖", "💝", "💞", "❤️"]:
            await event.edit(h)
            await asyncio.sleep(0.2)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.calc (.*)'))
    async def u_calc(event):
        try: result = eval(event.pattern_match.group(1))
        except: result = "ভুল ইকুয়েশন!"
        await event.edit(f"📊 **হিসাব:**\n`{event.pattern_match.group(1)} = {result}`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.save'))
    async def u_save(event):
        if not event.is_reply: return await event.edit("❌ মেসেজে রিপ্লাই কর।")
        await client.send_message("me", await event.get_reply_message())
        await event.edit("💾 Saved Messages-এ সুরক্ষিত রাখা হলো।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.purge'))
    async def u_purge(event):
        if not event.is_reply: return await event.edit("❌ মেসেজে রিপ্লাই কর।")
        rep = await event.get_reply_message()
        d_list = []
        async for m in client.iter_messages(event.chat_id, min_id=rep.id - 1):
            if m.out: d_list.append(m.id)
        if d_list: await client.delete_messages(event.chat_id, d_list)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.tagall'))
    async def u_tag(event):
        if event.is_private: return await event.edit("❌ শুধু গ্রুপে কাজ করবে।")
        await event.delete()
        t, c = "", 0
        async for u in client.iter_participants(event.chat_id):
            if u.bot: continue
            t += f"[{u.first_name}](tg://user?id={u.id}) "
            c += 1
            if c == 5:
                await client.send_message(event.chat_id, t)
                t, c = "", 0
                await asyncio.sleep(0.5)
        if t: await client.send_message(event.chat_id, t)

    # --- ফান, গেমস ও ট্রানস্লেশন ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.tr (.*)'))
    async def u_tr(event):
        if not event.is_reply: return await event.edit("❌ রিপ্লাই করো।")
        lang = event.pattern_match.group(1)
        r = await event.get_reply_message()
        txt = r.text
        if not txt: return await event.edit("❌ কোনো টেক্সট পাওয়া যায়নি।")
        try:
            tr_txt = GoogleTranslator(source='auto', target=lang).translate(txt)
            await event.edit(f"🌍 **Translation ({lang}):**\n`{tr_txt}`")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.(dice|coin|8ball)'))
    async def u_games(event):
        cmd = event.pattern_match.group(1)
        await event.delete()
        if cmd == "dice": await client.send_message(event.chat_id, file="🎲")
        elif cmd == "coin": 
            res = random.choice(["Head", "Tail"])
            await client.send_message(event.chat_id, f"🪙 টস রেজাল্ট: **{res}**")
        elif cmd == "8ball": await client.send_message(event.chat_id, file="🎱")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.count'))
    async def u_count(event):
        m = await client.get_messages(event.chat_id, limit=0)
        await event.edit(f"📊 এই চ্যাটে মোট মেসেজ: `{m.total}`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.stinfo'))
    async def u_stinfo(event):
        if not event.is_reply: return await event.edit("❌ স্টিকারে রিপ্লাই করো।")
        r = await event.get_reply_message()
        if r.sticker or r.document:
            await event.edit(f"🎨 **Sticker/Document ID:** `{r.document.id}`\n**Access Hash:** `{r.document.access_hash}`")
        else: await event.edit("❌ এটি স্টিকার নয়।")

    # --- টেক্সট স্টাইলিং ও ম্যাপ ডিকশনারি ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.(bold|italic|mono|strike|underline|rev|upper|lower|mock|binary|hex|base64|morse|vapor)'))
    async def u_text_engine(event):
        if not event.is_reply: return await event.edit("❌ টেক্সট মেসেজে রিপ্লাই করে কমান্ডটি দে।")
        cmd = event.pattern_match.group(1)
        r_msg = await event.get_reply_message()
        orig = r_msg.text or ""
        if not orig: return await event.edit("❌ কোনো টেক্সট পাওয়া যায়নি।")

        if cmd == "bold": out = f"**{orig}**"
        elif cmd == "italic": out = f"__{orig}__"
        elif cmd == "mono": out = f"`{orig}`"
        elif cmd == "strike": out = f"~~{orig}~~"
        elif cmd == "underline": out = f"<u>{orig}</u>"
        elif cmd == "rev": out = orig[::-1]
        elif cmd == "upper": out = orig.upper()
        elif cmd == "lower": out = orig.lower()
        elif cmd == "mock": out = "".join([c.upper() if idx%2==0 else c.lower() for idx, c in enumerate(orig)])
        elif cmd == "binary": out = " ".join(format(ord(x), 'b') for x in orig)
        elif cmd == "hex": out = orig.encode('utf-8').hex()
        elif cmd == "base64": out = base64.b64encode(orig.encode('utf-8')).decode('utf-8')
        elif cmd == "morse": out = " ".join(MORSE_CODE.get(c.upper(), c) for c in orig)
        elif cmd == "vapor": out = " ".join([c for c in orig])
        else: out = orig
        
        await event.edit(out)

    # --- চ্যাট মডারেশন ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.(kick|ban|mute|unban|unmute)'))
    async def u_mod_engine(event):
        if event.is_private: return await event.edit("❌ গ্রুপ এডমিন টুল এটি।")
        cmd = event.pattern_match.group(1)
        if not event.is_reply: return await event.edit("❌ ইউজারের মেসেজে রিপ্লাই কর।")
        rep = await event.get_reply_message()
        t_user = rep.sender_id
        
        try:
            if cmd == "kick": await client.kick_participant(event.chat_id, t_user); await event.edit("👞 মেম্বারকে কিক করা হয়েছে।")
            elif cmd == "ban": await client.edit_permissions(event.chat_id, t_user, view_messages=False); await event.edit("🚫 মেম্বার ব্যানড!")
            elif cmd == "mute": await client.edit_permissions(event.chat_id, t_user, send_messages=False); await event.edit("🔇 মেম্বারকে মিউট করা হলো।")
            elif cmd == "unban" or cmd == "unmute": await client.edit_permissions(event.chat_id, t_user, view_messages=True, send_messages=True); await event.edit("🔊 সব নিষেধাজ্ঞা তুলে নেওয়া হলো।")
        except Exception as e: await event.edit(f"❌ রাইটস নেই বা এরর: {e}")

    # ==========================================
    #  🔒 ইনকামিং ও আউটগোয়িং AFK (অটো-রিপ্লাই)
    # ==========================================
    
    @client.on(events.NewMessage(incoming=True))
    async def incoming_reply_manager(event):
        state = USER_STATES.get(uid)
        if state and state["is_afk"]:
            if event.is_private:
                if event.sender_id == uid: return
                sender_obj = await event.get_sender()
                if sender_obj and getattr(sender_obj, 'bot', False): return
                
                await event.reply(f"🤖 **[অটো-রিপ্লাই]**\nআমি এখন লাইনে নেই।\n📝 **কারণ:** {state['reason']}")
            elif event.mentioned:
                await event.reply(f"🤖 **[অটো-রিপ্লাই]** {state['reason']}")

    @client.on(events.NewMessage(outgoing=True))
    async def outgoing_afk_remover(event):
        state = USER_STATES.get(uid)
        if state and state["is_afk"]:
            if event.text.startswith('.afk') or event.text.startswith('.help'):
                return
            state["is_afk"] = False
            m = await event.respond("⚡ **আমি লাইনে ফিরে এসেছি! AFK মোড অফ করা হলো।**")
            await asyncio.sleep(2)
            await m.delete()

# ==========================================
#  🔄 রানিং বুটস্ট্র্যাপ
# ==========================================
async def main():
    global bot_client
    bot_client = TelegramClient('helper_bot_v2', API_ID, API_HASH)
    
    # হ্যান্ডলারগুলো রেজিস্টার করা হচ্ছে
    setup_bot_handlers(bot_client)

    threading.Thread(target=run_web_server, daemon=True).start()
    print("[+] Starting Controller Bot...")
    await bot_client.start(bot_token=BOT_TOKEN)
    
    if RAW_SESSIONS:
        sessions = [s.strip() for s in RAW_SESSIONS.split(",") if s.strip()]
        for session_str in sessions:
            try:
                cl = TelegramClient(StringSession(session_str), API_ID, API_HASH)
                await cl.connect()
                if await cl.is_user_authorized():
                    me = await cl.get_me()
                    register_userbot_handlers(cl, me)
                    print(f"[+] Multi-Session Connected: {me.first_name}")
            except Exception as e: print(f"[-] Session Error: {e}")

    await bot_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
