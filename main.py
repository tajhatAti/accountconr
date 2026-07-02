import os, asyncio, threading, time, json, re, base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator

API_ID       = int(os.environ.get("API_ID", 0))
API_HASH     = os.environ.get("API_HASH", "")
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
OWNER_ID     = int(os.environ.get("OWNER_ID", 0))
RAW_SESSIONS = os.environ.get("STRING_SESSIONS", "")
DB_FILE      = "data.json"

start_time  = time.time()
login_temp  = {"phone": None, "client": None}
USER_STATES = {}
COOLDOWNS   = {}
COOLDOWN_TIME = 10

MORSE = {'A':'.-','B':'-...','C':'-.-.','D':'-..','E':'.','F':'..-.','G':'--.','H':'....','I':'..','J':'.---','K':'-.-','L':'.-..','M':'--','N':'-.','O':'---','P':'.--.','Q':'--.-','R':'.-.','S':'...','T':'-','U':'..-','V':'...-','W':'.--','X':'-..-','Y':'-.--','Z':'--..'}

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE) as f: return json.load(f)
        except: pass
    return {"public_cmds": ["ping","alive","id","help"], "banned": [], "triggers": {}, "afk_msg": "I'm away right now."}

def save_db():
    with open(DB_FILE, "w") as f: json.dump(db, f, indent=2)

db = load_db()

def uptime():
    s = int(time.time() - start_time)
    h, s = divmod(s, 3600); m, s = divmod(s, 60)
    return f"{h}h {m}m {s}s"

class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type","text/plain"); self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

def run_server():
    HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), _H).serve_forever()

def setup_controller(bot):

    @bot.on(events.NewMessage(pattern='/start'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        await e.reply(
            "**Controller online.**\n\n"
            "Send a phone number (`+880...`) to add an account.\n"
            "Type `/help` for all commands."
        )

    @bot.on(events.NewMessage(pattern='/help'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        await e.reply(
            "**Controller Commands**\n\n"
            "`/list` — show all active sessions\n"
            "`/stats` — session count + uptime\n"
            "`/ping_all` — ping every session\n"
            "`/broadcast <text>` — send to all Saved Messages\n"
            "`/afk_all <reason>` — set all accounts AFK\n"
            "`/unafk_all` — disable AFK for all\n"
            "`/bio_all <text>` — change bio for all accounts\n"
            "`/name_all <name>` — change first name for all\n"
            "`/backup_sessions` — export all session strings as file\n"
            "`/session_count` — total connected count\n"
            "`/terminate_all` — disconnect all sessions\n"
            "`/clean_cache` — flush memory\n"
            "`/uptime` — bot uptime\n"
            "`/myid` — your Telegram ID\n"
            "`/reset` — clear pending login state"
        )

    @bot.on(events.NewMessage(pattern='/list'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        if not USER_STATES: return await e.reply("No active sessions.")
        lines = "\n".join(
            f"{i}. **{d['name']}** (`{uid}`) — {'AFK' if d['is_afk'] else 'Online'}"
            for i,(uid,d) in enumerate(USER_STATES.items(),1)
        )
        await e.reply(f"**Sessions ({len(USER_STATES)})**\n\n{lines}")

    @bot.on(events.NewMessage(pattern='/stats'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        await e.reply(f"**Sessions:** `{len(USER_STATES)}`\n**Uptime:** `{uptime()}`")

    @bot.on(events.NewMessage(pattern='/reset'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        login_temp["phone"] = None
        if login_temp["client"]:
            try: await login_temp["client"].disconnect()
            except: pass
        await e.reply("Login state cleared.")

    @bot.on(events.NewMessage(pattern=r'/broadcast (.+)'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        txt = e.pattern_match.group(1); ok = 0
        for d in USER_STATES.values():
            try: await d["client"].send_message("me", txt); ok += 1
            except: pass
        await e.reply(f"Sent to {ok} account(s).")

    @bot.on(events.NewMessage(pattern=r'/afk_all (.+)'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        r = e.pattern_match.group(1)
        for d in USER_STATES.values(): d["is_afk"] = True; d["reason"] = r
        await e.reply(f"All accounts set to AFK.\nReason: {r}")

    @bot.on(events.NewMessage(pattern='/unafk_all'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        for d in USER_STATES.values(): d["is_afk"] = False
        await e.reply("All accounts back online.")

    @bot.on(events.NewMessage(pattern=r'/bio_all (.+)'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        bio = e.pattern_match.group(1); ok = 0
        for d in USER_STATES.values():
            try: await d["client"](UpdateProfileRequest(about=bio)); ok += 1
            except: pass
        await e.reply(f"Bio updated for {ok} account(s).")

    @bot.on(events.NewMessage(pattern=r'/name_all (.+)'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        name = e.pattern_match.group(1); ok = 0
        for d in USER_STATES.values():
            try: await d["client"](UpdateProfileRequest(first_name=name)); ok += 1
            except: pass
        await e.reply(f"Name updated for {ok} account(s).")

    @bot.on(events.NewMessage(pattern='/ping_all'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        lines = []
        for d in USER_STATES.values():
            t = time.time()
            try:
                await d["client"].get_me()
                lines.append(f"• {d['name']}: `{(time.time()-t)*1000:.0f}ms`")
            except: lines.append(f"• {d['name']}: offline")
        await e.reply("**Ping**\n\n" + "\n".join(lines) if lines else "No sessions.")

    @bot.on(events.NewMessage(pattern='/session_count'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        await e.reply(f"Active sessions: `{len(USER_STATES)}`")

    @bot.on(events.NewMessage(pattern='/backup_sessions'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        if not USER_STATES: return await e.reply("No sessions.")
        lines = []
        for uid, d in USER_STATES.items():
            try: lines.append(f"# {d['name']} ({uid})\n{d['client'].session.save()}")
            except: pass
        path = "/tmp/sessions.txt"
        with open(path, "w") as f: f.write("\n\n".join(lines))
        await bot.send_file(e.chat_id, path, caption="Session backup")

    @bot.on(events.NewMessage(pattern='/terminate_all'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        n = 0
        for uid, d in list(USER_STATES.items()):
            try: await d["client"].disconnect(); n += 1
            except: pass
        USER_STATES.clear()
        await e.reply(f"Disconnected {n} session(s).")

    @bot.on(events.NewMessage(pattern='/clean_cache'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        import gc; gc.collect()
        await e.reply("Cache cleared.")

    @bot.on(events.NewMessage(pattern='/uptime'))
    async def _(e):
        if e.sender_id != OWNER_ID: return
        await e.reply(f"Uptime: `{uptime()}`")

    @bot.on(events.NewMessage(pattern='/myid'))
    async def _(e):
        await e.reply(f"Your ID: `{e.sender_id}`")

    @bot.on(events.NewMessage)
    async def _(e):
        if e.sender_id != OWNER_ID or not e.text or e.text.startswith('/'): return
        text = e.text.strip()

        if text.startswith('+') and not login_temp["phone"]:
            login_temp["phone"] = text
            await e.reply("Sending OTP...")
            try:
                login_temp["client"] = TelegramClient(StringSession(), API_ID, API_HASH)
                await login_temp["client"].connect()
                await login_temp["client"].send_code_request(login_temp["phone"])
                await e.reply("Code sent. Reply: `code 12345`")
            except Exception as ex:
                login_temp["phone"] = None
                await e.reply(f"Error: {ex}")

        elif text.startswith('code ') and login_temp["phone"]:
            try:
                await login_temp["client"].sign_in(login_temp["phone"], text.split()[1])
                await _finalize(e)
            except SessionPasswordNeededError:
                await e.reply("2FA enabled. Reply: `pass your_password`")
            except Exception as ex:
                login_temp["phone"] = None
                await e.reply(f"Error: {ex}")

        elif text.startswith('pass ') and login_temp["phone"]:
            try:
                await login_temp["client"].sign_in(password=text[5:].strip())
                await _finalize(e)
            except Exception as ex:
                await e.reply(f"Wrong password: {ex}")

async def _finalize(e):
    me  = await login_temp["client"].get_me()
    ss  = login_temp["client"].session.save()
    register_userbot(login_temp["client"], me)
    base = (RAW_SESSIONS + "," if RAW_SESSIONS else "") + ss
    await e.reply(
        f"**Logged in as {me.first_name}**\n\n"
        f"Update `STRING_SESSIONS` in Render with:\n`{base}`"
    )
    login_temp["phone"] = None

def register_userbot(client, me):
    uid   = me.id
    notes = {}
    USER_STATES[uid] = {"is_afk": False, "reason": "", "client": client, "name": me.first_name}

    def is_owner(e): return e.sender_id == uid
    def allowed(e, cmd):
        if e.sender_id == uid: return True
        if e.sender_id in db["banned"]: return False
        return cmd in db["public_cmds"]

    async def auto_delete(msg, delay=10):
        await asyncio.sleep(delay)
        try: await msg.delete()
        except: pass

    # ── HELP ─────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.help$'))
    async def _(e):
        await e.edit(
            f"**{me.first_name} — Commands**\n\n"
            "**Info**\n"
            "`.ping` `.alive` `.id` `.chatid` `.myinfo` `.userinfo` `.sysinfo`\n\n"
            "**Profile**\n"
            "`.bio <text>` `.name <text>` `.lastname <text>` `.username <text>`\n"
            "`.delpfp` `.setpfp` (reply to photo)\n\n"
            "**Messages**\n"
            "`.del` `.pin` `.unpin` `.read` `.echo <text>`\n"
            "`.frwd <@user>` `.save` `.purge` `.count`\n\n"
            "**Text Styles** (reply to a message)\n"
            "`.bold` `.italic` `.mono` `.strike` `.underline`\n"
            "`.rev` `.upper` `.lower` `.mock` `.binary` `.hex` `.b64` `.morse` `.vapor`\n\n"
            "**Utilities**\n"
            "`.calc <expr>` `.tr <lang>` `.remind <sec> <text>`\n\n"
            "**Notes**\n"
            "`.note <key> <text>` `.getnote <key>` `.notes` `.delnote <key>`\n\n"
            "**Animations**\n"
            "`.type <text>` `.loading` `.clock` `.heart` `.progress`\n\n"
            "**Moderation** (group admin only)\n"
            "`.kick` `.ban` `.mute <Xd/h/m>` `.unban` `.unmute`\n\n"
            "**AFK**\n"
            "`.afk <reason>` — enable (send any message to disable)\n\n"
            "**Owner Config**\n"
            "`!addcmd <cmd>` — make command public\n"
            "`!remcmd <cmd>` — remove from public\n"
            "`!ban` / `!unban` (reply) — ban/unban user\n"
            "`!banlist` — show banned users\n"
            "`!pubcmds` — show public commands\n"
            "`!setreply <trigger> | <response>` — auto-reply trigger\n"
            "`!delreply <trigger>` — remove trigger\n"
            "`!triggers` — list all triggers\n"
            "`!setafk <message>` — custom AFK message"
        )

    # ── PING (fixed — separate DM vs group latency) ───────────────────────────
    @client.on(events.NewMessage(pattern=r'(?i)^[.!\/]?ping(?:@\w+)?$'))
async def _(e):
    if not allowed(e, "ping"): return
    t1 = time.time()
    m = await e.reply("`...`")
    rtt = (time.time() - t1) * 1000
    status = "🟢" if rtt < 300 else ("🟡" if rtt < 800 else "🔴")
    await m.edit(f"**Ping:** `{rtt:.1f}ms` {status}\n**Uptime:** `{uptime()}`")
    if not is_owner(e):
        asyncio.create_task(auto_delete(m, 10))
        try: asyncio.create_task(auto_delete(e, 10))
        except: pass
    # ── ALIVE ─────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(pattern=r'(?i)^[.!]?alive$'))
    async def _(e):
        if not allowed(e, "alive"): return
        msg = f"**Status:** Online\n**Account:** {me.first_name}\n**Uptime:** `{uptime()}`"
        m = await e.reply(msg) if not is_owner(e) else await e.edit(msg)
        if not is_owner(e): asyncio.create_task(auto_delete(m, 10))

    # ── ID ────────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(pattern=r'(?i)^[.!]?id$'))
    async def _(e):
        if not allowed(e, "id"): return
        msg = f"**User ID:** `{e.sender_id}`\n**Chat ID:** `{e.chat_id}`"
        if e.is_reply:
            r = await e.get_reply_message()
            msg += f"\n**Target ID:** `{r.sender_id}`"
        m = await e.reply(msg) if not is_owner(e) else await e.edit(msg)
        if not is_owner(e): asyncio.create_task(auto_delete(m, 10))

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.chatid$'))
    async def _(e): await e.edit(f"**Chat ID:** `{e.chat_id}`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.myinfo$'))
    async def _(e):
        full = await client(GetFullUserRequest(uid))
        bio  = getattr(full.full_user, 'about', None) or "—"
        await e.edit(
            f"**My Info**\n"
            f"Name: {me.first_name} {me.last_name or ''}\n"
            f"Username: @{me.username or '—'}\n"
            f"ID: `{uid}`\n"
            f"Bio: {bio}"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.userinfo$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message.")
        r = await e.get_reply_message()
        u = await client.get_entity(r.sender_id)
        await e.edit(
            f"**User Info**\n"
            f"Name: {getattr(u,'first_name','') or ''} {getattr(u,'last_name','') or ''}\n"
            f"Username: @{getattr(u,'username',None) or '—'}\n"
            f"ID: `{u.id}`\n"
            f"Bot: {'Yes' if getattr(u,'bot',False) else 'No'}\n"
            f"Scam: {'Yes' if getattr(u,'scam',False) else 'No'}"
        )

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.sysinfo$'))
    async def _(e):
        try:
            import psutil
            ram = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            await e.edit(
                f"**System Info**\n"
                f"CPU: `{cpu}%`\n"
                f"RAM: `{ram.percent}%` of `{ram.total//1024//1024}MB`\n"
                f"Sessions: `{len(USER_STATES)}`\n"
                f"Uptime: `{uptime()}`"
            )
        except:
            await e.edit(f"Sessions: `{len(USER_STATES)}`\nUptime: `{uptime()}`")

    # ── PROFILE ───────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.bio (.+)'))
    async def _(e):
        try: await client(UpdateProfileRequest(about=e.pattern_match.group(1))); await e.edit("Bio updated.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.name (.+)'))
    async def _(e):
        try: await client(UpdateProfileRequest(first_name=e.pattern_match.group(1))); await e.edit("First name updated.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.lastname (.+)'))
    async def _(e):
        try: await client(UpdateProfileRequest(last_name=e.pattern_match.group(1))); await e.edit("Last name updated.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.username (.+)'))
    async def _(e):
        try: await client(UpdateUsernameRequest(e.pattern_match.group(1).strip())); await e.edit("Username updated.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.delpfp$'))
    async def _(e):
        try:
            p = await client.get_profile_photos("me")
            if p: await client.delete_profile_photos(p[0])
            await e.edit("Profile photo removed.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.setpfp$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a photo.")
        r = await e.get_reply_message()
        if not r.photo: return await e.edit("That's not a photo.")
        path = await r.download_media()
        file = await client.upload_file(path)
        await client(UploadProfilePhotoRequest(file=file))
        await e.edit("Profile photo updated.")

    # ── MESSAGES ──────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.del$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message.")
        await (await e.get_reply_message()).delete(); await e.delete()

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.pin$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message.")
        await client.pin_message(e.chat_id, (await e.get_reply_message()).id, notify=False)
        await e.edit("Pinned.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.unpin$'))
    async def _(e):
        await client.unpin_message(e.chat_id); await e.edit("Unpinned.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.read$'))
    async def _(e):
        await client.send_read_acknowledge(e.chat_id); await e.delete()

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.echo (.+)'))
    async def _(e):
        txt = e.pattern_match.group(1); await e.delete()
        await client.send_message(e.chat_id, txt)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.frwd (.+)'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message.")
        r = await e.get_reply_message()
        try:
            await client.forward_messages(e.pattern_match.group(1).strip(), r)
            await e.edit("Forwarded.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.save$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message.")
        await client.send_message("me", await e.get_reply_message())
        await e.edit("Saved.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.purge$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message.")
        rep = await e.get_reply_message(); ids = []
        async for m in client.iter_messages(e.chat_id, min_id=rep.id - 1):
            ids.append(m.id)
            if len(ids) >= 100: await client.delete_messages(e.chat_id, ids); ids = []
        if ids: await client.delete_messages(e.chat_id, ids)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.count$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message.")
        txt = (await e.get_reply_message()).text or ""
        await e.edit(f"Characters: `{len(txt)}`\nWords: `{len(txt.split())}`\nLines: `{txt.count(chr(10))+1}`")

    # ── TEXT STYLES ───────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.(bold|italic|mono|strike|underline|rev|upper|lower|mock|binary|hex|b64|morse|vapor)$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a text message.")
        orig = (await e.get_reply_message()).text or ""
        if not orig: return await e.edit("No text found.")
        cmd = e.pattern_match.group(1)
        if   cmd=="bold":      out=f"**{orig}**"
        elif cmd=="italic":    out=f"__{orig}__"
        elif cmd=="mono":      out=f"`{orig}`"
        elif cmd=="strike":    out=f"~~{orig}~~"
        elif cmd=="underline": out=f"<u>{orig}</u>"
        elif cmd=="rev":       out=orig[::-1]
        elif cmd=="upper":     out=orig.upper()
        elif cmd=="lower":     out=orig.lower()
        elif cmd=="mock":      out="".join(c.upper() if i%2==0 else c.lower() for i,c in enumerate(orig))
        elif cmd=="binary":    out=" ".join(format(ord(c),'b') for c in orig)
        elif cmd=="hex":       out=orig.encode().hex()
        elif cmd=="b64":       out=base64.b64encode(orig.encode()).decode()
        elif cmd=="morse":     out=" ".join(MORSE.get(c.upper(),c) for c in orig)
        elif cmd=="vapor":     out=" ".join(orig)
        else:                  out=orig
        await e.edit(out)

    # ── UTILITIES ─────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.calc (.+)'))
    async def _(e):
        expr = e.pattern_match.group(1)
        if not re.fullmatch(r'[\d\s\.\+\-\*\/\(\)]+', expr):
            return await e.edit("Only numbers and `+ - * / ( )` allowed.")
        try:   await e.edit(f"`{expr} = {eval(expr, {'__builtins__':{}})}`")
        except: await e.edit("Invalid expression.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.tr (\S+)$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a message. e.g. `.tr bn`")
        lang = e.pattern_match.group(1)
        txt  = (await e.get_reply_message()).text or ""
        if not txt: return await e.edit("No text to translate.")
        try:
            result = GoogleTranslator(source='auto', target=lang).translate(txt)
            await e.edit(f"**Translation ({lang}):**\n{result}")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.remind (\d+) (.+)'))
    async def _(e):
        secs=int(e.pattern_match.group(1)); txt=e.pattern_match.group(2)
        await e.edit(f"Reminder set for {secs}s.")
        async def _t():
            await asyncio.sleep(secs)
            await client.send_message(e.chat_id, f"**Reminder:** {txt}")
        asyncio.create_task(_t())

    # ── NOTES ─────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.note (\S+) (.+)'))
    async def _(e):
        k,v=e.pattern_match.group(1),e.pattern_match.group(2)
        notes[k]=v; await e.edit(f"Note saved: `{k}`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.getnote (\S+)'))
    async def _(e):
        k=e.pattern_match.group(1)
        await e.edit(f"**{k}:**\n{notes[k]}" if k in notes else f"No note named `{k}`.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.notes$'))
    async def _(e):
        await e.edit("**Notes:**\n"+"".join(f"• `{k}`\n" for k in notes) if notes else "No notes saved.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.delnote (\S+)'))
    async def _(e):
        k=e.pattern_match.group(1)
        if k in notes: del notes[k]; await e.edit(f"Deleted `{k}`.")
        else: await e.edit(f"No note named `{k}`.")

    # ── ANIMATIONS ────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.type (.+)'))
    async def _(e):
        txt=e.pattern_match.group(1); buf=""
        for ch in txt:
            buf+=ch; await e.edit(buf+"▌"); await asyncio.sleep(0.07)
        await e.edit(buf)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.loading$'))
    async def _(e):
        for p in [0,20,45,70,90,100]:
            bar="█"*(p//10)+"░"*(10-p//10)
            await e.edit(f"`[{bar}] {p}%`"); await asyncio.sleep(0.25)
        await e.edit("Done.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.clock$'))
    async def _(e):
        for em in ["🕐","🕑","🕒","🕓","🕔","🕕","🕖","🕗","🕘","🕙","🕚","🕛"]:
            await e.edit(em); await asyncio.sleep(0.15)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.heart$'))
    async def _(e):
        for h in ["🤍","❤️","🧡","💛","💚","💙","💜","❤️"]:
            await e.edit(h); await asyncio.sleep(0.18)

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.progress$'))
    async def _(e):
        for i in range(11):
            await e.edit(f"`{'▓'*i}{'░'*(10-i)} {i*10}%`"); await asyncio.sleep(0.12)

    # ── MODERATION ────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.kick$'))
    async def _(e):
        if e.is_private or not e.is_reply: return await e.edit("Group only. Reply to a user.")
        try:
            await client.kick_participant(e.chat_id, (await e.get_reply_message()).sender_id)
            await e.edit("Kicked.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.ban$'))
    async def _(e):
        if e.is_private or not e.is_reply: return await e.edit("Group only. Reply to a user.")
        try:
            await client.edit_permissions(e.chat_id, (await e.get_reply_message()).sender_id, view_messages=False)
            await e.edit("Banned.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.mute (\d+)([dhm])$'))
    async def _(e):
        if e.is_private or not e.is_reply: return await e.edit("Group only. Reply to a user.")
        amount=int(e.pattern_match.group(1)); unit=e.pattern_match.group(2)
        delta = {"d":timedelta(days=amount),"h":timedelta(hours=amount),"m":timedelta(minutes=amount)}[unit]
        rights = ChatBannedRights(until_date=datetime.now()+delta, send_messages=True)
        try:
            await client(EditBannedRequest(e.chat_id,(await e.get_reply_message()).sender_id,rights))
            await e.edit(f"Muted for {amount}{unit}.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    @client.on(events.NewMessage(outgoing=True, pattern=r'\.(unban|unmute)$'))
    async def _(e):
        if e.is_private or not e.is_reply: return await e.edit("Group only. Reply to a user.")
        try:
            await client.edit_permissions(e.chat_id,(await e.get_reply_message()).sender_id,view_messages=True,send_messages=True)
            await e.edit("Restrictions removed.")
        except Exception as ex: await e.edit(f"Error: {ex}")

    # ── AFK ───────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'\.afk(?: |$)(.*)'))
    async def _(e):
        reason = e.pattern_match.group(1).strip() or db["afk_msg"]
        USER_STATES[uid]["is_afk"] = True; USER_STATES[uid]["reason"] = reason
        await e.edit(f"AFK enabled.\n{reason}")

    # ── OWNER CONFIG ──────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r'!addcmd (.+)'))
    async def _(e):
        cmd=e.pattern_match.group(1).lower().strip()
        if cmd not in db["public_cmds"]: db["public_cmds"].append(cmd); save_db()
        await e.edit(f"`{cmd}` is now public.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!remcmd (.+)'))
    async def _(e):
        cmd=e.pattern_match.group(1).lower().strip()
        if cmd in db["public_cmds"]: db["public_cmds"].remove(cmd); save_db()
        await e.edit(f"`{cmd}` removed from public.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!pubcmds$'))
    async def _(e):
        cmds = db["public_cmds"]
        await e.edit("**Public Commands:**\n" + "\n".join(f"• `{c}`" for c in cmds) if cmds else "No public commands set.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!ban$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a user.")
        tid=(await e.get_reply_message()).sender_id
        if tid not in db["banned"]: db["banned"].append(tid); save_db()
        await e.edit(f"User `{tid}` banned.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!unban$'))
    async def _(e):
        if not e.is_reply: return await e.edit("Reply to a user.")
        tid=(await e.get_reply_message()).sender_id
        if tid in db["banned"]: db["banned"].remove(tid); save_db()
        await e.edit(f"User `{tid}` unbanned.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!banlist$'))
    async def _(e):
        if not db["banned"]: return await e.edit("No banned users.")
        await e.edit("**Banned Users:**\n" + "\n".join(f"• `{i}`" for i in db["banned"]))

    @client.on(events.NewMessage(outgoing=True, pattern=r'!setreply (.+?)\s*\|\s*(.+)'))
    async def _(e):
        t=e.pattern_match.group(1).lower().strip(); r=e.pattern_match.group(2).strip()
        db["triggers"][t]=r; save_db()
        await e.edit(f"Trigger set: `{t}`")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!delreply (.+)'))
    async def _(e):
        t=e.pattern_match.group(1).lower().strip()
        if t in db["triggers"]: del db["triggers"][t]; save_db(); await e.edit(f"Trigger `{t}` deleted.")
        else: await e.edit("Trigger not found.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'!triggers$'))
    async def _(e):
        if not db["triggers"]: return await e.edit("No triggers set.")
        await e.edit("**Triggers:**\n" + "\n".join(f"• `{k}` → {v}" for k,v in db["triggers"].items()))

    @client.on(events.NewMessage(outgoing=True, pattern=r'!setafk (.+)'))
    async def _(e):
        db["afk_msg"]=e.pattern_match.group(1); save_db()
        USER_STATES[uid]["is_afk"]=True; USER_STATES[uid]["reason"]=db["afk_msg"]
        await e.edit("AFK enabled with custom message.")

    # ── INCOMING HANDLER (AFK + triggers + public cmd cooldown) ───────────────
    @client.on(events.NewMessage(incoming=True))
    async def _(e):
        if not e.text: return
        sid = e.sender_id
        if sid in db["banned"]: return

        lower = e.text.lower()
        for trigger, response in db["triggers"].items():
            if trigger in lower:
                await e.reply(response); return

        st = USER_STATES.get(uid)
        if st and st["is_afk"] and sid != uid:
            sender = await e.get_sender()
            if sender and getattr(sender,'bot',False): return
            if e.is_private or e.mentioned:
                await e.reply(st["reason"])

    @client.on(events.NewMessage(outgoing=True))
    async def _(e):
        st = USER_STATES.get(uid)
        if st and st["is_afk"]:
            if e.text and (e.text.startswith('!setafk') or e.text.startswith('.afk')): return
            st["is_afk"] = False
            m = await e.respond("Back online."); await asyncio.sleep(2); await m.delete()

async def main():
    threading.Thread(target=run_server, daemon=True).start()
    bot = TelegramClient('controller', API_ID, API_HASH)
    setup_controller(bot)
    await bot.start(bot_token=BOT_TOKEN)
    print("[+] Controller online.")

    if RAW_SESSIONS:
        for s in [x.strip() for x in RAW_SESSIONS.split(",") if x.strip()]:
            try:
                cl = TelegramClient(StringSession(s), API_ID, API_HASH)
                await cl.connect()
                if await cl.is_user_authorized():
                    me = await cl.get_me()
                    register_userbot(cl, me)
                    print(f"[+] {me.first_name}")
            except Exception as ex: print(f"[-] {ex}")

    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
