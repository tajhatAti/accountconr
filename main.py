import os
import asyncio
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# --- কনফিগারেশন ---
API_ID = 37109385  # তোর API ID
API_HASH = "b50a9ccaf4a0352b895a9fb2998c7f0d"  # তোর API Hash
BOT_TOKEN = "8819790088:AAFHfaPUMYkD32DV9CbDiF80q_6RuKeJT1A"  # গেটওয়ে বটের টোকেন
OWNER_ID = 8768764605 # তোর পার্সোনাল আইডি

# গলোবাল স্টেট
phone_number = None
user_logged_in = False
start_time = time.time()
is_afk = False
afk_reason = ""

# রেন্ডার ওয়েব সার্ভার
class RenderServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Gateway Status: Stable")
    def log_message(self, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), RenderServer).serve_forever()

bot_client = TelegramClient('helper_bot', API_ID, API_HASH)
user_client = TelegramClient('user_session', API_ID, API_HASH)

# ==========================================
#  লগইন গেটওয়ে ও স্টেট ম্যানেজমেন্ট
# ==========================================

@bot_client.on(events.NewMessage(pattern='/start'))
async def bot_start(event):
    if event.sender_id != OWNER_ID: return
    await event.reply("📱 তোর পার্সোনাল ইউজারবট লগইন করতে তোর ফোন নাম্বারটি আন্তর্জাতিক ফরম্যাটে পাঠা।\nযেমন: `+88017XXXXXXXX`")

# 🛠️ নতুন এমার্জেন্সি রিসেট কমান্ড (কখনো আটকে গেলে এটি দিবি)
@bot_client.on(events.NewMessage(pattern='/reset'))
async def bot_reset(event):
    global phone_number, user_logged_in
    if event.sender_id != OWNER_ID: return
    phone_number = None
    user_logged_in = False
    try:
        await user_client.disconnect()
    except:
        pass
    await event.reply("🔄 বটের সব মেমোরি ও স্টেট রিসেট করা হয়েছে! এখন আবার নতুন করে নাম্বার পাঠাতে পারিস।")

@bot_client.on(events.NewMessage)
async def handle_login(event):
    global phone_number, user_logged_in
    if event.sender_id != OWNER_ID or event.text.startswith('/start') or event.text.startswith('/reset') or user_logged_in:
        return

    text = event.text.strip()

    # ফোন নাম্বার প্রসেসিং
    if text.startswith('+') and phone_number is None:
        phone_number = text
        await event.reply("⏳ টেলিগ্রাম সার্ভারে ওটিপি (OTP) রিকোয়েস্ট পাঠানো হচ্ছে...")
        try:
            await user_client.connect()
            await user_client.send_code_request(phone_number)
            await event.reply("📩 তোর অফিশিয়াল টেলিগ্রাম অ্যাপে কোড গেছে। কোডটি এভাবে পাঠা:\n`code 12345` (অবশ্যই code লিখে স্পেস দিবি)")
        except Exception as e:
            phone_number = None  # ফেইল হলে স্টেট রিসেট
            await event.reply(f"❌ ওটিপি পাঠাতে ব্যর্থ। এরর: {e}\n\n🔄 রিসেট হয়েছে। আবার ট্রাই কর।")
    
    # ওটিপি প্রসেসিং
    elif text.startswith('code ') and phone_number is not None:
        otp_code = text.split(' ')[1]
        await event.reply("⚙️ লগইন ভেরিফিকেশন চলছে...")
        try:
            await user_client.sign_in(phone_number, otp_code)
            user_logged_in = True
            await event.reply("🎉 লগইন সফল! ইউজারবট এখন ব্যাকগ্রাউন্ডে রেডি।")
            
            # সেভড মেসেজে স্ট্রিং সেশন ব্যাকআপ
            string_session = user_client.session.save()
            await user_client.send_message("me", f"💾 **রেন্ডার ব্যাকআপ স্ট্রিং সেশন:**\n\n`{string_session}`")
            
            asyncio.get_event_loop().create_task(start_userbot_handlers())
            
        except SessionPasswordNeededError:
            await event.reply("🔐 ২-স্টেপ ভেরিফিকেশন অন আছে। পাসওয়ার্ডটি এভাবে পাঠা:\n`pass তোর_পাসওয়ার্ড`")
        except Exception as e:
            phone_number = None  # 🛠️ ফিক্স: কোড এক্সপায়ার বা ভুল হলে স্টেট রিসেট হবে
            await event.reply(f"❌ লগইন ব্যর্থ। এরর: {e}\n\n🔄 মেমোরি ক্লিয়ার করা হয়েছে। আবার ফোন নাম্বার (`+880...`) পাঠিয়ে শুরু কর।")

    # পাসওয়ার্ড প্রসেসিং
    elif text.startswith('pass ') and phone_number is not None:
        pwd = text.replace('pass ', '').strip()
        try:
            await user_client.sign_in(password=pwd)
            user_logged_in = True
            await event.reply("🎉 টু-স্টেপ ভেরিফিকেশন সফল!")
            string_session = user_client.session.save()
            await user_client.send_message("me", f"💾 **ব্যাকআপ স্ট্রিং সেশন:**\n\n`{string_session}`")
            
            asyncio.get_event_loop().create_task(start_userbot_handlers())
        except Exception as e:
            phone_number = None  # ফেইল হলে স্টেট রিসেট
            await event.reply(f"❌ ভুল পাসওয়ার্ড বা এরর: {e}\n\n🔄 রিসেট হয়েছে। আবার নাম্বার পাঠা।")

# ==========================================
#  ইউজারবট ফিচার হ্যান্ডলার (তোর অ্যাকাউন্ট কমান্ড)
# ==========================================
async def start_userbot_handlers():
    print("[+] Userbot Active!")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.alive'))
    async def alive(event):
        uptime = int(time.time() - start_time)
        await event.edit(f"⚡ **ইউজারবট সচল আছে!**\n⏱️ আপটাইম: `{uptime}s`")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.ping'))
    async def ping(event):
        t1 = time.time()
        await event.edit("`Ping...`")
        t2 = time.time()
        await event.edit(f"🎯 **Pong!**\n⏱️ `{(t2 - t1) * 1000:.2f}ms`")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.afk(?: |$)(.*)'))
    async def set_afk(event):
        global is_afk, afk_reason
        is_afk = True
        afk_reason = event.pattern_match.group(1) or "এখন ব্যস্ত আছি।"
        await event.edit(f"💤 **AFK মোড চালু হলো।**\nকারণ: {afk_reason}")

    @user_client.on(events.NewMessage(outgoing=True))
    async def auto_unafk(event):
        global is_afk
        if is_afk and not event.text.startswith('.afk'):
            is_afk = False
            m = await event.respond("⚡ **আমি লাইনে ফিরেছি, AFK অফ করা হলো।**")
            await asyncio.sleep(2)
            await m.delete()

    @user_client.on(events.NewMessage(incoming=True, private=True))
    async def afk_reply(event):
        global is_afk, afk_reason
        if is_afk:
            await event.reply(f"🤖 **অটো-মেসেজ:** আমি এখন ব্যস্ত।\n📝 কারণ: {afk_reason}")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.bio (.*)'))
    async def change_bio(event):
        from telethon.tl.functions.account import UpdateProfileRequest
        new_bio = event.pattern_match.group(1)
        try:
            await user_client(UpdateProfileRequest(about=new_bio))
            await event.edit(f"✅ বায়ো আপডেট করা হয়েছে: `{new_bio}`")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.save'))
    async def save_msg(event):
        if not event.is_reply: return await event.edit("❌ মেসেজে রিপ্লাই কর।")
        reply = await event.get_reply_message()
        await user_client.send_message("me", reply)
        await event.edit("💾 **Saved Messages-এ রাখা হলো।**")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.frwd (.*)'))
    async def forward(event):
        if not event.is_reply: return await event.edit("❌ মেসেজে reply কর।")
        target = event.pattern_match.group(1)
        reply = await event.get_reply_message()
        try:
            await user_client.forward_messages(target, reply)
            await event.edit(f"⏩ {target}-এ পাঠানো হয়েছে।")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.id'))
    async def get_id(event):
        await event.edit(f"👤 তোর আইডি: `{event.sender_id}`\n📍 চ্যাট আইডি: `{event.chat_id}`")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r'\.info'))
    async def get_info(event):
        if not event.is_reply: return await event.edit("❌ কোনো ইউজারের মেসেজে রিপ্লাই কর।")
        from telethon.tl.functions.users import GetFullUserRequest
        reply = await event.get_reply_message()
        try:
            full = await user_client(GetFullUserRequest(reply.sender_id))
            await event.edit(f"📋 **নাম:** {full.users[0].first_name}\n🆔 **আইডি:** `{full.users[0].id}`\n📝 **বায়ো:** {full.about}")
        except Exception as e: await event.edit(f"❌ এরর: {e}")

# ==========================================
#  রানিং লুপ
# ==========================================
async def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    print("[+] Starting Helper Bot...")
    await bot_client.start(bot_token=BOT_TOKEN)
    
    await user_client.connect()
    if await user_client.is_user_authorized():
        global user_logged_in
        user_logged_in = True
        asyncio.get_event_loop().create_task(start_userbot_handlers())
        print("[+] Auto-Logged In!")

    await bot_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
            
