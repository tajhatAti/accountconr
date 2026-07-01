import os
import asyncio
import threading
import time
import json
import base64
import random
import re
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# Telethon & Third-party Imports
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights
from deep_translator import GoogleTranslator

# --- কনফিগারেশন ও এনভায়রনমেন্ট ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RAW_SESSIONS = os.environ.get("STRING_SESSIONS", "")

USER_STATES = {} 
bot_client = None  
start_time = time.time()
login_temp = {"phone": None, "client": None}

# --- JSON ডাটাবেস (কাস্টম সেটিংস সেভ রাখার জন্য) ---
CONFIG_FILE = "bot_config.json"
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"public_cmds": [], "banned_users": [], "triggers": {}, "afk_msg": None}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

bot_config = load_config()

# --- ওয়েব সার্ভার ---
class RenderServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"HyperEngine Bot Online")
    def log_message(self, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), RenderServer).serve_forever()

# --- অথেন্টিকেশন চেকার ---
def check_access(event, uid, cmd_name):
    sender = event.sender_id
    if sender == uid: return True
    if sender in bot_config["banned_users"]: return False
    if cmd_name in bot_config["public_cmds"]: return True
    return False

def setup_bot_handlers(client):
    @client.on(events.NewMessage(pattern='/start'))
    async def b_start(event):
        if event.sender_id != OWNER_ID: return
        await event.reply("⚙️ **কন্ট্রোলার প্যানেল সচল!**")

    # (আগের কন্ট্রোলার কমান্ডগুলো এখানে থাকবে, জায়গা বাঁচানোর জন্য সংক্ষিপ্ত করা হলো)
    # তুমি তোমার আগের কোডের প্যানেল ফিচারস এখানে যুক্ত রাখতে পারো।

async def finalize_login(event):
    me = await login_temp["client"].get_me()
    ss = login_temp["client"].session.save()
    register_userbot_handlers(login_temp["client"], me)
    existing = RAW_SESSIONS + "," if RAW_SESSIONS else ""
    await event.reply(f"🎉 **{me.first_name}** অনলাইন হয়েছে!\n\n`{existing}{ss}`")
    login_temp["phone"] = None

# ==========================================
#  👤 ইউজারবট ইঞ্জিন (কাস্টম কমান্ড ও রেস্ট্রিকশন সহ)
# ==========================================
def register_userbot_handlers(client, me):
    uid = me.id
    USER_STATES[uid] = {"is_afk": False, "client": client, "name": me.first_name}

    # --- মালিকের কাস্টমাইজেশন টুলস (পাবলিক নয়) ---
    @client.on(events.NewMessage(outgoing=True, pattern=r'!(add|rem) (.*)'))
    async def u_cmd_manager(event):
        action, cmd = event.pattern_match.group(1), event.pattern_match.group(2).lower()
        if action == "add":
            if cmd not in bot_config["public_cmds"]: bot_config["public_cmds"].append(cmd)
            msg = f"✅ `{cmd}` সাধারণ ইউজারদের জন্য উন্মুক্ত করা হয়েছে।"
        else:
            if cmd in bot_config["public_cmds"]: bot_config["public_cmds"].remove(cmd)
            msg = f"🚫 `{cmd}` সাধারণ ইউজারদের থেকে রিমুভ করা হয়েছে।"
        save_config(bot_config)
        await event.edit(msg)

    @client.on(events.NewMessage(outgoing=True, pattern=r'!banme(?:\s+(.*))?'))
    async def u_ban_user(event):
        target_id = None
        if event.is_reply: target_id = (await event.get_reply_message()).sender_id
        else: 
            try: target_id = (await client.get_entity(event.pattern_match.group(1))).id
            except: return await event.edit("❌ ইউজার পাওয়া যায়নি।")
        
        if target_id not in bot_config["banned_users"]:
            bot_config["banned_users"].append(target_id)
            save_config(bot_config)
        await event.edit(f"🔨 ইউজার `{target_id}` কে বটের ব্যবহার থেকে ব্যান করা হয়েছে।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!unbanme(?:\s+(.*))?'))
    async def u_unban_user(event):
        target_id = None
        if event.is_reply: target_id = (await event.get_reply_message()).sender_id
        else: 
            try: target_id = (await client.get_entity(event.pattern_match.group(1))).id
            except: return await event.edit("❌ ইউজার পাওয়া যায়নি।")
        
        if target_id in bot_config["banned_users"]:
            bot_config["banned_users"].remove(target_id)
            save_config(bot_config)
        await event.edit(f"✅ ইউজার `{target_id}` কে আনব্যান করা হয়েছে।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!setreply (.*?)\s*\|\s*(.*)'))
    async def u_set_reply(event):
        trigger = event.pattern_match.group(1).lower()
        response = event.pattern_match.group(2)
        bot_config["triggers"][trigger] = response
        save_config(bot_config)
        await event.edit(f"✅ ট্রিগার সেট করা হয়েছে:\n**When:** `{trigger}`\n**Reply:** `{response}`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!delreply (.*)'))
    async def u_del_reply(event):
        trigger = event.pattern_match.group(1).lower()
        if trigger in bot_config["triggers"]:
            del bot_config["triggers"][trigger]
            save_config(bot_config)
            await event.edit(f"🗑️ `{trigger}` ট্রিগারটি ডিলিট করা হয়েছে।")
        else: await event.edit("❌ ট্রিগারটি পাওয়া যায়নি।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!setafk (.*)'))
    async def u_set_afk(event):
        bot_config["afk_msg"] = event.pattern_match.group(1)
        save_config(bot_config)
        USER_STATES[uid]["is_afk"] = True
        await event.edit(f"💤 AFK মোড অন! কাস্টম মেসেজ সেট করা হয়েছে।")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!mute (\d+)([dhm])(?:\s+(.*))?'))
    async def u_mute_timer(event):
        amount, unit = int(event.pattern_match.group(1)), event.pattern_match.group(2)
        target = event.pattern_match.group(3)
        
        if event.is_reply: target_entity = await event.get_reply_message()
        elif target: target_entity = await client.get_entity(target)
        else: return await event.edit("❌ ইউজার মেনশন বা রিপ্লাই করো।")
        
        target_id = target_entity.sender_id if event.is_reply else target_entity.id
        
        if unit == 'd': delta = timedelta(days=amount)
        elif unit == 'h': delta = timedelta(hours=amount)
        elif unit == 'm': delta = timedelta(minutes=amount)
        
        until = datetime.now() + delta
        rights = ChatBannedRights(until_date=until, send_messages=True)
        try:
            await client(EditBannedRequest(event.chat_id, target_id, rights))
            await event.edit(f"🔇 ইউজারকে {amount}{unit} এর জন্য মিউট করা হয়েছে।")
        except Exception as e: await event.edit(f"❌ এরর বা এডমিন রাইটস নেই: {e}")

    # --- কোর কমান্ডস (পাবলিক এক্সেস সাপোর্ট সহ) ---
    # প্রিফিক্স ছাড়া বা প্রিফিক্স সহ কাজ করবে (যেমন: .ping, ping, !ping)
    @client.on(events.NewMessage(pattern=r'(?i)^[.\/!]?(ping)$'))
    async def u_ping(event):
        if not check_access(event, uid, "ping"): return
        t = time.time()
        m = await event.reply("`Pinging...`") if event.sender_id != uid else await event.edit("`Pinging...`")
        await m.edit(f"🎯 **Pong!**\n⏱️ `{(time.time() - t)*1000:.2f}ms`")

    @client.on(events.NewMessage(pattern=r'(?i)^[.\/!]?(id)$'))
    async def u_id(event):
        if not check_access(event, uid, "id"): return
        msg = f"👤 **ইউজার আইডি:** `{event.sender_id}`\n📍 **চ্যাট আইডি:** `{event.chat_id}`"
        await event.reply(msg) if event.sender_id != uid else await event.edit(msg)

    @client.on(events.NewMessage(pattern=r'(?i)^[.\/!]?(alive)$'))
    async def u_alive(event):
        if not check_access(event, uid, "alive"): return
        msg = f"⚡ **হাইব্রিড ইঞ্জিন সচল!**\n⏱️ আপটাইম: `{int(time.time() - start_time)}s`"
        await event.reply(msg) if event.sender_id != uid else await event.edit(msg)

    # --- অটো রেসপন্স ও AFK (কাস্টম মেসেজ) ---
    @client.on(events.NewMessage(incoming=True))
    async def auto_reply_manager(event):
        if event.sender_id in bot_config["banned_users"]: return
        if not event.text: return
        
        text = event.text.lower()
        
        # ১. কাস্টম ট্রিগার চেক (যেমন help বা emergency)
        for trigger, response in bot_config["triggers"].items():
            if trigger in text:
                await event.reply(response)
                return # রিপ্লাই দেওয়ার পর আর চেক করবে না
                
        # ২. AFK চেক
        state = USER_STATES.get(uid)
        if state and state["is_afk"]:
            if event.is_private and event.sender_id != uid:
                sender = await event.get_sender()
                if sender and not sender.bot:
                    afk_msg = bot_config["afk_msg"] or "আমি এখন অফলাইনে আছি।"
                    await event.reply(afk_msg)
            elif event.mentioned:
                afk_msg = bot_config["afk_msg"] or "আমি এখন অফলাইনে আছি।"
                await event.reply(afk_msg)

    @client.on(events.NewMessage(outgoing=True))
    async def outgoing_afk_remover(event):
        state = USER_STATES.get(uid)
        if state and state["is_afk"] and not event.text.startswith('!setafk'):
            state["is_afk"] = False
            m = await event.respond("⚡ AFK মোড অফ করা হয়েছে।")
            await asyncio.sleep(2)
            await m.delete()

# ==========================================
#  রানিং বুটস্ট্র্যাপ
# ==========================================
async def main():
    global bot_client
    bot_client = TelegramClient('helper_bot_v2', API_ID, API_HASH)
    setup_bot_handlers(bot_client)

    threading.Thread(target=run_web_server, daemon=True).start()
    print("[+] Starting Bot Engine...")
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
                    print(f"[+] Connected: {me.first_name}")
            except Exception as e: print(f"[-] Error: {e}")

    await bot_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
        
