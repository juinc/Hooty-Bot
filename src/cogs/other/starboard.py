"""
Discord StarboardCog - Starboard & Message Highlight System

OVERVIEW:
A full-featured starboard cog for Discord servers.  
Automatically highlights popular messages to a starboard channel when they reach a reaction threshold.  
Supports multiple starboards (per emoji), per-guild config, stats, and full logging.

SETUP:
- No manual setup required – auto-creates config at src/config/starboard_config.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.star.admin' or Administrator

COMMANDS (Slash & Prefix):
/starboard toggle <on/off>           - Enable/disable the starboard system (admin)
/starboard status                    - Show if starboard is enabled
/starboard create <channel> <emoji> <threshold> - Create a new starboard (admin)
/starboard stats                     - Show starboard statistics
/starboard delete <emoji>            - Delete a starboard (admin)
/starboard debug [on/off]            - Toggle debug mode (admin, prefix only)

Prefix commands: !starboard <subcommand> (same as above)

COMMAND EXPLANATIONS:
- toggle: Enable/disable the starboard system for your server.
- status: Show if starboard is enabled.
- create: Set up a starboard for a specific emoji, channel, and reaction threshold.
- stats: Show stats for all starboards in the server.
- delete: Remove a starboard and all its starred messages.
- debug: Toggle debug logging (prefix only).

FEATURES:
• Multiple starboards per server (different emojis, channels, thresholds)
• Automatically highlights messages that reach the reaction threshold
• Removes from starboard if reactions drop below threshold
• Prevents self-starring and bot messages (configurable)
• Tracks and displays starboard stats (total starred, reactions, etc.)
• Cleans up on message/channel/role deletion
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Persistent, per-guild config and stats (JSON)
• Both slash and prefix command support

USAGE BY OTHER COGS:
# Access starboard config or stats for integrations
starboard_cog = bot.get_cog('StarboardCog')
if starboard_cog:
    config = starboard_cog._load_config()
    guild_data = starboard_cog._get_guild_data(guild.id)
    stats = guild_data["starboards"]
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from typing import Union
from datetime import datetime
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

class StarboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = "src/database"
        self.config_dir = "src/config"
        
        # Ensure directories exist
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs("src/logs", exist_ok=True)
        
        # File paths
        self.starboard_config_path = os.path.join(self.config_dir, "starboard_config.json")
        
        # Initialize data files
        self._init_data_files()

    def _init_data_files(self):
        """Initialize all data files with default values if they don't exist"""
        default_starboard_config = {
            "guilds": {},
            "guild_settings": {},  # Per-guild settings
            "global_settings": {
                "allow_self_star": False,
                "allow_bot_messages": False,
                "debug_mode": False
            }
        }
        
        if not os.path.exists(self.starboard_config_path):
            with open(self.starboard_config_path, 'w') as f:
                json.dump(default_starboard_config, f, indent=4)

    def _load_config(self) -> dict:
        """Load starboard configuration from file"""
        try:
            with open(self.starboard_config_path, 'r') as f:
                config = json.load(f)
                # Ensure guild_settings exists
                if "guild_settings" not in config:
                    config["guild_settings"] = {}
                return config
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_data_files()
            with open(self.starboard_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save starboard configuration to file"""
        try:
            with open(self.starboard_config_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving starboard config: {e}")

    # ==================== TOGGLE SYSTEM ====================

    def is_starboard_enabled(self, guild_id: int) -> bool:
        """Check if starboard is enabled for a guild"""
        config = self._load_config()
        guild_config = config.get("guild_settings", {}).get(str(guild_id), {})
        return guild_config.get("starboard_enabled", True)  # Default to enabled

    def set_starboard_enabled(self, guild_id: int, enabled: bool):
        """Set starboard enabled status for a guild"""
        config = self._load_config()
        if "guild_settings" not in config:
            config["guild_settings"] = {}
        if str(guild_id) not in config["guild_settings"]:
            config["guild_settings"][str(guild_id)] = {}
        
        config["guild_settings"][str(guild_id)]["starboard_enabled"] = enabled
        self._save_config(config)

    async def starboard_check(self, interaction: discord.Interaction) -> bool:
        """Check if starboard is enabled before running commands"""
        if not self.is_starboard_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The starboard system is currently disabled in this server!", 
                ephemeral=True
            )
            return False
        return True

    # ==================== LOGGING SYSTEM ====================

    async def log_starboard_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log starboard actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Starboard {action}"
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
                    file_override="starboard_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log starboard action: {e}")

    async def log_starboard_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log starboard errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Starboard Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="starboard_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log starboard error: {e}")

    async def log_starboard_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log starboard warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Starboard Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="starboard_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log starboard warning: {e}")

    # ==================== UTILITY METHODS ====================

    def _get_guild_data(self, guild_id: int) -> dict:
        """Get or create guild starboard data"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "starboards": {},
                "starred_messages": {},
                "settings": {
                    "enabled": True
                }
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    def has_star_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has starboard admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.star.admin') or
                permissions_cog.has_permission(member, 'permissions.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def _normalize_emoji(self, emoji) -> str:
        """Normalize emoji for consistent storage and comparison"""
        if isinstance(emoji, discord.PartialEmoji):
            if emoji.is_custom_emoji():
                return f"<:{emoji.name}:{emoji.id}>"
            else:
                return str(emoji)
        elif isinstance(emoji, discord.Emoji):
            return f"<:{emoji.name}:{emoji.id}>"
        elif isinstance(emoji, str):
            # Handle string representation of custom emojis
            if emoji.startswith('<') and emoji.endswith('>'):
                return emoji
            # Handle unicode emojis
            return emoji
        else:
            return str(emoji)

    def _emojis_match(self, emoji1, emoji2) -> bool:
        """Compare two emojis for equality"""
        norm1 = self._normalize_emoji(emoji1)
        norm2 = self._normalize_emoji(emoji2)
        return norm1 == norm2

    async def _debug_log(self, message: str):
        """Debug logging"""
        config = self._load_config()
        if config["global_settings"].get("debug_mode", False):
            print(f"[STARBOARD DEBUG] {message}")

    async def _create_starboard_embed(self, message: discord.Message, reaction_count: int, emoji: str) -> discord.Embed:
        """Create an embed for starboard message"""
        embed = discord.Embed(
            description=message.content[:2048] if message.content else "*No text content*",
            color=discord.Color.gold(),
            timestamp=message.created_at
        )
        
        embed.set_author(
            name=f"{message.author.display_name}",
            icon_url=message.author.display_avatar.url
        )
        
        embed.add_field(
            name="Original Message",
            value=f"[Jump to message]({message.jump_url})",
            inline=True
        )
        
        embed.add_field(
            name="Channel",
            value=f"#{message.channel.name}",
            inline=True
        )
        
        embed.add_field(
            name=f"{emoji} Count",
            value=str(reaction_count),
            inline=True
        )
        
        # Handle attachments
        if message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith('image'):
                embed.set_image(url=attachment.url)
            else:
                embed.add_field(
                    name="Attachment",
                    value=f"[{attachment.filename}]({attachment.url})",
                    inline=False
                )
        
        embed.set_footer(text=f"Message ID: {message.id}")
        
        return embed

    async def _update_starboard_message(self, starboard_message: discord.Message, original_message: discord.Message, reaction_count: int, emoji: str):
        """Update an existing starboard message"""
        try:
            embed = await self._create_starboard_embed(original_message, reaction_count, emoji)
            content = f"{emoji} **{reaction_count}** | #{original_message.channel.name}"
            await starboard_message.edit(content=content, embed=embed)
        except discord.NotFound:
            # Starboard message was deleted, remove from tracking
            config = self._load_config()
            guild_data = config["guilds"][str(original_message.guild.id)]
            
            if str(original_message.id) in guild_data["starred_messages"]:
                del guild_data["starred_messages"][str(original_message.id)]
                self._save_config(config)

    async def _process_starboard_reaction(self, payload: discord.RawReactionActionEvent, added: bool):
        """Process starboard reactions"""
        await self._debug_log(f"Processing reaction: {payload.emoji} in guild {payload.guild_id}")
        
        if payload.user_id == self.bot.user.id:
            await self._debug_log("Ignoring bot reaction")
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            await self._debug_log("Guild not found")
            return

        # Check if starboard is enabled for this guild
        if not self.is_starboard_enabled(guild.id):
            await self._debug_log("Starboard disabled for this guild")
            return

        config = self._load_config()
        guild_data = self._get_guild_data(guild.id)

        emoji_str = self._normalize_emoji(payload.emoji)
        await self._debug_log(f"Normalized emoji: {emoji_str}")
        await self._debug_log(f"Available starboards: {list(guild_data['starboards'].keys())}")
        
        # Check if this emoji has a starboard
        starboard_emoji = None
        starboard_config = None
        
        for stored_emoji, config_data in guild_data["starboards"].items():
            if self._emojis_match(stored_emoji, emoji_str):
                starboard_emoji = stored_emoji
                starboard_config = config_data
                break
        
        if not starboard_config:
            await self._debug_log(f"No starboard found for emoji {emoji_str}")
            return

        await self._debug_log(f"Found starboard for {starboard_emoji}")

        channel = guild.get_channel(starboard_config["channel_id"])
        if not channel:
            await self._debug_log(f"Starboard channel not found: {starboard_config['channel_id']}")
            return

        # Get the original message
        try:
            original_channel = guild.get_channel(payload.channel_id)
            if not original_channel:
                await self._debug_log(f"Original channel not found: {payload.channel_id}")
                return
            
            original_message = await original_channel.fetch_message(payload.message_id)
            await self._debug_log(f"Found original message: {original_message.id}")
        except discord.NotFound:
            await self._debug_log(f"Original message not found: {payload.message_id}")
            return

        # Check if bot messages are allowed
        if original_message.author.bot and not config["global_settings"]["allow_bot_messages"]:
            await self._debug_log("Bot message ignored (bot messages disabled)")
            return

        # Get the user who reacted
        user = guild.get_member(payload.user_id)
        if not user:
            await self._debug_log(f"User not found: {payload.user_id}")
            return

        # Check if self-starring is allowed
        if user.id == original_message.author.id and not config["global_settings"]["allow_self_star"]:
            await self._debug_log("Self-star ignored (self-starring disabled)")
            return

        # Count current reactions for the specific emoji
        reaction_count = 0
        for reaction in original_message.reactions:
            if self._emojis_match(reaction.emoji, starboard_emoji):
                reaction_count = reaction.count
                await self._debug_log(f"Found matching reaction with count: {reaction_count}")
                break
        
        if reaction_count == 0:
            await self._debug_log("No matching reactions found on message")
            return

        threshold = starboard_config["threshold"]
        message_id_str = str(original_message.id)

        # Check if message is already starred
        is_starred = message_id_str in guild_data["starred_messages"]
        await self._debug_log(f"Message starred status: {is_starred}, reaction count: {reaction_count}, threshold: {threshold}")

        if reaction_count >= threshold and not is_starred:
            # Create new starboard message
            await self._debug_log("Creating new starboard message")
            embed = await self._create_starboard_embed(original_message, reaction_count, starboard_emoji)
            content = f"{starboard_emoji} **{reaction_count}** | #{original_message.channel.name}"
            
            try:
                starboard_message = await channel.send(content=content, embed=embed)
                await self._debug_log(f"Created starboard message: {starboard_message.id}")
                
                # Track the starboard message
                guild_data["starred_messages"][message_id_str] = {
                    "starboard_message_id": starboard_message.id,
                    "channel_id": channel.id,
                    "emoji": starboard_emoji,
                    "count": reaction_count,
                    "author_id": original_message.author.id,
                    "created_at": datetime.now().isoformat()
                }
                
                # Update stats
                if "stats" not in guild_data["starboards"][starboard_emoji]:
                    guild_data["starboards"][starboard_emoji]["stats"] = {"total_starred": 0, "total_reactions": 0}
                
                guild_data["starboards"][starboard_emoji]["stats"]["total_starred"] += 1
                guild_data["starboards"][starboard_emoji]["stats"]["total_reactions"] += reaction_count
                
                config["guilds"][str(guild.id)] = guild_data
                self._save_config(config)
                
                await self.log_starboard_action(
                    "message_starred",
                    guild,
                    original_message.author,
                    f"Message {original_message.id} starred with {reaction_count} {starboard_emoji}"
                )
                
            except discord.Forbidden:
                await self._debug_log("Failed to send starboard message (no permissions)")
                await self.log_starboard_error(
                    f"Failed to send starboard message: no permissions in channel {channel.name}",
                    guild
                )
            except Exception as e:
                await self._debug_log(f"Error creating starboard message: {e}")
                await self.log_starboard_error(f"Error creating starboard message: {e}", guild)

        elif is_starred:
            # Update existing starboard message
            await self._debug_log("Updating existing starboard message")
            starred_data = guild_data["starred_messages"][message_id_str]
            
            if reaction_count < threshold:
                # Remove from starboard if below threshold
                await self._debug_log("Removing from starboard (below threshold)")
                try:
                    starboard_channel = guild.get_channel(starred_data["channel_id"])
                    if starboard_channel:
                        starboard_message = await starboard_channel.fetch_message(starred_data["starboard_message_id"])
                        await starboard_message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
                
                del guild_data["starred_messages"][message_id_str]
                config["guilds"][str(guild.id)] = guild_data
                self._save_config(config)
                
                await self.log_starboard_action(
                    "message_unstarred",
                    guild,
                    original_message.author,
                    f"Message {original_message.id} removed from starboard (below threshold)"
                )
            else:
                # Update starboard message
                await self._debug_log("Updating starboard message count")
                try:
                    starboard_channel = guild.get_channel(starred_data["channel_id"])
                    if starboard_channel:
                        starboard_message = await starboard_channel.fetch_message(starred_data["starboard_message_id"])
                        await self._update_starboard_message(starboard_message, original_message, reaction_count, starboard_emoji)
                        
                        # Update count in data
                        starred_data["count"] = reaction_count
                        config["guilds"][str(guild.id)] = guild_data
                        self._save_config(config)
                        
                except (discord.NotFound, discord.Forbidden):
                    # Starboard message deleted, remove from tracking
                    del guild_data["starred_messages"][message_id_str]
                    config["guilds"][str(guild.id)] = guild_data
                    self._save_config(config)

    # ==================== TOGGLE COMMANDS ====================

    starboard_group = app_commands.Group(name="starboard", description="Starboard management commands")

    @starboard_group.command(name="toggle", description="Toggle the starboard system on/off (Admin only)")
    @app_commands.describe(enabled="Whether to enable or disable the starboard system")
    async def toggle_starboard(self, interaction: discord.Interaction, enabled: bool):
        """Toggle starboard system"""
        if not self.has_star_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to toggle the starboard system!", 
                ephemeral=True
            )
            return
        
        current_status = self.is_starboard_enabled(interaction.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await interaction.response.send_message(
                f"ℹ️ The starboard system is already {status_text} in this server!", 
                ephemeral=True
            )
            return
        
        self.set_starboard_enabled(interaction.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_starboard_action(
            "system_toggled", 
            interaction.guild, 
            interaction.user,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Starboard System {status_text.title()}",
            description=f"The starboard system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    @starboard_group.command(name="status", description="Check if the starboard system is enabled")
    async def starboard_status(self, interaction: discord.Interaction):
        """Check starboard status"""
        enabled = self.is_starboard_enabled(interaction.guild.id)
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        embed = discord.Embed(
            title=f"{status_emoji} Starboard System Status",
            description=f"The starboard system is currently **{status_text}** in this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    # ==================== EVENT LISTENERS ====================

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reaction additions for starboard"""
        await self._process_starboard_reaction(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Handle reaction removals for starboard"""
        await self._process_starboard_reaction(payload, False)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Clean up starboard when original message is deleted"""
        if not self.is_starboard_enabled(message.guild.id):
            return
            
        config = self._load_config()
        guild_data = self._get_guild_data(message.guild.id)
        message_id_str = str(message.id)
        
        if message_id_str in guild_data["starred_messages"]:
            starred_data = guild_data["starred_messages"][message_id_str]
            
            # Delete starboard message
            try:
                channel = message.guild.get_channel(starred_data["channel_id"])
                if channel:
                    starboard_message = await channel.fetch_message(starred_data["starboard_message_id"])
                    await starboard_message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            
            # Remove from tracking
            del guild_data["starred_messages"][message_id_str]
            config["guilds"][str(message.guild.id)] = guild_data
            self._save_config(config)
            
            await self.log_starboard_action(
                "message_cleanup", message.guild, None,
                f"Cleaned up deleted message: {message.id}"
            )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Clean up starboards when channel is deleted"""
        if not self.is_starboard_enabled(channel.guild.id):
            return
            
        config = self._load_config()
        guild_data = self._get_guild_data(channel.guild.id)
        
        # Remove starboards that used this channel
        starboards_to_remove = []
        for emoji, starboard_config in guild_data["starboards"].items():
            if starboard_config["channel_id"] == channel.id:
                starboards_to_remove.append(emoji)
        
        for emoji in starboards_to_remove:
            del guild_data["starboards"][emoji]
        
        # Remove starred messages from this channel
        messages_to_remove = []
        for message_id, starred_data in guild_data["starred_messages"].items():
            if starred_data["channel_id"] == channel.id:
                messages_to_remove.append(message_id)
        
        for message_id in messages_to_remove:
            del guild_data["starred_messages"][message_id]
        
        if starboards_to_remove or messages_to_remove:
            config["guilds"][str(channel.guild.id)] = guild_data
            self._save_config(config)
            
            await self.log_starboard_action(
                "channel_cleanup", channel.guild, None,
                f"Cleaned up deleted channel: {channel.name}, Starboards removed: {len(starboards_to_remove)}, Messages removed: {len(messages_to_remove)}"
            )

    # ==================== STARBOARD COMMANDS ====================

    @commands.group(name="starboard", invoke_without_command=True)
    async def starboard_prefix(self, ctx):
        """Starboard management commands"""
        if not self.is_starboard_enabled(ctx.guild.id):
            await ctx.send("❌ The starboard system is currently disabled in this server!")
            return
            
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Starboard Commands",
                description="Use `starboard create <channel> <emoji> <threshold>`, `starboard stats`, or `starboard delete <emoji>`",
                color=discord.Color.gold()
            )
            await ctx.send(embed=embed)

    @starboard_group.command(name="create", description="Create a new starboard")
    @app_commands.describe(
        channel="Channel for starboard messages",
        emoji="Emoji for the starboard",
        threshold="Number of reactions needed"
    )
    async def starboard_create_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, emoji: str, threshold: int):
        """Create a new starboard"""
        if not await self.starboard_check(interaction):
            return
        await self._starboard_create(interaction, channel, emoji, threshold)

    @starboard_group.command(name="stats", description="Show starboard statistics")
    async def starboard_stats_slash(self, interaction: discord.Interaction):
        """Show starboard statistics"""
        if not await self.starboard_check(interaction):
            return
        await self._starboard_stats(interaction)

    @starboard_group.command(name="delete", description="Delete a starboard")
    @app_commands.describe(emoji="Emoji of the starboard to delete")
    async def starboard_delete_slash(self, interaction: discord.Interaction, emoji: str):
        """Delete a starboard"""
        if not await self.starboard_check(interaction):
            return
        await self._starboard_delete(interaction, emoji)

    @starboard_prefix.command(name="create")
    async def starboard_create_prefix(self, ctx, channel: discord.TextChannel, emoji: str, threshold: int):
        """Create a new starboard"""
        if not self.is_starboard_enabled(ctx.guild.id):
            await ctx.send("❌ The starboard system is currently disabled in this server!")
            return
        await self._starboard_create(ctx, channel, emoji, threshold)

    @starboard_prefix.command(name="stats")
    async def starboard_stats_prefix(self, ctx):
        """Show starboard statistics"""
        if not self.is_starboard_enabled(ctx.guild.id):
            await ctx.send("❌ The starboard system is currently disabled in this server!")
            return
        await self._starboard_stats(ctx)

    @starboard_prefix.command(name="delete")
    async def starboard_delete_prefix(self, ctx, emoji: str):
        """Delete a starboard"""
        if not self.is_starboard_enabled(ctx.guild.id):
            await ctx.send("❌ The starboard system is currently disabled in this server!")
            return
        await self._starboard_delete(ctx, emoji)

    @starboard_prefix.command(name="toggle")
    async def starboard_toggle_prefix(self, ctx, enabled: bool = None):
        """Toggle starboard system (Admin only)"""
        if not self.has_star_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to toggle the starboard system!")
            return
        
        if enabled is None:
            current_status = self.is_starboard_enabled(ctx.guild.id)
            status_text = "enabled" if current_status else "disabled"
            status_emoji = "✅" if current_status else "❌"
            
            embed = discord.Embed(
                title=f"{status_emoji} Starboard System Status",
                description=f"The starboard system is currently **{status_text}** in this server.",
                color=0x00ff00 if current_status else 0xff0000
            )
            await ctx.send(embed=embed)
            return
        
        current_status = self.is_starboard_enabled(ctx.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await ctx.send(f"ℹ️ The starboard system is already {status_text} in this server!")
            return
        
        self.set_starboard_enabled(ctx.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_starboard_action(
            "system_toggled", 
            ctx.guild, 
            ctx.author,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Starboard System {status_text.title()}",
            description=f"The starboard system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await ctx.send(embed=embed)

    @starboard_prefix.command(name="debug")
    async def starboard_debug_prefix(self, ctx, toggle: bool = None):
        """Toggle debug mode"""
        if not self.has_star_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to toggle debug mode.")
            return
        
        config = self._load_config()
        if toggle is None:
            current = config["global_settings"].get("debug_mode", False)
            await ctx.send(f"Debug mode is currently: {'ON' if current else 'OFF'}")
        else:
            config["global_settings"]["debug_mode"] = toggle
            self._save_config(config)
            await ctx.send(f"Debug mode {'enabled' if toggle else 'disabled'}")
            
            await self.log_starboard_action(
                "debug_toggled", ctx.guild, ctx.author, f"Debug mode: {toggle}"
            )

    async def _starboard_create(self, ctx_or_interaction, channel: discord.TextChannel, emoji: str, threshold: int):
        """Create a new starboard"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_star_admin_permission(member):
            await respond("❌ You don't have permission to manage starboards.", ephemeral=True)
            return

        if not channel or not emoji or threshold is None:
            await respond("❌ Please specify channel, emoji, and threshold.", ephemeral=True)
            return

        if threshold < 1:
            await respond("❌ Threshold must be at least 1.", ephemeral=True)
            return

        # Test if bot can send messages to the channel
        try:
            test_msg = await channel.send("Testing starboard channel access...")
            await test_msg.delete()
        except discord.Forbidden:
            await respond("❌ I don't have permission to send messages in that channel.", ephemeral=True)
            return

        config = self._load_config()
        guild_data = self._get_guild_data(guild.id)
        emoji_str = self._normalize_emoji(emoji)

        # Check if starboard already exists for this emoji
        for stored_emoji in guild_data["starboards"]:
            if self._emojis_match(stored_emoji, emoji_str):
                await respond(f"❌ A starboard for {emoji} already exists.", ephemeral=True)
                return

        guild_data["starboards"][emoji_str] = {
            "channel_id": channel.id,
            "threshold": threshold,
            "created_at": datetime.now().isoformat(),
            "stats": {
                "total_starred": 0,
                "total_reactions": 0
            }
        }

        config["guilds"][str(guild.id)] = guild_data
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Starboard Created",
            description=f"Starboard created for {emoji} in {channel.mention}\nThreshold: {threshold} reactions",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_starboard_action(
            "starboard_created",
            guild,
            member,
            f"Emoji: {emoji}, Channel: {channel.name}, Threshold: {threshold}"
        )

    async def _starboard_stats(self, ctx_or_interaction):
        """Show starboard statistics"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        guild_data = self._get_guild_data(guild.id)

        if not guild_data["starboards"]:
            embed = discord.Embed(
                title="Starboard Statistics",
                description="No starboards configured for this server.",
                color=discord.Color.blue()
            )
            await respond(embed=embed)
            return

        embed = discord.Embed(
            title="Starboard Statistics",
            color=discord.Color.gold()
        )

        total_starred = 0
        total_reactions = 0

        for emoji, starboard_config in guild_data["starboards"].items():
            channel = guild.get_channel(starboard_config["channel_id"])
            channel_name = channel.name if channel else "Unknown Channel"
            
            stats = starboard_config.get("stats", {"total_starred": 0, "total_reactions": 0})
            total_starred += stats["total_starred"]
            total_reactions += stats["total_reactions"]
            
            embed.add_field(
                name=f"{emoji} Starboard",
                value=f"Channel: #{channel_name}\n"
                        f"Threshold: {starboard_config['threshold']}\n"
                        f"Messages Starred: {stats['total_starred']}\n"
                        f"Total Reactions: {stats['total_reactions']}",
                inline=True
            )

        embed.add_field(
            name="Overall Statistics",
            value=f"Total Starboards: {len(guild_data['starboards'])}\n"
                    f"Total Messages Starred: {total_starred}\n"
                    f"Total Reactions: {total_reactions}\n"
                    f"Currently Starred: {len(guild_data['starred_messages'])}",
            inline=False
        )

        await respond(embed=embed)

    async def _starboard_delete(self, ctx_or_interaction, emoji: str):
        """Delete a starboard"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_star_admin_permission(member):
            await respond("❌ You don't have permission to manage starboards.", ephemeral=True)
            return

        if not emoji:
            await respond("❌ Please specify an emoji.", ephemeral=True)
            return

        config = self._load_config()
        guild_data = self._get_guild_data(guild.id)
        emoji_str = self._normalize_emoji(emoji)

        # Find matching starboard
        emoji_to_delete = None
        for stored_emoji in guild_data["starboards"]:
            if self._emojis_match(stored_emoji, emoji_str):
                emoji_to_delete = stored_emoji
                break

        if not emoji_to_delete:
            await respond(f"❌ No starboard found for {emoji}.", ephemeral=True)
            return

        # Remove starboard
        del guild_data["starboards"][emoji_to_delete]

        # Remove all starred messages with this emoji
        messages_to_remove = []
        for message_id, starred_data in guild_data["starred_messages"].items():
            if self._emojis_match(starred_data["emoji"], emoji_to_delete):
                messages_to_remove.append(message_id)
                
                # Try to delete the starboard message
                try:
                    channel = guild.get_channel(starred_data["channel_id"])
                    if channel:
                        starboard_message = await channel.fetch_message(starred_data["starboard_message_id"])
                        await starboard_message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

        for message_id in messages_to_remove:
            del guild_data["starred_messages"][message_id]

        config["guilds"][str(guild.id)] = guild_data
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Starboard Deleted",
            description=f"Starboard for {emoji} has been deleted.\nRemoved {len(messages_to_remove)} starred messages.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_starboard_action(
            "starboard_deleted",
            guild,
            member,
            f"Emoji: {emoji}, Messages removed: {len(messages_to_remove)}"
        )

async def setup(bot):
    await bot.add_cog(StarboardCog(bot))
