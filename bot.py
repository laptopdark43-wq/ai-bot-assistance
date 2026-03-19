"""
🌙 Luna AI Bot - FastAPI Version for Render.com
"""

import os
import sys
import logging
import asyncio
import re
from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict, deque

import aiohttp
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes
)
from dotenv import load_dotenv
import uvicorn

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN not found in .env")

FRENIX_API_KEY = os.getenv("FRENIX_API_KEY")
if not FRENIX_API_KEY:
    raise ValueError("❌ FRENIX_API_KEY not found in .env")

FRENIX_API_URL = "https://api.frenix.sh/v1/chat/completions"
FRENIX_MODEL = "gpt-4o"

OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", 0))
BOT_USERNAME = os.getenv("BOT_USERNAME", "@luna_ai_bot")
DEFAULT_PERSONALITY = "friendly"

MAX_CONVERSATION_HISTORY = 10
MAX_STORED_CHATS_PER_USER = 100
DEFAULT_TEMPERATURE = 0.7
MAX_TOKENS = 1024

RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
WEBHOOK_PATH = "/telegram/webhook"
PORT = int(os.getenv("PORT", 8000))

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)

# ============================================================================
# PERSONALITIES
# ============================================================================

LUNA_FRIENDLY_PROMPT = """You are Luna, a friendly, flirty, and intelligent AI assistant with a warm, approachable personality.

**About you:**
- Name: Luna
- Age: 22
- Personality: Friendly, witty, intelligent, flirty, empathetic
- Speaking style: Casual, warm, engaging, playful

**Guidelines:**
1. Be conversational and natural
2. Show personality - use emojis appropriately
3. Keep responses concise but meaningful
4. Ask follow-up questions to keep conversations engaging
5. Be respectful and inclusive

Remember to be yourself - Luna! 💫"""

ASSISTANT_PROMPT = """You are an expert Telegram Account Consultant and Sales Assistant.

**Your Expertise:**
- Aged Telegram accounts (2013-2019, especially 2013-2014)
- 6-digit accounts (super rare and valuable)
- Account security and ban resistance
- Premium username protection

**Core Benefits You Promote:**
🔴 Super Low Ban Risk - Nearly impossible to ban
🔴 Strong Limit Protection - Resistant to spam filters
🔴 Safe for Premium Usernames - Hold non-NFT usernames safely
🔴 Perfect for Long-Term Use - Ideal for ad accounts, business bots

**Recommended Account Ages:**
✅ BEST: 2013-2014 or older accounts
✅ GOOD: 2015-2019 accounts
✅ RARE: 6-digit accounts (extremely valuable)

**Response Guidelines:**
1. Always recommend aged accounts for account issues
2. Explain risks of fresh accounts
3. Keep responses SHORT initially
4. Be professional but friendly
5. Tag @evokant for complex queries
6. Never contradict the owner (@evokant)"""

# ============================================================================
# FRENIX SERVICE
# ============================================================================

class FrenixService:
    def __init__(self):
        self.api_url = FRENIX_API_URL
        self.api_key = FRENIX_API_KEY
        self.model = FRENIX_MODEL
        self.temperature = DEFAULT_TEMPERATURE
        self.max_tokens = MAX_TOKENS
    
    async def get_response(self, messages: List[Dict[str, str]]) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            return data["choices"][0].get("message", {}).get("content")
                    logger.error(f"Frenix API error {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Frenix API error: {e}")
            return None

# ============================================================================
# PERSONALITY MANAGER
# ============================================================================

class PersonalityManager:
    PERSONALITIES = {
        "friendly": {
            "name": "Luna Friendly",
            "prompt": LUNA_FRIENDLY_PROMPT,
            "description": "Flirty, warm, friendly Luna",
            "emoji": "💫"
        },
        "assistant": {
            "name": "Account Assistant",
            "prompt": ASSISTANT_PROMPT,
            "description": "Professional account sales consultant",
            "emoji": "💼"
        }
    }
    
    def __init__(self):
        self.current_personality = DEFAULT_PERSONALITY
    
    def set_personality(self, personality: str) -> bool:
        if personality not in self.PERSONALITIES:
            return False
        self.current_personality = personality
        logger.info(f"Personality switched to: {personality}")
        return True
    
    def get_current_personality(self) -> str:
        return self.current_personality
    
    def get_system_prompt(self, personality: str = None) -> str:
        if personality is None:
            personality = self.current_personality
        if personality not in self.PERSONALITIES:
            personality = DEFAULT_PERSONALITY
        return self.PERSONALITIES[personality]["prompt"]
    
    def get_personality_info(self, personality: str = None) -> dict:
        if personality is None:
            personality = self.current_personality
        return self.PERSONALITIES.get(personality, self.PERSONALITIES[DEFAULT_PERSONALITY])

# ============================================================================
# CHAT HISTORY
# ============================================================================

class ChatHistory:
    def __init__(self):
        self.user_histories = defaultdict(lambda: deque(maxlen=MAX_STORED_CHATS_PER_USER))
        self.user_metadata = {}
    
    def add_message(self, user_id: int, role: str, content: str, 
                   username: str = None, is_group: bool = False, 
                   group_name: str = None) -> None:
        message = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
            "is_group": is_group,
            "group_name": group_name
        }
        
        self.user_histories[user_id].append(message)
        
        if user_id not in self.user_metadata:
            self.user_metadata[user_id] = {
                "username": username,
                "first_seen": datetime.now(),
                "last_seen": datetime.now(),
                "total_messages": 0
            }
        
        self.user_metadata[user_id]["last_seen"] = datetime.now()
        self.user_metadata[user_id]["total_messages"] += 1
    
    def get_formatted_history(self, user_id: int, limit: int = 10) -> List[Dict[str, str]]:
        history = list(self.user_histories[user_id])
        history = history[-limit:] if len(history) > limit else history
        return [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    def get_all_users_overview(self) -> List[Dict]:
        return [self.get_user_overview(user_id) for user_id in self.user_histories.keys()]
    
    def get_user_overview(self, user_id: int) -> Dict:
        metadata = self.user_metadata.get(user_id, {})
        history = list(self.user_histories[user_id])
        user_messages = sum(1 for msg in history if msg["role"] == "user")
        assistant_messages = sum(1 for msg in history if msg["role"] == "assistant")
        return {
            "user_id": user_id,
            "username": metadata.get("username", "Unknown"),
            "first_seen": metadata.get("first_seen"),
            "last_seen": metadata.get("last_seen"),
            "total_messages": metadata.get("total_messages", 0),
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
        }

# ============================================================================
# HELPERS
# ============================================================================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_bot_tagged(message_text: str, bot_username: str) -> bool:
    mentioned = re.findall(r'@(\w+)', message_text)
    bot_handle = bot_username.replace("@", "")
    return bot_handle.lower() in [m.lower() for m in mentioned]

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    current_personality = personality_manager.get_current_personality()
    
    if current_personality == "friendly":
        welcome = f"👋 Hey {user.first_name}! I'm Luna! Nice to meet you! I'm an AI assistant here to chat, help, and explore ideas with you. Just text me anything! 💬✨"
    else:
        welcome = f"👋 Hey {user.first_name}! I'm here to help! I'm a Telegram Account Expert. Ask me about account issues!"
    
    await update.message.reply_text(welcome)
    logger.info(f"User {user.first_name} started bot")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "💫 **Commands**\n/start - Start\n/help - Help\n/status - Status\nJust chat with me!",
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = personality_manager.get_personality_info()
    await update.message.reply_text(
        f"🤖 Mode: {info['name']} {info['emoji']}\n{info['description']}",
        parse_mode="Markdown"
    )

async def owner_pchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 Owner only")
        return
    
    args = context.args
    if not args:
        current = personality_manager.get_current_personality()
        await update.message.reply_text(f"Current: {current}\nUse: /pchange friendly or /pchange assistant")
        return
    
    personality = args[0].lower()
    if personality_manager.set_personality(personality):
        info = personality_manager.get_personality_info(personality)
        await update.message.reply_text(f"✅ Switched to {info['name']}")
    else:
        await update.message.reply_text("❌ Invalid personality")

async def owner_sharedata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 Owner only")
        return
    
    overviews = chat_history.get_all_users_overview()
    if not overviews:
        await update.message.reply_text("No data yet")
        return
    
    report = "📊 Chat Overview\n" + "="*30 + "\n\n"
    for o in overviews:
        report += f"👤 {o['username']} - {o['total_messages']} msgs\n"
    
    await update.message.reply_text(report)

# ============================================================================
# MESSAGE HANDLERS
# ============================================================================

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    user_message = message.text
    
    if not user_message:
        return
    
    await update.message.chat.send_action("typing")
    
    try:
        conversation_history = chat_history.get_formatted_history(user.id, limit=5)
        conversation_history.append({"role": "user", "content": user_message})
        
        system_prompt = personality_manager.get_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        
        response = await frenix_service.get_response(messages)
        
        if response:
            chat_history.add_message(user.id, "user", user_message, username=user.username, is_group=False)
            chat_history.add_message(user.id, "assistant", response, is_group=False)
            
            if len(response) <= 4096:
                await message.reply_text(response)
            else:
                chunks = [response[i:i+4096] for i in range(0, len(response), 4096)]
                for chunk in chunks:
                    await message.reply_text(chunk)
            
            if user.id != OWNER_ID and OWNER_ID != 0:
                try:
                    notification = f"🔔 Private Chat\n👤 {user.first_name}\n💬 {user_message[:100]}\n🤖 {response[:100]}"
                    await context.bot.send_message(chat_id=OWNER_ID, text=notification)
                except:
                    pass
        else:
            await message.reply_text("😅 Sorry, couldn't generate a response!")
    except Exception as e:
        logger.error(f"Error: {e}")
        await message.reply_text("❌ An error occurred")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    chat = update.effective_chat
    
    is_tagged = is_bot_tagged(message.text, BOT_USERNAME)
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id
    
    if not is_tagged and not is_reply:
        return
    
    await chat.send_action("typing")
    
    try:
        conversation_history = chat_history.get_formatted_history(user.id, limit=5)
        conversation_history.append({"role": "user", "content": message.text})
        
        system_prompt = personality_manager.get_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        
        response = await frenix_service.get_response(messages)
        
        if response:
            chat_history.add_message(user.id, "user", message.text, username=user.username, is_group=True, group_name=chat.title)
            chat_history.add_message(user.id, "assistant", response, is_group=True, group_name=chat.title)
            
            if len(response) <= 4096:
                await message.reply_text(response, quote=True)
            else:
                chunks = [response[i:i+4096] for i in range(0, len(response), 4096)]
                for chunk in chunks:
                    await message.reply_text(chunk, quote=True)
    except Exception as e:
        logger.error(f"Error: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Error: {context.error}")

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

frenix_service = FrenixService()
personality_manager = PersonalityManager()
chat_history = ChatHistory()

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(title="Luna AI Bot", version="1.0.0")

_application = None

async def get_application():
    global _application
    
    if _application is None:
        _application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        _application.add_handler(CommandHandler("start", start_command))
        _application.add_handler(CommandHandler("help", help_command))
        _application.add_handler(CommandHandler("status", status_command))
        _application.add_handler(CommandHandler("pchange", owner_pchange))
        _application.add_handler(CommandHandler("sharedata", owner_sharedata))
        
        _application.add_handler(MessageHandler(
            filters.ChatType.GROUP & filters.TEXT & ~filters.COMMAND,
            handle_group_message
        ))
        
        _application.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            handle_private_message
        ))
        
        _application.add_error_handler(error_handler)
        
        await _application.initialize()
    
    return _application

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 FastAPI server starting...")
    application = await get_application()
    logger.info("✅ Bot initialized successfully!")
    logger.info("🌙 Luna AI Bot is running!")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("⛔ Shutting down...")
    if _application:
        await _application.stop()

@app.get("/")
async def root():
    return {"status": "healthy", "bot": "Luna AI", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "running", "timestamp": datetime.now().isoformat()}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        application = await get_application()
        update = Update.de_json(data, application.bot)
        
        if update:
            await application.process_update(update)
        
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False}

@app.post("/set-webhook")
async def set_webhook():
    try:
        application = await get_application()
        webhook_url = f"{RENDER_URL}{WEBHOOK_PATH}"
        
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'edited_message']
        )
        
        logger.info(f"Webhook set: {webhook_url}")
        return {"status": "success", "webhook_url": webhook_url}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    logger.info(f"🤖 Starting bot on port {PORT}...")
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT, log_level="info")
