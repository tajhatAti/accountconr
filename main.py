import os
import asyncio
import threading
import time
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# --- Configuration ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
RAW_SESSIONS = os.environ.get("STRING_SESSIONS", "")
CONFIG_FILE = "bot_data.json"

start_time = time.time()
login_temp = {"phone": None, "client": None}
USER_STATES = {}  # Tracks all active userbot sessions dynamically

# --- Database Management ---
def load_data():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: 
                return json.load(f)
        except:
            pass
    return {
        "public_cmds": ["ping", "alive", "help", "id"], 
        "banned_users": [], 
        "triggers": {}, 
        "afk_msg": "I am currently offline. Please leave a message."
    }

def save_data(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f: 
        json.dump(data, f, indent=4)

bot_data = load_data()

# --- Web Server for Render Keep-Alive ---
class RenderServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"HyperEngine Engine Multi-Session Service Online")
    def log_message(self, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        HTTPServer(('0.0.0.0', port), RenderServer).serve_forever()
    except Exception as e:
        print(f"[-] Web Server Error: {e}")

def get_uptime():
    uptime_sec = int(time.time() - start_time)
    mins, secs = divmod(uptime_sec, 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    if mins > 0: parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

# ==========================================
#  🤖 MASTER CONTROL BOT HANDLERS (OTP ENGINE)
# ==========================================
def setup_master_bot(bot_client):
    @bot_client.on(events.NewMessage(pattern='/start'))
    async def b_start(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(
            "⚙️ **Hyperbot Controller Hub Active**\n\n"
            "💬 To log in a new account, send the international phone number directly (e.g., `+88017...`)\n"
            "💬 To view available management commands, type: `/bothelp`"
        )

    @bot_client.on(events.NewMessage(pattern='/bothelp'))
    async def b_help(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(
            "🤖 **Master Controller Commands:**\n\n"
            "1. `/start` - Boot control panel\n"
            "2. `/bothelp` - Show this menu\n"
            "3. `/list` - Live status of all logged accounts\n"
            "4. `/reset` - Clear current logging state\n"
            "5. `/stats` - Show combined active count and global runtime"
        )

    @bot_client.on(events.NewMessage(pattern='/list'))
    async def b_list(event):
        if event.sender_id != OWNER_ID: return
        if not USER_STATES: return await event.reply("❌ No active userbot sessions connected.")
        msg = "📋 **Connected Accounts Matrix:**\n\n"
        for idx, (uid, data) in enumerate(USER_STATES.items(), 1):
            st = "💤 AFK Mode" if data["is_afk"]() else "🟢 Active Online"
            msg += f"{idx}. 👤 **{data['name']}** (`{uid}`) - Status: {st}\n"
        await event.reply(msg)

    @bot_client.on(events.NewMessage(pattern='/reset'))
    async def b_reset(event):
        if event.sender_id != OWNER_ID: return
        login_temp["phone"] = None
        if login_temp["client"]: 
            await login_temp["client"].disconnect()
        await event.reply("🔄 Live authorization memory flushed successfully.")

    @bot_client.on(events.NewMessage(pattern='/stats'))
    async def b_stats(event):
        if event.sender_id != OWNER_ID: return
        await event.reply(f"📊 **Total Active Sessions Running:** `{len(USER_STATES)}` Accounts\n⏱ **Global Uptime:** `{get_uptime()}`")

    # --- Secure OTP & 2FA Extraction System ---
    @bot_client.on(events.NewMessage)
    async def b_login_engine(event):
        if event.sender_id != OWNER_ID or event.text.startswith('/'): return
        text = event.text.strip()

        if text.startswith('+') and login_temp["phone"] is None:
            login_temp["phone"] = text
            await event.reply("⏳ Sending OTP authorization request code...")
            try:
                login_temp["client"] = TelegramClient(StringSession(), API_ID, API_HASH)
                await login_temp["client"].connect()
                await login_temp["client"].send_code_request(login_temp["phone"])
                await event.reply("📩 Code dispatched. Reply back strictly using format: `code 12345`")
            except Exception as e:
                login_temp["phone"] = None
                await event.reply(f"❌ API Request Blocked: {e}")

        elif text.startswith('code ') and login_temp["phone"] is not None:
            code_val = text.split(' ')[1]
            try:
                await login_temp["client"].sign_in(login_temp["phone"], code_val)
                await finalize_bot_login(event)
            except SessionPasswordNeededError:
                await event.reply("🔐 Two-Step Verification (2FA) detected. Reply using format: `pass your_password`")
            except Exception as e:
                login_temp["phone"] = None
                await event.reply(f"❌ Login Failed: {e}")

        elif text.startswith('pass ') and login_temp["phone"] is not None:
            pwd_val = text.replace('pass ', '').strip()
            try:
                await login_temp["client"].sign_in(password=pwd_val)
                await finalize_bot_login(event)
            except Exception as e:
                await event.reply(f"❌ 2FA Authentication Failed: {e}")

async def finalize_bot_login(event):
    me = await login_temp["client"].get_me()
    string_generated = login_temp["client"].session.save()
    
    existing_raw = RAW_SESSIONS + "," if RAW_SESSIONS else ""
    updated_env_string = f"{existing_raw}{string_generated}"
    
    await event.reply(
        f"🎉 **Session Authentication Successful for {me.first_name}!**\n\n"
        f"📋 **Generated Telethon String Session Key:**\n"
        f"`{string_generated}`\n\n"
        f"⚙️ **Updated Render Environment Block:**\n"
        f"Go to your Render environment configuration settings, clear the old value of `STRING_SESSIONS` and paste this full sequence below to preserve data on rebuilds:\n\n"
        f"`{updated_env_string}`"
    )
    # Automatically register dynamically to current loop
    register_userbot_handlers(login_temp["client"], me)
    login_temp["phone"] = None

# ==========================================
#  👤 ADVANCED USERBOT MANAGEMENT MATRIX
# ==========================================
def register_userbot_handlers(client, me):
    uid = me.id
    afk_state = {"is_afk": False}
    USER_STATES[uid] = {"is_afk": lambda: afk_state["is_afk"], "name": me.first_name, "client": client}

    async def is_authorized(event, cmd_name):
        if event.sender_id == uid: return True
        if event.sender_id in bot_data["banned_users"]: return False
        return cmd_name in bot_data["public_cmds"]

    @client.on(events.NewMessage)
    async def universal_handler(event):
        if not event.text: return
        
        text = event.text.strip()
        sender_id = event.sender_id

        # 1. AFK Auto-Responder
        if afk_state["is_afk"] and sender_id != uid and sender_id not in bot_data["banned_users"]:
            if event.is_private or event.mentioned:
                await event.reply(f"💤 **[Auto-Reply]**\n{bot_data['afk_msg']}")
        
        # 2. Dynamic AFK Eraser
        if afk_state["is_afk"] and sender_id == uid:
            if not text.lower().startswith((".setafk", "!setafk", "/setafk")):
                afk_state["is_afk"] = False
                msg = await event.respond("⚡ **AFK status automatically structuralized to Offline. Welcome back.**")
                await asyncio.sleep(2)
                await msg.delete()

        # 3. Precision Custom Auto-Reply Filters
        if sender_id != uid and sender_id not in bot_data["banned_users"]:
            lower_text = text.lower()
            for trigger, response in bot_data["triggers"].items():
                if trigger in lower_text:
                    await event.reply(response)
                    return 

        # 4. Advanced Production Level Command Parsing Engine (Multi-line + Username Bypass)
        match = re.match(r'^([.!/])?([a-zA-Z0-9_]+)(?:@[a-zA-Z0-9_]+)?(?:\s+(.*))?$', text, re.DOTALL)
        if not match: return
        
        prefix, cmd_name, args = match.groups()
        cmd_name = cmd_name.lower()
        args = args.strip() if args else ""

        if not prefix and cmd_name not in bot_data["public_cmds"]: return
        if not await is_authorized(event, cmd_name): return

        is_owner = (sender_id == uid)
        
        # --- CORE WORKFLOW LOGIC ---
        if cmd_name == "ping":
            start = time.time()
            msg = await event.reply("`Processing Latency Metrics...`") if not is_owner else await event.edit("`Processing Latency Metrics...`")
            end = time.time()
            await msg.edit(f" ** 🎯 Pong! :** ⏱️`{(end - start) * 1000:.2f}ms`")

        elif cmd_name == "alive":
            uptime = get_uptime()
            alive_msg = (
                f"▫️ ** Identity:** {me.first_name}\n"
                f"▫️ **Uptime:** `{uptime}`"
            )
            await event.reply(alive_msg) if not is_owner else await event.edit(alive_msg)

        elif cmd_name == "id":
            id_msg = f"🆔 **Current Space ID:** `{sender_id}`\n💬 **Global Context Chat ID:** `{event.chat_id}`"
            if event.is_reply:
                rep = await event.get_reply_message()
                id_msg += f"\n🎯 **Target Target ID:** `{rep.sender_id}`"
            await event.reply(id_msg) if not is_owner else await event.edit(id_msg)

        elif cmd_name == "help":
            help_msg = (
                "⚙️ **Hyperbot Production System Control Center** ⚙️\n\n"
                "**🌐 Global Public Matrix Commands:**\n"
                "▫️ `ping` - Returns exact socket latency execution window\n"
                "▫️ `alive` - Verifies architecture runtime parameters\n"
                "▫️ `id` - Structuralizes unique context IDs\n"
                "▫️ `help` - Deploys this configuration control center map\n\n"
                "**👑 Security Administration Commands (Owner Privileged):**\n"
                "▫️ `!addcmd [cmd]` - White-lists selected commands for public use profiles\n"
                "▫️ `!remcmd [cmd]` - Hard-locks commands from public interaction matrices\n"
                "▫️ `!ban [user/reply]` - Access-denies target from engine interactions\n"
                "▫️ `!unban [user/reply]` - Drops database lock on selected entity\n"
                "▫️ `!setreply trigger | message` - Maps data text lines to reactive words\n"
                "▫️ `!delreply trigger` - Drops specified trigger profile\n"
                "▫️ `!setafk [message]` - Maps multi-line block responses to auto-reply frames\n\n"
                "**🛠 Execution Optimization Profiles:**\n"
                "▫️ `!purge` (Reply Target) - Flushes database records upwards safely\n"
                "▫️ `!userinfo` (Reply/Username) - Resolves structural target parameters"
            )
            await event.reply(help_msg) if not is_owner else await event.edit(help_msg)

        # --- EXCLUSIVE SYSTEM OPERATOR MANAGEMENT COMMAND MODULES ---
        if is_owner:
            if cmd_name == "addcmd":
                if args and args not in bot_data["public_cmds"]:
                    bot_data["public_cmds"].append(args.lower())
                    save_data(bot_data)
                    await event.edit(f"✅ Protocol access configured. `{args}` is now interactive globally.")
                else:
                    await event.edit("⚠️ Parameter resolution error: invalid or existing string structure.")

            elif cmd_name == "remcmd":
                if args and args in bot_data["public_cmds"]:
                    bot_data["public_cmds"].remove(args.lower())
                    save_data(bot_data)
                    await event.edit(f"🚫 Protocol locked. `{args}` stripped from public arrays.")

            elif cmd_name == "ban":
                target = args
                if event.is_reply:
                    target = (await event.get_reply_message()).sender_id
                if target and target not in bot_data["banned_users"]:
                    bot_data["banned_users"].append(target)
                    save_data(bot_data)
                    await event.edit(f"🔨 Firewall locked entity profile `{target}` safely.")

            elif cmd_name == "unban":
                target = args
                if event.is_reply:
                    target = (await event.get_reply_message()).sender_id
                if target in bot_data["banned_users"]:
                    bot_data["banned_users"].remove(target)
                    save_data(bot_data)
                    await event.edit(f"✅ Drop-lock structural sequence completed for entity `{target}`.")

            elif cmd_name == "setreply":
                if "|" in args:
                    trigger, response = map(str.strip, args.split("|", 1))
                    if trigger and response:
                        bot_data["triggers"][trigger.lower()] = response
                        save_data(bot_data)
                        await event.edit(f"✅ **Database Entry Structuralized.**\n**Target String:** `{trigger}`\n**Response Map Set Completely.**")
                else:
                    await event.edit("⚠️ **Syntax Parse Fault:** Execute via pattern: `!setreply text_key | Multi-line text block`")

            elif cmd_name == "delreply":
                if args.lower() in bot_data["triggers"]:
                    del bot_data["triggers"][args.lower()]
                    save_data(bot_data)
                    await event.edit(f"🗑 **Data Matrix Mapping Erased:** `{args}`")

            elif cmd_name == "setafk":
                afk_state["is_afk"] = True
                if args:
                    bot_data["afk_msg"] = args
                    save_data(bot_data)
                await event.edit(f"💤 **Auto-Reply Status Set to AFK.**\n**Preserved Message Structural Frame Configuration Loaded Safely.**")

            elif cmd_name == "purge":
                if not event.is_reply:
                    return await event.edit("⚠️ System validation requires a valid reference message to lock target window boundary.")
                rep = await event.get_reply_message()
                purge_bucket = []
                async for m in client.iter_messages(event.chat_id, min_id=rep.id - 1):
                    purge_bucket.append(m.id)
                    if len(purge_bucket) >= 100:
                        await client.delete_messages(event.chat_id, purge_bucket)
                        purge_bucket = []
                if purge_bucket:
                    await client.delete_messages(event.chat_id, purge_bucket)
                msg = await event.respond("🧹 **Matrix Database Purge Protocol Executed Successfully.**")
                await asyncio.sleep(2)
                await msg.delete()

            elif cmd_name == "userinfo":
                target = args
                if event.is_reply:
                    target = (await event.get_reply_message()).sender_id
                if not target:
                    return await event.edit("⚠️ Target tracking requires valid handle signature parameters.")
                try:
                    user = await client.get_entity(target)
                    info = (
                        f"👤 **Entity Diagnostic Record:**\n\n"
                        f"**True Handle First Name:** {user.first_name} {user.last_name or ''}\n"
                        f"**Database Array ID Key:** `{user.id}`\n"
                        f"**Global Network Handle Alias:** @{user.username if user.username else 'N/A'}\n"
                        f"**Automated Engine Bot Profile:** {'Yes' if user.bot else 'No'}\n"
                        f"**Malicious Script / Scam Profile:** {'Yes' if user.scam else 'No'}"
                    )
                    await event.edit(info)
                except Exception as e:
                    await event.edit(f"❌ **Failed to structuralize details block from API:** `{e}`")

# ==========================================
#  🔄 ASYNCHRONOUS SYSTEM ORCHESTRATION BOOT
# ==========================================
async def main():
    print("[+] Launching Multi-Session Engine Core Network...")
    threading.Thread(target=run_web_server, daemon=True).start()

    # Phase 1: Initialize Master Controller Bot
    if not BOT_TOKEN:
        print("[-] TERMINAL BLOCKER: BOT_TOKEN Environment Variable Missing.")
        return

    bot_client = TelegramClient('master_controller_hub', API_ID, API_HASH)
    setup_master_bot(bot_client)
    await bot_client.start(bot_token=BOT_TOKEN)
    print("[+] Controller Bot Hub Authentication Protocol Verified.")

    # Phase 2: Orchestrate Multi-Account String Sessions Safely
    if RAW_SESSIONS:
        session_list = [s.strip() for s in RAW_SESSIONS.split(",") if s.strip()]
        for idx, session_key in enumerate(session_list):
            try:
                ub_client = TelegramClient(StringSession(session_key), API_ID, API_HASH)
                await ub_client.connect()
                if await ub_client.is_user_authorized():
                    me = await ub_client.get_me()
                    register_userbot_handlers(ub_client, me)
                    print(f"[+] Operational Account Linked Node {idx+1}: {me.first_name}")
                else:
                    print(f"[-] Defunct Node Session Matrix Index: {idx+1}")
            except Exception as e:
                print(f"[-] Operational Failure Bootstrapping Session Node {idx+1}: {e}")
    else:
        print("[!] NOTICE: No default multi-session string tokens loaded into environment matrix arrays.")

    await bot_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
    
