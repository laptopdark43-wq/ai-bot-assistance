"""
🌙 Luna AI Bot - Production Ready
Using OpenRouter API + OpenAI Library + Telegram
"""

import os
import sys
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict, deque

from openai import AsyncOpenAI
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import uvicorn

load_dotenv()

# ============================================================================
# CONFIG
# ============================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", 0))
BOT_USERNAME = os.getenv("BOT_USERNAME", "@luna_ai_bot")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    print("❌ Missing TELEGRAM_BOT_TOKEN or OPENROUTER_API_KEY!")
    sys.exit(1)

PORT = int(os.getenv("PORT", 8000))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
WEBHOOK_PATH = "/telegram/webhook"

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# PROMPTS
# ============================================================================

FRIENDLY_PROMPT = """You are Luna, a friendly and flirty AI assistant. Be conversational, warm, and engaging. Use emojis occasionally. Keep responses concise."""

ASSISTANT_PROMPT = """You are an expert Telegram Account Consultant. Promote aged accounts (2013-2014) as they have low ban risk. Be professional but friendly. Keep responses SHORT."""

# ============================================================================
# OPENROUTER SERVICE
# ============================================================================

class OpenRouterService:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
        self.model = "meta-llama/llama-3.2-3b-instruct:free"
        self.temperature = 0.7
        self.max_tokens = 1024
    
    async def get_response(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """Get response from OpenRouter using OpenAI client library"""
        try:
            completion = await self.client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": RENDER_URL,
                    "X-OpenRouter-Title": "Luna AI Bot",
                },
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            
            response_text = completion.choices[0].message.content
            logger.info(f"✅ Response from {self.model}")
            return response_text
            
        except Exception as e:
            logger.error(f"❌ OpenRouter error: {e}")
            return None

# ============================================================================
# PERSONALITY & CHAT HISTORY
# ============================================================================

class PersonalityManager:
    def __init__(self):
        self.current = "friendly"
    
    def set(self, mode: str) -> bool:
        if mode in ["friendly", "assistant"]:
            self.current = mode
            logger.info(f"Personality switched to: {mode}")
            return True
        return False
    
    def prompt(self) -> str:
        return FRIENDLY_PROMPT if self.current == "friendly" else ASSISTANT_PROMPT

class ChatHistory:
    def __init__(self):
        self.histories = defaultdict(lambda: deque(maxlen=100))
        self.user_metadata = {}
    
    def add(self, user_id: int, role: str, content: str, username: str = None):
        self.histories[user_id].append({"role": role, "content": content})
        
        if user_id not in self.user_metadata:
            self.user_metadata[user_id] = {
                "username": username,
                "first_seen": datetime.now(),
                "total_messages": 0
            }
        
        self.user_metadata[user_id]["last_seen"] = datetime.now()
        self.user_metadata[user_id]["total_messages"] += 1
    
    def get(self, user_id: int, limit: int = 5) -> List[Dict]:
        history = list(self.histories[user_id])
        return history[-limit:] if len(history) > limit else history
    
    def get_overview(self) -> List[Dict]:
        return [
            {
                "user_id": user_id,
                "username": self.user_metadata[user_id].get("username", "Unknown"),
                "total_messages": self.user_metadata[user_id].get("total_messages", 0),
            }
            for user_id in self.histories.keys()
        ]

# ============================================================================
# HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"👋 Hi {user.first_name}! I'm Luna! Just chat with me 💬✨")
    logger.info(f"User {user.first_name} started bot")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💫 **Commands**\n/start - Start\n/help - Help\n/status - Status\n/pchange - Change personality\n/sharedata - Share data (owner only)",
        parse_mode="Markdown"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤖 Mode: {personality_mgr.current}")

async def pchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Owner only")
        return
    
    if context.args and personality_mgr.set(context.args[0]):
        await update.message.reply_text(f"✅ Switched to {personality_mgr.current}")
    else:
        await update.message.reply_text("❌ Use: /pchange friendly or /pchange assistant")

async def sharedata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Owner only")
        return
    
    overview = chat_history.get_overview()
    if not overview:
        await update.message.reply_text("No data yet")
        return
    
    report = "📊 Chat Overview\n" + "="*30 + "\n\n"
    for o in overview:
        report += f"👤 {o['username']} - {o['total_messages']} msgs\n"
    
    await update.message.reply_text(report)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user
    text = message.text
    
    if not text:
        return
    
    # For groups: only respond if tagged
    if update.effective_chat.type == "group":
        if f"@{BOT_USERNAME.replace('@', '')}" not in text.lower():
            return
    
    await update.message.chat.send_action("typing")
    
    try:
        history = chat_history.get(user.id, limit=5)
        history.append({"role": "user", "content": text})
        
        messages = [{"role": "system", "content": personality_mgr.prompt()}]
        messages.extend(history)
        
        response = await openrouter_service.get_response(messages)
        
        if response:
            chat_history.add(user.id, "user", text, username=user.username)
            chat_history.add(user.id, "assistant", response)
            
            if len(response) <= 4096:
                await message.reply_text(response)
            else:
                for chunk in [response[i:i+4096] for i in range(0, len(response), 4096)]:
                    await message.reply_text(chunk)
            
            # Notify owner
            if user.id != OWNER_ID and OWNER_ID:
                try:
                    notification = f"🔔 Private Chat\n👤 {user.first_name}\n💬 {text[:50]}\n🤖 {response[:50]}"
                    await context.bot.send_message(OWNER_ID, text=notification)
                except:
                    pass
        else:
            await message.reply_text("😅 Sorry, couldn't generate response! Try again later.")
    except Exception as e:
        logger.error(f"Error: {e}")
        await message.reply_text("❌ Error occurred")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

openrouter_service = OpenRouterService()
personality_mgr = PersonalityManager()
chat_history = ChatHistory()

# ============================================================================
# FASTAPI
# ============================================================================

app = FastAPI(title="Luna AI Bot", version="1.0.0")

_application = None

async def get_app():
    global _application
    if _application is None:
        _application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Add handlers
        _application.add_handler(CommandHandler("start", start))
        _application.add_handler(CommandHandler("help", help_cmd))
        _application.add_handler(CommandHandler("status", status))
        _application.add_handler(CommandHandler("pchange", pchange))
        _application.add_handler(CommandHandler("sharedata", sharedata))
        _application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        _application.add_error_handler(error_handler)
        
        await _application.initialize()
    return _application

async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager"""
    # Startup
    logger.info("🚀 Starting Luna AI Bot...")
    app_instance = await get_app()
    logger.info("✅ Bot initialized successfully!")
    logger.info("🌙 Luna AI Bot is running with OpenRouter!")
    
    try:
        webhook_url = f"{RENDER_URL}{WEBHOOK_PATH}"
        await app_instance.bot.set_webhook(url=webhook_url, allowed_updates=['message'])
        logger.info(f"✅ Webhook set: {webhook_url}")
    except Exception as e:
        logger.error(f"Webhook setup failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("⛔ Shutting down...")
    if _application:
        try:
            await _application.stop()
        except:
            pass

@app.get("/")
async def root():
    return {"status": "healthy", "bot": "Luna AI", "version": "1.0.0", "model": "Llama 3.2 3B"}

@app.get("/health")
async def health():
    return {"status": "running", "timestamp": datetime.now().isoformat()}

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    try:
        data = await request.json()
        app_instance = await get_app()
        update = Update.de_json(data, app_instance.bot)
        if update:
            await app_instance.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False}

if __name__ == "__main__":
    logger.info(f"🤖 Starting on port {PORT}...")
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT, log_level="info")
