"""
Discord Advanced Logging System - Comprehensive Event Tracking & Management

OVERVIEW:
Advanced logging system with granular per-channel controls, audit log integration,
file management, and comprehensive Discord event tracking. Auto-attaches to bot.log.

SETUP:
- No manual setup required - auto-creates files and directories
- Config: src/config/logging_config.json
- Logs: src/logs/ (events/, cogs/, exports/ subdirectories)
- Requires: PermissionsCog (optional for advanced permissions)
- Auto-attaches to bot.log for other cogs to use

PERMISSIONS:
- Log admin: 'permissions.logadmin' or Administrator
- Clear logs: Administrator only

COMMANDS:
/logs export <channel>              - Export channel messages to file
/logs event-channel [channel]       - Set/remove server events log channel
/logs general-channel [channel]     - Set/remove general log channel  
/logs cog-channel [channel]         - Set/remove cog log channel
/logs custom-channel <name> [channel] - Set/remove custom log channel
/logs exclude-all <channel>         - Exclude channel from ALL logging
/logs include-all <channel>         - Include channel in all logging
/logs exclude-event <channel> <event> - Exclude specific event for channel
/logs include-event <channel> <event> - Include specific event for channel
/logs toggle-event <event> <enabled> - Toggle events globally
/logs list-exclusions <channel>     - List channel exclusions
/logs clear <type> [days]           - Clear old log files
/logs config                        - View logging configuration

Prefix commands: !log <subcommand> (same functionality)

USAGE BY OTHER COGS:

# Basic logging
# Define the enums locally to avoid import issues
class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class LogType(Enum):
    GENERAL = "general"
    COG = "cogs"
    EVENT = "events"

class MyCog(commands.Cog):
    @commands.command()
    async def example(self, ctx):
        # Log with different levels
        await self.bot.log.log(LogLevel.INFO, "User performed action", ctx.guild, ctx.author)
        await self.bot.log.log(LogLevel.ERROR, "Something failed", ctx.guild, ctx.author)
        
        # Log to custom cog file
        await self.bot.log.log(
            LogLevel.INFO, 
            "Cog-specific action", 
            ctx.guild, 
            ctx.author,
            LogType.COG,
            file_override="my_cog_name"  # Creates logs/cogs/my_cog_name/
        )
        
        # Log events with custom fields
        await self.bot.log.log_event(
            "custom_action",
            "User performed custom action",
            ctx.guild,
            embed_fields=[
                {"name": "Action", "value": "Custom", "inline": True},
                {"name": "Result", "value": "Success", "inline": True}
            ]
        )

TRACKED EVENTS:
• Message operations: delete, edit, bulk delete
• Member events: join, leave, kick, ban, unban, updates (nickname, roles, avatar)
• Channel events: create, delete, update (name, topic, permissions, nsfw, slowmode)
• Role events: create, delete, update (name, color, permissions, hoist, mentionable)
• Voice events: join, leave, move channels
• Guild events: update (name, icon, banner, description, verification)
• Other: emoji updates, invites, webhooks, threads, audit log integration

FEATURES:
• Granular per-channel exclusion controls (exclude specific events or all events)
• Automatic file organization by date and cog (logs/cogs/cogname/MM-DD-YYYY.log)
• Enhanced audit log integration with caching and improved timing
• Discord channel logging with rich embeds and event-specific colors
• Custom log channels for different cogs/systems
• Export functionality for channel history
• Automatic log rotation and cleanup
• Comprehensive permission system integration
• Real-time event exclusion checking for performance
• Diff generation for message edits with intelligent formatting
• Both slash and prefix command support with autocomplete
• Complete channel exclusion vs selective event exclusion
• Improved kick/ban detection with extended audit log timeframes
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Union, TextIO
from pathlib import Path
import aiofiles
from enum import Enum
import difflib

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class LogType(Enum):
    GENERAL = "general"
    COG = "cogs"
    EVENT = "events"

class LogManager:
    """Centralized logging manager for the bot"""
    
    def __init__(self, bot):
        self.bot = bot
        self.data_file = "src/config/logging_config.json"
        self.logs_dir = Path("src/logs")
        self.logs_dir.mkdir(exist_ok=True)
        
        # Create subdirectories
        (self.logs_dir / "events").mkdir(exist_ok=True)
        (self.logs_dir / "cogs").mkdir(exist_ok=True)
        (self.logs_dir / "exports").mkdir(exist_ok=True)
        
        self.data = self.load_data()
        
        # In-memory tracking of custom logs (not saved to config)
        self.custom_logs = {}  # {custom_log_name: {"initialized": True, "channel_id": None}}
        
        # File handles for different log types
        self.file_handles = {}
        
        # Setup logging formatters
        self.setup_formatters()
        
        # Cache for recent audit log entries to avoid rate limits
        self.audit_cache = {}
        self.audit_cache_timeout = 30  # seconds
    
    def load_data(self) -> Dict[str, Any]:
        """Load logging configuration"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    # Ensure all expected keys exist
                    if "guilds" not in data:
                        data["guilds"] = {}
                    return data
        except Exception as e:
            print(f"Error loading logging config: {e}")
        return {"guilds": {}}
    
    def save_data(self):
        """Save logging configuration"""
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"Error saving logging config: {e}")
    
    def get_guild_data(self, guild_id: int) -> Dict[str, Any]:
        """Get or create guild logging data"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.data["guilds"]:
            self.data["guilds"][guild_id_str] = {
                "config": {
                    "enabled": True,
                    "log_to_file": True,
                    "log_to_channel": False,
                    "channels": {
                        "general": None,
                        "events": None,
                        "cogs": None
                    },
                    "custom_log_channels": {},  # Only custom log channels are saved here
                    "excluded_channels": [],  # Channel IDs to exclude completely from logging
                    "channel_event_exclusions": {},  # Per-channel event exclusions: {channel_id: [event_types]}
                    "file_logging": {
                        "max_size_mb": 10,
                        "backup_count": 5,
                        "separate_files": True
                    },
                    "events": {
                        "message_delete": True,
                        "message_edit": True,
                        "bulk_message_delete": True,
                        "member_join": True,
                        "member_remove": True,
                        "member_update": True,
                        "member_update_nickname": True,
                        "member_update_roles": True,
                        "member_update_avatar": True,
                        "member_ban": True,
                        "member_unban": True,
                        "guild_channel_create": True,
                        "guild_channel_delete": True,
                        "guild_channel_update": True,
                        "guild_channel_update_name": True,
                        "guild_channel_update_topic": True,
                        "guild_channel_update_nsfw": True,
                        "guild_channel_update_slowmode": True,
                        "guild_channel_update_permissions": True,
                        "guild_role_create": True,
                        "guild_role_delete": True,
                        "guild_role_update": True,
                        "guild_role_update_name": True,
                        "guild_role_update_color": True,
                        "guild_role_update_permissions": True,
                        "guild_role_update_hoist": True,
                        "guild_role_update_mentionable": True,
                        "voice_state_update": True,
                        "guild_update": True,
                        "guild_update_name": True,
                        "guild_update_icon": True,
                        "guild_update_banner": True,
                        "guild_update_description": True,
                        "guild_update_verification": True,
                        "guild_emojis_update": True,
                        "invite_create": True,
                        "invite_delete": True,
                        "webhook_update": True,
                        "integration_create": True,
                        "integration_update": True,
                        "integration_delete": True,
                        "stage_instance_create": True,
                        "stage_instance_delete": True,
                        "stage_instance_update": True,
                        "thread_create": True,
                        "thread_delete": True,
                        "thread_update": True,
                        "thread_update_name": True,
                        "thread_update_locked": True,
                        "thread_update_archived": True,
                        "thread_member_join": True,
                        "member_kick": True,
                        "thread_member_remove": True
                    }
                }
            }
            self.save_data()
        return self.data["guilds"][guild_id_str]
    
    def setup_formatters(self):
        """Setup log formatters"""
        self.formatters = {
            "file": "[{timestamp}] [{level}] [{guild}] [{user}] {message}",
            "discord": "**[{level}]** `{timestamp}` {message}",
            "event": "[{timestamp}] [{event_type}] [{guild}] {details}"
        }
    
    def is_channel_excluded(self, guild_id: int, channel_id: int) -> bool:
        """Check if a channel is completely excluded from logging"""
        try:
            guild_data = self.get_guild_data(guild_id)
            return channel_id in guild_data["config"]["excluded_channels"]
        except Exception as e:
            print(f"Error checking channel exclusion: {e}")
            return False
    
    def is_channel_event_excluded(self, guild_id: int, channel_id: int, event_type: str) -> bool:
        """Check if a specific event type is excluded for a channel"""
        try:
            guild_data = self.get_guild_data(guild_id)
            channel_exclusions = guild_data["config"]["channel_event_exclusions"].get(str(channel_id), [])
            return event_type in channel_exclusions
        except Exception as e:
            print(f"Error checking channel event exclusion: {e}")
            return False
    
    def is_event_enabled(self, guild_id: int, event_type: str) -> bool:
        """Check if an event type is globally enabled for logging"""
        try:
            guild_data = self.get_guild_data(guild_id)
            return guild_data["config"]["events"].get(event_type, True)
        except Exception as e:
            print(f"Error checking event enabled: {e}")
            return True
    
    def should_log_event(self, guild_id: int, event_type: str, channel_id: Optional[int] = None) -> bool:
        """
        Comprehensive check if an event should be logged.
        Checks: global enable, channel exclusion, and specific event exclusion
        """
        try:
            # Check if event type is globally enabled
            if not self.is_event_enabled(guild_id, event_type):
                return False
            
            # If no channel involved, just check global setting
            if channel_id is None:
                return True
            
            # Check if channel is completely excluded
            if self.is_channel_excluded(guild_id, channel_id):
                return False
            
            # Check if this specific event is excluded for this channel
            if self.is_channel_event_excluded(guild_id, channel_id, event_type):
                return False
            
            return True
        except Exception as e:
            print(f"Error in should_log_event: {e}")
            return True  # Default to logging if there's an error
    
    def _initialize_custom_log(self, custom_log_name: str):
        """Initialize a custom log in memory if not already initialized"""
        if custom_log_name not in self.custom_logs:
            self.custom_logs[custom_log_name] = {
                "initialized": True,
                "channel_id": None
            }
            print(f"Initialized custom log: {custom_log_name}")
    
    def set_custom_log_channel(self, guild_id: int, custom_log_name: str, channel_id: Optional[int]):
        """Set channel for a custom log and save to config"""
        try:
            guild_data = self.get_guild_data(guild_id)
            
            if channel_id:
                guild_data["config"]["custom_log_channels"][custom_log_name] = channel_id
            else:
                guild_data["config"]["custom_log_channels"].pop(custom_log_name, None)
            
            self.save_data()
            
            # Also update memory
            if custom_log_name in self.custom_logs:
                self.custom_logs[custom_log_name]["channel_id"] = channel_id
        except Exception as e:
            print(f"Error setting custom log channel: {e}")
    
    def add_excluded_channel(self, guild_id: int, channel_id: int):
        """Add a channel to the complete exclusion list"""
        try:
            guild_data = self.get_guild_data(guild_id)
            if channel_id not in guild_data["config"]["excluded_channels"]:
                guild_data["config"]["excluded_channels"].append(channel_id)
                self.save_data()
                print(f"Added channel {channel_id} to excluded list for guild {guild_id}")
        except Exception as e:
            print(f"Error adding excluded channel: {e}")
    
    def remove_excluded_channel(self, guild_id: int, channel_id: int):
        """Remove a channel from the complete exclusion list"""
        try:
            guild_data = self.get_guild_data(guild_id)
            if channel_id in guild_data["config"]["excluded_channels"]:
                guild_data["config"]["excluded_channels"].remove(channel_id)
                self.save_data()
                print(f"Removed channel {channel_id} from excluded list for guild {guild_id}")
        except Exception as e:
            print(f"Error removing excluded channel: {e}")
    
    def add_channel_event_exclusion(self, guild_id: int, channel_id: int, event_type: str):
        """Add a specific event exclusion for a channel"""
        try:
            guild_data = self.get_guild_data(guild_id)
            channel_id_str = str(channel_id)
            
            if channel_id_str not in guild_data["config"]["channel_event_exclusions"]:
                guild_data["config"]["channel_event_exclusions"][channel_id_str] = []
            
            if event_type not in guild_data["config"]["channel_event_exclusions"][channel_id_str]:
                guild_data["config"]["channel_event_exclusions"][channel_id_str].append(event_type)
                self.save_data()
        except Exception as e:
            print(f"Error adding channel event exclusion: {e}")
    
    def remove_channel_event_exclusion(self, guild_id: int, channel_id: int, event_type: str):
        """Remove a specific event exclusion for a channel"""
        try:
            guild_data = self.get_guild_data(guild_id)
            channel_id_str = str(channel_id)
            
            if (channel_id_str in guild_data["config"]["channel_event_exclusions"] and
                event_type in guild_data["config"]["channel_event_exclusions"][channel_id_str]):
                guild_data["config"]["channel_event_exclusions"][channel_id_str].remove(event_type)
                
                # Clean up empty lists
                if not guild_data["config"]["channel_event_exclusions"][channel_id_str]:
                    del guild_data["config"]["channel_event_exclusions"][channel_id_str]
                
                self.save_data()
        except Exception as e:
            print(f"Error removing channel event exclusion: {e}")
    
    def get_channel_event_exclusions(self, guild_id: int, channel_id: int) -> List[str]:
        """Get list of excluded events for a channel"""
        try:
            guild_data = self.get_guild_data(guild_id)
            return guild_data["config"]["channel_event_exclusions"].get(str(channel_id), [])
        except Exception as e:
            print(f"Error getting channel event exclusions: {e}")
            return []
    
    def set_event_enabled(self, guild_id: int, event_type: str, enabled: bool):
        """Enable or disable a specific event type globally"""
        try:
            guild_data = self.get_guild_data(guild_id)
            guild_data["config"]["events"][event_type] = enabled
            self.save_data()
        except Exception as e:
            print(f"Error setting event enabled: {e}")
    
    def truncate_text(self, text: str, max_length: int = 1000) -> str:
        """Truncate text with ellipsis if too long"""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."
    
    def format_message_content(self, message: discord.Message) -> str:
        """Format message content with attachments and embeds info"""
        content_parts = []
        
        if message.content:
            content_parts.append(f"Content: {self.truncate_text(message.content)}")
        
        if message.attachments:
            attachments = ", ".join([f"{att.filename} ({att.size} bytes)" for att in message.attachments])
            content_parts.append(f"Attachments: {attachments}")
        
        if message.embeds:
            content_parts.append(f"Embeds: {len(message.embeds)} embed(s)")
        
        if message.reactions:
            reactions = ", ".join([f"{reaction.emoji} ({reaction.count})" for reaction in message.reactions])
            content_parts.append(f"Reactions: {reactions}")
        
        return " | ".join(content_parts) if content_parts else "[No content]"
    
    def create_diff(self, old_text: str, new_text: str) -> str:
        """Create a diff between old and new text"""
        if old_text == new_text:
            return "No changes detected"
        
        # For short texts, show them directly
        if len(old_text) <= 100 and len(new_text) <= 100:
            return f"**Before:** {old_text}\n**After:** {new_text}"
        
        # For longer texts, try to show a meaningful diff
        old_lines = old_text.split('\n')
        new_lines = new_text.split('\n')
        
        diff = list(difflib.unified_diff(
            old_lines, 
            new_lines, 
            fromfile='before', 
            tofile='after', 
            lineterm='',
            n=2
        ))
        
        if len(diff) <= 20:  # If diff is reasonable length
            diff_text = '\n'.join(diff[2:])  # Skip the file headers
            return f"```diff\n{diff_text}\n```"
        else:
            # Fall back to truncated before/after
            return f"**Before:** {self.truncate_text(old_text, 200)}\n**After:** {self.truncate_text(new_text, 200)}"
    
    async def get_audit_entry(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None, max_age_seconds: int = 10) -> Optional[discord.AuditLogEntry]:
        """Get recent audit log entry with caching and improved reliability"""
        cache_key = f"{guild.id}_{action.value}_{target_id or 'none'}"
        current_time = datetime.now()
        
        # Check cache first
        if cache_key in self.audit_cache:
            cached_entry, cache_time = self.audit_cache[cache_key]
            if (current_time - cache_time).total_seconds() < self.audit_cache_timeout:
                return cached_entry
        
        try:
            # Increased limit for better detection
            async for entry in guild.audit_logs(limit=20, action=action):
                entry_age = (current_time - entry.created_at.replace(tzinfo=None)).total_seconds()
                
                if entry_age > max_age_seconds:
                    break
                
                if target_id is None or (hasattr(entry.target, 'id') and entry.target.id == target_id):
                    # Cache the result
                    self.audit_cache[cache_key] = (entry, current_time)
                    return entry
            
            # Cache None result to avoid repeated API calls
            self.audit_cache[cache_key] = (None, current_time)
            return None
            
        except discord.Forbidden:
            return None
        except Exception as e:
            print(f"Error getting audit log entry: {e}")
            return None
    
    async def log(self, 
                    level: LogLevel, 
                    message: str, 
                    guild: Optional[discord.Guild] = None,
                    user: Optional[Union[discord.Member, discord.User]] = None,
                    log_type: LogType = LogType.GENERAL,
                    channel_override: Optional[discord.TextChannel] = None,
                    file_override: Optional[str] = None,
                    send_to_discord: bool = True):
        """Main logging function"""
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        guild_name = guild.name if guild else "DM"
        user_name = str(user) if user else "System"
        
        # Format message for file
        file_message = self.formatters["file"].format(
            timestamp=timestamp,
            level=level.value,
            guild=guild_name,
            user=user_name,
            message=message
        )
        
        # Handle custom logs (file_override)
        if file_override:
            # Initialize custom log if not already done
            self._initialize_custom_log(file_override)
            
            # Write to custom log file
            await self._write_to_file(file_message, LogType.COG, file_override)
            
            # Send to custom log channel if configured
            if send_to_discord and guild:
                await self._send_to_custom_log_channel(level, message, guild, file_override)
        else:
            # Write to standard log file
            await self._write_to_file(file_message, log_type, file_override)
            
            # Send to Discord channel if enabled
            if send_to_discord and guild:
                await self._send_to_discord(level, message, guild, log_type, channel_override)
    
    async def log_event(self,
                        event_type: str,
                        details: str,
                        guild: discord.Guild,
                        embed_fields: Optional[List[Dict[str, Any]]] = None,
                        send_to_discord: bool = True,
                        channel_id: Optional[int] = None):
        """Log server events with enhanced formatting and granular checking"""
        
        # Use comprehensive check that includes channel exclusions
        if not self.should_log_event(guild.id, event_type, channel_id):
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format event message
        event_message = self.formatters["event"].format(
            timestamp=timestamp,
            event_type=event_type,
            guild=guild.name,
            details=details
        )
        
        # Write to events log
        await self._write_to_file(event_message, LogType.EVENT)
        
        # Send to Discord if enabled
        if send_to_discord:
            await self._send_enhanced_event_to_discord(
                event_type, 
                details, 
                guild, 
                embed_fields
            )
    
    async def _write_to_file(self, message: str, log_type: LogType, file_override: Optional[str] = None):
        """Write message to appropriate log file"""
        
        if log_type == LogType.GENERAL:
            # General logs go to a single file
            file_path = self.logs_dir / "general_logs.log"
        elif log_type == LogType.EVENT:
            # Events go to dated files in events folder
            date_str = datetime.now().strftime("%m-%d-%Y")
            file_path = self.logs_dir / "events" / f"{date_str}.log"
        elif log_type == LogType.COG:
            # Cogs go to dated files in cog-specific folders
            if file_override:
                date_str = datetime.now().strftime("%m-%d-%Y")
                cog_dir = self.logs_dir / "cogs" / file_override
                cog_dir.mkdir(exist_ok=True)
                file_path = cog_dir / f"{date_str}.log"
            else:
                # Fallback to general if no file_override specified
                file_path = self.logs_dir / "general_logs.log"
        
        try:
            async with aiofiles.open(file_path, 'a', encoding='utf-8') as f:
                await f.write(f"{message}\n")
        except Exception as e:
            print(f"Error writing to log file {file_path}: {e}")
    
    async def _send_to_custom_log_channel(self, level: LogLevel, message: str, guild: discord.Guild, custom_log_name: str):
        """Send custom log message to configured channel"""
        
        # Check if channel is configured for this custom log
        guild_data = self.get_guild_data(guild.id)
        channel_id = guild_data["config"]["custom_log_channels"].get(custom_log_name)
        
        if not channel_id:
            return
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        
        # Create embed
        color_map = {
            LogLevel.DEBUG: discord.Color.light_grey(),
            LogLevel.INFO: discord.Color.blue(),
            LogLevel.WARNING: discord.Color.orange(),
            LogLevel.ERROR: discord.Color.red(),
            LogLevel.CRITICAL: discord.Color.dark_red()
        }
        
        embed = discord.Embed(
            description=message,
            color=color_map.get(level, discord.Color.blue()),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Custom Log: {custom_log_name}")
        
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass  # Bot doesn't have permission to send messages
        except Exception as e:
            print(f"Error sending custom log to Discord: {e}")
    
    async def _send_to_discord(self,
                                level: LogLevel,
                                message: str,
                                guild: discord.Guild,
                                log_type: LogType,
                                channel_override: Optional[discord.TextChannel] = None):
        """Send log message to Discord channel"""
        
        guild_data = self.get_guild_data(guild.id)
        
        if not guild_data["config"]["log_to_channel"]:
            return
        
        # Determine which channel to use
        channel = None
        if channel_override:
            channel = channel_override
        else:
            channel_id = guild_data["config"]["channels"].get(log_type.value)
            if channel_id:
                channel = self.bot.get_channel(channel_id)
        
        if not channel:
            return
        
        # Create embed based on log level
        color_map = {
            LogLevel.DEBUG: discord.Color.light_grey(),
            LogLevel.INFO: discord.Color.blue(),
            LogLevel.WARNING: discord.Color.orange(),
            LogLevel.ERROR: discord.Color.red(),
            LogLevel.CRITICAL: discord.Color.dark_red()
        }
        
        embed = discord.Embed(
            description=message,
            color=color_map.get(level, discord.Color.blue()),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Log Type: {log_type.value.title()}")
        
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass  # Bot doesn't have permission to send messages
        except Exception as e:
            print(f"Error sending log to Discord: {e}")
    
    async def _send_enhanced_event_to_discord(self,
                                            event_type: str,
                                            details: str,
                                            guild: discord.Guild,
                                            embed_fields: Optional[List[Dict[str, Any]]] = None):
        """Send enhanced event message to Discord channel"""
        
        guild_data = self.get_guild_data(guild.id)
        
        if not guild_data["config"]["log_to_channel"]:
            return
        
        channel_id = guild_data["config"]["channels"].get("events")
        if not channel_id:
            return
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        
        # Event type to emoji mapping
        event_emojis = {
            "message_delete": "🗑️",
            "message_edit": "✏️",
            "bulk_message_delete": "🧹",
            "member_join": "📥",
            "member_leave": "📤",
            "member_kick": "🥾",
            "member_ban": "🔨",
            "member_unban": "🔓",
            "member_update": "👤",
            "guild_channel_create": "🆕",
            "guild_channel_delete": "❌",
            "guild_channel_update": "🔧",
            "guild_role_create": "🎭",
            "guild_role_delete": "🗑️",
            "guild_role_update": "🔧",
            "voice_state_update": "🔊",
            "guild_update": "🏠",
            "guild_emojis_update": "😀",
            "invite_create": "📨",
            "invite_delete": "📪",
            "thread_create": "🧵",
            "thread_delete": "✂️",
            "thread_update": "🔧"
        }
        
        # Event type to color mapping
        event_colors = {
            "message_delete": discord.Color.red(),
            "message_edit": discord.Color.blue(),
            "bulk_message_delete": discord.Color.dark_red(),
            "member_join": discord.Color.green(),
            "member_leave": discord.Color.orange(),
            "member_kick": discord.Color.red(),
            "member_ban": discord.Color.dark_red(),
            "member_unban": discord.Color.green(),
            "member_update": discord.Color.blue(),
            "guild_channel_create": discord.Color.green(),
            "guild_channel_delete": discord.Color.red(),
            "guild_channel_update": discord.Color.blue(),
            "guild_role_create": discord.Color.green(),
            "guild_role_delete": discord.Color.red(),
            "guild_role_update": discord.Color.blue(),
            "voice_state_update": discord.Color.blue(),
            "guild_update": discord.Color.blue(),
            "guild_emojis_update": discord.Color.gold(),
            "invite_create": discord.Color.green(),
            "invite_delete": discord.Color.red(),
            "thread_create": discord.Color.green(),
            "thread_delete": discord.Color.red(),
            "thread_update": discord.Color.blue()
        }
        
        emoji = event_emojis.get(event_type, "📋")
        color = event_colors.get(event_type, discord.Color.blue())
        
        embed = discord.Embed(
            title=f"{emoji} {event_type.replace('_', ' ').title()}",
            description=details,
            color=color,
            timestamp=datetime.now()
        )
        
        # Add additional fields if provided
        if embed_fields:
            for field in embed_fields:
                embed.add_field(
                    name=field.get("name", "Details"),
                    value=field.get("value", "N/A"),
                    inline=field.get("inline", True)
                )
        
        embed.set_footer(text=f"Guild: {guild.name}")
        
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass  # Bot doesn't have permission to send messages
        except Exception as e:
            print(f"Error sending event log to Discord: {e}")
    
    async def export_channel_logs(self, 
                                    channel: discord.TextChannel, 
                                    limit: Optional[int] = None) -> str:
        """Export channel logs to a file"""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"channel_export_{channel.id}_{timestamp}.txt"
        filepath = self.logs_dir / "exports" / filename
        
        try:
            async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
                await f.write(f"Channel Export: #{channel.name} ({channel.id})\n")
                await f.write(f"Guild: {channel.guild.name} ({channel.guild.id})\n")
                await f.write(f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                await f.write("=" * 50 + "\n\n")
                
                message_count = 0
                async for message in channel.history(limit=limit, oldest_first=True):
                    timestamp_str = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    
                    await f.write(f"[{timestamp_str}] {message.author}: {message.content}\n")
                    
                    if message.attachments:
                        for attachment in message.attachments:
                            await f.write(f"    Attachment: {attachment.filename} ({attachment.url})\n")
                    
                    if message.embeds:
                        await f.write(f"    Embeds: {len(message.embeds)} embed(s)\n")
                    
                    await f.write("\n")
                    message_count += 1
                
                await f.write(f"\nTotal Messages Exported: {message_count}")
            
            return str(filepath)
        
        except Exception as e:
            raise Exception(f"Failed to export channel logs: {e}")
    
    async def clear_logs(self, log_type: LogType, days_older_than: int = 30):
        """Clear old log files"""
        
        cutoff_date = datetime.now() - timedelta(days=days_older_than)
        cleared_files = []
        
        if log_type == LogType.GENERAL:
            # For general logs, we don't clear the main file, but we could implement rotation
            return cleared_files
        elif log_type == LogType.EVENT:
            log_dir = self.logs_dir / "events"
        elif log_type == LogType.COG:
            log_dir = self.logs_dir / "cogs"
        
        for file_path in log_dir.rglob("*.log"):
            try:
                # Parse date from filename
                date_str = file_path.stem
                file_date = datetime.strptime(date_str, "%m-%d-%Y")
                
                if file_date < cutoff_date:
                    file_path.unlink()
                    cleared_files.append(str(file_path.relative_to(self.logs_dir)))
            
            except (ValueError, OSError):
                continue  # Skip files that don't match expected format
        
        return cleared_files

class LoggingCog(commands.Cog):
    """Enhanced comprehensive logging system with granular per-channel controls"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Create and attach LogManager to bot
        self.bot.log = LogManager(bot)
        
        # Add logging permission to permission mappings if permissions cog exists
        self.setup_permissions()
    
    def setup_permissions(self):
        """Setup logging permissions in the permissions cog"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if permissions_cog:
            # Add logging permissions to the permission roles
            for guild_id_str, guild_data in permissions_cog.data.get("guilds", {}).items():
                config = guild_data.get("config", {})
            
            permissions_cog.save_data()
    
    def has_log_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has log admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.logadmin') or permissions_cog.has_permission(member, 'permissions.omni'))
    
    def has_manager_permission(self, member: discord.Member) -> bool:
        """Check if member has manager permission (for clearing logs)"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return member.guild_permissions.administrator
    
    # ==================== EVENT LISTENERS ====================
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Enhanced message deletion logging"""
        if message.author.bot or not message.guild:
            return
        
        # Check if we should log this event for this channel
        if not self.bot.log.should_log_event(message.guild.id, "message_delete", message.channel.id):
            return
        
        # Get who deleted the message from audit logs
        audit_entry = await self.bot.log.get_audit_entry(
            message.guild, 
            discord.AuditLogAction.message_delete,
            target_id=message.author.id
        )
        
        # Format message content
        content_info = self.bot.log.format_message_content(message)
        
        if audit_entry and audit_entry.target.id == message.author.id:
            deleter = audit_entry.user
            details = f"Message by **{message.author}** deleted by **{deleter}** in {message.channel.mention}"
            if audit_entry.reason:
                details += f"\n**Reason:** {audit_entry.reason}"
        else:
            details = f"Message by **{message.author}** deleted in {message.channel.mention}"
        
        embed_fields = [
            {
                "name": "Message Content",
                "value": content_info,
                "inline": False
            },
            {
                "name": "Author",
                "value": f"{message.author.mention} ({message.author.id})",
                "inline": True
            },
            {
                "name": "Channel",
                "value": f"{message.channel.mention}",
                "inline": True
            },
            {
                "name": "Message ID",
                "value": str(message.id),
                "inline": True
            }
        ]
        
        if message.created_at:
            embed_fields.append({
                "name": "Message Created",
                "value": message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "inline": True
            })
        
        await self.bot.log.log_event("message_delete", details, message.guild, embed_fields, channel_id=message.channel.id)
    
    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        """Enhanced bulk message deletion logging"""
        if not messages:
            return
        
        channel = messages[0].channel
        guild = channel.guild
        
        # Check if we should log this event for this channel
        if not self.bot.log.should_log_event(guild.id, "bulk_message_delete", channel.id):
            return
        
        # Get who deleted the messages from audit logs
        audit_entry = await self.bot.log.get_audit_entry(
            guild, 
            discord.AuditLogAction.message_bulk_delete
        )
        
        # Count messages by author
        author_counts = {}
        total_chars = 0
        for msg in messages:
            if not msg.author.bot:
                author_counts[msg.author] = author_counts.get(msg.author, 0) + 1
                total_chars += len(msg.content) if msg.content else 0
        
        if audit_entry:
            deleter = audit_entry.user
            details = f"**{len(messages)} messages** bulk deleted by **{deleter}** in {channel.mention}"
            if audit_entry.reason:
                details += f"\n**Reason:** {audit_entry.reason}"
        else:
            details = f"**{len(messages)} messages** bulk deleted in {channel.mention}"
        
        embed_fields = [
            {
                "name": "Messages Deleted",
                "value": str(len(messages)),
                "inline": True
            },
            {
                "name": "Channel",
                "value": channel.mention,
                "inline": True
            },
            {
                "name": "Total Characters",
                "value": f"{total_chars:,}",
                "inline": True
            }
        ]
        
        if author_counts:
            authors_info = []
            for author, count in sorted(author_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                authors_info.append(f"{author}: {count}")
            
            embed_fields.append({
                "name": "Top Authors",
                "value": "\n".join(authors_info),
                "inline": False
            })
        
        await self.bot.log.log_event("bulk_message_delete", details, guild, embed_fields, channel_id=channel.id)
    
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Enhanced message edit logging"""
        if before.author.bot or before.content == after.content or not before.guild:
            return
        
        # Check if we should log this event for this channel
        if not self.bot.log.should_log_event(before.guild.id, "message_edit", before.channel.id):
            return
        
        # Create diff between old and new content
        diff_text = self.bot.log.create_diff(before.content, after.content)
        
        details = f"Message by **{before.author}** edited in {before.channel.mention}"
        
        embed_fields = [
            {
                "name": "Changes",
                "value": diff_text,
                "inline": False
            },
            {
                "name": "Author",
                "value": f"{before.author.mention} ({before.author.id})",
                "inline": True
            },
            {
                "name": "Channel",
                "value": f"{before.channel.mention}",
                "inline": True
            },
            {
                "name": "Message ID",
                "value": str(before.id),
                "inline": True
            }
        ]
        
        # Add link to message if possible
        embed_fields.append({
            "name": "Jump to Message",
            "value": f"[Click here]({after.jump_url})",
            "inline": True
        })
        
        await self.bot.log.log_event("message_edit", details, before.guild, embed_fields, channel_id=before.channel.id)
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Enhanced member join logging"""
        # Check if we should log this event
        if not self.bot.log.should_log_event(member.guild.id, "member_join"):
            return
        
        # Calculate account age
        account_age = datetime.now() - member.created_at.replace(tzinfo=None)
        
        details = f"**{member}** joined the server"
        
        embed_fields = [
            {
                "name": "User",
                "value": f"{member.mention} ({member.id})",
                "inline": True
            },
            {
                "name": "Account Created",
                "value": member.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "inline": True
            },
            {
                "name": "Account Age",
                "value": f"{account_age.days} days",
                "inline": True
            },
            {
                "name": "Member Count",
                "value": str(member.guild.member_count),
                "inline": True
            }
        ]
        
        # Check if account is suspiciously new
        if account_age.days < 7:
            embed_fields.append({
                "name": "⚠️ Warning",
                "value": "Account is less than 7 days old",
                "inline": False
            })
        
        await self.bot.log.log_event("member_join", details, member.guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Enhanced member leave/kick logging with improved kick detection"""
        guild = member.guild
        
        # Wait longer for audit log to be created
        await asyncio.sleep(3)
        
        # Check for kick in audit logs with longer timeframe
        kick_entry = await self.bot.log.get_audit_entry(
            guild, 
            discord.AuditLogAction.kick,
            target_id=member.id,
            max_age_seconds=20
        )
        
        # Also check for ban (in case of ban + immediate unban)
        ban_entry = await self.bot.log.get_audit_entry(
            guild, 
            discord.AuditLogAction.ban,
            target_id=member.id,
            max_age_seconds=20
        )
        
        # Calculate how long they were in the server
        join_duration = datetime.now() - member.joined_at.replace(tzinfo=None) if member.joined_at else None
        
        embed_fields = [
            {
                "name": "User",
                "value": f"{member.mention} ({member.id})",
                "inline": True
            },
            {
                "name": "Member Count",
                "value": str(guild.member_count),
                "inline": True
            }
        ]
        
        if join_duration:
            embed_fields.append({
                "name": "Time in Server",
                "value": f"{join_duration.days} days, {join_duration.seconds // 3600} hours",
                "inline": True
            })
        
        if member.roles and len(member.roles) > 1:  # Exclude @everyone
            roles = [role.mention for role in member.roles[1:]][:5]  # Show top 5 roles
            embed_fields.append({
                "name": "Roles",
                "value": ", ".join(roles),
                "inline": False
            })
        
        # Improved kick detection logic
        if kick_entry and hasattr(kick_entry.target, 'id') and kick_entry.target.id == member.id:
            # Check if we should log kick events
            if not self.bot.log.should_log_event(guild.id, "member_kick"):
                return
            
            details = f"**{member}** was kicked by **{kick_entry.user}**"
            if kick_entry.reason:
                details += f"\n**Reason:** {kick_entry.reason}"
            
            embed_fields.append({
                "name": "Kicked By",
                "value": f"{kick_entry.user.mention} ({kick_entry.user.id})",
                "inline": True
            })
            
            if kick_entry.reason:
                embed_fields.append({
                    "name": "Reason",
                    "value": kick_entry.reason,
                    "inline": False
                })
            
            await self.bot.log.log_event("member_kick", details, guild, embed_fields)
        
        elif ban_entry and hasattr(ban_entry.target, 'id') and ban_entry.target.id == member.id:
            # Check if we should log ban events
            if not self.bot.log.should_log_event(guild.id, "member_ban"):
                return
            
            # This was actually a ban, not a leave - but still log as removal since they left
            details = f"**{member}** was banned by **{ban_entry.user}**"
            if ban_entry.reason:
                details += f"\n**Reason:** {ban_entry.reason}"
            
            embed_fields.append({
                "name": "Banned By",
                "value": f"{ban_entry.user.mention} ({ban_entry.user.id})",
                "inline": True
            })
            
            if ban_entry.reason:
                embed_fields.append({
                    "name": "Reason",
                    "value": ban_entry.reason,
                    "inline": False
                })
            
            await self.bot.log.log_event("member_ban", details, guild, embed_fields)
        
        else:
            # Check if we should log member remove events
            if not self.bot.log.should_log_event(guild.id, "member_remove"):
                return
            
            # Regular leave
            details = f"**{member}** left the server"
            await self.bot.log.log_event("member_remove", details, guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Enhanced member update logging with granular controls"""
        changes = []
        embed_fields = []
        
        # Nickname changes
        if before.nick != after.nick:
            if self.bot.log.should_log_event(after.guild.id, "member_update_nickname"):
                changes.append("nickname")
                embed_fields.append({
                    "name": "Nickname Change",
                    "value": f"**Before:** {before.nick or 'None'}\n**After:** {after.nick or 'None'}",
                    "inline": True
                })
        
        # Role changes
        if before.roles != after.roles:
            if self.bot.log.should_log_event(after.guild.id, "member_update_roles"):
                added_roles = set(after.roles) - set(before.roles)
                removed_roles = set(before.roles) - set(after.roles)
                
                if added_roles:
                    changes.append("roles added")
                    role_mentions = [role.mention for role in added_roles]
                    embed_fields.append({
                        "name": "Roles Added",
                        "value": ", ".join(role_mentions),
                        "inline": False
                    })
                
                if removed_roles:
                    changes.append("roles removed")
                    role_mentions = [role.mention for role in removed_roles]
                    embed_fields.append({
                        "name": "Roles Removed",
                        "value": ", ".join(role_mentions),
                        "inline": False
                    })
        
        # Avatar changes (if different from user avatar)
        if getattr(before, 'avatar', None) != getattr(after, 'avatar', None):
            if self.bot.log.should_log_event(after.guild.id, "member_update_avatar"):
                changes.append("avatar")
                embed_fields.append({
                    "name": "Avatar Changed",
                    "value": "User updated their server avatar",
                    "inline": True
                })
        
        if changes and self.bot.log.should_log_event(after.guild.id, "member_update"):
            details = f"**{after}** updated: {', '.join(changes)}"
            
            embed_fields.insert(0, {
                "name": "User",
                "value": f"{after.mention} ({after.id})",
                "inline": True
            })
            
            await self.bot.log.log_event("member_update", details, after.guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Enhanced member ban logging"""
        # Check if we should log ban events
        if not self.bot.log.should_log_event(guild.id, "member_ban"):
            return
        
        # Wait for audit log
        await asyncio.sleep(2)
        
        # Get ban details from audit logs
        ban_entry = await self.bot.log.get_audit_entry(
            guild, 
            discord.AuditLogAction.ban,
            target_id=user.id,
            max_age_seconds=15
        )
        
        if ban_entry and hasattr(ban_entry.target, 'id') and ban_entry.target.id == user.id:
            details = f"**{user}** was banned by **{ban_entry.user}**"
            if ban_entry.reason:
                details += f"\n**Reason:** {ban_entry.reason}"
            
            embed_fields = [
                {
                    "name": "Banned User",
                    "value": f"{user.mention} ({user.id})",
                    "inline": True
                },
                {
                    "name": "Banned By",
                    "value": f"{ban_entry.user.mention} ({ban_entry.user.id})",
                    "inline": True
                }
            ]
            
            if ban_entry.reason:
                embed_fields.append({
                    "name": "Reason",
                    "value": ban_entry.reason,
                    "inline": False
                })
        else:
            details = f"**{user}** was banned"
            embed_fields = [
                {
                    "name": "Banned User",
                    "value": f"{user.mention} ({user.id})",
                    "inline": True
                }
            ]
        
        await self.bot.log.log_event("member_ban", details, guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        """Enhanced member unban logging"""
        # Check if we should log unban events
        if not self.bot.log.should_log_event(guild.id, "member_unban"):
            return
        
        # Wait for audit log
        await asyncio.sleep(2)
        
        # Get unban details from audit logs
        unban_entry = await self.bot.log.get_audit_entry(
            guild, 
            discord.AuditLogAction.unban,
            target_id=user.id,
            max_age_seconds=15
        )
        
        if unban_entry and hasattr(unban_entry.target, 'id') and unban_entry.target.id == user.id:
            details = f"**{user}** was unbanned by **{unban_entry.user}**"
            if unban_entry.reason:
                details += f"\n**Reason:** {unban_entry.reason}"
            
            embed_fields = [
                {
                    "name": "Unbanned User",
                    "value": f"{user.mention} ({user.id})",
                    "inline": True
                },
                {
                    "name": "Unbanned By",
                    "value": f"{unban_entry.user.mention} ({unban_entry.user.id})",
                    "inline": True
                }
            ]
            
            if unban_entry.reason:
                embed_fields.append({
                    "name": "Reason",
                    "value": unban_entry.reason,
                    "inline": False
                })
        else:
            details = f"**{user}** was unbanned"
            embed_fields = [
                {
                    "name": "Unbanned User",
                    "value": f"{user.mention} ({user.id})",
                    "inline": True
                }
            ]
        
        await self.bot.log.log_event("member_unban", details, guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Enhanced channel creation logging"""
        # Check if we should log channel creation events
        if not self.bot.log.should_log_event(channel.guild.id, "guild_channel_create"):
            return
        
        # Get creation details from audit logs
        create_entry = await self.bot.log.get_audit_entry(
            channel.guild, 
            discord.AuditLogAction.channel_create
        )
        
        details = f"Channel {channel.mention} created"
        
        embed_fields = [
            {
                "name": "Channel",
                "value": f"{channel.mention} ({channel.id})",
                "inline": True
            },
            {
                "name": "Type",
                "value": str(channel.type).title(),
                "inline": True
            }
        ]
        
        if create_entry:
            embed_fields.append({
                "name": "Created By",
                "value": f"{create_entry.user.mention} ({create_entry.user.id})",
                "inline": True
            })
        
        if hasattr(channel, 'category') and channel.category:
            embed_fields.append({
                "name": "Category",
                "value": channel.category.name,
                "inline": True
            })
        
        await self.bot.log.log_event("guild_channel_create", details, channel.guild, embed_fields, channel_id=channel.id)
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Enhanced channel deletion logging"""
        # Check if we should log channel deletion events
        if not self.bot.log.should_log_event(channel.guild.id, "guild_channel_delete"):
            return
        
        # Get deletion details from audit logs
        delete_entry = await self.bot.log.get_audit_entry(
            channel.guild, 
            discord.AuditLogAction.channel_delete
        )
        
        details = f"Channel **#{channel.name}** deleted"
        
        embed_fields = [
            {
                "name": "Channel Name",
                "value": f"#{channel.name} ({channel.id})",
                "inline": True
            },
            {
                "name": "Type",
                "value": str(channel.type).title(),
                "inline": True
            }
        ]
        
        if delete_entry:
            embed_fields.append({
                "name": "Deleted By",
                "value": f"{delete_entry.user.mention} ({delete_entry.user.id})",
                "inline": True
            })
        
        if hasattr(channel, 'category') and channel.category:
            embed_fields.append({
                "name": "Category",
                "value": channel.category.name,
                "inline": True
            })
        
        await self.bot.log.log_event("guild_channel_delete", details, channel.guild, embed_fields, channel_id=channel.id)
    
    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        """Enhanced channel update logging with granular controls"""
        changes = []
        embed_fields = []
        
        # Check each type of change individually with granular controls
        if before.name != after.name and self.bot.log.should_log_event(after.guild.id, "guild_channel_update_name", after.id):
            changes.append("name")
            embed_fields.append({
                "name": "Name Change",
                "value": f"**Before:** {before.name}\n**After:** {after.name}",
                "inline": True
            })
        
        if (getattr(before, 'topic', None) != getattr(after, 'topic', None) and 
            self.bot.log.should_log_event(after.guild.id, "guild_channel_update_topic", after.id)):
            changes.append("topic")
            before_topic = getattr(before, 'topic', None) or "None"
            after_topic = getattr(after, 'topic', None) or "None"
            embed_fields.append({
                "name": "Topic Change",
                "value": f"**Before:** {self.bot.log.truncate_text(before_topic, 200)}\n**After:** {self.bot.log.truncate_text(after_topic, 200)}",
                "inline": False
            })
        
        if (hasattr(before, 'nsfw') and before.nsfw != after.nsfw and 
            self.bot.log.should_log_event(after.guild.id, "guild_channel_update_nsfw", after.id)):
            changes.append("NSFW setting")
            embed_fields.append({
                "name": "NSFW Change",
                "value": f"**Before:** {before.nsfw}\n**After:** {after.nsfw}",
                "inline": True
            })
        
        if (hasattr(before, 'slowmode_delay') and before.slowmode_delay != after.slowmode_delay and 
            self.bot.log.should_log_event(after.guild.id, "guild_channel_update_slowmode", after.id)):
            changes.append("slowmode")
            embed_fields.append({
                "name": "Slowmode Change",
                "value": f"**Before:** {before.slowmode_delay}s\n**After:** {after.slowmode_delay}s",
                "inline": True
            })
        
        # Check for permission overwrites changes
        if (before.overwrites != after.overwrites and 
            self.bot.log.should_log_event(after.guild.id, "guild_channel_update_permissions", after.id)):
            changes.append("permissions")
            embed_fields.append({
                "name": "Permissions Changed",
                "value": "Channel permission overwrites were modified",
                "inline": True
            })
        
        if changes and self.bot.log.should_log_event(after.guild.id, "guild_channel_update", after.id):
            details = f"Channel {after.mention} updated: {', '.join(changes)}"
            
            embed_fields.insert(0, {
                "name": "Channel",
                "value": f"{after.mention} ({after.id})",
                "inline": True
            })
            
            await self.bot.log.log_event("guild_channel_update", details, after.guild, embed_fields, channel_id=after.id)
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        """Enhanced role creation logging"""
        # Check if we should log role creation events
        if not self.bot.log.should_log_event(role.guild.id, "guild_role_create"):
            return
        
        # Get creation details from audit logs
        create_entry = await self.bot.log.get_audit_entry(
            role.guild, 
            discord.AuditLogAction.role_create
        )
        
        details = f"Role @{role.name} created"
        
        embed_fields = [
            {
                "name": "Role",
                "value": f"{role.mention} ({role.id})",
                "inline": True
            },
            {
                "name": "Color",
                "value": str(role.color),
                "inline": True
            },
            {
                "name": "Hoisted",
                "value": str(role.hoist),
                "inline": True
            },
            {
                "name": "Mentionable",
                "value": str(role.mentionable),
                "inline": True
            }
        ]
        
        if create_entry:
            embed_fields.append({
                "name": "Created By",
                "value": f"{create_entry.user.mention} ({create_entry.user.id})",
                "inline": True
            })
        
        await self.bot.log.log_event("guild_role_create", details, role.guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        """Enhanced role deletion logging"""
        # Check if we should log role deletion events
        if not self.bot.log.should_log_event(role.guild.id, "guild_role_delete"):
            return
        
        # Get deletion details from audit logs
        delete_entry = await self.bot.log.get_audit_entry(
            role.guild, 
            discord.AuditLogAction.role_delete
        )
        
        details = f"Role **@{role.name}** deleted"
        
        embed_fields = [
            {
                "name": "Role Name",
                "value": f"@{role.name} ({role.id})",
                "inline": True
            },
            {
                "name": "Color",
                "value": str(role.color),
                "inline": True
            },
            {
                "name": "Member Count",
                "value": str(len(role.members)),
                "inline": True
            }
        ]
        
        if delete_entry:
            embed_fields.append({
                "name": "Deleted By",
                "value": f"{delete_entry.user.mention} ({delete_entry.user.id})",
                "inline": True
            })
        
        await self.bot.log.log_event("guild_role_delete", details, role.guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        """Enhanced role update logging with granular controls"""
        changes = []
        embed_fields = []
        
        if before.name != after.name and self.bot.log.should_log_event(after.guild.id, "guild_role_update_name"):
            changes.append("name")
            embed_fields.append({
                "name": "Name Change",
                "value": f"**Before:** @{before.name}\n**After:** @{after.name}",
                "inline": True
            })
        
        if before.color != after.color and self.bot.log.should_log_event(after.guild.id, "guild_role_update_color"):
            changes.append("color")
            embed_fields.append({
                "name": "Color Change",
                "value": f"**Before:** {before.color}\n**After:** {after.color}",
                "inline": True
            })
        
        if before.hoist != after.hoist and self.bot.log.should_log_event(after.guild.id, "guild_role_update_hoist"):
            changes.append("hoist setting")
            embed_fields.append({
                "name": "Hoist Change",
                "value": f"**Before:** {before.hoist}\n**After:** {after.hoist}",
                "inline": True
            })
        
        if (before.mentionable != after.mentionable and 
            self.bot.log.should_log_event(after.guild.id, "guild_role_update_mentionable")):
            changes.append("mentionable setting")
            embed_fields.append({
                "name": "Mentionable Change",
                "value": f"**Before:** {before.mentionable}\n**After:** {after.mentionable}",
                "inline": True
            })
        
        if (before.permissions != after.permissions and 
            self.bot.log.should_log_event(after.guild.id, "guild_role_update_permissions")):
            changes.append("permissions")
            embed_fields.append({
                "name": "Permissions Changed",
                "value": "Role permissions were modified",
                "inline": True
            })
        
        if changes and self.bot.log.should_log_event(after.guild.id, "guild_role_update"):
            details = f"Role {after.mention} updated: {', '.join(changes)}"
            
            embed_fields.insert(0, {
                "name": "Role",
                "value": f"{after.mention} ({after.id})",
                "inline": True
            })
            
            await self.bot.log.log_event("guild_role_update", details, after.guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Enhanced voice state logging"""
        if before.channel == after.channel:
            return
        
        # Check if we should log voice events
        if not self.bot.log.should_log_event(member.guild.id, "voice_state_update"):
            return
        
        embed_fields = [
            {
                "name": "User",
                "value": f"{member.mention} ({member.id})",
                "inline": True
            }
        ]
        
        channel_id = None
        if before.channel is None and after.channel:
            details = f"**{member}** joined voice channel {after.channel.mention}"
            channel_id = after.channel.id
            embed_fields.extend([
                {
                    "name": "Action",
                    "value": "Joined Voice",
                    "inline": True
                },
                {
                    "name": "Channel",
                    "value": after.channel.mention,
                    "inline": True
                }
            ])
        elif before.channel and after.channel is None:
            details = f"**{member}** left voice channel **{before.channel.name}**"
            channel_id = before.channel.id
            embed_fields.extend([
                {
                    "name": "Action",
                    "value": "Left Voice",
                    "inline": True
                },
                {
                    "name": "Channel",
                    "value": before.channel.name,
                    "inline": True
                }
            ])
        else:
            details = f"**{member}** moved from **{before.channel.name}** to {after.channel.mention}"
            # For moves, check both channels but prioritize the destination
            channel_id = after.channel.id
            embed_fields.extend([
                {
                    "name": "Action",
                    "value": "Moved Channels",
                    "inline": True
                },
                {
                    "name": "From",
                    "value": before.channel.name,
                    "inline": True
                },
                {
                    "name": "To",
                    "value": after.channel.mention,
                    "inline": True
                }
            ])
        
        await self.bot.log.log_event("voice_state_update", details, member.guild, embed_fields, channel_id=channel_id)
    
    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        """Enhanced guild update logging with granular controls"""
        changes = []
        embed_fields = []
        
        if before.name != after.name and self.bot.log.should_log_event(after.id, "guild_update_name"):
            changes.append("name")
            embed_fields.append({
                "name": "Name Change",
                "value": f"**Before:** {before.name}\n**After:** {after.name}",
                "inline": True
            })
        
        if before.icon != after.icon and self.bot.log.should_log_event(after.id, "guild_update_icon"):
            changes.append("icon")
            embed_fields.append({
                "name": "Icon Change",
                "value": "Server icon was updated",
                "inline": True
            })
        
        if before.banner != after.banner and self.bot.log.should_log_event(after.id, "guild_update_banner"):
            changes.append("banner")
            embed_fields.append({
                "name": "Banner Change",
                "value": "Server banner was updated",
                "inline": True
            })
        
        if (hasattr(before, 'description') and before.description != after.description and
            self.bot.log.should_log_event(after.id, "guild_update_description")):
            changes.append("description")
            before_desc = before.description or "None"
            after_desc = after.description or "None"
            embed_fields.append({
                "name": "Description Change",
                "value": f"**Before:** {self.bot.log.truncate_text(before_desc, 100)}\n**After:** {self.bot.log.truncate_text(after_desc, 100)}",
                "inline": False
            })
        
        if (before.verification_level != after.verification_level and
            self.bot.log.should_log_event(after.id, "guild_update_verification")):
            changes.append("verification level")
            embed_fields.append({
                "name": "Verification Level",
                "value": f"**Before:** {before.verification_level}\n**After:** {after.verification_level}",
                "inline": True
            })
        
        if changes and self.bot.log.should_log_event(after.id, "guild_update"):
            details = f"Server updated: {', '.join(changes)}"
            await self.bot.log.log_event("guild_update", details, after, embed_fields)
    
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        """Enhanced emoji update logging"""
        # Check if we should log emoji events
        if not self.bot.log.should_log_event(guild.id, "guild_emojis_update"):
            return
        
        added = set(after) - set(before)
        removed = set(before) - set(after)
        
        if added:
            emoji_names = [emoji.name for emoji in added]
            details = f"Emojis added: {', '.join(emoji_names)}"
            
            embed_fields = [
                {
                    "name": "Added Emojis",
                    "value": ", ".join([f":{emoji.name}:" for emoji in added]),
                    "inline": False
                },
                {
                    "name": "Count",
                    "value": str(len(added)),
                    "inline": True
                }
            ]
            
            await self.bot.log.log_event("guild_emojis_update", details, guild, embed_fields)
        
        if removed:
            emoji_names = [emoji.name for emoji in removed]
            details = f"Emojis removed: {', '.join(emoji_names)}"
            
            embed_fields = [
                {
                    "name": "Removed Emojis",
                    "value": ", ".join([f":{emoji.name}:" for emoji in removed]),
                    "inline": False
                },
                {
                    "name": "Count",
                    "value": str(len(removed)),
                    "inline": True
                }
            ]
            
            await self.bot.log.log_event("guild_emojis_update", details, guild, embed_fields)
    
    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        """Enhanced invite creation logging"""
        # Check if we should log invite events
        if not self.bot.log.should_log_event(invite.guild.id, "invite_create"):
            return
        
        details = f"Invite created: **{invite.code}**"
        
        embed_fields = [
            {
                "name": "Invite Code",
                "value": invite.code,
                "inline": True
            },
            {
                "name": "Channel",
                "value": invite.channel.mention if invite.channel else "Unknown",
                "inline": True
            }
        ]
        
        if invite.inviter:
            details += f" by **{invite.inviter}**"
            embed_fields.append({
                "name": "Created By",
                "value": f"{invite.inviter.mention} ({invite.inviter.id})",
                "inline": True
            })
        
        if invite.max_uses:
            embed_fields.append({
                "name": "Max Uses",
                "value": str(invite.max_uses),
                "inline": True
            })
        
        if invite.max_age:
            embed_fields.append({
                "name": "Expires In",
                "value": f"{invite.max_age} seconds",
                "inline": True
            })
        
        channel_id = invite.channel.id if invite.channel else None
        await self.bot.log.log_event("invite_create", details, invite.guild, embed_fields, channel_id=channel_id)
    
    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        """Enhanced invite deletion logging"""
        # Check if we should log invite events
        if not self.bot.log.should_log_event(invite.guild.id, "invite_delete"):
            return
        
        details = f"Invite deleted: **{invite.code}**"
        
        embed_fields = [
            {
                "name": "Invite Code",
                "value": invite.code,
                "inline": True
            },
            {
                "name": "Channel",
                "value": invite.channel.mention if invite.channel else "Unknown",
                "inline": True
            }
        ]
        
        if invite.inviter:
            embed_fields.append({
                "name": "Original Creator",
                "value": f"{invite.inviter.mention} ({invite.inviter.id})",
                "inline": True
            })
        
        if hasattr(invite, 'uses'):
            embed_fields.append({
                "name": "Times Used",
                "value": str(invite.uses),
                "inline": True
            })
        
        channel_id = invite.channel.id if invite.channel else None
        await self.bot.log.log_event("invite_delete", details, invite.guild, embed_fields, channel_id=channel_id)
    
    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        """Enhanced webhook update logging"""
        # Check if we should log webhook events
        if not self.bot.log.should_log_event(channel.guild.id, "webhook_update", channel.id):
            return
        
        details = f"Webhooks updated in {channel.mention}"
        
        embed_fields = [
            {
                "name": "Channel",
                "value": f"{channel.mention} ({channel.id})",
                "inline": True
            }
        ]
        
        await self.bot.log.log_event("webhook_update", details, channel.guild, embed_fields, channel_id=channel.id)
    
    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        """Enhanced thread creation logging"""
        # Check if we should log thread events for the parent channel
        if not self.bot.log.should_log_event(thread.guild.id, "thread_create", thread.parent.id):
            return
        
        details = f"Thread created: **{thread.name}** in {thread.parent.mention}"
        
        embed_fields = [
            {
                "name": "Thread",
                "value": f"{thread.mention} ({thread.id})",
                "inline": True
            },
            {
                "name": "Parent Channel",
                "value": f"{thread.parent.mention}",
                "inline": True
            },
            {
                "name": "Type",
                "value": str(thread.type).replace('_', ' ').title(),
                "inline": True
            }
        ]
        
        if thread.owner:
            embed_fields.append({
                "name": "Created By",
                "value": f"{thread.owner.mention} ({thread.owner.id})",
                "inline": True
            })
        
        await self.bot.log.log_event("thread_create", details, thread.guild, embed_fields, channel_id=thread.parent.id)
    
    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        """Enhanced thread deletion logging"""
        # Check if we should log thread events for the parent channel
        if not self.bot.log.should_log_event(thread.guild.id, "thread_delete", thread.parent.id):
            return
        
        details = f"Thread deleted: **{thread.name}** from **{thread.parent.name}**"
        
        embed_fields = [
            {
                "name": "Thread Name",
                "value": f"{thread.name} ({thread.id})",
                "inline": True
            },
            {
                "name": "Parent Channel",
                "value": thread.parent.name,
                "inline": True
            },
            {
                "name": "Type",
                "value": str(thread.type).replace('_', ' ').title(),
                "inline": True
            }
        ]
        
        if thread.owner:
            embed_fields.append({
                "name": "Original Creator",
                "value": f"{thread.owner.mention} ({thread.owner.id})",
                "inline": True
            })
        
        await self.bot.log.log_event("thread_delete", details, thread.guild, embed_fields, channel_id=thread.parent.id)
    
    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        """Enhanced thread update logging with granular controls"""
        changes = []
        embed_fields = []
        
        # Check each type of change individually with granular controls
        if before.name != after.name and self.bot.log.should_log_event(after.guild.id, "thread_update_name", after.parent.id):
            changes.append("name")
            embed_fields.append({
                "name": "Name Change",
                "value": f"**Before:** {before.name}\n**After:** {after.name}",
                "inline": True
            })
        
        if before.locked != after.locked and self.bot.log.should_log_event(after.guild.id, "thread_update_locked", after.parent.id):
            changes.append("lock status")
            embed_fields.append({
                "name": "Lock Status",
                "value": f"**Before:** {'Locked' if before.locked else 'Unlocked'}\n**After:** {'Locked' if after.locked else 'Unlocked'}",
                "inline": True
            })
        
        if before.archived != after.archived and self.bot.log.should_log_event(after.guild.id, "thread_update_archived", after.parent.id):
            changes.append("archive status")
            embed_fields.append({
                "name": "Archive Status",
                "value": f"**Before:** {'Archived' if before.archived else 'Active'}\n**After:** {'Archived' if after.archived else 'Active'}",
                "inline": True
            })
        
        if changes and self.bot.log.should_log_event(after.guild.id, "thread_update", after.parent.id):
            details = f"Thread {after.mention} updated: {', '.join(changes)}"
            
            embed_fields.insert(0, {
                "name": "Thread",
                "value": f"{after.mention} ({after.id})",
                "inline": True
            })
            
            await self.bot.log.log_event("thread_update", details, after.guild, embed_fields, channel_id=after.parent.id)
    
    @commands.Cog.listener()
    async def on_command(self, ctx):
        """Enhanced command usage logging"""
        command_name = ctx.command.qualified_name if ctx.command else "Unknown"
        
        message = f"Command '**{command_name}**' used by **{ctx.author}** in {ctx.channel.mention}"
        
        # Add command arguments if any
        if hasattr(ctx, 'args') and len(ctx.args) > 1:  # Skip self argument
            message += f" with arguments"
        
        await self.bot.log.log(
            LogLevel.INFO, 
            message, 
            ctx.guild, 
            ctx.author, 
            LogType.GENERAL
        )
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Enhanced command error logging"""
        command_name = ctx.command.qualified_name if ctx.command else "Unknown"
        error_type = type(error).__name__
        
        message = f"Error in command '**{command_name}**' by **{ctx.author}**: {error_type} - {str(error)[:200]}"
        
        await self.bot.log.log(
            LogLevel.ERROR, 
            message, 
            ctx.guild, 
            ctx.author, 
            LogType.GENERAL
        )
    
    # ==================== SHARED IMPLEMENTATION METHODS ====================
    
    async def _export_channel_impl(self, guild: discord.Guild, author: discord.Member, channel: discord.TextChannel, respond_func):
        """Shared implementation for channel export"""
        if not self.has_log_admin_permission(author):
            await respond_func("❌ You don't have permission to export logs.", ephemeral=True)
            return
        
        try:
            await respond_func("🔄 Exporting channel logs... This may take a while.", ephemeral=True)
            
            filepath = await self.bot.log.export_channel_logs(channel, limit=10000)
            
            # Send file to user
            file = discord.File(filepath, filename=f"export_{channel.name}.txt")
            await respond_func(
                content=f"✅ Exported logs for #{channel.name}",
                file=file,
                ephemeral=True
            )
            
            # Log the export action
            await self.bot.log.log(
                LogLevel.INFO,
                f"Channel logs exported for #{channel.name} by {author}",
                guild,
                author,
                LogType.GENERAL
            )
            
        except Exception as e:
            await respond_func(f"❌ Failed to export logs: {e}", ephemeral=True)
    
    async def _set_log_channel_impl(self, guild: discord.Guild, author: discord.Member, log_type: str, channel: Optional[discord.TextChannel], respond_func):
        """Shared implementation for setting log channels"""
        if not self.has_log_admin_permission(author):
            await respond_func("❌ You don't have permission to configure logging.", ephemeral=True)
            return
        
        guild_data = self.bot.log.get_guild_data(guild.id)
        
        if channel:
            guild_data["config"]["channels"][log_type] = channel.id
            guild_data["config"]["log_to_channel"] = True
            await respond_func(f"✅ Set {log_type} log channel to {channel.mention}")
        else:
            guild_data["config"]["channels"][log_type] = None
            await respond_func(f"✅ Removed {log_type} log channel")
        
        self.bot.log.save_data()
        
        # Log the configuration change
        await self.bot.log.log(
            LogLevel.INFO,
            f"Log channel for {log_type} {'set to ' + channel.mention if channel else 'removed'} by {author}",
            guild,
            author,
            LogType.GENERAL
        )
    
    async def _set_custom_log_channel_impl(self, guild: discord.Guild, author: discord.Member, custom_log_name: str, channel: Optional[discord.TextChannel], respond_func):
        """Shared implementation for setting custom log channels"""
        if not self.has_log_admin_permission(author):
            await respond_func("❌ You don't have permission to configure logging.", ephemeral=True)
            return
        
        # Check if custom log exists
        if custom_log_name not in self.bot.log.custom_logs:
            await respond_func(f"❌ Custom log '{custom_log_name}' doesn't exist. It must be used at least once before setting a channel.", ephemeral=True)
            return
        
        # Set the channel
        self.bot.log.set_custom_log_channel(guild.id, custom_log_name, channel.id if channel else None)
        
        if channel:
            await respond_func(f"✅ Set custom log '{custom_log_name}' channel to {channel.mention}")
        else:
            await respond_func(f"✅ Removed custom log '{custom_log_name}' channel")
        
        # Log the configuration change
        await self.bot.log.log(
            LogLevel.INFO,
            f"Custom log channel for '{custom_log_name}' {'set to ' + channel.mention if channel else 'removed'} by {author}",
            guild,
            author,
            LogType.GENERAL
        )
    
    async def _exclude_channel_impl(self, guild: discord.Guild, author: discord.Member, channel: discord.TextChannel, exclude: bool, respond_func):
        """Shared implementation for excluding/including channels completely"""
        if not self.has_log_admin_permission(author):
            await respond_func("❌ You don't have permission to configure logging.", ephemeral=True)
            return
        
        if exclude:
            self.bot.log.add_excluded_channel(guild.id, channel.id)
            await respond_func(f"✅ Completely excluded {channel.mention} from all logging")
        else:
            self.bot.log.remove_excluded_channel(guild.id, channel.id)
            await respond_func(f"✅ Included {channel.mention} in logging")
        
        # Log the configuration change
        await self.bot.log.log(
            LogLevel.INFO,
            f"Channel {channel.mention} {'completely excluded from' if exclude else 'included in'} logging by {author}",
            guild,
            author,
            LogType.GENERAL
        )
    
    async def _exclude_channel_event_impl(self, guild: discord.Guild, author: discord.Member, channel: discord.TextChannel, event_type: str, exclude: bool, respond_func):
        """Shared implementation for excluding/including specific events for a channel"""
        if not self.has_log_admin_permission(author):
            await respond_func("❌ You don't have permission to configure logging.", ephemeral=True)
            return
        
        # Check if event type exists
        guild_data = self.bot.log.get_guild_data(guild.id)
        if event_type not in guild_data["config"]["events"]:
            await respond_func(f"❌ Unknown event type: {event_type}", ephemeral=True)
            return
        
        if exclude:
            self.bot.log.add_channel_event_exclusion(guild.id, channel.id, event_type)
            await respond_func(f"✅ Excluded event '{event_type}' for {channel.mention}")
        else:
            self.bot.log.remove_channel_event_exclusion(guild.id, channel.id, event_type)
            await respond_func(f"✅ Included event '{event_type}' for {channel.mention}")
        
        # Log the configuration change
        await self.bot.log.log(
            LogLevel.INFO,
            f"Event '{event_type}' {'excluded for' if exclude else 'included for'} {channel.mention} by {author}",
            guild,
            author,
            LogType.GENERAL
        )
    
    async def _toggle_event_impl(self, guild: discord.Guild, author: discord.Member, event_type: str, enabled: bool, respond_func):
        """Shared implementation for toggling events globally"""
        if not self.has_log_admin_permission(author):
            await respond_func("❌ You don't have permission to configure logging.", ephemeral=True)
            return
        
        # Check if event type exists
        guild_data = self.bot.log.get_guild_data(guild.id)
        if event_type not in guild_data["config"]["events"]:
            await respond_func(f"❌ Unknown event type: {event_type}", ephemeral=True)
            return
        
        self.bot.log.set_event_enabled(guild.id, event_type, enabled)
        
        status = "enabled" if enabled else "disabled"
        await respond_func(f"✅ {status.title()} logging for event: {event_type}")
        
        # Log the configuration change
        await self.bot.log.log(
            LogLevel.INFO,
            f"Event '{event_type}' {status} globally by {author}",
            guild,
            author,
            LogType.GENERAL
        )

    # ==================== PREFIX COMMANDS ====================
    
    @commands.group(name="log", aliases=["logs", "logging"])
    async def log_group(self, ctx):
        """Enhanced logging management commands with granular per-channel controls"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🔍 Enhanced Logging System",
                description="Comprehensive server event logging with granular per-channel exclusion controls",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="📤 Export",
                value="`log export <channel>` - Export channel messages to file",
                inline=False
            )
            embed.add_field(
                name="📺 Channel Configuration",
                value="`log event <channel>` - Set server events log channel\n"
                        "`log channel <channel>` - Set general log channel\n"
                        "`log cog <channel>` - Set cog log channel\n"
                        "`log custom <log_name> <channel>` - Set custom log channel",
                inline=False
            )
            embed.add_field(
                name="🚫 Channel Exclusions",
                value="`log exclude-all <channel>` - Exclude channel from ALL logging\n"
                        "`log include-all <channel>` - Include channel in all logging\n"
                        "`log exclude-event <channel> <event>` - Exclude specific event for channel\n"
                        "`log include-event <channel> <event>` - Include specific event for channel",
                inline=False
            )
            embed.add_field(
                name="⚙️ Global Event Controls",
                value="`log event-toggle <event> <on/off>` - Toggle events globally\n"
                        "`log list-exclusions <channel>` - List channel exclusions",
                inline=False
            )
            embed.add_field(
                name="🧹 Maintenance",
                value="`log clear <type> [days]` - Clear old log files\n"
                        "`log config` - View logging configuration",
                inline=False
            )
            embed.add_field(
                name="✨ New Features",
                value="• **Granular per-channel controls** - Exclude specific events per channel\n"
                      "• **Complete channel exclusion** - Block ALL events for a channel\n"
                      "• **Improved kick/ban detection** - Fixed audit log timing\n"
                      "• **Comprehensive event checking** - All events respect exclusions",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @log_group.command(name="export")
    async def export_channel_prefix(self, ctx, channel: discord.TextChannel):
        """Export channel logs to a file"""
        async def respond(content=None, file=None, ephemeral=False):
            if file:
                await ctx.send(content=content, file=file)
            else:
                await ctx.send(content)
        
        await self._export_channel_impl(ctx.guild, ctx.author, channel, respond)
    
    @log_group.command(name="event")
    async def set_event_channel_prefix(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Set server events log channel"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._set_log_channel_impl(ctx.guild, ctx.author, "events", channel, respond)
    
    @log_group.command(name="channel")
    async def set_general_channel_prefix(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Set general log channel"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._set_log_channel_impl(ctx.guild, ctx.author, "general", channel, respond)
    
    @log_group.command(name="cog")
    async def set_cog_channel_prefix(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Set cog log channel"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._set_log_channel_impl(ctx.guild, ctx.author, "cogs", channel, respond)
    
    @log_group.command(name="custom")
    async def set_custom_log_channel_prefix(self, ctx, custom_log_name: str, channel: Optional[discord.TextChannel] = None):
        """Set custom log channel"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._set_custom_log_channel_impl(ctx.guild, ctx.author, custom_log_name, channel, respond)
    
    @log_group.command(name="exclude-all")
    async def exclude_all_channel_prefix(self, ctx, channel: discord.TextChannel):
        """Completely exclude a channel from ALL logging"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._exclude_channel_impl(ctx.guild, ctx.author, channel, True, respond)
    
    @log_group.command(name="include-all")
    async def include_all_channel_prefix(self, ctx, channel: discord.TextChannel):
        """Include a channel in all logging"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._exclude_channel_impl(ctx.guild, ctx.author, channel, False, respond)
    
    @log_group.command(name="exclude-event")
    async def exclude_event_channel_prefix(self, ctx, channel: discord.TextChannel, event_type: str):
        """Exclude a specific event type for a channel"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._exclude_channel_event_impl(ctx.guild, ctx.author, channel, event_type, True, respond)
    
    @log_group.command(name="include-event")
    async def include_event_channel_prefix(self, ctx, channel: discord.TextChannel, event_type: str):
        """Include a specific event type for a channel"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._exclude_channel_event_impl(ctx.guild, ctx.author, channel, event_type, False, respond)
    
    @log_group.command(name="event-toggle")
    async def toggle_event_prefix(self, ctx, event_type: str, state: str):
        """Toggle specific event logging globally"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        if state.lower() not in ["on", "off", "true", "false", "enable", "disable"]:
            await ctx.send("❌ State must be one of: on, off, true, false, enable, disable")
            return
        
        enabled = state.lower() in ["on", "true", "enable"]
        await self._toggle_event_impl(ctx.guild, ctx.author, event_type, enabled, respond)
    
    @log_group.command(name="list-exclusions")
    async def list_exclusions_prefix(self, ctx, channel: discord.TextChannel):
        """List all exclusions for a channel"""
        if not self.has_log_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to view logging configuration.")
            return
        
        try:
            # Check if channel is completely excluded
            completely_excluded = self.bot.log.is_channel_excluded(ctx.guild.id, channel.id)
            
            # Get specific event exclusions
            event_exclusions = self.bot.log.get_channel_event_exclusions(ctx.guild.id, channel.id)
            
            embed = discord.Embed(
                title=f"🚫 Exclusions for {channel.name}",
                color=discord.Color.orange()
            )
            
            if completely_excluded:
                embed.add_field(
                    name="Complete Exclusion",
                    value="❌ This channel is completely excluded from ALL logging",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Complete Exclusion",
                    value="✅ Channel is included in logging",
                    inline=False
                )
            
            if event_exclusions:
                exclusions_text = "\n".join([f"• {event}" for event in event_exclusions])
                # Truncate if too long
                if len(exclusions_text) > 1000:
                    exclusions_text = exclusions_text[:1000] + "..."
                embed.add_field(
                    name="Excluded Events",
                    value=exclusions_text,
                    inline=False
                )
            else:
                embed.add_field(
                    name="Excluded Events",
                    value="None - All events are included",
                    inline=False
                )
            
            embed.set_footer(text="Use exclude-event/include-event to manage specific exclusions")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error retrieving exclusions: {e}")
    
    @log_group.command(name="clear")
    async def clear_logs_prefix(self, ctx, log_type: str, days: int = 30):
        """Clear old log files"""
        if not self.has_manager_permission(ctx.author):
            await ctx.send("❌ You don't have permission to clear logs.")
            return
        
        try:
            log_type_enum = LogType(log_type.lower())
        except ValueError:
            valid_types = [t.value for t in LogType]
            await ctx.send(f"❌ Invalid log type. Valid types: {', '.join(valid_types)}")
            return
        
        try:
            cleared_files = await self.bot.log.clear_logs(log_type_enum, days)
            
            if cleared_files:
                await ctx.send(f"✅ Cleared {len(cleared_files)} log files older than {days} days")
            else:
                await ctx.send(f"ℹ️ No log files found older than {days} days")
            
            # Log the clear action
            await self.bot.log.log(
                LogLevel.INFO,
                f"Cleared {len(cleared_files)} {log_type} log files by {ctx.author}",
                ctx.guild,
                ctx.author,
                LogType.GENERAL
            )
            
        except Exception as e:
            await ctx.send(f"❌ Failed to clear logs: {e}")
    
    @log_group.command(name="config")
    async def show_config_prefix(self, ctx):
        """Show enhanced logging configuration"""
        if not self.has_log_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to view logging configuration.")
            return
        
        try:
            guild_data = self.bot.log.get_guild_data(ctx.guild.id)
            config = guild_data["config"]
            
            embed = discord.Embed(
                title="🔍 Enhanced Logging Configuration",
                description="Comprehensive server monitoring with granular per-channel controls",
                color=discord.Color.green()
            )
            
            # General settings
            embed.add_field(
                name="⚙️ General Settings",
                value=f"**Enabled:** {config['enabled']}\n"
                        f"**Log to File:** {config['log_to_file']}\n"
                        f"**Log to Channel:** {config['log_to_channel']}",
                inline=False
            )
            
            # Standard channels
            channels_info = []
            for log_type, channel_id in config["channels"].items():
                if channel_id:
                    try:
                        channel = ctx.guild.get_channel(channel_id)
                        if channel:
                            channels_info.append(f"**{log_type.title()}:** {channel.mention}")
                        else:
                            channels_info.append(f"**{log_type.title()}:** Unknown Channel ({channel_id})")
                    except Exception:
                        channels_info.append(f"**{log_type.title()}:** Error loading channel")
                else:
                    channels_info.append(f"**{log_type.title()}:** Not set")
            
            embed.add_field(
                name="📺 Standard Log Channels",
                value="\n".join(channels_info) if channels_info else "None configured",
                inline=False
            )
            
            # Exclusions summary
            excluded_count = len(config.get("excluded_channels", []))
            event_exclusion_count = len(config.get("channel_event_exclusions", {}))
            
            embed.add_field(
                name="🚫 Exclusions Summary",
                value=f"**Complete exclusions:** {excluded_count} channels\n**Event exclusions:** {event_exclusion_count} channels",
                inline=True
            )
            
            # Events summary
            enabled_events = [event for event, enabled in config["events"].items() if enabled]
            disabled_events = [event for event, enabled in config["events"].items() if not enabled]
            
            embed.add_field(
                name=f"📊 Global Events ({len(enabled_events)}/{len(config['events'])})",
                value=f"**Enabled:** {len(enabled_events)}\n**Disabled:** {len(disabled_events)}",
                inline=True
            )
            
            embed.set_footer(text="Use list-exclusions to see detailed channel exclusions")
            
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error showing config: {e}")

    # ==================== SLASH COMMANDS ====================
    
    log_group_commands = app_commands.Group(name="logs", description="Enhanced logging system with granular controls")
    
    @log_group_commands.command(name="export", description="Export channel logs to a file")
    @app_commands.describe(channel="Channel to export logs from")
    async def export_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Export channel logs to a file"""
        async def respond(content=None, file=None, ephemeral=False):
            if interaction.response.is_done():
                if file:
                    await interaction.followup.send(content=content, file=file, ephemeral=ephemeral)
                else:
                    await interaction.followup.send(content, ephemeral=ephemeral)
            else:
                if file:
                    await interaction.response.send_message(content=content, file=file, ephemeral=ephemeral)
                else:
                    await interaction.response.send_message(content, ephemeral=ephemeral)
        
        await self._export_channel_impl(interaction.guild, interaction.user, channel, respond)
    
    @log_group_commands.command(name="event-channel", description="Set server events log channel")
    @app_commands.describe(channel="Channel for enhanced server event logs (leave empty to remove)")
    async def set_event_channel_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Set server events log channel"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._set_log_channel_impl(interaction.guild, interaction.user, "events", channel, respond)
    
    @log_group_commands.command(name="general-channel", description="Set general log channel")
    @app_commands.describe(channel="Channel for general logs (leave empty to remove)")
    async def set_general_channel_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Set general log channel"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._set_log_channel_impl(interaction.guild, interaction.user, "general", channel, respond)
    
    @log_group_commands.command(name="cog-channel", description="Set cog log channel")
    @app_commands.describe(channel="Channel for cog logs (leave empty to remove)")
    async def set_cog_channel_slash(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Set cog log channel"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._set_log_channel_impl(interaction.guild, interaction.user, "cogs", channel, respond)
    
    @log_group_commands.command(name="custom-channel", description="Set custom log channel")
    @app_commands.describe(
        custom_log_name="Name of the custom log",
        channel="Channel for custom log (leave empty to remove)"
    )
    async def set_custom_log_channel_slash(self, interaction: discord.Interaction, custom_log_name: str, channel: Optional[discord.TextChannel] = None):
        """Set custom log channel"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._set_custom_log_channel_impl(interaction.guild, interaction.user, custom_log_name, channel, respond)
    
    @log_group_commands.command(name="exclude-all", description="Completely exclude a channel from ALL logging")
    @app_commands.describe(channel="Channel to exclude from all logging")
    async def exclude_all_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Completely exclude a channel from ALL logging"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._exclude_channel_impl(interaction.guild, interaction.user, channel, True, respond)
    
    @log_group_commands.command(name="include-all", description="Include a channel in all logging")
    @app_commands.describe(channel="Channel to include in all logging")
    async def include_all_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Include a channel in all logging"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._exclude_channel_impl(interaction.guild, interaction.user, channel, False, respond)
    
    @log_group_commands.command(name="exclude-event", description="Exclude a specific event for a channel")
    @app_commands.describe(
        channel="Channel to exclude event for",
        event_type="Event type to exclude"
    )
    async def exclude_event_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, event_type: str):
        """Exclude a specific event type for a channel"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._exclude_channel_event_impl(interaction.guild, interaction.user, channel, event_type, True, respond)
    
    @log_group_commands.command(name="include-event", description="Include a specific event for a channel")
    @app_commands.describe(
        channel="Channel to include event for",
        event_type="Event type to include"
    )
    async def include_event_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, event_type: str):
        """Include a specific event type for a channel"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._exclude_channel_event_impl(interaction.guild, interaction.user, channel, event_type, False, respond)
    
    @log_group_commands.command(name="toggle-event", description="Toggle specific event logging globally")
    @app_commands.describe(
        event_type="Event type to toggle",
        enabled="Whether to enable or disable the event"
    )
    async def toggle_event_slash(self, interaction: discord.Interaction, event_type: str, enabled: bool):
        """Toggle specific event logging globally"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._toggle_event_impl(interaction.guild, interaction.user, event_type, enabled, respond)
    
    @log_group_commands.command(name="list-exclusions", description="List all exclusions for a channel")
    @app_commands.describe(channel="Channel to list exclusions for")
    async def list_exclusions_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """List all exclusions for a channel"""
        if not self.has_log_admin_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to view logging configuration.", ephemeral=True)
            return
        
        try:
            # Check if channel is completely excluded
            completely_excluded = self.bot.log.is_channel_excluded(interaction.guild.id, channel.id)
            
            # Get specific event exclusions
            event_exclusions = self.bot.log.get_channel_event_exclusions(interaction.guild.id, channel.id)
            
            embed = discord.Embed(
                title=f"🚫 Exclusions for {channel.name}",
                color=discord.Color.orange()
            )
            
            if completely_excluded:
                embed.add_field(
                    name="Complete Exclusion",
                    value="❌ This channel is completely excluded from ALL logging",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Complete Exclusion",
                    value="✅ Channel is included in logging",
                    inline=False
                )
            
            if event_exclusions:
                exclusions_text = "\n".join([f"• {event}" for event in event_exclusions])
                # Truncate if too long
                if len(exclusions_text) > 1000:
                    exclusions_text = exclusions_text[:1000] + "..."
                embed.add_field(
                    name="Excluded Events",
                    value=exclusions_text,
                    inline=False
                )
            else:
                embed.add_field(
                    name="Excluded Events",
                    value="None - All events are included",
                    inline=False
                )
            
            embed.set_footer(text="Use exclude-event/include-event to manage specific exclusions")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error retrieving exclusions: {e}", ephemeral=True)
    
    @log_group_commands.command(name="clear", description="Clear old log files")
    @app_commands.describe(
        log_type="Type of logs to clear",
        days="Delete files older than this many days (default: 30)"
    )
    async def clear_logs_slash(self, interaction: discord.Interaction, 
                                log_type: str, 
                                days: int = 30):
        """Clear old log files"""
        if not self.has_manager_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to clear logs.", ephemeral=True)
            return
        
        try:
            log_type_enum = LogType(log_type.lower())
        except ValueError:
            valid_types = [t.value for t in LogType]
            await interaction.response.send_message(
                f"❌ Invalid log type. Valid types: {', '.join(valid_types)}", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            cleared_files = await self.bot.log.clear_logs(log_type_enum, days)
            
            if cleared_files:
                await interaction.followup.send(
                    f"✅ Cleared {len(cleared_files)} log files older than {days} days", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"ℹ️ No log files found older than {days} days", 
                    ephemeral=True
                )
            
            # Log the clear action
            await self.bot.log.log(
                LogLevel.INFO,
                f"Cleared {len(cleared_files)} {log_type} log files by {interaction.user}",
                interaction.guild,
                interaction.user,
                LogType.GENERAL
            )
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to clear logs: {e}", ephemeral=True)
    
    @log_group_commands.command(name="config", description="Show enhanced logging configuration")
    async def show_config_slash(self, interaction: discord.Interaction):
        """Show enhanced logging configuration"""
        if not self.has_log_admin_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to view logging configuration.", ephemeral=True)
            return
        
        try:
            guild_data = self.bot.log.get_guild_data(interaction.guild.id)
            config = guild_data["config"]
            
            embed = discord.Embed(
                title="🔍 Enhanced Logging Configuration",
                description="Comprehensive server monitoring with granular per-channel controls",
                color=discord.Color.green()
            )
            
            # General settings
            embed.add_field(
                name="⚙️ General Settings",
                value=f"**Enabled:** {config['enabled']}\n"
                        f"**Log to File:** {config['log_to_file']}\n"
                        f"**Log to Channel:** {config['log_to_channel']}",
                inline=False
            )
            
            # Standard channels
            channels_info = []
            for log_type, channel_id in config["channels"].items():
                if channel_id:
                    try:
                        channel = interaction.guild.get_channel(channel_id)
                        if channel:
                            channels_info.append(f"**{log_type.title()}:** {channel.mention}")
                        else:
                            channels_info.append(f"**{log_type.title()}:** Unknown Channel ({channel_id})")
                    except Exception:
                        channels_info.append(f"**{log_type.title()}:** Error loading channel")
                else:
                    channels_info.append(f"**{log_type.title()}:** Not set")
            
            embed.add_field(
                name="📺 Standard Log Channels",
                value="\n".join(channels_info) if channels_info else "None configured",
                inline=False
            )
            
            # Exclusions summary
            excluded_count = len(config.get("excluded_channels", []))
            event_exclusion_count = len(config.get("channel_event_exclusions", {}))
            
            embed.add_field(
                name="🚫 Exclusions Summary",
                value=f"**Complete exclusions:** {excluded_count} channels\n**Event exclusions:** {event_exclusion_count} channels",
                inline=True
            )
            
            # Events summary
            enabled_events = [event for event, enabled in config["events"].items() if enabled]
            disabled_events = [event for event, enabled in config["events"].items() if not enabled]
            
            embed.add_field(
                name=f"📊 Global Events ({len(enabled_events)}/{len(config['events'])})",
                value=f"**Enabled:** {len(enabled_events)}\n**Disabled:** {len(disabled_events)}",
                inline=True
            )
            
            embed.set_footer(text="Use list-exclusions to see detailed channel exclusions")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error showing config: {e}", ephemeral=True)
    
    # Autocomplete functions
    async def log_type_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        log_types = [t.value for t in LogType]
        return [
            app_commands.Choice(name=log_type, value=log_type)
            for log_type in log_types
            if current.lower() in log_type.lower()
        ][:25]
    
    async def custom_log_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        custom_logs = list(self.bot.log.custom_logs.keys())
        return [
            app_commands.Choice(name=log_name, value=log_name)
            for log_name in custom_logs
            if current.lower() in log_name.lower()
        ][:25]
    
    async def event_type_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        try:
            guild_data = self.bot.log.get_guild_data(interaction.guild.id)
            event_types = list(guild_data["config"]["events"].keys())
            return [
                app_commands.Choice(name=event_type, value=event_type)
                for event_type in event_types
                if current.lower() in event_type.lower()
            ][:25]
        except Exception:
            return []
    
    # Add autocomplete to commands
    clear_logs_slash.autocomplete('log_type')(log_type_autocomplete)
    set_custom_log_channel_slash.autocomplete('custom_log_name')(custom_log_autocomplete)
    toggle_event_slash.autocomplete('event_type')(event_type_autocomplete)
    exclude_event_channel_slash.autocomplete('event_type')(event_type_autocomplete)
    include_event_channel_slash.autocomplete('event_type')(event_type_autocomplete)

async def setup(bot):
    await bot.add_cog(LoggingCog(bot))