"""
Discord Embed Management Cog - Advanced Embed Creation & Tracking System

OVERVIEW:
Comprehensive embed management with real-time tracking, automatic cleanup, and advanced
configuration syntax. Tracks embed lifecycle and provides management tools.

SETUP:
- No manual setup required - auto-creates database files
- Database: src/database/embed_db.json
- Export directory: src/database/embeds/
- Requires: PermissionsCog (optional), LoggingCog (optional)
- Auto-attaches to bot.embed_manager for other cogs

PERMISSIONS:
- Send embeds: 'permissions.sendembed' or manage messages
- Manage embeds: 'permissions.manageembeds' or manage messages

COMMANDS:
/embeds send <channel> <config>     - Send embed with advanced config syntax
/embeds list [page] [include_deleted] - List server embeds with status
/embeds info <id>                   - Get detailed embed information
/embeds edit <id> <config>          - Edit existing embed in-place
/embeds refresh                     - Force check all embed statuses
/embeds cleanup <confirm>           - Remove deleted embed records
/embeds export [format]             - Export embeds (JSON/TXT)
/embeds check <id>                  - Check if specific embed exists
/embeds help                        - Show configuration syntax

Prefix commands: !embed <subcommand> (same functionality)

USAGE BY OTHER COGS:

# Quick embed creation
class MyCog(commands.Cog):
    @commands.command()
    async def example(self, ctx):
        # Simple success embed
        embed_data = await self.bot.embed_manager.create_success_embed(
            "Operation completed!", ctx.channel, ctx.author
        )
        
        # Error embed
        embed_data = await self.bot.embed_manager.create_error_embed(
            "Something went wrong!", ctx.channel, ctx.author
        )
        
        # Custom embed
        embed_data = await self.bot.embed_manager.create_quick_embed(
            title="Custom Title",
            description="Custom description", 
            channel=ctx.channel,
            author=ctx.author,
            color=0x00ff00
        )
        
        # Get embed message object
        message = await self.bot.embed_manager.get_embed_message(embed_data['id'])

CONFIG SYNTAX EXAMPLES:
title="My Title" description="Line 1\\nLine 2" color=0x00ff00 timestamp=true
author_name="Author" footer_text="Footer" thumbnail="https://image.url"
field1_name="Field" field1_value="Value" field1_inline=true

FEATURES:
• Advanced configuration syntax with escape sequences (\\n for newlines)
• Real-time embed existence tracking with automatic status updates
• Event listeners for message/channel/guild deletion detection
• Background task checking embed statuses every 2 hours
• Permission-based access control with role integration
• Export functionality (JSON/TXT) with timestamped files
• Pagination for large embed lists with status indicators
• In-place embed editing with version tracking
• Comprehensive logging integration for all operations
• Automatic cleanup of deleted channel/guild records
• Helper methods for other cogs (success/error/info embeds)
• Force refresh capabilities for immediate status updates
• Detailed embed information with direct Discord links
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

class EmbedConfig:
    """Class to handle embed configuration parsing and creation"""
    
    def __init__(self, config_dict: Dict[str, Any]):
        self.config = config_dict
    
    @classmethod
    def from_string(cls, config_string: str):
        """Create EmbedConfig from a formatted string"""
        config = {}
        
        # Parse key=value pairs
        pattern = r'(\w+)=(?:"([^"]*)"|(\S+))'
        matches = re.findall(pattern, config_string)
        
        for match in matches:
            key, quoted_value, unquoted_value = match
            value = quoted_value if quoted_value else unquoted_value
            
            # Process escape sequences for text fields
            text_fields = ['title', 'description', 'author_name', 'footer_text']
            is_field_text = key.endswith('_name') or key.endswith('_value')
            is_text_field = key in text_fields or is_field_text
            
            if value and is_text_field:
                # Convert escape sequences to actual characters
                value = value.replace('\\n', '\n')  # Convert \n to actual newlines
                value = value.replace('\\t', '\t')  # Convert \t to actual tabs
                value = value.replace('\\r', '\r')  # Convert \r to carriage returns
                value = value.replace('\\\\', '\\')  # Convert \\ to literal backslash
            
            # Type conversion
            if key == 'color':
                if value.startswith('0x'):
                    config[key] = int(value, 16)
                elif value.isdigit():
                    config[key] = int(value)
                else:
                    config[key] = value
            elif key in ['timestamp']:
                config[key] = value.lower() in ('true', '1', 'yes')
            elif key.endswith('_inline'):
                config[key] = value.lower() in ('true', '1', 'yes')
            else:
                config[key] = value
        
        return cls(config)
    
    def to_embed(self) -> discord.Embed:
        """Convert configuration to Discord embed"""
        # Handle color
        color = discord.Color.default()
        if 'color' in self.config:
            if isinstance(self.config['color'], int):
                color = discord.Color(self.config['color'])
            elif isinstance(self.config['color'], str):
                color = getattr(discord.Color, self.config['color'], discord.Color.default)()
        
        # Create embed
        embed = discord.Embed(
            title=self.config.get('title'),
            description=self.config.get('description'),
            color=color,
            url=self.config.get('url')
        )
        
        # Add timestamp if requested
        if self.config.get('timestamp'):
            embed.timestamp = datetime.now()
        
        # Add author
        if 'author_name' in self.config:
            embed.set_author(
                name=self.config['author_name'],
                url=self.config.get('author_url'),
                icon_url=self.config.get('author_icon')
            )
        
        # Add footer
        if 'footer_text' in self.config:
            embed.set_footer(
                text=self.config['footer_text'],
                icon_url=self.config.get('footer_icon')
            )
        
        # Add thumbnail
        if 'thumbnail' in self.config:
            embed.set_thumbnail(url=self.config['thumbnail'])
        
        # Add image
        if 'image' in self.config:
            embed.set_image(url=self.config['image'])
        
        # Add fields
        field_count = 1
        while f'field{field_count}_name' in self.config:
            embed.add_field(
                name=self.config[f'field{field_count}_name'],
                value=self.config[f'field{field_count}_value'],
                inline=self.config.get(f'field{field_count}_inline', True)
            )
            field_count += 1
        
        return embed

class EmbedManager:
    """Manages embed storage, tracking, and operations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.data_file = "src/database/embed_db.json"
        self.messages_dir = Path("src/database/embeds")
        self.messages_dir.mkdir(parents=True, exist_ok=True)
        
        self.data = self.load_data()
        
        # Start background task
        self.check_deleted_embeds.start()
    
    async def log_embed_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log embed actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Embed {action}"
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
                    file_override="embed_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log embed action: {e}")

    async def log_embed_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log embed errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Embed Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="embed_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log embed error: {e}")

    async def log_embed_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log embed warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Embed Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="embed_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log embed warning: {e}")
    
    def load_data(self) -> Dict[str, Any]:
        """Load embed data from file"""
        try:
            if Path(self.data_file).exists():
                with open(self.data_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_embed_error(f"Error loading embed data: {e}"))
        return {
            "embeds": {},
            "guild_settings": {},
            "templates": {},
            "next_id": 1
        }
    
    def save_data(self):
        """Save embed data to file"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_embed_error(f"Error saving embed data: {e}"))
    
    def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get guild-specific settings"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.data["guild_settings"]:
            self.data["guild_settings"][guild_id_str] = {
                "auto_delete_tracking": True,
                "log_embed_sends": True,
                "max_stored_embeds": 1000,
                "real_time_checking": True,
                "auto_cleanup_deleted": True
            }
            self.save_data()
        return self.data["guild_settings"][guild_id_str]
    
    def mark_embed_deleted(self, message_id: int, reason: str = "message_deleted"):
        """Mark an embed as deleted based on message ID"""
        for embed_id, embed_data in self.data["embeds"].items():
            if embed_data["message_id"] == message_id and embed_data["exists"]:
                embed_data["exists"] = False
                embed_data["last_checked"] = datetime.now().isoformat()
                embed_data["deletion_reason"] = reason
                break
        self.save_data()
    
    def mark_channel_embeds_deleted(self, channel_id: int):
        """Mark all embeds in a deleted channel as no longer existing"""
        updated_count = 0
        for embed_id, embed_data in self.data["embeds"].items():
            if embed_data["channel_id"] == channel_id and embed_data["exists"]:
                embed_data["exists"] = False
                embed_data["last_checked"] = datetime.now().isoformat()
                embed_data["deletion_reason"] = "channel_deleted"
                updated_count += 1
        
        if updated_count > 0:
            self.save_data()
            print(f"Marked {updated_count} embeds as deleted due to channel deletion")
        
        return updated_count
    
    def mark_guild_embeds_deleted(self, guild_id: int):
        """Mark all embeds in a deleted guild as no longer existing"""
        updated_count = 0
        for embed_id, embed_data in self.data["embeds"].items():
            if embed_data["guild_id"] == guild_id and embed_data["exists"]:
                embed_data["exists"] = False
                embed_data["last_checked"] = datetime.now().isoformat()
                embed_data["deletion_reason"] = "guild_left"
                updated_count += 1
        
        if updated_count > 0:
            self.save_data()
            print(f"Marked {updated_count} embeds as deleted due to guild removal")
        
        return updated_count
    
    async def create_embed(self, 
                            config: EmbedConfig, 
                            channel: discord.TextChannel,
                            author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Create and send an embed, then store it"""
        
        embed = config.to_embed()
        
        try:
            message = await channel.send(embed=embed)
            
            # Store embed data
            embed_id = self.data["next_id"]
            self.data["next_id"] += 1
            
            embed_data = {
                "id": embed_id,
                "guild_id": channel.guild.id,
                "channel_id": channel.id,
                "message_id": message.id,
                "author_id": author.id,
                "config": config.config,
                "created_at": datetime.now().isoformat(),
                "last_checked": datetime.now().isoformat(),
                "exists": True,
                "edit_count": 0
            }
            
            self.data["embeds"][str(embed_id)] = embed_data
            self.save_data()
            
            # Log the action
            await self.log_embed_action(
                "sent",
                channel.guild,
                author,
                f"Embed ID {embed_id} sent to #{channel.name}"
            )
            
            return embed_data
            
        except discord.Forbidden:
            await self.log_embed_error(
                f"No permission to send embed in #{channel.name}",
                channel.guild,
                author
            )
            raise Exception("No permission to send messages in that channel")
        except discord.HTTPException as e:
            await self.log_embed_error(
                f"Failed to send embed in #{channel.name}: {e}",
                channel.guild,
                author
            )
            raise Exception(f"Failed to send embed: {e}")
    
    async def edit_embed(self, embed_id: int, new_config: EmbedConfig, editor: Union[discord.Member, discord.User] = None) -> bool:
        """Edit an existing embed"""
        embed_data = self.data["embeds"].get(str(embed_id))
        if not embed_data:
            await self.log_embed_warning(f"Attempted to edit non-existent embed ID {embed_id}")
            return False
        
        # Check if channel still exists
        channel = self.bot.get_channel(embed_data["channel_id"])
        if not channel:
            embed_data["exists"] = False
            embed_data["deletion_reason"] = "channel_deleted"
            embed_data["last_checked"] = datetime.now().isoformat()
            self.save_data()
            await self.log_embed_warning(
                f"Cannot edit embed {embed_id} - channel deleted",
                None,
                editor
            )
            return False
        
        if not embed_data["exists"]:
            await self.log_embed_warning(
                f"Attempted to edit deleted embed {embed_id}",
                channel.guild,
                editor
            )
            return False
        
        try:
            message = await channel.fetch_message(embed_data["message_id"])
            new_embed = new_config.to_embed()
            
            await message.edit(embed=new_embed)
            
            # Update stored data
            embed_data["config"] = new_config.config
            embed_data["edit_count"] += 1
            embed_data["last_checked"] = datetime.now().isoformat()
            
            # Remove deletion reason if it exists
            if "deletion_reason" in embed_data:
                del embed_data["deletion_reason"]
            
            self.save_data()
            
            # Log the edit
            await self.log_embed_action(
                "edited",
                channel.guild,
                editor,
                f"Embed ID {embed_id} edited (edit #{embed_data['edit_count']})"
            )
            
            return True
            
        except discord.NotFound:
            # Message was deleted
            embed_data["exists"] = False
            embed_data["deletion_reason"] = "message_deleted"
            embed_data["last_checked"] = datetime.now().isoformat()
            self.save_data()
            
            await self.log_embed_action(
                "edit failed - message deleted",
                channel.guild,
                editor,
                f"Embed ID {embed_id} was already deleted"
            )
            return False
        except discord.Forbidden:
            await self.log_embed_error(
                f"No permission to edit embed {embed_id}",
                channel.guild,
                editor
            )
            return False
    
    async def check_embed_exists(self, embed_id: int, force_check: bool = False) -> bool:
        """Check if an embed message still exists"""
        embed_data = self.data["embeds"].get(str(embed_id))
        if not embed_data:
            return False
        
        # If we've checked recently and it existed, and we're not forcing a check, assume it still exists
        if not force_check and embed_data["exists"]:
            last_checked = datetime.fromisoformat(embed_data["last_checked"])
            if datetime.now() - last_checked < timedelta(minutes=5):
                return True
        
        # Check if channel exists first
        channel = self.bot.get_channel(embed_data["channel_id"])
        if not channel:
            embed_data["exists"] = False
            embed_data["last_checked"] = datetime.now().isoformat()
            embed_data["deletion_reason"] = "channel_deleted"
            self.save_data()
            return False
        
        try:
            await channel.fetch_message(embed_data["message_id"])
            embed_data["last_checked"] = datetime.now().isoformat()
            embed_data["exists"] = True
            
            # Remove deletion reason if it exists (embed was recovered)
            if "deletion_reason" in embed_data:
                del embed_data["deletion_reason"]
            
            self.save_data()
            return True
            
        except discord.NotFound:
            embed_data["exists"] = False
            embed_data["last_checked"] = datetime.now().isoformat()
            embed_data["deletion_reason"] = "message_deleted"
            self.save_data()
            
            # Log deletion
            await self.log_embed_action(
                "detected as deleted",
                channel.guild,
                details=f"Embed ID {embed_id}"
            )
            
            return False
        except discord.Forbidden:
            return True  # Assume it exists if we can't check
    
    async def check_embeds_for_guild(self, guild_id: int, max_checks: int = 10) -> int:
        """Check a few embeds for a guild to update their status"""
        checked = 0
        updated = 0
        
        for embed_id, embed_data in self.data["embeds"].items():
            if embed_data["guild_id"] == guild_id and embed_data["exists"]:
                # Only check embeds that haven't been checked recently
                last_checked = datetime.fromisoformat(embed_data["last_checked"])
                if datetime.now() - last_checked > timedelta(minutes=30):
                    old_status = embed_data["exists"]
                    await self.check_embed_exists(int(embed_id), force_check=True)
                    new_status = embed_data["exists"]
                    
                    if old_status != new_status:
                        updated += 1
                    
                    checked += 1
                    if checked >= max_checks:
                        break
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.1)
        
        if checked > 0:
            guild = self.bot.get_guild(guild_id)
            await self.log_embed_action(
                "status check completed",
                guild,
                details=f"Checked {checked} embeds, {updated} status changes"
            )
        
        return updated
    
    def get_embeds_for_guild(self, guild_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """Get all embeds for a guild"""
        embeds = []
        for embed_data in self.data["embeds"].values():
            if embed_data["guild_id"] == guild_id:
                if include_deleted or embed_data["exists"]:
                    embeds.append(embed_data)
        
        return sorted(embeds, key=lambda x: x["created_at"], reverse=True)
    
    def cleanup_deleted_channel_embeds(self, guild_id: int) -> int:
        """Remove embed records for channels that no longer exist"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return 0
        
        deleted_count = 0
        
        for embed_id, embed_data in list(self.data["embeds"].items()):
            if embed_data["guild_id"] == guild_id:
                channel = guild.get_channel(embed_data["channel_id"])
                if not channel:  # Channel no longer exists
                    del self.data["embeds"][embed_id]
                    deleted_count += 1
        
        if deleted_count > 0:
            self.save_data()
            # Log cleanup action
            asyncio.create_task(self.log_embed_action(
                "cleanup completed",
                guild,
                details=f"Removed {deleted_count} records for deleted channels"
            ))
        
        return deleted_count
    
    async def export_embeds(self, guild_id: int, format_type: str = "json") -> str:
        """Export embeds to a file"""
        embeds = self.get_embeds_for_guild(guild_id, include_deleted=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            if format_type.lower() == "json":
                filename = f"embeds_export_{guild_id}_{timestamp}.json"
                filepath = self.embeds_dir / filename
                
                async with aiofiles.open(filepath, 'w') as f:
                    await f.write(json.dumps(embeds, indent=2))
            
            elif format_type.lower() == "txt":
                filename = f"embeds_export_{guild_id}_{timestamp}.txt"
                filepath = self.embeds_dir / filename
                
                async with aiofiles.open(filepath, 'w') as f:
                    await f.write(f"Embed Export for Guild {guild_id}\n")
                    await f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    await f.write("=" * 50 + "\n\n")
                    
                    for embed in embeds:
                        await f.write(f"Embed ID: {embed['id']}\n")
                        await f.write(f"Created: {embed['created_at']}\n")
                        await f.write(f"Channel: {embed['channel_id']}\n")
                        await f.write(f"Message: {embed['message_id']}\n")
                        await f.write(f"Author: {embed['author_id']}\n")
                        await f.write(f"Exists: {embed['exists']}\n")
                        await f.write(f"Edit Count: {embed['edit_count']}\n")
                        
                        if "deletion_reason" in embed:
                            await f.write(f"Deletion Reason: {embed['deletion_reason']}\n")
                        
                        await f.write(f"Config: {json.dumps(embed['config'], indent=2)}\n")
                        await f.write("-" * 30 + "\n\n")
            
            # Log export action
            guild = self.bot.get_guild(guild_id)
            await self.log_embed_action(
                "export completed",
                guild,
                details=f"Exported {len(embeds)} embeds to {format_type.upper()} format"
            )
            
            return str(filepath)
            
        except Exception as e:
            guild = self.bot.get_guild(guild_id)
            await self.log_embed_error(f"Export failed: {e}", guild)
            raise
    
    # Helper methods for other cogs
    async def create_quick_embed(self, 
                                title: str, 
                                description: str, 
                                channel: discord.TextChannel,
                                author: Union[discord.Member, discord.User],
                                color: int = 0x00ff00,
                               **kwargs) -> Dict[str, Any]:
        """Quick method to create simple embeds"""
        config_dict = {
            "title": title,
            "description": description,
            "color": color,
            **kwargs
        }
        
        config = EmbedConfig(config_dict)
        return await self.create_embed(config, channel, author)
    
    async def create_error_embed(self, 
                                error_message: str,
                                channel: discord.TextChannel,
                                author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Create a standardized error embed"""
        config = EmbedConfig({
            "title": "❌ Error",
            "description": error_message,
            "color": 0xff0000,
            "timestamp": True
        })
        
        return await self.create_embed(config, channel, author)
    
    async def create_success_embed(self, 
                                    success_message: str,
                                    channel: discord.TextChannel,
                                    author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Create a standardized success embed"""
        config = EmbedConfig({
            "title": "✅ Success",
            "description": success_message,
            "color": 0x00ff00,
            "timestamp": True
        })
        
        return await self.create_embed(config, channel, author)
    
    async def create_info_embed(self, 
                                info_message: str,
                                channel: discord.TextChannel,
                                author: Union[discord.Member, discord.User]) -> Dict[str, Any]:
        """Create a standardized info embed"""
        config = EmbedConfig({
            "title": "ℹ️ Information",
            "description": info_message,
            "color": 0x0099ff,
            "timestamp": True
        })
        
        return await self.create_embed(config, channel, author)
    
    def get_embed_by_id(self, embed_id: int) -> Optional[Dict[str, Any]]:
        """Get embed data by ID"""
        return self.data["embeds"].get(str(embed_id))
    
    async def get_embed_message(self, embed_id: int) -> Optional[discord.Message]:
        """Get the Discord message object for an embed"""
        embed_data = self.get_embed_by_id(embed_id)
        if not embed_data or not embed_data["exists"]:
            return None
        
        try:
            channel = self.bot.get_channel(embed_data["channel_id"])
            if channel:
                return await channel.fetch_message(embed_data["message_id"])
        except discord.NotFound:
            # Mark as deleted
            embed_data["exists"] = False
            embed_data["deletion_reason"] = "message_deleted"
            embed_data["last_checked"] = datetime.now().isoformat()
            self.save_data()
            
            await self.log_embed_action(
                "marked as deleted during fetch",
                channel.guild if channel else None,
                details=f"Embed ID {embed_id}"
            )
        
        return None
    
    @tasks.loop(hours=2)
    async def check_deleted_embeds(self):
        """Periodically check for deleted embeds"""
        checked_count = 0
        deleted_count = 0
        
        for embed_id, embed_data in self.data["embeds"].items():
            if embed_data["exists"]:
                # Check embeds that haven't been checked in the last 6 hours
                last_checked = datetime.fromisoformat(embed_data["last_checked"])
                if datetime.now() - last_checked > timedelta(hours=6):
                    exists = await self.check_embed_exists(int(embed_id), force_check=True)
                    checked_count += 1
                    if not exists:
                        deleted_count += 1
                    
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.2)
        
        if checked_count > 0:
            print(f"Background check: {checked_count} embeds checked, {deleted_count} found deleted")

class EmbedCog(commands.Cog):
    """Comprehensive embed management system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.embed_manager = EmbedManager(bot)
        
        # Attach to bot for other cogs to use
        self.bot.embed_manager = self.embed_manager
    
    def has_send_embed_permission(self, member: discord.Member) -> bool:
        """Check if member has send embed permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.manage_messages
        
        return (permissions_cog.has_permission(member, 'permissions.sendembed') or 
                permissions_cog.has_permission(member, 'permissions.omni'))
    
    def has_manage_embed_permission(self, member: discord.Member) -> bool:
        """Check if member has manage embed permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.manage_messages
        
        return (permissions_cog.has_permission(member, 'permissions.manageembeds')or 
                permissions_cog.has_permission(member, 'permissions.omni'))
    
    # ==================== EVENT LISTENERS ====================
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Track when embed messages are deleted"""
        if message.embeds:  # Only track messages with embeds
            self.embed_manager.mark_embed_deleted(message.id, "message_deleted")
    
    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        """Track when embed messages are bulk deleted"""
        for message in messages:
            if message.embeds:
                self.embed_manager.mark_embed_deleted(message.id, "bulk_deleted")
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Handle when a channel containing embeds is deleted"""
        if isinstance(channel, discord.TextChannel):
            updated_count = self.embed_manager.mark_channel_embeds_deleted(channel.id)
            
            if updated_count > 0:
                await self.embed_manager.log_embed_action(
                    "channel deleted",
                    channel.guild,
                    details=f"Channel #{channel.name} deleted, marked {updated_count} embeds as deleted"
                )
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Handle when the bot is removed from a guild or guild is deleted"""
        updated_count = self.embed_manager.mark_guild_embeds_deleted(guild.id)
        
        if updated_count > 0:
            await self.embed_manager.log_embed_action(
                "guild left",
                guild,
                details=f"Bot removed from guild {guild.name}, marked {updated_count} embeds as deleted"
            )
    
    # ==================== SHARED IMPLEMENTATION METHODS ====================
    async def _send_embed_impl(self, guild: discord.Guild, author: discord.Member, config_string: str, channel: discord.TextChannel, respond_func):
        """Shared implementation for sending embeds"""
        if not self.has_send_embed_permission(author):
            await respond_func("❌ You don't have permission to send embeds.", ephemeral=True)
            return
        
        try:
            config = EmbedConfig.from_string(config_string)
            embed_data = await self.embed_manager.create_embed(config, channel, author)
            
            embed = discord.Embed(
                title="Embed Sent Successfully",
                description=f"Embed ID: `{embed_data['id']}`\nChannel: {channel.mention}\nMessage: [View Message](https://discord.com/channels/{guild.id}/{channel.id}/{embed_data['message_id']})",
                color=discord.Color.green()
            )
            
            await respond_func(embed=embed)
            
        except Exception as e:
            await self.embed_manager.log_embed_error(
                f"Failed to send embed: {e}",
                guild,
                author
            )
            await respond_func(f"❌ Failed to send embed: {e}")
    
    async def _list_embeds_impl(self, guild: discord.Guild, author: discord.Member, page: int, include_deleted: bool, respond_func):
        """Shared implementation for listing embeds"""
        # First, check a few embeds to update their status
        await respond_func("🔄 Checking embed status...", ephemeral=True)
        updated = await self.embed_manager.check_embeds_for_guild(guild.id, max_checks=15)
        
        embeds = self.embed_manager.get_embeds_for_guild(guild.id, include_deleted)
        
        if not embeds:
            await respond_func("❌ No embeds found for this server.")
            return
        
        # Pagination
        per_page = 10
        total_pages = (len(embeds) + per_page - 1) // per_page
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_embeds = embeds[start_idx:end_idx]
        
        embed = discord.Embed(
            title=f"Embeds for {guild.name}",
            description=f"Showing {len(page_embeds)} of {len(embeds)} embeds (Page {page}/{total_pages})",
            color=discord.Color.blue()
        )
        
        if updated > 0:
            embed.description += f"\n🔄 Updated {updated} embed statuses"
        
        for embed_data in page_embeds:
            channel = guild.get_channel(embed_data["channel_id"])
            channel_name = channel.name if channel else "❌ Deleted Channel"
            
            status = "✅" if embed_data["exists"] else "❌"
            created_date = datetime.fromisoformat(embed_data["created_at"]).strftime("%Y-%m-%d %H:%M")
            
            # Add deletion reason if available
            status_text = status
            if not embed_data["exists"] and "deletion_reason" in embed_data:
                reason_icons = {
                    "message_deleted": "🗑️",
                    "channel_deleted": "📁",
                    "bulk_deleted": "🧹",
                    "guild_left": "👋"
                }
                icon = reason_icons.get(embed_data["deletion_reason"], "❌")
                status_text = icon
            
            embed.add_field(
                name=f"{status_text} Embed {embed_data['id']}",
                value=f"Channel: #{channel_name}\nCreated: {created_date}\nEdits: {embed_data['edit_count']}",
                inline=True
            )
        
        embed.set_footer(text=f"Use 'embed info <id>' for detailed information • Real-time tracking enabled")
        await respond_func(embed=embed)
    
    async def _embed_info_impl(self, guild: discord.Guild, embed_id: int, respond_func):
        """Shared implementation for embed info"""
        embed_data = self.embed_manager.data["embeds"].get(str(embed_id))
        
        if not embed_data or embed_data["guild_id"] != guild.id:
            await respond_func("❌ Embed not found.")
            return
        
        # Check if the embed still exists
        current_exists = await self.embed_manager.check_embed_exists(embed_id, force_check=True)
        
        channel = guild.get_channel(embed_data["channel_id"])
        author = guild.get_member(embed_data["author_id"])
        
        embed = discord.Embed(
            title=f"Embed Information - ID {embed_id}",
            color=discord.Color.green() if current_exists else discord.Color.red()
        )
        
        # Build status text
        status_text = "✅ Exists" if current_exists else "❌ Deleted"
        if not current_exists and "deletion_reason" in embed_data:
            reason_map = {
                "message_deleted": "Message was deleted",
                "channel_deleted": "Channel was deleted", 
                "bulk_deleted": "Bulk message delete",
                "guild_left": "Bot left guild"
            }
            reason = reason_map.get(embed_data["deletion_reason"], embed_data["deletion_reason"])
            status_text += f" ({reason})"
        
        embed.add_field(
            name="Basic Info",
            value=f"Status: {status_text}\n"
                    f"Channel: {channel.mention if channel else '❌ Channel Deleted'}\n"
                    f"Author: {author.mention if author else 'Unknown'}\n"
                    f"Created: {datetime.fromisoformat(embed_data['created_at']).strftime('%Y-%m-%d %H:%M:%S')}",
            inline=False
        )
        
        embed.add_field(
            name="Statistics",
            value=f"Edit Count: {embed_data['edit_count']}\n"
                    f"Last Checked: {datetime.fromisoformat(embed_data['last_checked']).strftime('%Y-%m-%d %H:%M:%S')}",
            inline=False
        )
        
        if current_exists and channel:
            embed.add_field(
                name="Links",
                value=f"[View Message](https://discord.com/channels/{guild.id}/{embed_data['channel_id']}/{embed_data['message_id']})",
                inline=False
            )
        
        # Show config preview
        config_preview = json.dumps(embed_data["config"], indent=2)[:1000]
        if len(config_preview) == 1000:
            config_preview += "..."
        
        embed.add_field(
            name="Configuration",
            value=f"```json\n{config_preview}\n```",
            inline=False
        )
        
        await respond_func(embed=embed)

    # ==================== PREFIX COMMANDS ====================
    
    @commands.group(name="embed", aliases=["embeds"])
    async def embed_group(self, ctx):
        """Embed management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Embed Commands",
                description="Available embed management commands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Send Embed",
                value="`embed send <channel> <config>` - Send an embed",
                inline=False
            )
            embed.add_field(
                name="List Embeds",
                value="`embed list [page] [include_deleted]` - List server embeds",
                inline=False
            )
            embed.add_field(
                name="Embed Info",
                value="`embed info <id>` - Get embed information",
                inline=False
            )
            embed.add_field(
                name="Edit Embed",
                value="`embed edit <id> <config>` - Edit an existing embed",
                inline=False
            )
            embed.add_field(
                name="Management",
                value="`embed refresh` - Force check statuses\n"
                        "`embed cleanup confirm` - Remove deleted records\n"
                        "`embed export [format]` - Export all embeds",
                inline=False
            )
            embed.add_field(
                name="Help",
                value="`embed help` - Show configuration syntax",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @embed_group.command(name="send")
    async def send_embed_prefix(self, ctx, channel: discord.TextChannel, *, config: str):
        """Send an embed to a channel"""
        async def respond(content=None, embed=None, ephemeral=False):
            if embed:
                await ctx.send(embed=embed)
            else:
                await ctx.send(content)
        
        await self._send_embed_impl(ctx.guild, ctx.author, config, channel, respond)
    
    @embed_group.command(name="list")
    async def list_embeds_prefix(self, ctx, page: int = 1, include_deleted: bool = False):
        """List embeds for this server"""
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
        
        await self._list_embeds_impl(ctx.guild, ctx.author, page, include_deleted, respond)
    
    @embed_group.command(name="info")
    async def embed_info_prefix(self, ctx, embed_id: int):
        """Get detailed information about an embed"""
        async def respond(content=None, embed=None, ephemeral=False):
            if embed:
                await ctx.send(embed=embed)
            else:
                await ctx.send(content)
        
        await self._embed_info_impl(ctx.guild, embed_id, respond)
    
    @embed_group.command(name="edit")
    async def edit_embed_prefix(self, ctx, embed_id: int, *, config: str):
        """Edit an existing embed"""
        if not self.has_manage_embed_permission(ctx.author):
            await ctx.send("❌ You don't have permission to edit embeds.")
            return
        
        try:
            new_config = EmbedConfig.from_string(config)
            success = await self.embed_manager.edit_embed(embed_id, new_config, ctx.author)
            
            if success:
                await ctx.send(f"✅ Embed {embed_id} updated successfully!")
            else:
                await ctx.send(f"❌ Failed to edit embed {embed_id}. It may not exist or may have been deleted.")
        
        except Exception as e:
            await self.embed_manager.log_embed_error(
                f"Edit command failed: {e}",
                ctx.guild,
                ctx.author
            )
            await ctx.send(f"❌ Failed to edit embed: {e}")
    
    @embed_group.command(name="refresh")
    async def refresh_embeds_prefix(self, ctx):
        """Force refresh embed statuses for this server"""
        msg = await ctx.send("🔄 Refreshing embed statuses...")
        
        updated = await self.embed_manager.check_embeds_for_guild(ctx.guild.id, max_checks=50)
        
        if updated > 0:
            await msg.edit(content=f"✅ Refreshed embed statuses. Updated {updated} embeds.")
        else:
            await msg.edit(content="✅ Refreshed embed statuses. No changes detected.")
    
    @embed_group.command(name="cleanup")
    async def cleanup_deleted_prefix(self, ctx, confirm: str = None):
        """Remove embed records for deleted channels/messages"""
        if not self.has_manage_embed_permission(ctx.author):
            await ctx.send("❌ You don't have permission to cleanup embeds.")
            return
        
        if confirm != "confirm":
            await ctx.send("⚠️ This will permanently remove embed records for deleted channels and messages.\n"
                            "Use `embed cleanup confirm` to proceed.")
            return
        
        deleted_count = self.embed_manager.cleanup_deleted_channel_embeds(ctx.guild.id)
        
        if deleted_count > 0:
            await ctx.send(f"✅ Removed {deleted_count} embed records for deleted channels.")
        else:
            await ctx.send("ℹ️ No embed records found for deleted channels.")
    
    @embed_group.command(name="export")
    async def export_embeds_prefix(self, ctx, format_type: str = "json"):
        """Export all embeds for this server"""
        if not self.has_manage_embed_permission(ctx.author):
            await ctx.send("❌ You don't have permission to export embeds.")
            return
        
        if format_type.lower() not in ["json", "txt"]:
            await ctx.send("❌ Invalid format. Use 'json' or 'txt'.")
            return
        
        try:
            await ctx.send("🔄 Exporting embeds... This may take a moment.")
            
            filepath = await self.embed_manager.export_embeds(ctx.guild.id, format_type)
            
            file = discord.File(filepath)
            await ctx.send(f"✅ Exported {len(self.embed_manager.get_embeds_for_guild(ctx.guild.id, True))} embeds:", file=file)
        
        except Exception as e:
            await self.embed_manager.log_embed_error(
                f"Export command failed: {e}",
                ctx.guild,
                ctx.author
            )
            await ctx.send(f"❌ Failed to export embeds: {e}")
    
    @embed_group.command(name="check")
    async def check_embed_prefix(self, ctx, embed_id: int):
        """Check if an embed still exists"""
        exists = await self.embed_manager.check_embed_exists(embed_id, force_check=True)
        
        if exists:
            await ctx.send(f"✅ Embed {embed_id} still exists.")
        else:
            await ctx.send(f"❌ Embed {embed_id} has been deleted or cannot be found.")
    
    @embed_group.command(name="help")
    async def embed_help_prefix(self, ctx):
        """Show embed configuration syntax"""
        embed = discord.Embed(
            title="Embed Configuration Syntax",
            description="Use key=value pairs to configure your embed:",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Basic Properties",
            value='`title="My Title"`\n'
                    '`description="My Description"`\n'
                    '`color=0x00ff00` or `color=red`\n'
                    '`url="https://example.com"`\n'
                    '`timestamp=true`',
            inline=False
        )
        
        embed.add_field(
            name="Author",
            value='`author_name="Author Name"`\n'
                    '`author_url="https://example.com"`\n'
                    '`author_icon="https://image.url"`',
            inline=False
        )
        
        embed.add_field(
            name="Footer",
            value='`footer_text="Footer Text"`\n'
                    '`footer_icon="https://image.url"`',
            inline=False
        )
        
        embed.add_field(
            name="Images",
            value='`thumbnail="https://image.url"`\n'
                    '`image="https://image.url"`',
            inline=False
        )
        
        embed.add_field(
            name="Fields",
            value='`field1_name="Field Name"`\n'
                    '`field1_value="Field Value"`\n'
                    '`field1_inline=true`\n'
                    '(Use field2_, field3_, etc. for more fields)',
            inline=False
        )
        
        embed.add_field(
            name="**New: Line Breaks**",
            value='Use `\\n` for line breaks in any text field:\n'
                    '`description="Line 1\\nLine 2\\nLine 3"`\n'
                    '`field1_value="First line\\nSecond line"`\n'
                    'Also supports `\\t` for tabs',
            inline=False
        )
        
        embed.add_field(
            name="Example",
            value='`embed send #general title="Hello World" description="This is line 1\\nThis is line 2" color=0x00ff00 timestamp=true`',
            inline=False
        )
        
        await ctx.send(embed=embed)

    # ==================== SLASH COMMANDS ====================
    embed_group_commands = app_commands.Group(name="embeds", description="Commands for managing embeds.")
    
    @embed_group_commands.command(name="send", description="Send an embed to a channel")
    @app_commands.describe(
        channel="Channel to send the embed to",
        config="Embed configuration (use /embed help for syntax)"
    )
    async def send_embed_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, config: str):
        """Send an embed to a channel"""
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
        
        await self._send_embed_impl(interaction.guild, interaction.user, config, channel, respond)
    
    @embed_group_commands.command(name="list", description="List embeds for this server")
    @app_commands.describe(
        page="Page number (default: 1)",
        include_deleted="Include deleted embeds (default: false)"
    )
    async def list_embeds_slash(self, interaction: discord.Interaction, page: int = 1, include_deleted: bool = False):
        """List embeds for this server"""
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
        
        await self._list_embeds_impl(interaction.guild, interaction.user, page, include_deleted, respond)
    
    @embed_group_commands.command(name="info", description="Get detailed information about an embed")
    @app_commands.describe(embed_id="ID of the embed to get information about")
    async def embed_info_slash(self, interaction: discord.Interaction, embed_id: int):
        """Get detailed information about an embed"""
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
        
        await self._embed_info_impl(interaction.guild, embed_id, respond)
    
    @embed_group_commands.command(name="edit", description="Edit an existing embed")
    @app_commands.describe(
        embed_id="ID of the embed to edit",
        config="New embed configuration"
    )
    async def edit_embed_slash(self, interaction: discord.Interaction, embed_id: int, config: str):
        """Edit an existing embed"""
        if not self.has_manage_embed_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to edit embeds.", ephemeral=True)
            return
        
        try:
            new_config = EmbedConfig.from_string(config)
            success = await self.embed_manager.edit_embed(embed_id, new_config, interaction.user)
            
            if success:
                await interaction.response.send_message(f"✅ Embed {embed_id} updated successfully!")
            else:
                await interaction.response.send_message(f"❌ Failed to edit embed {embed_id}. It may not exist or may have been deleted.")
        
        except Exception as e:
            await self.embed_manager.log_embed_error(
                f"Edit slash command failed: {e}",
                interaction.guild,
                interaction.user
            )
            await interaction.response.send_message(f"❌ Failed to edit embed: {e}")
    
    @embed_group_commands.command(name="refresh", description="Force refresh embed statuses for this server")
    async def refresh_embeds_slash(self, interaction: discord.Interaction):
        """Force refresh embed statuses for this server"""
        await interaction.response.send_message("🔄 Refreshing embed statuses...", ephemeral=True)
        
        updated = await self.embed_manager.check_embeds_for_guild(interaction.guild.id, max_checks=50)
        
        if updated > 0:
            await interaction.edit_original_response(content=f"✅ Refreshed embed statuses. Updated {updated} embeds.")
        else:
            await interaction.edit_original_response(content="✅ Refreshed embed statuses. No changes detected.")
    
    @embed_group_commands.command(name="cleanup", description="Remove embed records for deleted channels")
    @app_commands.describe(confirm="Type 'confirm' to proceed with cleanup")
    async def cleanup_deleted_slash(self, interaction: discord.Interaction, confirm: str = ""):
        """Remove embed records for deleted channels/messages"""
        if not self.has_manage_embed_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to cleanup embeds.", ephemeral=True)
            return
        
        if confirm != "confirm":
            await interaction.response.send_message(
                "⚠️ This will permanently remove embed records for deleted channels and messages.\n"
                "Use `/embeds cleanup confirm:confirm` to proceed.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        deleted_count = self.embed_manager.cleanup_deleted_channel_embeds(interaction.guild.id)
        
        if deleted_count > 0:
            await interaction.followup.send(f"✅ Removed {deleted_count} embed records for deleted channels.", ephemeral=True)
        else:
            await interaction.followup.send("ℹ️ No embed records found for deleted channels.", ephemeral=True)
    
    @embed_group_commands.command(name="export", description="Export all embeds for this server")
    @app_commands.describe(format_type="Export format (json or txt)")
    @app_commands.choices(format_type=[
        app_commands.Choice(name="JSON", value="json"),
        app_commands.Choice(name="Text", value="txt")
    ])
    async def export_embeds_slash(self, interaction: discord.Interaction, format_type: str = "json"):
        """Export all embeds for this server"""
        if not self.has_manage_embed_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to export embeds.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            filepath = await self.embed_manager.export_embeds(interaction.guild.id, format_type)
            
            file = discord.File(filepath)
            embed_count = len(self.embed_manager.get_embeds_for_guild(interaction.guild.id, True))
            await interaction.followup.send(
                f"✅ Exported {embed_count} embeds:",
                file=file,
                ephemeral=True
            )
        
        except Exception as e:
            await self.embed_manager.log_embed_error(
                f"Export slash command failed: {e}",
                interaction.guild,
                interaction.user
            )
            await interaction.followup.send(f"❌ Failed to export embeds: {e}", ephemeral=True)
    
    @embed_group_commands.command(name="check", description="Check if an embed still exists")
    @app_commands.describe(embed_id="ID of the embed to check")
    async def check_embed_slash(self, interaction: discord.Interaction, embed_id: int):
        """Check if an embed still exists"""
        await interaction.response.defer(ephemeral=True)
        
        exists = await self.embed_manager.check_embed_exists(embed_id, force_check=True)
        
        if exists:
            await interaction.followup.send(f"✅ Embed {embed_id} still exists.", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Embed {embed_id} has been deleted or cannot be found.", ephemeral=True)
    
    @embed_group_commands.command(name="help", description="Show embed configuration syntax")
    async def embed_help_slash(self, interaction: discord.Interaction):
        """Show embed configuration syntax"""
        embed = discord.Embed(
            title="Embed Configuration Syntax",
            description="Use key=value pairs to configure your embed:",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Basic Properties",
            value='`title="My Title"`\n'
                    '`description="My Description"`\n'
                    '`color=0x00ff00` or `color=red`\n'
                    '`url="https://example.com"`\n'
                    '`timestamp=true`',
            inline=False
        )
        
        embed.add_field(
            name="Author",
            value='`author_name="Author Name"`\n'
                    '`author_url="https://example.com"`\n'
                    '`author_icon="https://image.url"`',
            inline=False
        )
        
        embed.add_field(
            name="Footer",
            value='`footer_text="Footer Text"`\n'
                    '`footer_icon="https://image.url"`',
            inline=False
        )
        
        embed.add_field(
            name="Images",
            value='`thumbnail="https://image.url"`\n'
                    '`image="https://image.url"`',
            inline=False
        )
        
        embed.add_field(
            name="Fields",
            value='`field1_name="Field Name"`\n'
                    '`field1_value="Field Value"`\n'
                    '`field1_inline=true`\n'
                    '(Use field2_, field3_, etc. for more fields)',
            inline=False
        )
        
        embed.add_field(
            name="**New: Line Breaks**",
            value='Use `\\n` for line breaks in any text field:\n'
                    '`description="Line 1\\nLine 2\\nLine 3"`\n'
                    '`field1_value="First line\\nSecond line"`\n'
                    'Also supports `\\t` for tabs',
            inline=False
        )
        
        embed.add_field(
            name="Example",
            value='`/embeds send channel:#general config:title="Hello" description="World\\nNew Line" color=0x00ff00`',
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(EmbedCog(bot))
