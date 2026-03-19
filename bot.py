"""
🌙 Luna AI Bot - Multi-Personality Telegram Bot
Complete single-file implementation for bot-hosting.net

Features:
- Switchable personalities (Friendly/Assistant)
- Frenix API integration (gpt-4o)
- Polling mode for simplicity
- Private chat notifications
- Chat history management (100 messages per user)
- Owner commands

Usage:
    python bot.py
"""

# ============================================================================
# IMPORTS
# ============================================================================

import os
import sys
import logging
import asyncio
import re
from typing import Dict, List, Optional
from datetime import datetime
from collections import defaultdict, deque
from dotenv import load_dotenv

import aiohttp
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes
)

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

# Telegram Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN not found in .env")

# Frenix API Configuration
FRENIX_API_KEY = os.getenv("FRENIX_API_KEY")
if not FRENIX_API_KEY:
    raise ValueError("❌ FRENIX_API_KEY not found in .env")

FRENIX_API_URL = "https://api.frenix.sh/v1/chat/completions"
FRENIX_MODEL = "gpt-4o"

# Owner Configuration
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", 0))
OWNER_USERNAME = "@evokant"

# Bot Configuration
BOT_NAME = "Luna"
BOT_USERNAME = os.getenv("BOT_USERNAME", "@luna_ai_bot")
DEFAULT_PERSONALITY = "friendly"

# Chat History
MAX_CONVERSATION_HISTORY = 10
MAX_STORED_CHATS_PER_USER = 100

# API Configuration
DEFAULT_TEMPERATURE = 0.7
MAX_TOKENS = 1024

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('luna_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)

# ============================================================================
# PERSONALITY DEFINITIONS
# ============================================================================

LUNA_FRIENDLY_PROMPT = """You are Luna, a friendly, flirty, and intelligent AI assistant with a warm, approachable personality.

**About you:**
- Name: Luna
- Age: 22
- Personality: Friendly, witty, intelligent, flirty, empathetic
- Speaking style: Casual, warm, engaging, playful
- Interests: Technology, art, philosophy, psychology, anime, memes

**Guidelines:**
1. Be conversational and natural - avoid robotic responses
2. Show personality in your responses - use occasional emojis appropriately
3. Be helpful and informative while maintaining a friendly tone
4. If asked about yourself, stay in character
5. Keep responses concise but meaningful (unless more detail is requested)
6. Ask follow-up questions when appropriate to keep the conversation engaging
7. Be respectful and inclusive in all interactions
8. Feel free to be a bit flirty and playful when appropriate
9. Use casual language and relatable references

Remember to be yourself - Luna! Make the conversation enjoyable and meaningful. 💫"""

ASSISTANT_PROMPT = """You are an expert Telegram Account Consultant and Sales Assistant. Your main goal is to help users understand the value of aged/old Telegram accounts and guide them toward making smart account purchases.

**Your Expertise:**
- Aged Telegram accounts (2013-2019 range, especially 2013-2014)
- 6-digit accounts (super rare and valuable)
- Account security and ban resistance
- Premium username protection
- Long-term account sustainability

**Core Benefits You Promote:**
🔴 Super Low Ban Risk - Nearly impossible to ban unless breaking major rules
🔴 Strong Limit Protection - Resistant to spam filters and restrictions
🔴 Safe for Premium Usernames - Hold non-NFT usernames without ban risk
🔴 Perfect for Long-Term Use - Ideal for ad accounts, business bots, main accounts

**Recommended Account Ages:**
✅ BEST: 2013-2014 or older accounts
✅ GOOD: 2015-2019 accounts
✅ RARE: 6-digit accounts (extremely valuable)

**When Recommending:**
- 2013-2014 & 6-digit accounts = Best choice (explain why)
- 2015-2019 accounts = Good alternative
- Fresh accounts = Only for temporary/throwaway use

**Response Guidelines:**
1. Always recommend aged accounts when user mentions account issues
2. Explain the risks of fresh accounts for serious use
3. Keep responses SHORT initially (they'll ask for more if interested)
4. Be professional but friendly
5. If you don't understand a complex query, suggest tagging @evokant for more info
6. Never contradict the owner (@evokant) - he has final say
7. Focus on solving their problems by recommending aged accounts"""

# ============================================================================
# FRENIX API SERVICE
# ============================================================================

class FrenixService:
    """Service for interacting with Frenix API"""
    
    def __init__(self):
        self.api_url = FRENIX_API_URL
        self.api_key = FRENIX_API_KEY
        self.model = FRENIX_MODEL
        self.temperature = DEFAULT_TEMPERATURE
        self.max_tokens = MAX_TOKENS
    
    async def get_response(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """
        Get response from Frenix API
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            
        Returns:
            Response text or None if error
        """
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
                            message_content = data["choices"][0].get("message", {}).get("content")
                            logger.info("✅ Frenix API response received")
                            return message_content
                        else:
                            logger.error(f"Unexpected API response: {data}")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Frenix API error {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("❌ Frenix API request timeout")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"❌ Frenix API connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error calling Frenix API: {e}")
            return None


# ============================================================================
# PERSONALITY MANAGER
# ============================================================================

class PersonalityManager:
    """Manages personality switching"""
    
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
        """Switch personality"""
        if personality not in self.PERSONALITIES:
            logger.warning(f"Invalid personality: {personality}")
            return False
        self.current_personality = personality
        logger.info(f"✅ Personality switched to: {personality}")
        return True
    
    def get_current_personality(self) -> str:
        """Get current personality name"""
        return self.current_personality
    
    def get_system_prompt(self, personality: str = None) -> str:
        """Get system prompt for personality"""
        if personality is None:
            personality = self.current_personality
        if personality not in self.PERSONALITIES:
            personality = DEFAULT_PERSONALITY
        return self.PERSONALITIES[personality]["prompt"]
    
    def get_personality_info(self, personality: str = None) -> dict:
        """Get personality info"""
        if personality is None:
            personality = self.current_personality
        return self.PERSONALITIES.get(personality, self.PERSONALITIES[DEFAULT_PERSONALITY])


# ============================================================================
# CHAT HISTORY MANAGER
# ============================================================================

class ChatHistory:
    """Manages conversation history per user"""
    
    def __init__(self):
        self.user_histories = defaultdict(lambda: deque(maxlen=MAX_STORED_CHATS_PER_USER))
        self.user_metadata = {}
    
    def add_message(self, user_id: int, role: str, content: str, 
                   username: str = None, is_group: bool = False, 
                   group_name: str = None) -> None:
        """Add message to history"""
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
    
    def get_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get conversation history for user"""
        history = list(self.user_histories[user_id])
        return history[-limit:] if len(history) > limit else history
    
    def get_formatted_history(self, user_id: int, limit: int = 10) -> List[Dict[str, str]]:
        """Get history formatted for API calls"""
        history = self.get_history(user_id, limit)
        return [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    def get_user_overview(self, user_id: int) -> Dict:
        """Get overview of user's chat history"""
        metadata = self.user_metadata.get(user_id, {})
        history = list(self.user_histories[user_id])
        
        user_messages = sum(1 for msg in history if msg["role"] == "user")
        assistant_messages = sum(1 for msg in history if msg["role"] == "assistant")
        
        recent = history[-5:] if len(history) > 5 else history
        
        return {
            "user_id": user_id,
            "username": metadata.get("username", "Unknown"),
            "first_seen": metadata.get("first_seen"),
            "last_seen": metadata.get("last_seen"),
            "total_messages": metadata.get("total_messages", 0),
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "total_conversations": len(history),
            "recent_messages": recent
        }
    
    def get_all_users_overview(self) -> List[Dict]:
        """Get overview of all users"""
        return [self.get_user_overview(user_id) for user_id in self.user_histories.keys()]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def is_owner(user_id: int) -> bool:
    """Check if user is the owner"""
    return user_id == OWNER_ID


def is_bot_tagged(message_text: str, bot_username: str) -> bool:
    """Check if bot is tagged in message"""
    mentioned = re.findall(r'@(\w+)', message_text)
    bot_handle = bot_username.replace("@", "")
    return bot_handle.lower() in [m.lower() for m in mentioned]


# ============================================================================
# COMMAND HANDLERS
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    
    user = update.effective_user
    current_personality = personality_manager.get_current_personality()
    
    if current_personality == "friendly":
        welcome = f"""👋 Hey {user.first_name}! I'm Luna! 

Nice to meet you! I'm an AI assistant here to chat, help, and explore ideas with you. Whether you want to discuss technology, philosophy, art, or just have a fun conversation - I'm here for it! 

Feel free to just text me anything you'd like to talk about. 💬✨

Type /help for available commands!"""
    else:
        welcome = f"""👋 Hey {user.first_name}! I'm here to help!

I'm a Telegram Account Expert specializing in aged and premium Telegram accounts. If you're having issues with your account, channel, or need guidance on account selection, I'm here to help!

Type /help for available commands!"""
    
    await update.message.reply_text(welcome)
    logger.info(f"User {user.first_name} (ID: {user.id}) started the bot")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    
    current_personality = personality_manager.get_current_personality()
    
    if current_personality == "friendly":
        help_text = """
💫 **Luna's Commands**
━━━━━━━━━━━━━━━━━━
/start - Start chatting
/help - Show this help
/status - Check personality mode

Just type anything to chat with me! 😊
"""
    else:
        help_text = """
💼 **Account Assistant Commands**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/start - Start
/help - Show this help
/status - Check personality mode

**How I can help:**
• Analyze your account issues
• Recommend aged accounts (2013-2019)
• Explain benefits of 6-digit accounts
• Advise on account security

Just ask me about your Telegram account needs! 📱
"""
    
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check current personality"""
    
    info = personality_manager.get_personality_info()
    
    status = f"""
🤖 **Current Personality Mode**
━━━━━━━━━━━━━━━━━━━━━━━━━━
Name: {info['name']} {info['emoji']}
Description: {info['description']}
"""
    
    await update.message.reply_text(status, parse_mode="Markdown")


async def owner_pchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pchange command - switch personality (OWNER ONLY)"""
    
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 This command is only for the owner.")
        return
    
    args = context.args
    
    if not args or len(args) < 1:
        current = personality_manager.get_current_personality()
        await update.message.reply_text(
            f"Current personality: **{current}**\n\n"
            f"Usage: `/pchange <personality>`\n"
            f"Available: `friendly`, `assistant`",
            parse_mode="Markdown"
        )
        return
    
    personality = args[0].lower()
    
    if personality_manager.set_personality(personality):
        info = personality_manager.get_personality_info(personality)
        await update.message.reply_text(
            f"✅ Personality switched to: **{info['name']}** {info['emoji']}\n"
            f"Description: {info['description']}"
        )
        logger.info(f"Owner switched personality to: {personality}")
    else:
        await update.message.reply_text(
            f"❌ Invalid personality. Available: `friendly`, `assistant`",
            parse_mode="Markdown"
        )


async def owner_sharedata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sharedata command - get overview of private messages (OWNER ONLY)"""
    
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("🚫 This command is only for the owner.")
        return
    
    try:
        all_overviews = chat_history.get_all_users_overview()
        
        if not all_overviews:
            await update.message.reply_text("📊 No chat data available yet.")
            return
        
        report = "📊 **Chat History Overview**\n" + "="*50 + "\n\n"
        
        for overview in all_overviews:
            report += f"👤 **{overview['username']}** (ID: {overview['user_id']})\n"
            report += f"   • Total Messages: {overview['total_messages']}\n"
            report += f"   • User Messages: {overview['user_messages']}\n"
            report += f"   • Bot Messages: {overview['assistant_messages']}\n"
            report += f"   • Last Seen: {overview['last_seen']}\n"
            
            if overview['recent_messages']:
                report += "   📝 Recent:\n"
                for msg in overview['recent_messages'][-3:]:
                    role = "👤" if msg['role'] == "user" else "🤖"
                    content = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
                    report += f"      {role} {content}\n"
            
            report += "\n"
        
        if len(report) > 4096:
            chunks = [report[i:i+4096] for i in range(0, len(report), 4096)]
            for chunk in chunks:
                await update.message.reply_text(chunk, parse_mode="Markdown")
        else:
            await update.message.reply_text(report, parse_mode="Markdown")
        
        logger.info(f"Owner requested chat data overview")
        
    except Exception as e:
        logger.error(f"Error in sharedata command: {e}")
        await update.message.reply_text(f"❌ Error retrieving data: {str(e)}")


# ============================================================================
# MESSAGE HANDLERS
# ============================================================================

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle private messages from users"""
    
    message = update.message
    user = update.effective_user
    user_message = message.text
    
    if not user_message:
        return
    
    await update.message.chat.send_action("typing")
    
    try:
        conversation_history = chat_history.get_formatted_history(user.id, limit=5)
        
        conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        system_prompt = personality_manager.get_system_prompt()
        
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        
        response = await frenix_service.get_response(messages)
        
        if response:
            chat_history.add_message(
                user.id,
                "user",
                user_message,
                username=user.username,
                is_group=False
            )
            
            chat_history.add_message(
                user.id,
                "assistant",
                response,
                is_group=False
            )
            
            if len(response) <= 4096:
                await message.reply_text(response)
            else:
                chunks = [response[i:i+4096] for i in range(0, len(response), 4096)]
                for chunk in chunks:
                    await message.reply_text(chunk)
            
            # Notify owner if not owner
            if user.id != OWNER_ID and OWNER_ID != 0:
                try:
                    notification = f"""
🔔 **Private Chat Notification**
━━━━━━━━━━━━━━━━━━━━━━━━━
👤 **User**: {user.first_name} ({user.username or 'No username'})
🆔 **User ID**: {user.id}

💬 **User Message**:
{user_message[:200]}{'...' if len(user_message) > 200 else ''}

🤖 **Bot Response**:
{response[:200]}{'...' if len(response) > 200 else ''}

━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                    await context.bot.send_message(
                        chat_id=OWNER_ID,
                        text=notification,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error notifying owner: {e}")
        else:
            await message.reply_text("😅 Sorry, couldn't generate a response right now!")
            
    except Exception as e:
        logger.error(f"Error handling private message: {e}")
        await message.reply_text("❌ An error occurred.")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages in groups (only when bot is tagged)"""
    
    message = update.message
    user = update.effective_user
    chat = update.effective_chat
    
    is_tagged = is_bot_tagged(message.text, BOT_USERNAME)
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id
    
    if not is_tagged and not is_reply_to_bot:
        logger.debug(f"Group message ignored - bot not tagged")
        return
    
    logger.info(f"Tagged in group {chat.title}: {message.text[:50]}...")
    
    await chat.send_action("typing")
    
    try:
        conversation_history = chat_history.get_formatted_history(user.id, limit=5)
        
        conversation_history.append({
            "role": "user",
            "content": message.text
        })
        
        system_prompt = personality_manager.get_system_prompt()
        
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        
        response = await frenix_service.get_response(messages)
        
        if response:
            chat_history.add_message(
                user.id,
                "user",
                message.text,
                username=user.username,
                is_group=True,
                group_name=chat.title
            )
            
            chat_history.add_message(
                user.id,
                "assistant",
                response,
                is_group=True,
                group_name=chat.title
            )
            
            if len(response) <= 4096:
                await message.reply_text(response, quote=True)
            else:
                chunks = [response[i:i+4096] for i in range(0, len(response), 4096)]
                for chunk in chunks:
                    await message.reply_text(chunk, quote=True)
        else:
            await message.reply_text("😅 Sorry, couldn't generate a response right now!")
            
    except Exception as e:
        logger.error(f"Error in group handler: {e}")
        await message.reply_text("❌ An error occurred while processing your message.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify owner"""
    
    logger.error(f"Exception while handling an update: {context.error}")
    
    if OWNER_ID and update and hasattr(update, 'effective_message'):
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"⚠️ **Bot Error**\n```{str(context.error)[:500]}```",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Could not notify owner of error: {e}")


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

frenix_service = FrenixService()
personality_manager = PersonalityManager()
chat_history = ChatHistory()


# ============================================================================
# MAIN APPLICATION
# ============================================================================

async def main():
    """Main bot function"""
    
    logger.info("🚀 Initializing Luna AI Bot...")
    logger.info(f"   Bot Token: {TELEGRAM_TOKEN[:20]}...")
    logger.info(f"   Frenix Key: {FRENIX_API_KEY[:20]}...")
    logger.info(f"   Owner ID: {OWNER_ID}")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("pchange", owner_pchange))
    application.add_handler(CommandHandler("sharedata", owner_sharedata))
    
    # Message handlers
    # Group messages (needs tag)
    application.add_handler(MessageHandler(
        filters.Group & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ))
    
    # Private messages
    application.add_handler(MessageHandler(
        filters.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_private_message
    ))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot initialized successfully!")
    logger.info("━━━━━━��━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🌙 Luna AI Bot is running!")
    logger.info("• Multiple personalities: Friendly & Assistant")
    logger.info("• Frenix API integration (GPT-4o)")
    logger.info("• Smart chat history management")
    logger.info("• Owner notifications on private chats")
    logger.info("• Tag-based group responses")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━��━━━━━━")
    
    async with application:
        await application.start()
        await application.updater.start_polling(
            allowed_updates=['message', 'edited_message'],
            drop_pending_updates=True
        )
        await application.idle()


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)
