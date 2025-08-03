"""
Discord Message Management Cog - Bot Message Tracking & Lifecycle System

OVERVIEW:
Comprehensive system for sending, tracking, and managing bot messages with lifecycle
monitoring, editing capabilities, and automatic cleanup. Auto-attaches to bot.message_manager.

SETUP:
- No manual setup required - auto-creates files and directories
- Database: src/database/message_db.json
- Export directory: src/database/messages/
- Requires: PermissionsCog (optional), LoggingCog (optional)
- Auto-attaches to bot.message_manager for other cogs

PERMISSIONS:
- Send messages: 'permissions.sendbotmessage' or manage messages
- Manage messages: 'permissions.managebotmessages' or manage messages

COMMANDS:
/bmessage send <content> <channel>    - Send tracked message with escape sequences
/bmessage list [page] [include_deleted] - List server messages with status
/bmessage info <id>                   - Get detailed message information
/bmessage edit <id> <content>         - Edit existing message in-place
/bmessage refresh                     - Force check all message statuses
/bmessage cleanup <confirm>           - Remove deleted message records
/bmessage export [format]             - Export messages (JSON/TXT)
/bmessage check <id>                  - Check if specific message exists

Prefix commands: !message <subcommand> (same functionality)

USAGE BY OTHER COGS:

# Quick message sending
class MyCog(commands.Cog):
    @commands.command()
    async def example(self, ctx):
        # Send tracked messages with escape sequences
        message_data = await self.bot.message_manager.send_quick_message(
            "Hello\\nWorld\\nWith line breaks",
            ctx.channel,
            ctx.author
        )
        
        # Helper methods for common message types
        await self.bot.message_manager.send_success_message(
            "Operation completed successfully!", ctx.channel, ctx.author
        )
        
        await self.bot.message_manager.send_error_message(
            "Something went wrong!", ctx.channel, ctx.author
        )
        
        await self.bot.message_manager.send_info_message(
            "Here's some information", ctx.channel, ctx.author
        )
        
        # Get message data and Discord object
        msg_data = self.bot.message_manager.get_message_by_id(message_data['id'])
        discord_msg = await self.bot.message_manager.get_discord_message(message_data['id'])
        
        # Edit tracked message
        success = await self.bot.message_manager.edit_message(
            message_data['id'], "New content\\nWith line breaks", ctx.author
        )

ESCAPE SEQUENCES:
\\n - Line breaks (newlines)
\\t - Tab characters  
\\r - Carriage returns
\\\\ - Literal backslash

FEATURES:
• Message lifecycle tracking with real-time deletion detection
• Escape sequence processing for formatted content (\\n for newlines)
• In-place message editing with version tracking
• Automatic status checking every 3 hours via background task
• Event listeners for message/channel/guild deletion detection
• Export functionality (JSON/TXT) with timestamped files
• Pagination for large message lists with status indicators
• Permission-based access control with role integration
• Comprehensive logging integration for all operations
• Automatic cleanup of deleted channel/guild records
• Helper methods for standardized success/error/info messages
• Force refresh capabilities for immediate status updates
• Detailed message information with direct Discord links
• Both slash and prefix command support
• Character limit validation with escape sequence processing
• Real-time tracking of embeds and file attachments
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import aiofiles
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Union
from pathlib import Path
import re
import io
from enum import Enum

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

class MessageManager:
    """Manages message storage, tracking, and operations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.data_file = "src/database/message_db.json"
        self.messages_dir = Path("src/database/messages")
        self.messages_dir.mkdir(parents=True, exist_ok=True)
        
        self.data = self.load_data()
        
        # Start background task
        self.check_deleted_messages.start()
    
    @staticmethod
    def process_escape_sequences(content: str) -> str:
        """Process escape sequences in message content"""
        if not content:
            return content
        
        # Convert escape sequences to actual characters
        content = content.replace('\\n', '\n')  # Convert \n to actual newlines
        content = content.replace('\\t', '\t')  # Convert \t to actual tabs
        content = content.replace('\\r', '\r')  # Convert \r to carriage returns
        content = content.replace('\\\\', '\\')  # Convert \\ to literal backslash
        
        return content
    
    async def log_message_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log message actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Message {action}"
                if details:
                    log_message += f" - {details}"
                if user:
                    log_message += f" - User: {user.name} ({user.id})"
                
                await self.bot.log.log(
                    LogLevel.INFO,
                    log_message,
                    guild,
                    user,
                    LogType.COG,
                    file_override="message_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log message action: {e}")

    async def log_message_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log message errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Message Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="message_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log message error: {e}")

    async def log_message_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log message warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Message Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="message_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log message warning: {e}")
    
    def load_data(self) -> Dict[str, Any]:
        """Load message data from file"""
        if Path(self.data_file).exists():
            with open(self.data_file, 'r') as f:
                return json.load(f)
        return {
            "messages": {},
            "guild_settings": {},
            "templates": {},
            "next_id": 1
        }
    
    def save_data(self):
        """Save message data to file"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_message_error(f"Error saving message data: {e}"))
    
    def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get guild-specific settings"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.data["guild_settings"]:
            self.data["guild_settings"][guild_id_str] = {
                "auto_delete_tracking": True,
                "log_message_sends": True,
                "max_stored_messages": 2000,
                "real_time_checking": True,
                "auto_cleanup_deleted": True
            }
            self.save_data()
        return self.data["guild_settings"][guild_id_str]
    
    def mark_message_deleted(self, message_id: int, reason: str = "message_deleted"):
        """Mark a message as deleted based on message ID"""
        for msg_id, msg_data in self.data["messages"].items():
            if msg_data["message_id"] == message_id and msg_data["exists"]:
                msg_data["exists"] = False
                msg_data["last_checked"] = datetime.now().isoformat()
                msg_data["deletion_reason"] = reason
                break
        self.save_data()
    
    def mark_channel_messages_deleted(self, channel_id: int):
        """Mark all messages in a deleted channel as no longer existing"""
        updated_count = 0
        for msg_id, msg_data in self.data["messages"].items():
            if msg_data["channel_id"] == channel_id and msg_data["exists"]:
                msg_data["exists"] = False
                msg_data["last_checked"] = datetime.now().isoformat()
                msg_data["deletion_reason"] = "channel_deleted"
                updated_count += 1
        
        if updated_count > 0:
            self.save_data()
            print(f"Marked {updated_count} messages as deleted due to channel deletion")
        
        return updated_count
    
    def mark_guild_messages_deleted(self, guild_id: int):
        """Mark all messages in a deleted guild as no longer existing"""
        updated_count = 0
        for msg_id, msg_data in self.data["messages"].items():
            if msg_data["guild_id"] == guild_id and msg_data["exists"]:
                msg_data["exists"] = False
                msg_data["last_checked"] = datetime.now().isoformat()
                msg_data["deletion_reason"] = "guild_left"
                updated_count += 1
        
        if updated_count > 0:
            self.save_data()
            print(f"Marked {updated_count} messages as deleted due to guild removal")
        
        return updated_count
    
    async def create_message(self, 
                           content: str,
                           channel: discord.TextChannel,
                           author: Union[discord.Member, discord.User],
                           **kwargs) -> Dict[str, Any]:
        """Create and send a message, then store it"""
        
        try:
            # Process escape sequences in content
            processed_content = self.process_escape_sequences(content)
            
            # Handle file attachments if provided
            files = kwargs.get('files', None)
            embed = kwargs.get('embed', None)
            
            message = await channel.send(content=processed_content, files=files, embed=embed)
            
            # Store message data
            message_id = self.data["next_id"]
            self.data["next_id"] += 1
            
            message_data = {
                "id": message_id,
                "guild_id": channel.guild.id,
                "channel_id": channel.id,
                "message_id": message.id,
                "author_id": author.id,
                "content": processed_content,  # Store the processed content
                "has_embed": embed is not None,
                "has_files": files is not None and len(files) > 0,
                "created_at": datetime.now().isoformat(),
                "last_checked": datetime.now().isoformat(),
                "exists": True,
                "edit_count": 0
            }
            
            self.data["messages"][str(message_id)] = message_data
            self.save_data()
            
            # Log the action
            await self.log_message_action(
                "sent", 
                channel.guild, 
                author, 
                f"Message ID {message_id} sent to #{channel.name}"
            )
            
            return message_data
            
        except discord.Forbidden:
            await self.log_message_error(
                f"No permission to send message in #{channel.name}",
                channel.guild,
                author
            )
            raise Exception("No permission to send messages in that channel")
        except discord.HTTPException as e:
            await self.log_message_error(
                f"Failed to send message in #{channel.name}: {e}",
                channel.guild,
                author
            )
            raise Exception(f"Failed to send message: {e}")
    
    async def edit_message(self, message_id: int, new_content: str, editor: Union[discord.Member, discord.User] = None) -> bool:
        """Edit an existing message"""
        message_data = self.data["messages"].get(str(message_id))
        if not message_data:
            await self.log_message_warning(f"Attempted to edit non-existent message ID {message_id}")
            return False
        
        # Check if channel still exists
        channel = self.bot.get_channel(message_data["channel_id"])
        if not channel:
            message_data["exists"] = False
            message_data["deletion_reason"] = "channel_deleted"
            message_data["last_checked"] = datetime.now().isoformat()
            self.save_data()
            await self.log_message_warning(
                f"Cannot edit message {message_id} - channel deleted",
                None,
                editor
            )
            return False
        
        if not message_data["exists"]:
            await self.log_message_warning(
                f"Attempted to edit deleted message {message_id}",
                channel.guild,
                editor
            )
            return False
        
        try:
            message = await channel.fetch_message(message_data["message_id"])
            
            # Process escape sequences in new content
            processed_content = self.process_escape_sequences(new_content)
            
            await message.edit(content=processed_content)
            
            # Update stored data
            message_data["content"] = processed_content  # Store the processed content
            message_data["edit_count"] += 1
            message_data["last_checked"] = datetime.now().isoformat()
            
            # Remove deletion reason if it exists
            if "deletion_reason" in message_data:
                del message_data["deletion_reason"]
            
            self.save_data()
            
            # Log the edit
            await self.log_message_action(
                "edited",
                channel.guild,
                editor,
                f"Message ID {message_id} edited (edit #{message_data['edit_count']})"
            )
            
            return True
            
        except discord.NotFound:
            # Message was deleted
            message_data["exists"] = False
            message_data["deletion_reason"] = "message_deleted"
            message_data["last_checked"] = datetime.now().isoformat()
            self.save_data()
            
            await self.log_message_action(
                "edit failed - message deleted",
                channel.guild,
                editor,
                f"Message ID {message_id} was already deleted"
            )
            return False
        except discord.Forbidden:
            await self.log_message_error(
                f"No permission to edit message {message_id}",
                channel.guild,
                editor
            )
            return False
    
    async def check_message_exists(self, message_id: int, force_check: bool = False) -> bool:
        """Check if a message still exists"""
        message_data = self.data["messages"].get(str(message_id))
        if not message_data:
            return False
        
        # If we've checked recently and it existed, and we're not forcing a check, assume it still exists
        if not force_check and message_data["exists"]:
            last_checked = datetime.fromisoformat(message_data["last_checked"])
            if datetime.now() - last_checked < timedelta(minutes=5):
                return True
        
        # Check if channel exists first
        channel = self.bot.get_channel(message_data["channel_id"])
        if not channel:
            message_data["exists"] = False
            message_data["last_checked"] = datetime.now().isoformat()
            message_data["deletion_reason"] = "channel_deleted"
            self.save_data()
            return False
        
        try:
            await channel.fetch_message(message_data["message_id"])
            message_data["last_checked"] = datetime.now().isoformat()
            message_data["exists"] = True
            
            # Remove deletion reason if it exists (message was recovered)
            if "deletion_reason" in message_data:
                del message_data["deletion_reason"]
            
            self.save_data()
            return True
            
        except discord.NotFound:
            message_data["exists"] = False
            message_data["last_checked"] = datetime.now().isoformat()
            message_data["deletion_reason"] = "message_deleted"
            self.save_data()
            
            # Log deletion
            await self.log_message_action(
                "detected as deleted",
                channel.guild,
                details=f"Message ID {message_id}"
            )
            
            return False
        except discord.Forbidden:
            return True  # Assume it exists if we can't check
    
    async def check_messages_for_guild(self, guild_id: int, max_checks: int = 15) -> int:
        """Check a few messages for a guild to update their status"""
        checked = 0
        updated = 0
        
        for msg_id, msg_data in self.data["messages"].items():
            if msg_data["guild_id"] == guild_id and msg_data["exists"]:
                # Only check messages that haven't been checked recently
                last_checked = datetime.fromisoformat(msg_data["last_checked"])
                if datetime.now() - last_checked > timedelta(minutes=30):
                    old_status = msg_data["exists"]
                    await self.check_message_exists(int(msg_id), force_check=True)
                    new_status = msg_data["exists"]
                    
                    if old_status != new_status:
                        updated += 1
                    
                    checked += 1
                    if checked >= max_checks:
                        break
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.1)
        
        if checked > 0:
            guild = self.bot.get_guild(guild_id)
            await self.log_message_action(
                "status check completed",
                guild,
                details=f"Checked {checked} messages, {updated} status changes"
            )
        
        return updated
    
    def get_messages_for_guild(self, guild_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """Get all messages for a guild"""
        messages = []
        for msg_data in self.data["messages"].values():
            if msg_data["guild_id"] == guild_id:
                if include_deleted or msg_data["exists"]:
                    messages.append(msg_data)
        
        return sorted(messages, key=lambda x: x["created_at"], reverse=True)
    
    def cleanup_deleted_channel_messages(self, guild_id: int) -> int:
        """Remove message records for channels that no longer exist"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return 0
        
        deleted_count = 0
        
        for msg_id, msg_data in list(self.data["messages"].items()):
            if msg_data["guild_id"] == guild_id:
                channel = guild.get_channel(msg_data["channel_id"])
                if not channel:  # Channel no longer exists
                    del self.data["messages"][msg_id]
                    deleted_count += 1
        
        if deleted_count > 0:
            self.save_data()
            # Log cleanup action
            asyncio.create_task(self.log_message_action(
                "cleanup completed",
                guild,
                details=f"Removed {deleted_count} records for deleted channels"
            ))
        
        return deleted_count
    
    async def export_messages(self, guild_id: int, format_type: str = "json") -> str:
        """Export messages to a file"""
        messages = self.get_messages_for_guild(guild_id, include_deleted=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            if format_type.lower() == "json":
                filename = f"messages_export_{guild_id}_{timestamp}.json"
                filepath = self.messages_dir / filename
                
                async with aiofiles.open(filepath, 'w') as f:
                    await f.write(json.dumps(messages, indent=2))
            
            elif format_type.lower() == "txt":
                filename = f"messages_export_{guild_id}_{timestamp}.txt"
                filepath = self.messages_dir / filename
                
                async with aiofiles.open(filepath, 'w') as f:
                    await f.write(f"Message Export for Guild {guild_id}\n")
                    await f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    await f.write("=" * 50 + "\n\n")
                    
                    for message in messages:
                        await f.write(f"Message ID: {message['id']}\n")
                        await f.write(f"Created: {message['created_at']}\n")
                        await f.write(f"Channel: {message['channel_id']}\n")
                        await f.write(f"Discord Message ID: {message['message_id']}\n")
                        await f.write(f"Author: {message['author_id']}\n")
                        await f.write(f"Exists: {message['exists']}\n")
                        await f.write(f"Edit Count: {message['edit_count']}\n")
                        await f.write(f"Has Embed: {message.get('has_embed', False)}\n")
                        await f.write(f"Has Files: {message.get('has_files', False)}\n")
                        
                        if "deletion_reason" in message:
                            await f.write(f"Deletion Reason: {message['deletion_reason']}\n")
                        
                        await f.write(f"Content: {message['content']}\n")
                        await f.write("-" * 30 + "\n\n")
            
            # Log export action
            guild = self.bot.get_guild(guild_id)
            await self.log_message_action(
                "export completed",
                guild,
                details=f"Exported {len(messages)} messages to {format_type.upper()} format"
            )
            
            return str(filepath)
            
        except Exception as e:
            guild = self.bot.get_guild(guild_id)
            await self.log_message_error(f"Export failed: {e}", guild)
            raise
    
    # Helper methods for other cogs
    async def send_quick_message(self, 
                               content: str,
                               channel: discord.TextChannel,
                               author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Quick method to send tracked messages"""
        return await self.create_message(content, channel, author)
    
    async def send_success_message(self, 
                                 success_text: str,
                                 channel: discord.TextChannel,
                                 author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Send a standardized success message"""
        content = f"✅ {success_text}"
        return await self.create_message(content, channel, author)
    
    async def send_error_message(self, 
                               error_text: str,
                               channel: discord.TextChannel,
                               author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Send a standardized error message"""
        content = f"❌ {error_text}"
        return await self.create_message(content, channel, author)
    
    async def send_info_message(self, 
                              info_text: str,
                              channel: discord.TextChannel,
                              author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Send a standardized info message"""
        content = f"ℹ️ {info_text}"
        return await self.create_message(content, channel, author)
    
    def get_message_by_id(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Get message data by ID"""
        return self.data["messages"].get(str(message_id))
    
    async def get_discord_message(self, message_id: int) -> Optional[discord.Message]:
        """Get the Discord message object for a tracked message"""
        message_data = self.get_message_by_id(message_id)
        if not message_data or not message_data["exists"]:
            return None
        
        try:
            channel = self.bot.get_channel(message_data["channel_id"])
            if channel:
                return await channel.fetch_message(message_data["message_id"])
        except discord.NotFound:
            # Mark as deleted
            message_data["exists"] = False
            message_data["deletion_reason"] = "message_deleted"
            message_data["last_checked"] = datetime.now().isoformat()
            self.save_data()
            
            await self.log_message_action(
                "marked as deleted during fetch",
                channel.guild if channel else None,
                details=f"Message ID {message_id}"
            )
        
        return None
    
    @tasks.loop(hours=3)
    async def check_deleted_messages(self):
        """Periodically check for deleted messages"""
        checked_count = 0
        deleted_count = 0
        
        for msg_id, msg_data in self.data["messages"].items():
            if msg_data["exists"]:
                # Check messages that haven't been checked in the last 8 hours
                last_checked = datetime.fromisoformat(msg_data["last_checked"])
                if datetime.now() - last_checked > timedelta(hours=8):
                    exists = await self.check_message_exists(int(msg_id), force_check=True)
                    checked_count += 1
                    if not exists:
                        deleted_count += 1
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.3)
        
        if checked_count > 0:
            print(f"Background check: {checked_count} messages checked, {deleted_count} found deleted")

class MessageCog(commands.Cog):
    """Comprehensive message management system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.message_manager = MessageManager(bot)
        
        # Attach to bot for other cogs to use
        self.bot.message_manager = self.message_manager
    
    def has_send_message_permission(self, member: discord.Member) -> bool:
        """Check if member has send message permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.manage_messages
        
        return (permissions_cog.has_permission(member, 'permissions.sendbotmessage') or 
                permissions_cog.has_permission(member, 'permissions.omni'))
    
    def has_manage_message_permission(self, member: discord.Member) -> bool:
        """Check if member has manage message permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.manage_messages
        
        return (permissions_cog.has_permission(member, 'permissions.managebotmessages') or 
                permissions_cog.has_permission(member, 'permissions.omni'))
    
    # ==================== EVENT LISTENERS ====================
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Track when tracked messages are deleted"""
        # Only track our managed messages, not all messages
        self.message_manager.mark_message_deleted(message.id, "message_deleted")
    
    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        """Track when tracked messages are bulk deleted"""
        for message in messages:
            self.message_manager.mark_message_deleted(message.id, "bulk_deleted")
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Handle when a channel containing messages is deleted"""
        if isinstance(channel, discord.TextChannel):
            updated_count = self.message_manager.mark_channel_messages_deleted(channel.id)
            
            if updated_count > 0:
                await self.message_manager.log_message_action(
                    "channel deleted",
                    channel.guild,
                    details=f"Channel #{channel.name} deleted, marked {updated_count} messages as deleted"
                )
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Handle when the bot is removed from a guild or guild is deleted"""
        updated_count = self.message_manager.mark_guild_messages_deleted(guild.id)
        
        if updated_count > 0:
            await self.message_manager.log_message_action(
                "guild left",
                guild,
                details=f"Bot removed from guild {guild.name}, marked {updated_count} messages as deleted"
            )
    
    # ==================== SHARED IMPLEMENTATION METHODS ====================
    async def _send_message_impl(self, guild: discord.Guild, author: discord.Member, content: str, channel: discord.TextChannel, respond_func):
        """Shared implementation for sending messages"""
        if not self.has_send_message_permission(author):
            await respond_func("❌ You don't have permission to send tracked messages.", ephemeral=True)
            return
        
        try:
            # Check if content is too long (after processing escape sequences)
            processed_content = MessageManager.process_escape_sequences(content)
            if len(processed_content) > 2000:
                await respond_func("❌ Message content is too long (max 2000 characters after processing escape sequences).")
                return
            
            message_data = await self.message_manager.create_message(content, channel, author)
            
            embed = discord.Embed(
                title="Message Sent Successfully",
                description=f"Message ID: `{message_data['id']}`\nChannel: {channel.mention}\nMessage: [View Message](https://discord.com/channels/{guild.id}/{channel.id}/{message_data['message_id']})",
                color=discord.Color.green()
            )
            
            await respond_func(embed=embed)
            
        except Exception as e:
            await self.message_manager.log_message_error(
                f"Failed to send message: {e}",
                guild,
                author
            )
            await respond_func(f"❌ Failed to send message: {e}")
    
    async def _list_messages_impl(self, guild: discord.Guild, author: discord.Member, page: int, include_deleted: bool, respond_func):
        """Shared implementation for listing messages"""
        # First, check a few messages to update their status
        await respond_func("🔄 Checking message status...", ephemeral=True)
        updated = await self.message_manager.check_messages_for_guild(guild.id, max_checks=20)
        
        messages = self.message_manager.get_messages_for_guild(guild.id, include_deleted)
        
        if not messages:
            await respond_func("❌ No tracked messages found for this server.")
            return
        
        # Pagination
        per_page = 10
        total_pages = (len(messages) + per_page - 1) // per_page
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_messages = messages[start_idx:end_idx]
        
        embed = discord.Embed(
            title=f"Tracked Messages for {guild.name}",
            description=f"Showing {len(page_messages)} of {len(messages)} messages (Page {page}/{total_pages})",
            color=discord.Color.blue()
        )
        
        if updated > 0:
            embed.description += f"\n🔄 Updated {updated} message statuses"
        
        for msg_data in page_messages:
            channel = guild.get_channel(msg_data["channel_id"])
            channel_name = channel.name if channel else "❌ Deleted Channel"
            
            status = "✅" if msg_data["exists"] else "❌"
            created_date = datetime.fromisoformat(msg_data["created_at"]).strftime("%Y-%m-%d %H:%M")
            
            # Add deletion reason if available
            status_text = status
            if not msg_data["exists"] and "deletion_reason" in msg_data:
                reason_icons = {
                    "message_deleted": "🗑️",
                    "channel_deleted": "📁",
                    "bulk_deleted": "🧹",
                    "guild_left": "👋"
                }
                icon = reason_icons.get(msg_data["deletion_reason"], "❌")
                status_text = icon
            
            # Truncate content for display
            content_preview = msg_data["content"][:50] + ("..." if len(msg_data["content"]) > 50 else "")
            
            embed.add_field(
                name=f"{status_text} Message {msg_data['id']}",
                value=f"Channel: #{channel_name}\nCreated: {created_date}\nEdits: {msg_data['edit_count']}\nContent: {content_preview}",
                inline=True
            )
        
        embed.set_footer(text=f"Use 'message info <id>' for detailed information • Real-time tracking enabled")
        await respond_func(embed=embed)
    
    async def _message_info_impl(self, guild: discord.Guild, message_id: int, respond_func):
        """Shared implementation for message info"""
        message_data = self.message_manager.data["messages"].get(str(message_id))
        
        if not message_data or message_data["guild_id"] != guild.id:
            await respond_func("❌ Message not found.")
            return
        
        # Check if the message still exists
        current_exists = await self.message_manager.check_message_exists(message_id, force_check=True)
        
        channel = guild.get_channel(message_data["channel_id"])
        author = guild.get_member(message_data["author_id"])
        
        embed = discord.Embed(
            title=f"Message Information - ID {message_id}",
            color=discord.Color.green() if current_exists else discord.Color.red()
        )
        
        # Build status text
        status_text = "✅ Exists" if current_exists else "❌ Deleted"
        if not current_exists and "deletion_reason" in message_data:
            reason_map = {
                "message_deleted": "Message was deleted",
                "channel_deleted": "Channel was deleted", 
                "bulk_deleted": "Bulk message delete",
                "guild_left": "Bot left guild"
            }
            reason = reason_map.get(message_data["deletion_reason"], message_data["deletion_reason"])
            status_text += f" ({reason})"
        
        embed.add_field(
            name="Basic Info",
            value=f"Status: {status_text}\n"
                    f"Channel: {channel.mention if channel else '❌ Channel Deleted'}\n"
                    f"Author: {author.mention if author else 'Unknown'}\n"
                    f"Created: {datetime.fromisoformat(message_data['created_at']).strftime('%Y-%m-%d %H:%M:%S')}",
            inline=False
        )
        
        embed.add_field(
            name="Statistics",
            value=f"Edit Count: {message_data['edit_count']}\n"
                    f"Has Embed: {message_data.get('has_embed', False)}\n"
                    f"Has Files: {message_data.get('has_files', False)}\n"
                    f"Last Checked: {datetime.fromisoformat(message_data['last_checked']).strftime('%Y-%m-%d %H:%M:%S')}",
            inline=False
        )
        
        if current_exists and channel:
            embed.add_field(
                name="Links",
                value=f"[View Message](https://discord.com/channels/{guild.id}/{message_data['channel_id']}/{message_data['message_id']})",
                inline=False
            )
        
        # Show content preview
        content = message_data["content"]
        if len(content) > 1000:
            content = content[:1000] + "..."
        
        embed.add_field(
            name="Content",
            value=f"```\n{content}\n```",
            inline=False
        )
        
        await respond_func(embed=embed)

    # ==================== PREFIX COMMANDS ====================
    
    @commands.group(name="message", aliases=["msg", "messages"])
    async def message_group(self, ctx):
        """Message management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Message Commands",
                description="Available message management commands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Send Message",
                value="`message send <channel> <content>` - Send a tracked message",
                inline=False
            )
            embed.add_field(
                name="List Messages",
                value="`message list [page] [include_deleted]` - List server messages",
                inline=False
            )
            embed.add_field(
                name="Message Info",
                value="`message info <id>` - Get message information",
                inline=False
            )
            embed.add_field(
                name="Edit Message",
                value="`message edit <id> <content>` - Edit an existing message",
                inline=False
            )
            embed.add_field(
                name="Management",
                value="`message refresh` - Force check statuses\n"
                        "`message cleanup confirm` - Remove deleted records\n"
                        "`message export [format]` - Export all messages",
                inline=False
            )
            embed.add_field(
                name="**New: Line Breaks**",
                value='Use `\\n` for line breaks in message content:\n'
                        '`message send #general "Line 1\\nLine 2\\nLine 3"`\n'
                        'Also supports `\\t` for tabs',
                inline=False
            )
            await ctx.send(embed=embed)
    
    @message_group.command(name="send")
    async def send_message_prefix(self, ctx, channel: discord.TextChannel, *, content: str):
        """Send a tracked message to a channel"""
        async def respond(content=None, embed=None, ephemeral=False):
            if embed:
                await ctx.send(embed=embed)
            else:
                await ctx.send(content)
        
        await self._send_message_impl(ctx.guild, ctx.author, content, channel, respond)
    
    @message_group.command(name="list")
    async def list_messages_prefix(self, ctx, page: int = 1, include_deleted: bool = False):
        """List tracked messages for this server"""
        msg = None
        
        async def respond(content=None, embed=None, ephemeral=False):
            nonlocal msg
            if msg is None:
                if embed:
                    msg = await ctx.send(embed=embed)
                else:
                    msg = await ctx.send(content)
            else:
                if embed:
                    await msg.edit(content=None, embed=embed)
                else:
                    await msg.edit(content=content, embed=None)
        
        await self._list_messages_impl(ctx.guild, ctx.author, page, include_deleted, respond)
    
    @message_group.command(name="info")
    async def message_info_prefix(self, ctx, message_id: int):
        """Get detailed information about a message"""
        async def respond(content=None, embed=None, ephemeral=False):
            if embed:
                await ctx.send(embed=embed)
            else:
                await ctx.send(content)
        
        await self._message_info_impl(ctx.guild, message_id, respond)
    
    @message_group.command(name="edit")
    async def edit_message_prefix(self, ctx, message_id: int, *, content: str):
        """Edit an existing tracked message"""
        if not self.has_manage_message_permission(ctx.author):
            await ctx.send("❌ You don't have permission to edit messages.")
            return
        
        # Check length after processing escape sequences
        processed_content = MessageManager.process_escape_sequences(content)
        if len(processed_content) > 2000:
            await ctx.send("❌ Message content is too long (max 2000 characters after processing escape sequences).")
            return
        
        try:
            success = await self.message_manager.edit_message(message_id, content, ctx.author)
            
            if success:
                await ctx.send(f"✅ Message {message_id} updated successfully!")
            else:
                await ctx.send(f"❌ Failed to edit message {message_id}. It may not exist or may have been deleted.")
        
        except Exception as e:
            await self.message_manager.log_message_error(
                f"Edit command failed: {e}",
                ctx.guild,
                ctx.author
            )
            await ctx.send(f"❌ Failed to edit message: {e}")
    
    @message_group.command(name="refresh")
    async def refresh_messages_prefix(self, ctx):
        """Force refresh message statuses for this server"""
        msg = await ctx.send("🔄 Refreshing message statuses...")
        
        updated = await self.message_manager.check_messages_for_guild(ctx.guild.id, max_checks=50)
        
        if updated > 0:
            await msg.edit(content=f"✅ Refreshed message statuses. Updated {updated} messages.")
        else:
            await msg.edit(content="✅ Refreshed message statuses. No changes detected.")
    
    @message_group.command(name="cleanup")
    async def cleanup_deleted_prefix(self, ctx, confirm: str = None):
        """Remove message records for deleted channels/messages"""
        if not self.has_manage_message_permission(ctx.author):
            await ctx.send("❌ You don't have permission to cleanup messages.")
            return
        
        if confirm != "confirm":
            await ctx.send("⚠️ This will permanently remove message records for deleted channels and messages.\n"
                            "Use `message cleanup confirm` to proceed.")
            return
        
        deleted_count = self.message_manager.cleanup_deleted_channel_messages(ctx.guild.id)
        
        if deleted_count > 0:
            await ctx.send(f"✅ Removed {deleted_count} message records for deleted channels.")
        else:
            await ctx.send("ℹ️ No message records found for deleted channels.")
    
    @message_group.command(name="export")
    async def export_messages_prefix(self, ctx, format_type: str = "json"):
        """Export all tracked messages for this server"""
        if not self.has_manage_message_permission(ctx.author):
            await ctx.send("❌ You don't have permission to export messages.")
            return
        
        if format_type.lower() not in ["json", "txt"]:
            await ctx.send("❌ Invalid format. Use 'json' or 'txt'.")
            return
        
        try:
            await ctx.send("🔄 Exporting messages... This may take a moment.")
            
            filepath = await self.message_manager.export_messages(ctx.guild.id, format_type)
            
            file = discord.File(filepath)
            await ctx.send(f"✅ Exported {len(self.message_manager.get_messages_for_guild(ctx.guild.id, True))} messages:", file=file)
        
        except Exception as e:
            await self.message_manager.log_message_error(
                f"Export command failed: {e}",
                ctx.guild,
                ctx.author
            )
            await ctx.send(f"❌ Failed to export messages: {e}")
    
    @message_group.command(name="check")
    async def check_message_prefix(self, ctx, message_id: int):
        """Check if a message still exists"""
        exists = await self.message_manager.check_message_exists(message_id, force_check=True)
        
        if exists:
            await ctx.send(f"✅ Message {message_id} still exists.")
        else:
            await ctx.send(f"❌ Message {message_id} has been deleted or cannot be found.")

    # ==================== SLASH COMMANDS ====================
    
    bmessages_group = app_commands.Group(name="bmessage", description="Commands for managing bot messages.")
    
    @bmessages_group.command(name="send", description="Send a tracked message to a channel")
    @app_commands.describe(
        content="Message content to send (use \\n for line breaks)",
        channel="Channel to send the message to"
    )
    async def send_message_slash(self, interaction: discord.Interaction, content: str, channel: discord.TextChannel):
        """Send a tracked message to a channel"""
        async def respond(content=None, embed=None, ephemeral=False):
            if interaction.response.is_done():
                if embed:
                    await interaction.followup.send(embed=embed, ephemeral=ephemeral)
                else:
                    await interaction.followup.send(content, ephemeral=ephemeral)
            else:
                if embed:
                    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
                else:
                    await interaction.response.send_message(content, ephemeral=ephemeral)
        
        await self._send_message_impl(interaction.guild, interaction.user, content, channel, respond)
    
    @bmessages_group.command(name="list", description="List tracked messages for this server")
    @app_commands.describe(
        page="Page number (default: 1)",
        include_deleted="Include deleted messages (default: false)"
    )
    async def list_messages_slash(self, interaction: discord.Interaction, page: int = 1, include_deleted: bool = False):
        """List tracked messages for this server"""
        has_responded = False
        
        async def respond(content=None, embed=None, ephemeral=False):
            nonlocal has_responded
            if not has_responded:
                has_responded = True
                if embed:
                    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
                else:
                    await interaction.response.send_message(content, ephemeral=ephemeral)
            else:
                if embed:
                    await interaction.edit_original_response(content=None, embed=embed)
                else:
                    await interaction.edit_original_response(content=content, embed=None)
        
        await self._list_messages_impl(interaction.guild, interaction.user, page, include_deleted, respond)
    
    @bmessages_group.command(name="info", description="Get detailed information about a message")
    @app_commands.describe(message_id="ID of the message to get information about")
    async def message_info_slash(self, interaction: discord.Interaction, message_id: int):
        """Get detailed information about a message"""
        async def respond(content=None, embed=None, ephemeral=False):
            if interaction.response.is_done():
                if embed:
                    await interaction.followup.send(embed=embed, ephemeral=ephemeral)
                else:
                    await interaction.followup.send(content, ephemeral=ephemeral)
            else:
                if embed:
                    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
                else:
                    await interaction.response.send_message(content, ephemeral=ephemeral)
        
        await self._message_info_impl(interaction.guild, message_id, respond)
    
    @bmessages_group.command(name="edit", description="Edit an existing tracked message")
    @app_commands.describe(
        message_id="ID of the message to edit",
        content="New message content (use \\n for line breaks)"
    )
    async def edit_message_slash(self, interaction: discord.Interaction, message_id: int, content: str):
        """Edit an existing tracked message"""
        if not self.has_manage_message_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to edit messages.", ephemeral=True)
            return
        
        # Check length after processing escape sequences
        processed_content = MessageManager.process_escape_sequences(content)
        if len(processed_content) > 2000:
            await interaction.response.send_message("❌ Message content is too long (max 2000 characters after processing escape sequences).", ephemeral=True)
            return
        
        try:
            success = await self.message_manager.edit_message(message_id, content, interaction.user)
            
            if success:
                await interaction.response.send_message(f"✅ Message {message_id} updated successfully!")
            else:
                await interaction.response.send_message(f"❌ Failed to edit message {message_id}. It may not exist or may have been deleted.")
        
        except Exception as e:
            await self.message_manager.log_message_error(
                f"Edit slash command failed: {e}",
                interaction.guild,
                interaction.user
            )
            await interaction.response.send_message(f"❌ Failed to edit message: {e}")
    
    @bmessages_group.command(name="refresh", description="Force refresh message statuses for this server")
    async def refresh_messages_slash(self, interaction: discord.Interaction):
        """Force refresh message statuses for this server"""
        await interaction.response.send_message("🔄 Refreshing message statuses...", ephemeral=True)
        
        updated = await self.message_manager.check_messages_for_guild(interaction.guild.id, max_checks=50)
        
        if updated > 0:
            await interaction.edit_original_response(content=f"✅ Refreshed message statuses. Updated {updated} messages.")
        else:
            await interaction.edit_original_response(content="✅ Refreshed message statuses. No changes detected.")
    
    @bmessages_group.command(name="cleanup", description="Remove message records for deleted channels")
    @app_commands.describe(confirm="Type 'confirm' to proceed with cleanup")
    async def cleanup_deleted_slash(self, interaction: discord.Interaction, confirm: str = ""):
        """Remove message records for deleted channels/messages"""
        if not self.has_manage_message_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to cleanup messages.", ephemeral=True)
            return
        
        if confirm != "confirm":
            await interaction.response.send_message(
                "⚠️ This will permanently remove message records for deleted channels and messages.\n"
                "Use `/bmessage cleanup confirm:confirm` to proceed.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        deleted_count = self.message_manager.cleanup_deleted_channel_messages(interaction.guild.id)
        
        if deleted_count > 0:
            await interaction.followup.send(f"✅ Removed {deleted_count} message records for deleted channels.", ephemeral=True)
        else:
            await interaction.followup.send("ℹ️ No message records found for deleted channels.", ephemeral=True)
    
    @bmessages_group.command(name="export", description="Export all tracked messages for this server")
    @app_commands.describe(format_type="Export format (json or txt)")
    @app_commands.choices(format_type=[
        app_commands.Choice(name="JSON", value="json"),
        app_commands.Choice(name="Text", value="txt")
    ])
    async def export_messages_slash(self, interaction: discord.Interaction, format_type: str = "json"):
        """Export all tracked messages for this server"""
        if not self.has_manage_message_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to export messages.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            filepath = await self.message_manager.export_messages(interaction.guild.id, format_type)
            
            file = discord.File(filepath)
            message_count = len(self.message_manager.get_messages_for_guild(interaction.guild.id, True))
            await interaction.followup.send(
                f"✅ Exported {message_count} messages:",
                file=file,
                ephemeral=True
            )
        
        except Exception as e:
            await self.message_manager.log_message_error(
                f"Export slash command failed: {e}",
                interaction.guild,
                interaction.user
            )
            await interaction.followup.send(f"❌ Failed to export messages: {e}", ephemeral=True)
    
    @bmessages_group.command(name="check", description="Check if a message still exists")
    @app_commands.describe(message_id="ID of the message to check")
    async def check_message_slash(self, interaction: discord.Interaction, message_id: int):
        """Check if a message still exists"""
        await interaction.response.defer(ephemeral=True)
        
        exists = await self.message_manager.check_message_exists(message_id, force_check=True)
        
        if exists:
            await interaction.followup.send(f"✅ Message {message_id} still exists.", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Message {message_id} has been deleted or cannot be found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MessageCog(bot))
