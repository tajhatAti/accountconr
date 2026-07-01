import os
import asyncio
import time
import json
import re
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- Configuration ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
RAW_SESSION = os.environ.get("STRING_SESSION", "")
CONFIG_FILE = "bot_data.json"

start_time = time.time()

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

# --- Utility Functions ---
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

# --- Core Userbot Logic ---
def register_handlers(client, me):
    uid = me.id
    afk_status = {"is_afk": False}

    async def is_authorized(event, cmd_name):
        if event.sender_id == uid: return True
        if event.sender_id in bot_data["banned_users"]: return False
        return cmd_name in bot_data["public_cmds"]

    @client.on(events.NewMessage)
    async def universal_handler(event):
        if not event.text: return
        
        text = event.text.strip()
        sender_id = event.sender_id

        # 1. AFK Manager (Incoming)
        if afk_status["is_afk"] and sender_id != uid and sender_id not in bot_data["banned_users"]:
            if event.is_private or event.mentioned:
                await event.reply(f"💤 **[Auto-Reply]**\n{bot_data['afk_msg']}")
        
        # 2. AFK Remover (Outgoing)
        if afk_status["is_afk"] and sender_id == uid:
            if not text.lower().startswith(("!setafk", "/setafk", ".setafk")):
                afk_status["is_afk"] = False
                msg = await event.respond("⚡ **AFK mode disabled. You are back online.**")
                await asyncio.sleep(3)
                await msg.delete()

        # 3. Custom Auto-Reply (Triggers)
        if sender_id != uid and sender_id not in bot_data["banned_users"]:
            lower_text = text.lower()
            for trigger, response in bot_data["triggers"].items():
                if trigger in lower_text:
                    await event.reply(response)
                    return # Stop processing further if trigger matched

        # 4. Command Parser (Regex handles prefixes, @username, and multi-line arguments safely)
        # Matches: [prefix](command)[@botusername] [arguments]
        match = re.match(r'^([.!/])?([a-zA-Z0-9_]+)(?:@[a-zA-Z0-9_]+)?(?:\s+(.*))?$', text, re.DOTALL)
        
        if not match: return
        
        prefix, cmd_name, args = match.groups()
        cmd_name = cmd_name.lower()
        args = args.strip() if args else ""

        # Avoid processing normal text without prefix unless it's a specific public command
        if not prefix and cmd_name not in bot_data["public_cmds"]:
            return

        if not await is_authorized(event, cmd_name): return

        is_owner = (sender_id == uid)
        
        # =====================================
        # PUBLIC / BASIC COMMANDS
        # =====================================
        if cmd_name == "ping":
            start = time.time()
            msg = await event.reply("`Pinging...`") if not is_owner else await event.edit("`Pinging...`")
            end = time.time()
            await msg.edit(f"🏓 **System Latency:** `{(end - start) * 1000:.2f}ms`")

        elif cmd_name == "alive":
            uptime = get_uptime()
            alive_msg = (
                f"⚡ **System Status:** Online\n"
                f"👤 **User:** {me.first_name}\n"
                f"⏱ **Uptime:** `{uptime}`\n"
                f"🛡 **Engine:** Advanced Userbot"
            )
            await event.reply(alive_msg) if not is_owner else await event.edit(alive_msg)

        elif cmd_name == "id":
            id_msg = f"🆔 **User ID:** `{sender_id}`\n💬 **Chat ID:** `{event.chat_id}`"
            if event.is_reply:
                rep = await event.get_reply_message()
                id_msg += f"\n🎯 **Replied User ID:** `{rep.sender_id}`"
            await event.reply(id_msg) if not is_owner else await event.edit(id_msg)

        elif cmd_name == "help":
            help_msg = (
                "🛠 **Hyperbot Command Center** 🛠\n\n"
                "**🌐 Public Commands:**\n"
                "▫️ `ping` - Check system latency\n"
                "▫️ `alive` - Check bot status & uptime\n"
                "▫️ `id` - Get Chat/User IDs\n"
                "▫️ `help` - Show this menu\n\n"
                "**👑 Owner Commands (Admin Only):**\n"
                "▫️ `!addcmd [cmd]` - Allow a command for public use\n"
                "▫️ `!remcmd [cmd]` - Remove a command from public use\n"
                "▫️ `!ban [user/reply]` - Ban user from using the bot\n"
                "▫️ `!unban [user/reply]` - Unban user\n"
                "▫️ `!setreply trigger | text` - Set auto-reply\n"
                "▫️ `!delreply trigger` - Delete auto-reply\n"
                "▫️ `!setafk [text]` - Enable AFK mode\n\n"
                "**⚙️ Utility Commands (Owner Only):**\n"
                "▫️ `!purge` (Reply) - Delete messages up to replied message\n"
                "▫️ `!userinfo` (Reply/Username) - Get user details\n"
            )
            await event.reply(help_msg) if not is_owner else await event.edit(help_msg)

        # =====================================
        # OWNER / MANAGEMENT COMMANDS
        # =====================================
        if is_owner:
            if cmd_name == "addcmd":
                if args and args not in bot_data["public_cmds"]:
                    bot_data["public_cmds"].append(args.lower())
                    save_data(bot_data)
                    await event.edit(f"✅ Command `{args}` is now available for public use.")
                else:
                    await event.edit("⚠️ Please specify a valid command or it's already added.")

            elif cmd_name == "remcmd":
                if args and args in bot_data["public_cmds"]:
                    bot_data["public_cmds"].remove(args.lower())
                    save_data(bot_data)
                    await event.edit(f"🚫 Command `{args}` has been removed from public use.")

            elif cmd_name == "ban":
                target = args
                if event.is_reply:
                    target = (await event.get_reply_message()).sender_id
                
                if target and target not in bot_data["banned_users"]:
                    bot_data["banned_users"].append(target)
                    save_data(bot_data)
                    await event.edit(f"🔨 User `{target}` is now banned from interacting with the bot.")

            elif cmd_name == "unban":
                target = args
                if event.is_reply:
                    target = (await event.get_reply_message()).sender_id
                
                if target in bot_data["banned_users"]:
                    bot_data["banned_users"].remove(target)
                    save_data(bot_data)
                    await event.edit(f"✅ User `{target}` has been unbanned.")

            elif cmd_name == "setreply":
                # Splitting by the first occurrence of '|'
                if "|" in args:
                    trigger, response = map(str.strip, args.split("|", 1))
                    if trigger and response:
                        bot_data["triggers"][trigger.lower()] = response
                        save_data(bot_data)
                        await event.edit(f"✅ **Auto-reply set successfully.**\n**Trigger:** `{trigger}`\n**Response:**\n{response}")
                else:
                    await event.edit("⚠️ **Syntax Error:** Use `!setreply trigger | Your long message here`")

            elif cmd_name == "delreply":
                if args.lower() in bot_data["triggers"]:
                    del bot_data["triggers"][args.lower()]
                    save_data(bot_data)
                    await event.edit(f"🗑 **Trigger deleted:** `{args}`")

            elif cmd_name == "setafk":
                afk_status["is_afk"] = True
                if args:
                    bot_data["afk_msg"] = args
                    save_data(bot_data)
                await event.edit(f"💤 **AFK Mode Enabled.**\n**Message:**\n{bot_data['afk_msg']}")

            elif cmd_name == "purge":
                if not event.is_reply:
                    return await event.edit("⚠️ Reply to a message to purge from there.")
                rep = await event.get_reply_message()
                messages_to_delete = []
                async for m in client.iter_messages(event.chat_id, min_id=rep.id - 1):
                    messages_to_delete.append(m.id)
                    if len(messages_to_delete) >= 100:  # Delete in chunks to avoid flood
                        await client.delete_messages(event.chat_id, messages_to_delete)
                        messages_to_delete = []
                if messages_to_delete:
                    await client.delete_messages(event.chat_id, messages_to_delete)
                msg = await event.respond("🧹 **Purge Complete.**")
                await asyncio.sleep(3)
                await msg.delete()

            elif cmd_name == "userinfo":
                target = args
                if event.is_reply:
                    target = (await event.get_reply_message()).sender_id
                if not target:
                    return await event.edit("⚠️ Reply to a user or provide a username/ID.")
                try:
                    user = await client.get_entity(target)
                    info = (
                        f"👤 **User Information:**\n"
                        f"**Name:** {user.first_name} {user.last_name or ''}\n"
                        f"**ID:** `{user.id}`\n"
                        f"**Username:** @{user.username if user.username else 'N/A'}\n"
                        f"**Bot:** {'Yes' if user.bot else 'No'}\n"
                        f"**Scam:** {'Yes' if user.scam else 'No'}"
                    )
                    await event.edit(info)
                except Exception as e:
                    await event.edit(f"❌ **Error fetching user:** `{e}`")

# --- Main Bootstrapper ---
async def main():
    if not RAW_SESSION:
        print("[-] ERROR: STRING_SESSION is missing.")
        return

    print("[+] Initializing Engine...")
    client = TelegramClient(StringSession(RAW_SESSION), API_ID, API_HASH)
    
    await client.connect()
    if not await client.is_user_authorized():
        print("[-] ERROR: Invalid String Session.")
        return
        
    me = await client.get_me()
    register_handlers(client, me)
    print(f"[+] Userbot Online as: {me.first_name}")
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
            
