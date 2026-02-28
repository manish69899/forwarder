# -*- coding: utf-8 -*-
"""
================================================================================
                       ULTIMATE TELEGRAM PUBLISHER BOT (FIXED)
================================================================================
Author: Senior Python Architect
Version: 6.1.0 (Enterprise Edition - Multi-Channel Support - Bug Fixed)
Description: 
    A professional-grade Telegram bot for automating channel publications.
    
    🔥 ENTERPRISE FEATURES:
    - 📡 Multi-Channel Support: Add/Remove multiple target channels
    - 🛡️ Rotating Logs: Prevents storage overflow on Render
    - 📂 Smart Directory: Auto-creates 'downloads' folder
    - ♻️ Resilience: Auto-backup system
    - 🚀 FIFO Queue with Priority Injection support
    - 🎭 Smart Sticker System (Random/Fixed modes)
    - 🧹 Caption Cleaner (Remove links/@mentions)
    
    🐛 BUG FIXES (v6.1.0):
    - Fixed QueryIdInvalid infinite recursion bug
    - Fixed recursive callback_router calls
    - Added proper error handling for expired callbacks
    - Improved callback query management

Requirements:
    pip install pyrogram tgcrypto flask python-dotenv

Usage:
    python telegram_publisher_bot.py
================================================================================
"""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import os
import shutil
import time
import random
import sys
import traceback
import re
from datetime import datetime
from typing import List, Optional, Dict, Any

# --- Third Party Imports ---
from dotenv import load_dotenv
from pyrogram import Client, filters, idle, enums
from pyrogram.raw import functions, types
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery,
    BotCommand
)
from pyrogram.errors import (
    FloodWait, 
    RPCError, 
    MessageNotModified, 
    ChatAdminRequired,
    PeerIdInvalid,
    QueryIdInvalid
)

# --- Local Imports ---
try:
    from keep_alive import keep_alive
except ImportError:
    # Create a dummy keep_alive function if module not found
    def keep_alive():
        pass

# 1. Load Environment Variables (Sabse Pehle)
load_dotenv()

# ==============================================================================
#                               CONFIGURATION
# ==============================================================================

# ⚠️ SECURITY WARNING: Replace these with your actual credentials in .env file
try:
    API_ID = int(os.getenv("API_ID", "0")) 
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "0"))
except ValueError:
    print("❌ ERROR: API_ID or SUPER_ADMIN_ID must be integers in .env file.")
    sys.exit(1)

# Critical Check
if not API_HASH or not BOT_TOKEN or API_ID == 0:
    print("❌ CRITICAL ERROR: .env file is missing or variables are empty!")
    sys.exit(1)

# --- 📂 STORAGE MANAGEMENT (Render Free Tier Optimization) ---
DB_NAME = "enterprise_bot.db"
LOG_FILE = "system.log"
DOWNLOAD_PATH = "downloads/"

# Create downloads folder if not exists
if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

# --- 📝 LOGGING CONFIGURATION (Space Saver) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=1), 
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("EnterpriseBot")

# Suppress noisy logs from Pyrogram
logging.getLogger("pyrogram").setLevel(logging.WARNING)


# ==============================================================================
#                           DATABASE MANAGER (SQLite - Enterprise)
# ==============================================================================

class DatabaseManager:
    """
    Handles all interactions with the SQLite database.
    Features: WAL Mode (High Speed), Smart Defaults, Thread Safety, Multi-Channel Support.
    """
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.conn = None
        self.cursor = None
        self.connect()
        self.init_tables()

    def connect(self):
        """Establishes a high-performance connection with WAL Mode."""
        try:
            self.conn = sqlite3.connect(
                self.db_name, 
                check_same_thread=False, 
                timeout=30.0
            )
            self.conn.row_factory = sqlite3.Row 
            self.cursor = self.conn.cursor()
            
            # PERFORMANCE: Enable WAL Mode
            self.cursor.execute("PRAGMA journal_mode=WAL;")
            self.cursor.execute("PRAGMA synchronous=NORMAL;")
            
            logger.info("💾 Database Connected (WAL Mode Enabled).")
        except sqlite3.Error as e:
            logger.critical(f"❌ Critical Database Connection Failed: {e}")
            sys.exit(1)

    def init_tables(self):
        """Creates necessary tables including Multi-Channel Support."""
        try:
            # 1. Settings Table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')

            # 2. Target Channels Table (NEW: Multi-Channel Support)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS target_channels (
                    channel_id INTEGER PRIMARY KEY,
                    channel_title TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            ''')

            # 3. Sticker Sets (For Random Mode)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS sticker_sets (
                    set_name TEXT PRIMARY KEY,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 4. Admins (For Permission)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 5. Stats (Analytics)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    date DATE PRIMARY KEY,
                    processed INTEGER DEFAULT 0,
                    stickers_sent INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0
                )
            ''')
            
            # --- SMART DEFAULTS ---
            defaults = {
                "delay": "30",
                "footer": "NONE",
                "mode": "copy",
                "is_paused": "0",
                "sticker_state": "ON",
                "sticker_mode": "RANDOM",
                "single_sticker_id": "",
                "sticker_pack_link": "",
                "caption_cleaner": "OFF",
            }
            
            for key, val in defaults.items():
                self.cursor.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                    (key, val)
                )
            
            # Ensure Super Admin Access
            self.cursor.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)", 
                (SUPER_ADMIN_ID, 0)
            )
            
            self.conn.commit()
            logger.info("✅ Database Tables & Smart Settings Ready.")
            
        except sqlite3.Error as e:
            logger.critical(f"❌ Table Initialization Error: {e}")
            sys.exit(1)

    # ========================== SETTINGS OPERATIONS ==========================

    def get_setting(self, key: str, default: str = None) -> str:
        """Retrieves a setting safely."""
        try:
            self.cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
            res = self.cursor.fetchone()
            if res:
                return res[0] if isinstance(res, tuple) else res['value']
            return default
        except sqlite3.Error:
            return default

    def set_setting(self, key: str, value: str):
        """Updates or Inserts a setting immediately."""
        try:
            self.cursor.execute(
                "REPLACE INTO settings (key, value) VALUES (?, ?)", 
                (key, str(value))
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"⚠️ DB Write Error (set_setting): {e}")

    # ========================== MULTI-CHANNEL OPERATIONS ==========================

    def add_target_channel(self, channel_id: int, channel_title: str = "Unknown") -> bool:
        """Adds a new target channel."""
        try:
            self.cursor.execute(
                "INSERT OR REPLACE INTO target_channels (channel_id, channel_title, is_active) VALUES (?, ?, 1)", 
                (channel_id, channel_title)
            )
            self.conn.commit()
            logger.info(f"✅ Channel Added: {channel_id} ({channel_title})")
            return True
        except sqlite3.Error as e:
            logger.error(f"❌ Add Channel Error: {e}")
            return False

    def remove_target_channel(self, channel_id: int) -> bool:
        """Removes a target channel."""
        try:
            self.cursor.execute("DELETE FROM target_channels WHERE channel_id=?", (channel_id,))
            self.conn.commit()
            logger.info(f"🗑 Channel Removed: {channel_id}")
            return True
        except sqlite3.Error as e:
            logger.error(f"❌ Remove Channel Error: {e}")
            return False

    def get_all_channels(self) -> List[Dict]:
        """Returns list of all target channels with details."""
        try:
            self.cursor.execute("SELECT channel_id, channel_title, is_active FROM target_channels ORDER BY added_at")
            rows = self.cursor.fetchall()
            channels = []
            for row in rows:
                channels.append({
                    'id': row[0] if isinstance(row, tuple) else row['channel_id'],
                    'title': row[1] if isinstance(row, tuple) else row['channel_title'],
                    'is_active': row[2] if isinstance(row, tuple) else row['is_active']
                })
            return channels
        except sqlite3.Error:
            return []

    def get_active_channels(self) -> List[int]:
        """Returns list of active channel IDs only."""
        try:
            self.cursor.execute("SELECT channel_id FROM target_channels WHERE is_active=1")
            rows = self.cursor.fetchall()
            return [row[0] if isinstance(row, tuple) else row['channel_id'] for row in rows]
        except sqlite3.Error:
            return []

    def toggle_channel_status(self, channel_id: int) -> bool:
        """Toggles channel active/inactive status."""
        try:
            self.cursor.execute(
                "UPDATE target_channels SET is_active = NOT is_active WHERE channel_id=?", 
                (channel_id,)
            )
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    def clear_all_channels(self) -> bool:
        """Removes all target channels."""
        try:
            self.cursor.execute("DELETE FROM target_channels")
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    # ========================== STICKER OPERATIONS ==========================

    def add_sticker_pack(self, name: str):
        """Adds a sticker pack link to the rotation list."""
        try:
            self.cursor.execute("INSERT OR IGNORE INTO sticker_sets (set_name) VALUES (?)", (name,))
            self.conn.commit()
        except sqlite3.Error:
            pass

    def remove_sticker_pack(self, name: str):
        """Removes a sticker pack from rotation."""
        try:
            self.cursor.execute("DELETE FROM sticker_sets WHERE set_name=?", (name,))
            self.conn.commit()
        except sqlite3.Error:
            pass

    def get_sticker_packs(self) -> List[str]:
        """Returns a list of all saved sticker pack names/links."""
        try:
            self.cursor.execute("SELECT set_name FROM sticker_sets")
            rows = self.cursor.fetchall()
            if rows and isinstance(rows[0], tuple):
                return [row[0] for row in rows]
            return [row['set_name'] for row in rows]
        except sqlite3.Error:
            return []

    # ========================== ADMIN OPERATIONS ==========================

    def add_admin(self, user_id: int, added_by: int):
        """Authorizes a new user as an admin."""
        try:
            self.cursor.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)", 
                (user_id, added_by)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"❌ Add Admin Error: {e}")

    def remove_admin(self, user_id: int):
        """Revokes admin access (Super Admin is protected)."""
        if user_id == SUPER_ADMIN_ID:
            logger.warning("🛡️ Security Alert: Attempt to remove Super Admin blocked.")
            return 
        try:
            self.cursor.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"❌ Remove Admin Error: {e}")

    def is_admin(self, user_id: int) -> bool:
        """Checks if a user is an admin or super admin."""
        if user_id == SUPER_ADMIN_ID:
            return True
        try:
            self.cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
            return self.cursor.fetchone() is not None
        except sqlite3.Error:
            return False

    def get_all_admins(self) -> List[int]:
        """Returns list of all admin IDs."""
        try:
            self.cursor.execute("SELECT user_id FROM admins")
            rows = self.cursor.fetchall()
            if rows and isinstance(rows[0], tuple):
                return [row[0] for row in rows]
            return [row['user_id'] for row in rows]
        except sqlite3.Error:
            return []

    # ========================== STATS OPERATIONS ==========================

    def update_stats(self, processed=0, stickers=0, errors=0):
        """Updates daily statistics safely using UPSERT logic."""
        try:
            today = datetime.now().date()
            self.cursor.execute("""
                INSERT INTO stats (date, processed, stickers_sent, errors)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    processed = processed + ?,
                    stickers_sent = stickers_sent + ?,
                    errors = errors + ?
            """, (today, processed, stickers, errors, processed, stickers, errors))
            self.conn.commit()
        except sqlite3.Error:
            pass

    def get_total_stats(self) -> Dict[str, int]:
        """Aggregates all-time stats."""
        try:
            self.cursor.execute("SELECT SUM(processed), SUM(stickers_sent), SUM(errors) FROM stats")
            res = self.cursor.fetchone()
            
            proc = res[0] if res and res[0] else 0
            stik = res[1] if res and res[1] else 0
            errs = res[2] if res and res[2] else 0
            
            return {
                "processed": proc,
                "stickers": stik,
                "errors": errs
            }
        except sqlite3.Error:
            return {"processed": 0, "stickers": 0, "errors": 0}


# Initialize DB (Global Instance)
db = DatabaseManager(DB_NAME)

# ==============================================================================
#                           GLOBAL STATE & OBJECTS
# ==============================================================================

# 1. Telegram Client Initialization
app = Client(
    "enterprise_publisher_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN
)

# 2. In-Memory Message Queues
vip_queue = asyncio.Queue()
msg_queue = asyncio.Queue()

# 3. User Input State (RAM)
user_input_mode: Dict[int, str] = {}

# 4. System Start Time
start_time = time.time()

# 5. Smart Album Tracking
last_processed_album_id = None 


# ==============================================================================
#                           HELPER FUNCTIONS
# ==============================================================================

def get_uptime() -> str:
    """Returns a human-readable uptime string."""
    try:
        if 'start_time' not in globals():
            return "0d 0h 0m 0s"
        seconds = int(time.time() - start_time)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        return f"{d}d {h}h {m}m {s}s"
    except Exception as e:
        logger.error(f"⚠️ Uptime Error: {e}")
        return "0d 0h 0m 0s"


async def safe_answer_callback(cb: CallbackQuery, text: str = "", show_alert: bool = False):
    """
    Safely answers a callback query, handling QueryIdInvalid errors.
    This prevents crashes when callback queries expire.
    """
    try:
        await cb.answer(text, show_alert=show_alert)
        return True
    except QueryIdInvalid:
        # Callback query has expired, this is normal - don't log as error
        logger.debug("Callback query expired (QueryIdInvalid)")
        return False
    except Exception as e:
        logger.debug(f"Callback answer failed: {e}")
        return False


async def safe_edit_message(cb: CallbackQuery, text: str, reply_markup=None):
    """
    Safely edits a callback message, handling common errors.
    """
    try:
        await cb.edit_message_text(text, reply_markup=reply_markup)
        return True
    except MessageNotModified:
        # Message content is same, not an error
        return True
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")
        return False


# ==============================================================================
#                           GUI KEYBOARD FACTORIES
# ==============================================================================

def get_main_menu() -> InlineKeyboardMarkup:
    """Generates the Main Dashboard with live status."""
    try:
        is_paused = db.get_setting("is_paused", "0") == "1"
        delay = db.get_setting("delay", "30")
        
        mode = db.get_setting("mode", "copy") 
        mode_display = "⏩ Forward" if mode == "forward" else "©️ Copy"
        
        st_state = db.get_setting("sticker_state", "ON")
        st_icon = "🟢" if st_state == "ON" else "🔴"
        
        footer_val = db.get_setting("footer", "NONE")
        footer_status = "✅" if footer_val != "NONE" else "❌"

        # Channel count
        channels = db.get_all_channels()
        active_count = len([c for c in channels if c['is_active'] == 1])
        total_count = len(channels)
        ch_text = f"📡 Channels: {active_count}/{total_count}" if channels else "⚠️ Add Channels"

        status_text = "🔴 PAUSED" if is_paused else "🟢 RUNNING"
        status_callback = "resume_bot" if is_paused else "pause_bot"

        keyboard = [
            [
                InlineKeyboardButton(status_text, callback_data=status_callback),
            ],
            [
                InlineKeyboardButton(ch_text, callback_data="menu_channels")
            ],
            [
                InlineKeyboardButton(f"⏱ Delay: {delay}s", callback_data="ask_delay"),
                InlineKeyboardButton(f"🔄 Mode: {mode_display}", callback_data="toggle_mode")
            ],
            [
                InlineKeyboardButton(f"✍️ Footer: {footer_status}", callback_data="menu_footer"),
                InlineKeyboardButton(f"🎭 Sticker: {st_icon}", callback_data="menu_stickers")
            ],
            [
                InlineKeyboardButton(f"📥 Queue: {msg_queue.qsize()}", callback_data="view_queue"),
                InlineKeyboardButton("📊 Stats", callback_data="view_stats")
            ],
            [
                InlineKeyboardButton("⚙️ Admin Panel", callback_data="menu_admins"),
                InlineKeyboardButton("🔄 Refresh", callback_data="refresh_home")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
        
    except Exception as e:
        logger.error(f"❌ Menu Generation Error: {e}")
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data="refresh_home")]])


def get_channel_menu() -> InlineKeyboardMarkup:
    """Multi-Channel Management Menu."""
    channels = db.get_all_channels()
    btns = []
    
    # Add Channel Button
    btns.append([
        InlineKeyboardButton("➕ Add Channel", callback_data="ask_channel"),
    ])
    
    # List existing channels
    if channels:
        btns.append([InlineKeyboardButton(f"── 📋 Your Channels ({len(channels)}) ──", callback_data="noop")])
        
        for ch in channels[:8]:  # Limit to 8 for UI
            ch_id = ch['id']
            ch_title = ch['title'][:20] if len(ch['title']) > 20 else ch['title']
            status_icon = "✅" if ch['is_active'] == 1 else "⏸"
            
            btns.append([
                InlineKeyboardButton(f"{status_icon} {ch_title}", callback_data=f"toggle_ch_{ch_id}"),
                InlineKeyboardButton("🗑", callback_data=f"del_ch_{ch_id}")
            ])
        
        if len(channels) > 8:
            btns.append([InlineKeyboardButton(f"... and {len(channels)-8} more", callback_data="noop")])
        
        # Clear All Button
        btns.append([InlineKeyboardButton("🗑 Clear All Channels", callback_data="clear_all_channels")])
    
    btns.append([InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_home")])
    return InlineKeyboardMarkup(btns)


def get_sticker_menu() -> InlineKeyboardMarkup:
    """Advanced Sticker Control Panel."""
    state = db.get_setting("sticker_state", "ON")
    mode = db.get_setting("sticker_mode", "RANDOM")
    
    btn_state_text = "🔴 Turn OFF" if state == "ON" else "🟢 Turn ON"
    btn_state_cb = "toggle_sticker_off" if state == "ON" else "toggle_sticker_on"
    
    btn_mode_text = "🎲 Mode: Random" if mode == "RANDOM" else "🎯 Mode: Fixed"
    btn_mode_cb = "set_mode_single" if mode == "RANDOM" else "set_mode_random"
    
    btns = [
        [
            InlineKeyboardButton(btn_state_text, callback_data=btn_state_cb),
            InlineKeyboardButton(btn_mode_text, callback_data=btn_mode_cb)
        ],
        [
            InlineKeyboardButton("➕ Add Pack", callback_data="ask_sticker"),
            InlineKeyboardButton("🎯 Set Fixed", callback_data="ask_single_sticker")
        ]
    ]

    packs = db.get_sticker_packs()
    if packs:
        btns.append([InlineKeyboardButton(f"── 📦 Packs ({len(packs)}) ──", callback_data="noop")])
        for i, pack in enumerate(packs[:5]):
            name = pack.split('/')[-1]
            if len(name) > 15: name = name[:12] + "..."
            
            btns.append([
                InlineKeyboardButton(f"📦 {name}", callback_data="noop"),
                InlineKeyboardButton("🗑", callback_data=f"del_pack_{pack}")
            ])
            
        if len(packs) > 5:
            btns.append([InlineKeyboardButton(f"... +{len(packs)-5} more", callback_data="noop")])
            
    btns.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
    return InlineKeyboardMarkup(btns)


def get_footer_menu() -> InlineKeyboardMarkup:
    """Sub-menu for Footer Management."""
    current_footer = db.get_setting("footer", "NONE")
    has_footer = current_footer != "NONE"
    
    btns = []
    if has_footer:
        btns.append([InlineKeyboardButton("👀 View Footer", callback_data="view_footer_text")])
        btns.append([InlineKeyboardButton("🗑 Remove Footer", callback_data="remove_footer")])
    
    btns.append([InlineKeyboardButton("✏️ Set Footer", callback_data="ask_footer")])
    btns.append([InlineKeyboardButton("🔙 Back", callback_data="back_home")])
    
    return InlineKeyboardMarkup(btns)


def get_upload_success_kb() -> InlineKeyboardMarkup:
    """Shows after file is queued."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Send More", callback_data="noop")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="refresh_home")]
    ])


def get_cancel_kb() -> InlineKeyboardMarkup:
    """Standard Cancel Button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_input")]])


def get_back_home_kb() -> InlineKeyboardMarkup:
    """Standard Back Button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_home")]])


# ==============================================================================
#                        SMART STICKER SENDER
# ==============================================================================

async def send_smart_sticker(client, chat_id):
    """Decides whether to send a Fixed Sticker or a Random one from packs."""
    try:
        state = db.get_setting("sticker_state", "ON")
        if state == "OFF":
            return

        mode = db.get_setting("sticker_mode", "RANDOM")
        
        # MODE A: SINGLE FIXED STICKER
        if mode == "SINGLE":
            file_id = db.get_setting("single_sticker_id")
            if file_id:
                await client.send_sticker(chat_id, file_id)
                db.update_stats(stickers=1)
                await asyncio.sleep(1.0)
                return

        # MODE B: RANDOM FROM PACKS
        packs = db.get_sticker_packs()
        if not packs: 
            return

        pack_name = random.choice(packs)
        short_name = pack_name.split('/')[-1]

        pack_data = await client.invoke(
            functions.messages.GetStickerSet(
                stickerset=types.InputStickerSetShortName(short_name=short_name),
                hash=0
            )
        )

        if pack_data and pack_data.documents:
            sticker = random.choice(pack_data.documents)
            
            await client.invoke(
                functions.messages.SendMedia(
                    peer=await client.resolve_peer(chat_id),
                    media=types.InputMediaDocument(
                        id=types.InputDocument(
                            id=sticker.id,
                            access_hash=sticker.access_hash,
                            file_reference=sticker.file_reference
                        )
                    ),
                    message="",
                    random_id=client.rnd_id()
                )
            )
            
            db.update_stats(stickers=1)
            logger.info(f"🤡 Sticker sent ({mode} mode)")
            await asyncio.sleep(1.0)

    except Exception as e:
        pass


# ==============================================================================
#                           WORKER ENGINE
# ==============================================================================

async def worker_engine():
    """The Brain of the System - Handles publishing to all active channels."""
    logger.info("🚀 Enterprise Worker Engine Started...")
    
    global last_processed_album_id
    
    while True:
        # PRIORITY QUEUE FETCHING
        if not vip_queue.empty():
            message = await vip_queue.get()
            is_vip = True
        else:
            message = await msg_queue.get()
            is_vip = False
        
        try:
            # Check Pause State
            while db.get_setting("is_paused") == "1":
                await asyncio.sleep(5)
            
            # Get ALL Active Channels (Multi-Channel Support)
            target_channels = db.get_active_channels()
            if not target_channels:
                logger.warning("⚠️ No active target channels. Dropping message.")
                if is_vip: vip_queue.task_done()
                else: msg_queue.task_done()
                continue

            # SMART ALBUM & STICKER LOGIC
            current_group_id = message.media_group_id
            should_send_sticker = True
            
            if current_group_id is not None:
                if current_group_id == last_processed_album_id:
                    should_send_sticker = True
                else:
                    last_processed_album_id = current_group_id
            else:
                last_processed_album_id = None

            # CONTENT PREPARATION
            mode = db.get_setting("mode", "copy")
            footer = db.get_setting("footer", "NONE")
            cleaner_mode = db.get_setting("caption_cleaner", "OFF")
            
            original_text = message.text or message.caption or ""
            
            # Auto-Cleaner Logic
            if cleaner_mode == "ON" and original_text:
                original_text = re.sub(r'http\S+', '', original_text)
                original_text = re.sub(r'@\w+', '', original_text)
                original_text = original_text.strip()

            # Merge Footer
            if footer != "NONE" and footer:
                if original_text:
                    final_text = f"{original_text}\n\n{footer}"
                else:
                    final_text = footer
            else:
                final_text = original_text

            # PUBLISH TO ALL ACTIVE CHANNELS
            success_count = 0
            for target_id in target_channels:
                try:
                    # Send sticker before post (only for first channel)
                    if should_send_sticker and success_count == 0:
                        await send_smart_sticker(app, target_id)

                    # Publish Content
                    if mode == "forward":
                        await message.forward(target_id)
                    else:
                        await message.copy(
                            chat_id=target_id,
                            caption=final_text
                        )
                    success_count += 1
                    
                except FloodWait as fw:
                    logger.warning(f"⏳ FloodWait {fw.value}s for channel {target_id}")
                    await asyncio.sleep(fw.value)
                except RPCError as rpc_err:
                    logger.error(f"❌ RPC Error for channel {target_id}: {rpc_err}")
                    db.update_stats(errors=1)

            # Update Stats
            if success_count > 0:
                db.update_stats(processed=success_count)
            
            q_total = msg_queue.qsize() + vip_queue.qsize()
            logger.info(f"✅ Published to {success_count} channels. Queue: {q_total}")
            
            # Dynamic Delay
            delay = int(db.get_setting("delay", "30"))
            await asyncio.sleep(delay)

        except FloodWait as e:
            logger.warning(f"⏳ FloodWait: Sleeping {e.value}s")
            await asyncio.sleep(e.value)
            
        except RPCError as e:
            logger.error(f"❌ Telegram API Error: {e}")
            db.update_stats(errors=1)
            
        except Exception as e:
            logger.critical(f"❌ Worker Error: {e}")
            traceback.print_exc()
            db.update_stats(errors=1)
            
        finally:
            if is_vip:
                vip_queue.task_done()
            else:
                msg_queue.task_done()


# ==============================================================================
#                           AUTO-BACKUP SYSTEM
# ==============================================================================

async def auto_backup_task(app):
    """Sends Database Backup to Super Admin every 1 Hour + Cleanup."""
    logger.info("💾 Auto-Backup & Cleanup System Started...")
    
    while True:
        try:
            await asyncio.sleep(3600)  # 1 Hour
            
            # DATABASE BACKUP
            if os.path.exists(DB_NAME) and os.path.getsize(DB_NAME) > 0:
                caption = (
                    f"🗄 **System Backup**\n"
                    f"📅 Date: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
                    f"ℹ️ **Restore:** Reply with `/restore`"
                )
                
                await app.send_document(
                    chat_id=SUPER_ADMIN_ID,
                    document=DB_NAME,
                    caption=caption
                )
                logger.info("✅ Database Backup sent to Super Admin.")

            # STORAGE CLEANUP
            if os.path.exists("downloads"):
                for filename in os.listdir("downloads"):
                    file_path = os.path.join("downloads", filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except Exception as e:
                        logger.error(f"⚠️ Cleanup Error: {e}")
                logger.info("🧹 Downloads folder cleaned.")

            # Truncate Logs if too big
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 5 * 1024 * 1024:
                with open(LOG_FILE, "w") as f:
                    f.truncate(0)
                logger.info("🧹 System Log truncated.")

        except Exception as e:
            logger.error(f"❌ Backup/Cleanup Failed: {e}")
            await asyncio.sleep(60)


# ==============================================================================
#                           CALLBACK HANDLERS (FIXED)
# ==============================================================================

async def show_dashboard(client: Client, cb: CallbackQuery):
    """Helper function to show the main dashboard (avoids recursion)."""
    user_id = cb.from_user.id
    
    if user_id in user_input_mode: 
        del user_input_mode[user_id]
    
    paused = db.get_setting("is_paused") == "1"
    status = "🔴 PAUSED" if paused else "🟢 ONLINE"
    channels = db.get_all_channels()
    active = len([c for c in channels if c['is_active'] == 1])
    
    dash_text = (
        f"🎛 **ENTERPRISE CONTROL HUB**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👋 **Welcome:** `{cb.from_user.first_name}`\n"
        f"🛡️ **Access:** `{'Super Admin' if user_id == SUPER_ADMIN_ID else 'Admin'}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 **LIVE TELEMETRY**\n"
        f"➤ **Status:** `{status}`\n"
        f"➤ **Uptime:** `{get_uptime()}`\n"
        f"➤ **Channels:** `{active}` active\n"
        f"➤ **Queue:** `{msg_queue.qsize()}` Normal + `{vip_queue.qsize()}` VIP\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    await safe_edit_message(cb, dash_text, reply_markup=get_main_menu())


async def show_channel_menu(client: Client, cb: CallbackQuery):
    """Helper function to show channel menu."""
    channels = db.get_all_channels()
    text = f"📡 **CHANNEL MANAGER**\n\n📊 Total: {len(channels)} channels"
    await safe_edit_message(cb, text, reply_markup=get_channel_menu())


async def show_sticker_menu(client: Client, cb: CallbackQuery):
    """Helper function to show sticker menu."""
    text = (
        "🎭 **STICKER STUDIO**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "• **Random:** Picks from your packs.\n"
        "• **Single:** Uses one fixed sticker."
    )
    await safe_edit_message(cb, text, reply_markup=get_sticker_menu())


async def show_footer_menu(client: Client, cb: CallbackQuery):
    """Helper function to show footer menu."""
    text = "✍️ **BRANDING SUITE**\nManage your auto-signature."
    await safe_edit_message(cb, text, reply_markup=get_footer_menu())


@app.on_callback_query()
async def callback_router(client: Client, cb: CallbackQuery):
    """
    Handles all Button Interactions.
    FIXED: No more recursive calls - uses helper functions instead.
    """
    user_id = cb.from_user.id
    data = cb.data

    # Security Barrier
    if not db.is_admin(user_id):
        await safe_answer_callback(cb, "🚫 ACCESS DENIED", show_alert=True)
        return

    try:
        # --- DASHBOARD & NAVIGATION ---
        if data in ["back_home", "refresh_home"]:
            await show_dashboard(client, cb)

        # --- SYSTEM CONTROL ---
        elif data in ["pause_bot", "resume_bot"]:
            if user_id != SUPER_ADMIN_ID:
                await safe_answer_callback(cb, "⛔ Only Owner can Pause/Resume!", show_alert=True)
                return

            if data == "pause_bot":
                db.set_setting("is_paused", "1")
                await safe_answer_callback(cb, "⚠️ System Paused!")
            else:
                db.set_setting("is_paused", "0")
                await safe_answer_callback(cb, "🚀 System Resumed!")
            
            # Refresh dashboard without recursion
            await show_dashboard(client, cb)

        # --- MODE SWITCHING ---
        elif data == "toggle_mode":
            curr = db.get_setting("mode", "copy")
            new_mode = "forward" if curr == "copy" else "copy"
            db.set_setting("mode", new_mode)
            
            txt = "⏩ Forward" if new_mode == "forward" else "©️ Copy"
            await safe_answer_callback(cb, f"Mode: {txt}")
            await show_dashboard(client, cb)

        # --- MULTI-CHANNEL MANAGEMENT ---
        elif data == "menu_channels":
            await show_channel_menu(client, cb)

        elif data == "ask_channel":
            user_input_mode[user_id] = "SET_CHANNEL"
            await safe_edit_message(
                cb, 
                "📡 **ADD CHANNEL**\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "1️⃣ **Forward** a message from target channel.\n"
                "2️⃣ **Send** Channel ID (e.g., -100...).\n"
                "3️⃣ **Send** Channel username (e.g., @mychannel).",
                reply_markup=get_cancel_kb()
            )

        elif data.startswith("toggle_ch_"):
            ch_id = int(data.replace("toggle_ch_", ""))
            db.toggle_channel_status(ch_id)
            await safe_answer_callback(cb, "✅ Channel status toggled!")
            await show_channel_menu(client, cb)

        elif data.startswith("del_ch_"):
            ch_id = int(data.replace("del_ch_", ""))
            db.remove_target_channel(ch_id)
            await safe_answer_callback(cb, "🗑 Channel removed!")
            await show_channel_menu(client, cb)

        elif data == "clear_all_channels":
            if user_id != SUPER_ADMIN_ID:
                await safe_answer_callback(cb, "⛔ Super Admin only!", show_alert=True)
                return
            db.clear_all_channels()
            await safe_answer_callback(cb, "🗑 All channels cleared!")
            await show_channel_menu(client, cb)

        # --- STICKER CONTROLS ---
        elif data == "menu_stickers":
            await show_sticker_menu(client, cb)

        elif data == "toggle_sticker_on":
            db.set_setting("sticker_state", "ON")
            await safe_answer_callback(cb, "✅ Stickers ON")
            await show_sticker_menu(client, cb)
            
        elif data == "toggle_sticker_off":
            db.set_setting("sticker_state", "OFF")
            await safe_answer_callback(cb, "🚫 Stickers OFF")
            await show_sticker_menu(client, cb)

        elif data == "set_mode_random":
            db.set_setting("sticker_mode", "RANDOM")
            await safe_answer_callback(cb, "🎲 Random Mode")
            await show_sticker_menu(client, cb)

        elif data == "set_mode_single":
            db.set_setting("sticker_mode", "SINGLE")
            await safe_answer_callback(cb, "🎯 Single Mode")
            await show_sticker_menu(client, cb)

        elif data == "ask_single_sticker":
            user_input_mode[user_id] = "SET_SINGLE_STICKER"
            await safe_edit_message(
                cb, 
                "🎯 **SET FIXED STICKER**\n\n👉 Send the **Sticker** you want to use.",
                reply_markup=get_cancel_kb()
            )

        elif data == "ask_sticker":
            user_input_mode[user_id] = "ADD_STICKER"
            await safe_edit_message(
                cb, 
                "➕ **ADD STICKER PACK**\n\n"
                "👉 Send a **Sticker** from pack OR **Link**.\n"
                "Ex: `https://t.me/addstickers/Animals`",
                reply_markup=get_cancel_kb()
            )

        elif data.startswith("del_pack_"):
            pack = data.replace("del_pack_", "")
            db.remove_sticker_pack(pack)
            await safe_answer_callback(cb, "🗑 Pack Removed")
            await show_sticker_menu(client, cb)

        # --- QUEUE OPS ---
        elif data == "view_queue":
            q_msg = f"📥 Normal: {msg_queue.qsize()} | ⚡ VIP: {vip_queue.qsize()}"
            await safe_answer_callback(cb, q_msg, show_alert=True)
            
        elif data == "noop":
            await safe_answer_callback(cb)

        # --- INPUT HANDLERS ---
        elif data == "ask_delay":
            user_input_mode[user_id] = "SET_DELAY"
            await safe_edit_message(cb, "⏱ **SET DELAY (Seconds)**\n\n👉 Send a number (Min 5).", reply_markup=get_cancel_kb())

        elif data == "cancel_input":
            if user_id in user_input_mode: del user_input_mode[user_id]
            await safe_answer_callback(cb, "🚫 Cancelled")
            await show_dashboard(client, cb)

        # --- FOOTER ---
        elif data == "menu_footer":
            await show_footer_menu(client, cb)

        elif data == "ask_footer":
            user_input_mode[user_id] = "SET_FOOTER"
            await safe_edit_message(cb, "✍️ **SEND NEW FOOTER**\nSupports HTML/Markdown.", reply_markup=get_cancel_kb())

        elif data == "remove_footer":
            db.set_setting("footer", "NONE")
            await safe_answer_callback(cb, "🗑 Footer Deleted")
            await show_footer_menu(client, cb)
            
        elif data == "view_footer_text":
            ft = db.get_setting("footer", "NONE")
            await safe_edit_message(
                cb, 
                f"📝 **PREVIEW:**\n\n{ft}", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_footer")]])
            )

        # --- ADMINS ---
        elif data == "menu_admins":
            if user_id != SUPER_ADMIN_ID:
                await safe_answer_callback(cb, "⛔ Super Admin Only!", show_alert=True)
                return
            admins = db.get_all_admins()
            txt = "**👥 ADMIN TEAM:**\n\n" + "\n".join([f"• `{a}`" for a in admins])
            kb = [
                [InlineKeyboardButton("➕ Add", callback_data="ask_add_admin"), 
                 InlineKeyboardButton("➖ Remove", callback_data="ask_rem_admin")], 
                [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
            ]
            await safe_edit_message(cb, txt, reply_markup=InlineKeyboardMarkup(kb))

        elif data == "ask_add_admin":
            user_input_mode[user_id] = "ADD_ADMIN"
            await safe_edit_message(cb, "👤 Send **User ID** to add.", reply_markup=get_cancel_kb())

        elif data == "ask_rem_admin":
            user_input_mode[user_id] = "REM_ADMIN"
            await safe_edit_message(cb, "👤 Send **User ID** to remove.", reply_markup=get_cancel_kb())
            
        # --- STATS ---
        elif data == "view_stats":
            stats = db.get_total_stats()
            txt = f"📊 **STATISTICS**\n\n✅ Sent: `{stats['processed']}`\n🎭 Stickers: `{stats['stickers']}`\n❌ Errors: `{stats['errors']}`"
            await safe_edit_message(cb, txt, reply_markup=get_back_home_kb())

    except MessageNotModified:
        # Message content is same, not an error - just ignore
        pass
    except QueryIdInvalid:
        # Callback query expired - this is normal, don't log as error
        logger.debug("Callback query expired during processing")
    except Exception as e:
        logger.error(f"Callback Error: {e}")
        # Don't try to answer the callback here - it might be expired
        # Just log the error and move on


# ==============================================================================
#                           MESSAGE HANDLER
# ==============================================================================

@app.on_message(filters.private & ~filters.bot & ~filters.command(["restore", "logs"]))
async def message_processor(client: Client, message: Message):
    """The Gatekeeper - Handles all inputs."""
    user_id = message.from_user.id

    # Security Check
    if not db.is_admin(user_id):
        return

    # /start Command
    if message.text and message.text.lower() == "/start":
        if user_id in user_input_mode: del user_input_mode[user_id]
        
        await message.reply_text(
            f"👋 **Hello, {message.from_user.first_name}!**\n\n"
            "🚀 **Enterprise Publisher System Online**\n"
            "Ready to manage your channel content.",
            reply_markup=get_main_menu()
        )
        return

    # INPUT MODE HANDLING
    if user_id in user_input_mode:
        mode = user_input_mode[user_id]
        
        try:
            # SET CHANNEL (Multi-Channel Support)
            if mode == "SET_CHANNEL":
                target = None
                title = "Unknown"
                
                if message.forward_from_chat:
                    target = message.forward_from_chat.id
                    title = message.forward_from_chat.title or "Unknown"
                elif message.text:
                    text = message.text.strip()
                    try:
                        target = int(text)
                        title = f"ID: {target}"
                    except ValueError:
                        # Try as username
                        if text.startswith("@"):
                            try:
                                chat = await client.get_chat(text)
                                target = chat.id
                                title = chat.title or text
                            except:
                                pass
                
                if target:
                    db.add_target_channel(target, title)
                    channels = db.get_all_channels()
                    await message.reply_text(
                        f"✅ **Channel Added!**\n"
                        f"ID: `{target}`\n"
                        f"Name: `{title}`\n"
                        f"Total Channels: {len(channels)}", 
                        reply_markup=get_channel_menu()
                    )
                else:
                    await message.reply_text("❌ Invalid Input. Forward a message or send ID/username.")
                    return

            # SET DELAY
            elif mode == "SET_DELAY":
                try:
                    val = int(message.text)
                    if val < 5: raise ValueError
                    db.set_setting("delay", str(val))
                    await message.reply_text(f"⏱ **Delay Updated:** `{val}s`", reply_markup=get_back_home_kb())
                except:
                    await message.reply_text("❌ Invalid! Minimum 5 seconds.")
                    return

            # SET FOOTER
            elif mode == "SET_FOOTER":
                text = message.text.html if message.text else "NONE"
                db.set_setting("footer", text)
                await message.reply_text("✍️ **Footer Updated!**", reply_markup=get_footer_menu())

            # ADD STICKER PACK
            elif mode == "ADD_STICKER":
                pack_name = None
                if message.sticker:
                    pack_name = message.sticker.set_name
                elif message.text:
                    if "addstickers/" in message.text:
                        pack_name = message.text.split("addstickers/")[-1].split()[0]
                    else:
                        pack_name = message.text.strip()
                
                if pack_name:
                    db.add_sticker_pack(pack_name)
                    await message.reply_text(f"✅ **Pack Added:** `{pack_name}`", reply_markup=get_sticker_menu())
                else:
                    await message.reply_text("❌ Error. Send a sticker or link.")
                    return

            # SET SINGLE STICKER
            elif mode == "SET_SINGLE_STICKER":
                if message.sticker:
                    file_id = message.sticker.file_id
                    db.set_setting("single_sticker_id", file_id)
                    db.set_setting("sticker_mode", "SINGLE")
                    await message.reply_text("🎯 **Fixed Sticker Set!**", reply_markup=get_sticker_menu())
                else:
                    await message.reply_text("❌ Please send a Sticker.")
                    return

            # ADMIN MANAGEMENT
            elif mode == "ADD_ADMIN":
                try:
                    new_id = int(message.text)
                    db.add_admin(new_id, user_id)
                    await message.reply_text(f"👤 **Admin Added:** `{new_id}`", reply_markup=get_back_home_kb())
                except:
                    await message.reply_text("❌ Send Numeric User ID.")
                    return

            elif mode == "REM_ADMIN":
                try:
                    rem_id = int(message.text)
                    if rem_id == SUPER_ADMIN_ID:
                        await message.reply_text("🛡️ Cannot remove Super Admin.")
                    else:
                        db.remove_admin(rem_id)
                        await message.reply_text(f"🗑 **Admin Removed:** `{rem_id}`", reply_markup=get_back_home_kb())
                except:
                    await message.reply_text("❌ Invalid ID.")
                    return

            del user_input_mode[user_id]
        
        except Exception as e:
            logger.error(f"Input Handler Error: {e}")
            await message.reply_text(f"❌ Error: {e}", reply_markup=get_back_home_kb())
        
        return

    # CONTENT QUEUEING
    channels = db.get_active_channels()
    if not channels:
        await message.reply_text("⚠️ **No Active Channels!**\nAdd channels first.", reply_markup=get_main_menu())
        return

    # Priority Check
    is_vip = False
    caption = message.caption or ""
    if "#urgent" in caption.lower() or "#vip" in caption.lower():
        is_vip = True
        await vip_queue.put(message)
    else:
        await msg_queue.put(message)

    # Feedback
    pos = vip_queue.qsize() if is_vip else msg_queue.qsize()
    queue_type = "⚡ VIP Queue" if is_vip else "📥 Normal Queue"
    
    try:
        await message.reply_text(
            f"✅ **Added to {queue_type}**\n"
            f"🔢 Position: `{pos}`\n"
            f"📡 Will publish to {len(channels)} channels\n"
            f"⏳ Processing...",
            quote=True,
            reply_markup=get_upload_success_kb()
        )
    except Exception as e:
        logger.error(f"Feedback Error: {e}")


# ==============================================================================
#                           COMMAND HANDLERS
# ==============================================================================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    """Shows the Main Dashboard."""
    if not db.is_admin(message.from_user.id):
        return
    
    if message.from_user.id in user_input_mode:
        del user_input_mode[message.from_user.id]

    await message.reply(
        f"🤖 **Enterprise Publisher Dashboard**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👋 Welcome, `{message.from_user.first_name}`!\n"
        f"⚡ System **Online**.\n"
        f"━━━━━━━━━━━━━━━━━━",
        reply_markup=get_main_menu()
    )


@app.on_message(filters.command("logs") & filters.private)
async def logs_handler(client: Client, message: Message):
    """Sends the system.log file to Super Admin."""
    if message.from_user.id != SUPER_ADMIN_ID: return
    
    if os.path.exists(LOG_FILE):
        await message.reply_document(
            LOG_FILE, 
            caption="📜 **System Logs** (Last 5MB)"
        )
    else:
        await message.reply("⚠️ Log file is empty or missing.")


@app.on_message(filters.command("restore") & filters.private)
async def restore_handler(client: Client, message: Message):
    """Restores the database from a backup file."""
    if message.from_user.id != SUPER_ADMIN_ID: return

    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("⚠️ **Usage:** Reply to a `.db` backup with `/restore`.")
        return

    try:
        status = await message.reply("⏳ **Restoring Database...**")
        await message.reply_to_message.download(file_name=DB_NAME)
        db.connect() 
        await status.edit("✅ **Restore Complete!**")
    except Exception as e:
        await message.reply(f"❌ Restore Failed: {e}")


# ==============================================================================
#                           MAIN EXECUTOR
# ==============================================================================

async def main():
    """Starts the Enterprise Bot System."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 60)
    print("       🚀 ENTERPRISE PUBLISHER BOT v6.1 🚀")
    print("       📡 Multi-Channel Support Enabled")
    print("       🐛 Bug Fixes Applied")
    print("=" * 60)
    
    logger.info("📡 Connecting to Telegram Servers...")
    await app.start()
    
    # Set Bot Commands
    commands = [
        BotCommand("start", "🏠 Dashboard"),
        BotCommand("logs", "📜 View Logs"),
        BotCommand("restore", "♻️ Restore Backup")
    ]
    await app.set_bot_commands(commands)
    logger.info("✅ Bot Commands Menu Updated.")
    
    # Notify Super Admin
    me = await app.get_me()
    logger.info(f"✅ Logged in as: @{me.username}")
    
    try:
        await app.send_message(
            SUPER_ADMIN_ID, 
            f"🚀 **Bot Started!**\n"
            f"📅 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"📡 Multi-Channel Mode Active\n\n"
            f"Send /start to open panel."
        )
    except:
        logger.warning("⚠️ Could not DM Super Admin.")

    # Start Background Workers
    worker_task = asyncio.create_task(worker_engine())
    backup_task = asyncio.create_task(auto_backup_task(app))
    
    logger.info("🟢 SYSTEM ONLINE. WAITING FOR COMMANDS.")
    await idle()
    
    # Shutdown
    worker_task.cancel()
    backup_task.cancel()
    await app.stop()


if __name__ == "__main__":
    try:
        keep_alive()  
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by User")
    except Exception as e:
        logger.critical(f"❌ Fatal Error: {e}")
        traceback.print_exc()
