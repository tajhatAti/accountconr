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

# Settings
COOLDOWN_TIME = 10 # Seconds (সাধারণ ইউজারের জন্য স্প্যাম লিমিট)
AUTO_DELETE_DELAY = 60 # Seconds (মেসেজ ডিলিট হওয়ার সময়সীমা)

start_time = time.time()
login_temp = {"phone": None, "client": None}
USER_STATES = {}
USER_COOLDOWNS = {} # Tracks user command usage timestamps

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
        self.wfile.write(b"HyperEngine Active")
    def log_message(self, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        HTTPServer(('0.0.0.0', port), RenderServer).serve_forever()
    except Exception as e:
        pass

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
        await event.reply("⚙️ **Hyperbot Controller Active**\n💬 Send phone number (`+88017...`) to login.")

    @bot_client.on(events.NewMessage)
    async def b_login_engine(event):
        if event.sender_id != OWNER_ID or event.text.startswith('/'): return
        text = event.text.strip()

        if text.startswith('+') and login_temp["phone"] is None:
            login_temp["phone"] = text
            await event.reply("⏳ Sending OTP...")
            try:
                login_temp["client"] = TelegramClient(StringSession(), API_ID, API_HASH)
                await login_temp["client"].connect()
                await login_temp["client"].send_code_request(login_temp["phone"])
                await event.reply("📩 Send code as: `code 12345`")
            except Exception as e:
                login_temp["phone"] = None
                await event.reply(f"❌ Error: {e}")

        elif text.startswith('code ') and login_temp["phone"] is not None:
            code_val = text.split(' ')[1]
            try:
                await login_temp["client"].sign_in(login_temp["phone"], code_val)
                await finalize_bot_login(event)
            except SessionPasswordNeededError:
                await event.reply("🔐 2FA detected. Send password as: `pass your_password`")
            except Exception as e:
                login_temp["phone"] = None
                await event.reply(f"❌ Error: {e}")

        elif text.startswith('pass ') and login_temp["phone"] is not None:
            pwd_val = text.replace('pass ', '').strip()
            try:
                await login_temp["client"].sign_in(password=pwd_val)
                await finalize_bot_login(event)
            except Exception as e:
                await event.reply(f"❌ Error: {e}")

async def finalize_bot_login(event):
    me = await login_temp["client"].get_me()
    string_generated = login_temp["client"].session.save()
    updated_env = f"{RAW_SESSIONS},{string_generated}" if RAW_SESSIONS else string_generated
    await event.reply(f"🎉 **Login Success: {me.first_name}**\n\n`{string_generated}`\n\nUpdate `STRING_SESSIONS` in Render.")
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

        # 1. AFK Handling
        if afk_state["is_afk"] and sender_id != uid and sender_id not in bot_data["banned_users"]:
            if event.is_private or event.mentioned:
                await event.reply(f"💤 **[AFK Auto-Reply]**\n{bot_data['afk_msg']}")
        
        if afk_state["is_afk"] and sender_id == uid:
            if not text.lower().startswith((".setafk", "!setafk", "/setafk")):
                afk_state["is_afk"] = False
                msg = await event.respond("⚡ **AFK Disabled.**")
                await asyncio.sleep(3)
                await msg.delete()

        # 2. Custom Auto-Reply Filters
        if sender_id != uid and sender_id not in bot_data["banned_users"]:
            lower_text = text.lower()
            for trigger, response in bot_data["triggers"].items():
                if trigger in lower_text:
                    return await event.reply(response)

        # 3. Command Parsing Engine
        match = re.match(r'^([.!/])?([a-zA-Z0-9_]+)(?:@[a-zA-Z0-9_]+)?(?:\s+(.*))?$', text, re.DOTALL)
        if not match: return
        
        prefix, cmd_name, args = match.groups()
        cmd_name = cmd_name.lower()
        args = args.strip() if args else ""

        if not prefix and cmd_name not in bot_data["public_cmds"]: return
        if not await is_authorized(event, cmd_name): return

        is_owner = (sender_id == uid)

        # 4. Anti-Spam / Cooldown Check (Only for non-owners)
        if not is_owner:
            last_used = USER_COOLDOWNS.get(sender_id, 0)
            time_passed = time.time() - last_used
            if time_passed < COOLDOWN_TIME:
                wait_time = int(COOLDOWN_TIME - time_passed)
                spam_msg = await event.reply(f"⏳ **Net, please wait {wait_time} seconds before using this command again.**")
                await asyncio.sleep(5)
                return await spam_msg.delete()
            USER_COOLDOWNS[sender_id] = time.time()
        
        # --- COMMAND PROCESSING ---
        output_msg = None

       if cmd_name == "ping":
            start = time.time()
            # সবক্ষেত্রে আগে একটা রিপ্লাই পাঠাবে, তারপর সেটা এডিট করবে (এটা সবচেয়ে নিরাপদ)
            msg = await event.reply("`Processing...`")
            end = time.time()
            latency = int((end - start) * 1000)
            
            status = "🟢 Excellent" if latency < 150 else ("🟡 Average" if latency < 400 else "🔴 Poor")
            
            output = (
                f"🏓 **Pong!**\n\n"
                f"🧭 **Ping:** `{latency} ms`\n"
                f"📶 **Status:** {status}\n\n"
                f"📝 *Note: This ping shows exact TBC processing time.*\n"
                f"🗑 *This message will be deleted after {AUTO_DELETE_DELAY} seconds.*"
            )
            output_msg = await msg.edit(output)


        elif cmd_name == "alive":
            output = (
                f"⚡ **System Status:**\n\n"
                f"👤 **Node Identity:** {me.first_name}\n"
                f"⏱ **System Uptime:** `{get_uptime()}`\n"
                f"🛡 **Engine:** Secure Multi-Session Matrix\n\n"
                f"🗑 *This message will be deleted after {AUTO_DELETE_DELAY} seconds.*"
            )
            output_msg = await event.reply(output) if not is_owner else await event.edit(output)

        elif cmd_name == "id":
            output = f"🆔 **User ID:** `{sender_id}`\n💬 **Chat ID:** `{event.chat_id}`"
            if event.is_reply:
                rep = await event.get_reply_message()
                output += f"\n🎯 **Replied User ID:** `{rep.sender_id}`"
            output += f"\n\n🗑 *Auto-deleting in {AUTO_DELETE_DELAY}s.*"
            output_msg = await event.reply(output) if not is_owner else await event.edit(output)

        elif cmd_name == "help":
            if is_owner:
                # Owner Help Menu (Full Access)
                output = (
                    "⚙️ **Owner Control Panel** ⚙️\n\n"
                    "**🌐 Public Commands:** `ping`, `alive`, `id`, `help`\n"
                    "**🛡 Access Control:**\n"
                    "▫️ `!addcmd [cmd]` - Make command public\n"
                    "▫️ `!remcmd [cmd]` - Make command private\n"
                    "▫️ `!ban / !unban [user/reply]` - Manage access\n"
                    "**⚙️ Utility:**\n"
                    "▫️ `!setreply trigger | text` - Set auto-reply\n"
                    "▫️ `!delreply trigger` - Delete auto-reply\n"
                    "▫️ `!setafk [text]` - Enable AFK\n"
                    "▫️ `!purge` (Reply) - Clear messages\n"
                    "▫️ `!userinfo` - Get user details\n\n"
                    f"🗑 *Auto-deleting in {AUTO_DELETE_DELAY}s.*"
                )
            else:
                # Regular User Help Menu (Dynamic based on allowed commands)
                allowed = "\n".join([f"▫️ `{cmd}`" for cmd in bot_data["public_cmds"]])
                output = (
                    "🌐 **Available Public Commands:**\n\n"
                    f"{allowed}\n\n"
                    f"📝 *Note: You can only use the commands listed above.*\n"
                    f"🗑 *Auto-deleting in {AUTO_DELETE_DELAY}s.*"
                )
            output_msg = await event.reply(output) if not is_owner else await event.edit(output)

        # --- EXCLUSIVE SYSTEM OPERATOR MANAGEMENT COMMAND MODULES ---
        if is_owner:
            if cmd_name == "addcmd":
                if args and args not in bot_data["public_cmds"]:
                    bot_data["public_cmds"].append(args.lower())
                    save_data(bot_data)
                    output_msg = await event.edit(f"✅ `{args}` is now available for public users.\n🗑 *Auto-deleting in 5s.*")
                    AUTO_DELETE_DELAY = 5 # Force quick delete for config commands
                else:
                    await event.edit("⚠️ Invalid or existing command.")

            elif cmd_name == "remcmd":
                if args and args in bot_data["public_cmds"]:
                    bot_data["public_cmds"].remove(args.lower())
                    save_data(bot_data)
                    output_msg = await event.edit(f"🚫 `{args}` hidden from public users.\n🗑 *Auto-deleting in 5s.*")
                    AUTO_DELETE_DELAY = 5

            elif cmd_name == "ban":
                target = args if not event.is_reply else (await event.get_reply_message()).sender_id
                if target and target not in bot_data["banned_users"]:
                    bot_data["banned_users"].append(target)
                    save_data(bot_data)
                    await event.edit(f"🔨 Entity `{target}` banned.")

            elif cmd_name == "unban":
                target = args if not event.is_reply else (await event.get_reply_message()).sender_id
                if target in bot_data["banned_users"]:
                    bot_data["banned_users"].remove(target)
                    save_data(bot_data)
                    await event.edit(f"✅ Entity `{target}` unbanned.")

            elif cmd_name == "setreply":
                if "|" in args:
                    trigger, response = map(str.strip, args.split("|", 1))
                    bot_data["triggers"][trigger.lower()] = response
                    save_data(bot_data)
                    await event.edit(f"✅ **Trigger Set:** `{trigger}`")
                else:
                    await event.edit("⚠️ Use: `!setreply text | response`")

            elif cmd_name == "delreply":
                if args.lower() in bot_data["triggers"]:
                    del bot_data["triggers"][args.lower()]
                    save_data(bot_data)
                    await event.edit(f"🗑 **Trigger Deleted:** `{args}`")

            elif cmd_name == "setafk":
                afk_state["is_afk"] = True
                if args:
                    bot_data["afk_msg"] = args
                    save_data(bot_data)
                await event.edit(f"💤 **AFK Enabled.**")

            elif cmd_name == "purge":
                if not event.is_reply: return await event.edit("⚠️ Reply to a message.")
                rep = await event.get_reply_message()
                purge_bucket = []
                async for m in client.iter_messages(event.chat_id, min_id=rep.id - 1):
                    purge_bucket.append(m.id)
                    if len(purge_bucket) >= 100:
                        await client.delete_messages(event.chat_id, purge_bucket)
                        purge_bucket = []
                if purge_bucket: await client.delete_messages(event.chat_id, purge_bucket)
                output_msg = await event.respond("🧹 **Purge Complete.**")
                AUTO_DELETE_DELAY = 3 # Quick delete for purge notification

            elif cmd_name == "userinfo":
                target = args if not event.is_reply else (await event.get_reply_message()).sender_id
                if not target: return await event.edit("⚠️ Provide target.")
                try:
                    user = await client.get_entity(target)
                    info = (
                        f"👤 **Name:** {user.first_name}\n"
                        f"**ID:** `{user.id}`\n"
                        f"**Username:** @{user.username or 'N/A'}\n"
                    )
                    await event.edit(info)
                except Exception as e:
                    await event.edit(f"❌ **Error:** `{e}`")

                # --- AUTO DELETE ENGINE (সব রিপ্লাইয়ের জন্য একই নিয়ম) ---
        if output_msg:
            async def auto_delete(msg):
                await asyncio.sleep(AUTO_DELETE_DELAY)
                try: await msg.delete()
                except: pass
            asyncio.create_task(auto_delete(output_msg))
            
            # Using actual delay value for specific commands (e.g. 5s for addcmd, 60s for ping)
            current_delay = 5 if is_owner and cmd_name in ["addcmd", "remcmd", "purge"] else AUTO_DELETE_DELAY
            asyncio.create_task(delete_later(output_msg, current_delay))

# ==========================================
#  🔄 SYSTEM ORCHESTRATION BOOT
# ==========================================
async def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    
    if BOT_TOKEN:
        bot_client = TelegramClient('master_controller_hub', API_ID, API_HASH)
        setup_master_bot(bot_client)
        await bot_client.start(bot_token=BOT_TOKEN)
        print("[+] Controller Hub Online.")

    if RAW_SESSIONS:
        session_list = [s.strip() for s in RAW_SESSIONS.split(",") if s.strip()]
        for idx, session_key in enumerate(session_list):
            try:
                ub_client = TelegramClient(StringSession(session_key), API_ID, API_HASH)
                await ub_client.connect()
                if await ub_client.is_user_authorized():
                    me = await ub_client.get_me()
                    register_userbot_handlers(ub_client, me)
                    print(f"[+] Operational Account: {me.first_name}")
            except Exception as e:
                print(f"[-] Node Failure: {e}")

    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
            
