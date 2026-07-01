import os
import asyncio
import threading
import time
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest

# --- কোর কনফিগারেশন (Render Env Variables থেকে আসবে) ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RAW_SESSIONS = os.environ.get("STRING_SESSIONS", "")  # কমা দিয়ে আলাদা করা সেশনসমূহ

# মাল্টিপল ক্লায়েন্ট ও স্টেট ট্র্যাকিং ডিকশনারি
USER_STATES = {}  # {user_id: {"is_afk": False, "reason": "", "client": client_instance, "name": ""}}
bot_client = TelegramClient('helper_bot_auth', API_ID, API_HASH)
start_time = time.time()

# নতুন লগইন সেশনের জন্য সাময়িক গ্লোবাল ট্র্যাকার
login_temp = {"phone": None, "client": None}

# --- রেন্ডার হেলথ চেক ওয়েব সার্ভার ---
class RenderServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Multi-Account Hybrid Engine is Running!")
    def log_message(self, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), RenderServer).serve_forever()

# ==========================================
#  🤖 ক্যাটাগরি ১: হেল্পার বটের কমান্ডসমূহ (কন্ট্রোল প্যানেল)
# ==========================================

@bot_client.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != OWNER_ID: return
    guide = (
        "👑 **মাল্টি-আইডি হাইব্রিড কন্ট্রোল প্যানেল**\n\n"
        "📱 **নতুন আইডি যোগ করতে:** সরাসরি ফোন নাম্বার পাঠা (যেমন: `+88017XXXXXXXX`)\n"
        "📊 `/list` - অ্যাক্টিভ সব পার্সোনাল আইডির লিস্ট ও স্ট্যাটাস\n"
        "📢 `/broadcast [মেসেজ]` - সব আইডি থেকে একসাথে গ্রুপ/চ্যানেলে মেসেজ পাঠানো\n"
        "🔄 `/reset` - লগইন প্রসেস আটকে গেলে ক্লিয়ার করার কমান্ড"
    )
    await event.reply(guide)

@bot_client.on(events.NewMessage(pattern='/reset'))
async def bot_reset(event):
    if event.sender_id != OWNER_ID: return
    login_temp["phone"] = None
    if login_temp["client"]:
        await login_temp["client"].disconnect()
        login_temp["client"] = None
    await event.reply("🔄 লগইন মেমোরি ক্লিয়ার করা হয়েছে। নতুন করে নাম্বার পাঠাতে পারিস।")

@bot_client.on(events.NewMessage(pattern='/list'))
async def bot_list(event):
    if event.sender_id != OWNER_ID: return
    if not USER_STATES: return await event.reply("ℹ️ কোনো পার্সোনাল অ্যাকাউন্ট এখন লাইভ নেই।")
    
    status_text = "📊 **লাইভ অ্যাকাউন্ট সমূহের তালিকা:**\n\n"
    for uid, data in USER_STATES.items():
        afk_status = f"💤 AFK ({data['reason']})" if data['is_afk'] else "🟢 Active"
        status_text += f"👤 **{data['name']}** (ID: `{uid}`)\n└ স্ট্যাটাস: {afk_status}\n\n"
    await event.reply(status_text)

@bot_client.on(events.NewMessage(pattern=r'/broadcast (.*)'))
async def bot_broadcast(event):
    if event.sender_id != OWNER_ID: return
    msg = event.pattern_match.group(1)
    if not USER_STATES: return await event.reply("❌ কোনো আইডি লগইন করা নেই।")
    
    await event.reply(f"📢 {len(USER_STATES)} টি অ্যাকাউন্ট থেকে ব্রডকাস্ট শুরু হচ্ছে...")
    success = 0
    for uid, data in USER_STATES.items():
        try:
            # ওনারের সেভড মেসেজে টেস্ট ব্রডকাস্ট (তুই চাইলে চ্যাট আইডি লুপ করতে পারিস)
            await data["client"].send_message("me", f"📢 **[সব আইডি থেকে ব্রডকাস্ট]:** {msg}")
            success += 1
        except: pass
    await event.reply(f"✅ ব্রডকাস্ট সম্পন্ন। সফল: {success}/{len(USER_STATES)}")

# 🔐 বটের মাধ্যমে ওটিপি ভিত্তিক নতুন অ্যাকাউন্ট লগইন মেকানিজম
@bot_client.on(events.NewMessage)
async def bot_login_handler(event):
    if event.sender_id != OWNER_ID or event.text.startswith('/'): return
    text = event.text.strip()

    if text.startswith('+') and login_temp["phone"] is None:
        login_temp["phone"] = text
        await event.reply("⏳ ওটিপি রিকোয়েস্ট পাঠানো হচ্ছে...")
        try:
            login_temp["client"] = TelegramClient(StringSession(), API_ID, API_HASH)
            await login_temp["client"].connect()
            await login_temp["client"].send_code_request(login_temp["phone"])
            await event.reply("📩 কোড গেছে। এভাবে পাঠা: `code 12345`")
        except Exception as e:
            login_temp["phone"] = None
            await event.reply(f"❌ ব্যর্থ: {e}")

    elif text.startswith('code ') and login_temp["phone"] is not None:
        code = text.split(' ')[1]
        try:
            await login_temp["client"].sign_in(login_temp["phone"], code)
            me = await login_temp["client"].get_me()
            ss = login_temp["client"].session.save()
            
            # মেমোরিতে রেজিস্টার করা
            register_userbot_handlers(login_temp["client"], me)
            await event.reply(f"🎉 **{me.first_name}** সফলভাবে লগইন হয়েছে!\n\n⚠️ **রেন্ডার পার্মানেন্ট ব্যাকআপ স্ট্রিং সেশন:**\n`{ss}`\n\n💡 একাধিক আইডি সচল রাখতে রেন্ডারের `STRING_SESSIONS` ভেরিয়েবলে কমা (,) দিয়ে এই স্ট্রিংটি যোগ করে দে।")
            login_temp["phone"] = None
        except SessionPasswordNeededError:
            await event.reply("🔐 ২-স্টেপ পাসওয়ার্ড লাগবে। এভাবে পাঠা: `pass তোর_পাসওয়ার্ড`")
        except Exception as e:
            login_temp["phone"] = None
            await event.reply(f"❌ ভুল কোড বা এরর: {e}")

    elif text.startswith('pass ') and login_temp["phone"] is not None:
        pwd = text.replace('pass ', '').strip()
        try:
            await login_temp["client"].sign_in(password=pwd)
            me = await login_temp["client"].get_me()
            ss = login_temp["client"].session.save()
            register_userbot_handlers(login_temp["client"], me)
            await event.reply(f"🎉 2FA ভেরিফাইড! **{me.first_name}** লাইভ।\n\n`{ss}`")
            login_temp["phone"] = None
        except Exception as e:
            await event.reply(f"❌ পাসওয়ার্ড ভুল: {e}")

# ==========================================
#  👤 ক্যাটাগরি ২: পার্সোনাল আইডির নিজস্ব ফিচারসমূহ (Userbot)
# ==========================================

def register_userbot_handlers(client, me):
    uid = me.id
    USER_STATES[uid] = {"is_afk": False, "reason": "", "client": client, "name": me.first_name}

    # ১. এলাইভ (.alive)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.alive'))
    async def u_alive(event):
        ut = int(time.time() - start_time)
        await event.edit(f"⚡ **[ {me.first_name} ] ইউজারবট প্রোফাইল অনলাইন!**\n⏱️ আপটাইম: `{ut}s`\n🎯 ইঞ্জিন: মাল্টি-কন্ট্রোল স্ট্যাবল")

    # ২. পিং (.ping)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.ping'))
    async def u_ping(event):
        t1 = time.time()
        await event.edit("`Ping...`")
        await event.edit(f"🎯 **Pong!**\n⏱️ `{(time.time() - t1)*1000:.2f}ms`")

    # ৩. এএফকে অন (.afk)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.afk(?: |$)(.*)'))
    async def u_afk(event):
        reason = event.pattern_match.group(1) or "এখন ব্যস্ত আছি।"
        USER_STATES[uid]["is_afk"] = True
        USER_STATES[uid]["reason"] = reason
        await event.edit(f"💤 **AFK মোড চালু হলো!**\n📝 কারণ: {reason}")

    # ৪. আইডি চেক (.id)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.id'))
    async def u_id(event):
        await event.edit(f"👤 তোর অ্যাকাউন্ট আইডি: `{uid}`\n📍 এই চ্যাটের আইডি: `{event.chat_id}`")

    # ৫. বায়ো চেঞ্জ (.bio)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.bio(?: |$)(.*)'))
    async def u_bio(event):
        nbio = event.pattern_match.group(1)
        if not nbio: return await event.edit("❌ ফরম্যাট: `.bio তোর টেক্সট`")
        try:
            await client(UpdateProfileRequest(about=nbio))
            await event.edit(f"✅ বায়ো পরিবর্তন সফল: `{nbio}`")
        except Exception as e: await event.edit(f"❌ ভুল: {e}")

    # ৬. সেভড মেসেজে পাঠানো (.save)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.save'))
    async def u_save(event):
        if not event.is_reply: return await event.edit("❌ মেসেজে রিপ্লাই করে `.save` লেখ।")
        reply = await event.get_reply_message()
        await client.send_message("me", reply)
        await event.edit("💾 **Saved Messages-এ রাখা হলো।**")

    # ৭. ফরোয়ার্ড করা (.frwd)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.frwd(?: |$)(.*)'))
    async def u_frwd(event):
        target = event.pattern_match.group(1)
        if not event.is_reply or not target: return await event.edit("❌ ফরম্যাট: মেসেজে রিপ্লাই করে লিখবি `.frwd @username`")
        reply = await event.get_reply_message()
        try:
            await client.forward_messages(target, reply)
            await event.edit(f"⏩ সফলভাবে ফরোয়ার্ড করা হয়েছে।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    # ৮. ইনফো বের করা (.info)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.info'))
    async def u_info(event):
        if not event.is_reply: return await event.edit("❌ কারো মেসেজে রিপ্লাই করে `.info` লেখ।")
        reply = await event.get_reply_message()
        try:
            full = await client(GetFullUserRequest(reply.sender_id))
            await event.edit(f"📋 **নাম:** {full.users[0].first_name}\n🆔 **আইডি:** `{full.users[0].id}`\n📝 **বায়ো:** {full.about or 'খালি'}")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    # ৯. নিজের সব মেসেজ ডিলিট বা পার্জ (.purge)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.purge'))
    async def u_purge(event):
        if not event.is_reply: return await event.edit("❌ যেখান থেকে ডিলিট শুরু করবি সেই মেসেজে রিপ্লাই কর।")
        reply = await event.get_reply_message()
        to_delete = []
        async for msg in client.iter_messages(event.chat_id, min_id=reply.id - 1):
            if msg.out: to_delete.append(msg.id)
        if to_delete: await client.delete_messages(event.chat_id, to_delete)

    # ১০. গ্রুপ মেম্বারদের একসাথে ট্যাগ করা (.tagall)
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.tagall'))
    async def u_tagall(event):
        if event.is_private: return await event.edit("❌ এটি শুধু গ্রুপে কাজ করবে।")
        await event.delete()
        text = ""
        counter = 0
        async for user in client.iter_participants(event.chat_id):
            if user.bot: continue
            text += f"[{user.first_name}](tg://user?id={user.id}) "
            counter += 1
            if counter == 5:  # প্রতি মেসেজে ৫ জন করে ট্যাগ করবে স্প্যাম ফিল্টার এড়াতে
                await client.send_message(event.chat_id, text)
                text = ""
                counter = 0
                await asyncio.sleep(1)
        if text: await client.send_message(event.chat_id, text)

    # 🛑 ইনকামিং মেসেজ হ্যান্ডলার (AFK অটো রিপ্লাই এবং রিমুভাল মেকানিজম)
    @client.on(events.NewMessage(incoming=True))
    async def incoming_afk_manager(event):
        if USER_STATES[uid]["is_afk"] and event.is_private:
            # ওনার নিজে অন্য আইডি থেকে মেসেজ দিলে যাতে লুপ না হয়
            if event.sender_id == OWNER_ID: return 
            await event.reply(f"🤖 **[অটো-রিপ্লাই]**\nআমি এখন লাইনে নেই।\n📝 **কারণ:** {USER_STATES[uid]['reason']}")

    @client.on(events.NewMessage(outgoing=True))
    async def outgoing_afk_remover(event):
        if USER_STATES[uid]["is_afk"] and not event.text.startswith('.afk'):
            USER_STATES[uid]["is_afk"] = False
            m = await event.respond("⚡ **আমি লাইনে ফিরেছি, AFK মোড অফ করা হলো।**")
            await asyncio.sleep(2)
            await m.delete()

# ==========================================
#  🔄 বুটস্ট্র্যাপ ও অটো-রিস্টার্ট ইঞ্জিন
# ==========================================

async def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    print("[+] Starting Gateway Control Bot...")
    await bot_client.start(bot_token=BOT_TOKEN)
    
    # রেন্ডার রিস্টার্টের পর ভেরিয়েবল থেকে মাল্টিপল আইডি রিল্যান্ড করা
    if RAW_SESSIONS:
        sessions = [s.strip() for s in RAW_SESSIONS.split(",") if s.strip()]
        print(f"[+] Found {len(sessions)} backup sessions. Auto-connecting...")
        for index, session_str in enumerate(sessions):
            try:
                cl = TelegramClient(StringSession(session_str), API_ID, API_HASH)
                await cl.connect()
                if await cl.is_user_authorized():
                    me = await cl.get_me()
                    register_userbot_handlers(cl, me)
                    print(f"[+] Account {index+1} ({me.first_name}) Connected Automatically!")
            except Exception as e:
                print(f"[-] Failed to load session {index+1}: {e}")

    await bot_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
        
