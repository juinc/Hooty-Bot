"""
Discord ModerationCog - Advanced Moderation & Auto-Moderation System

OVERVIEW:
A comprehensive moderation cog for Discord servers.  
Supports bans, kicks, mutes, timeouts, warnings, purges, role management, channel locks, monitoring, auto-actions, and full logging.  
Persistent, per-guild config and moderation history. Both slash and prefix commands.

SETUP:
- No manual setup required – auto-creates config/database files:
  - Config: src/config/moderation_config.json
  - Database: src/database/moderation_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin/mod commands require 'permissions.mod.<action>' or Administrator

COMMANDS (Slash & Prefix):
User Moderation:
  /user ban <user> [reason] [duration] [del_msgs]   - Ban (temp or perm) a user
  /user unban <user_id>                             - Unban a user by ID
  /user kick <user> [reason]                        - Kick a user
  /user timeout <user> <duration> [reason]          - Timeout a user
  /user untimeout <user>                            - Remove timeout
  /user mute/unmute <user> [reason]                 - Mute/unmute a user (mute role)
  /user warn <user> [reason]                        - Warn a user
  /user warnings <user>                             - View warnings
  /user clearwarnings <user>                        - Clear warnings
  /user nick <user> [nickname]                      - Change nickname
  /user userinfo <user>                             - User info

Channel Management:
  /channel purge <amount>                           - Purge messages in channel
  /channel purgeuser <user> [amount]                - Purge messages from user
  /channel purgeuserglobal <user> [amount]          - Purge user messages server-wide
  /channel purgebot [amount]                        - Purge bot messages
  /channel lock/unlock [reason]                     - Lock/unlock channel
  /channel slowmode <seconds>                       - Set slowmode
  /channel mediaonly <on/off>                       - Media-only mode
  /channel deletemessage <link>                     - Delete message by link

Advanced:
  /advanced hardmute/unhardmute <user> [reason]     - Hard mute (remove all roles)
  /advanced softban <user> [reason]                 - Ban then unban (message wipe)
  /advanced massban <user_ids> [reason]             - Ban multiple users

Config:
  /modconfig logchannel/modlog/monitor-channel/muterole <channel/role> - Set log/mod/monitor/mute channels/roles
  /modconfig maxwarnings <amount>                  - Set max warnings before auto-action
  /modconfig setautoaction <action>                - Set auto-action (kick/ban/mute/timeout/none)
  /modconfig setupmute                             - Auto-create mute role
  /modconfig setupmute                             - Auto-create hard mute role
  /modconfig banmessage-channel/toggle             - Set/toggle ban message channel
  /modconfig senddm <punishment> <on/off>          - Toggle DM notifications for punishments

Monitoring:
  /monitor add/remove <user>                       - Add/remove monitor role to user

Role Management:
  /role add/remove <user> <role>                   - Add/remove role
  /role massadd/massremove <role> <user_ids>       - Mass add/remove role

Lookup:
  /lookup user <user_id>                           - Lookup user by ID
  /lookup modhistory <user>                        - View user's mod history
  /lookup cases [mod] [action]                     - Search mod cases

Cleanup:
  /cleanup inactive <days>                         - List inactive members
  /cleanup noroles                                 - List members with no roles
  /cleanup duplicatenicks                          - Find duplicate nicknames

Server Info:
  /serverinfo settings                             - View moderation settings
  /serverinfo stats                                - View moderation stats
  /serverinfo membercount                          - Member stats

Prefix commands: !mod <subcommand> (same as above)

COMMAND EXPLANATIONS:
- ban/kick/mute/timeout: Standard moderation actions (temp/perm, with logging and DM)
- warn: Issue warnings, auto-action on max warnings
- purge: Bulk delete messages (by user, bot, or all)
- lock/unlock: Lock/unlock channels
- hardmute: Remove all roles from user (restore on unhardmute)
- softban: Ban then unban to wipe messages
- massban: Ban multiple users by ID
- role: Add/remove/mass manage roles
- monitor: Track users with monitor role, log their messages
- config: Set log/modlog/monitor/mute channels/roles, auto-action, DM, etc.
- lookup: Advanced user/case lookup
- cleanup: Find inactive/no-role/duplicate-nick members
- serverinfo: View moderation settings and stats

FEATURES:
• All standard moderation actions (ban, kick, mute, timeout, warn, etc.)
• Temporary bans and auto-unban
• Hardmute (remove all roles) and restore
• Warnings system with auto-action (kick/ban/mute/timeout/none)
• Purge messages (by user, bot, or all, server-wide)
• Channel lock, unlock, slowmode, media-only
• Role management (add/remove/mass)
• Monitoring: log messages from users with monitor role
• Logging to both LoggingCog and modlog channels
• DM notifications for punishments (configurable)
• Persistent, per-guild config and moderation history (JSON)
• Both slash and prefix command support
• Permission checks (if PermissionsCog present)
• Background task for auto-unban

USAGE BY OTHER COGS:
# Access warnings, temp bans, or config for integrations
mod_cog = bot.get_cog('ModerationCog')
if mod_cog:
    db = mod_cog._load_db()
    config = mod_cog._get_guild_config(guild.id)
    warnings = db["warnings"].get(str(user.id), {}).get(str(guild.id), [])
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from typing import Optional, Union
from datetime import datetime, timedelta
import re
import asyncio
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

class AutoAction(Enum):
    NONE = "none"
    KICK = "kick"
    BAN = "ban"
    MUTE = "mute"
    TIMEOUT = "timeout"

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = "src/database"
        self.config_dir = "src/config"
        
        # Ensure directories exist
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)
        
        # File paths
        self.moderation_config_path = os.path.join(self.config_dir, "moderation_config.json")
        self.moderation_db_path = os.path.join(self.data_dir, "moderation_db.json")
        
        # Initialize data files
        self._init_data_files()
        
        # Start unban task
        self.check_unbans.start()

    def _init_data_files(self):
        """Initialize all data files with default values if they don't exist"""
        default_moderation_config = {
            "guilds": {},
            "global_settings": {
                "enabled": True,
                "log_actions": True
            }
        }
        
        default_moderation_db = {
            "warnings": {},
            "temp_bans": {},
            "locked_channels": {},
            "hardmuted_users": {}
        }
        
        files_to_init = [
            (self.moderation_config_path, default_moderation_config),
            (self.moderation_db_path, default_moderation_db)
        ]
        
        for file_path, default_data in files_to_init:
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    json.dump(default_data, f, indent=4)

    def _load_config(self) -> dict:
        """Load moderation configuration from file"""
        try:
            with open(self.moderation_config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_data_files()
            with open(self.moderation_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save moderation configuration to file"""
        with open(self.moderation_config_path, 'w') as f:
            json.dump(data, f, indent=4)

    def _load_db(self) -> dict:
        """Load moderation database from file"""
        try:
            with open(self.moderation_db_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_data_files()
            with open(self.moderation_db_path, 'r') as f:
                return json.load(f)

    def _save_db(self, data: dict):
        """Save moderation database to file"""
        with open(self.moderation_db_path, 'w') as f:
            json.dump(data, f, indent=4)

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create guild moderation configuration"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "enabled": True,
                "log_channel_id": None,
                "modlog_channel_id": None,
                "monitor_channel_id": None,
                "monitor_role_id": None,
                "mute_role_id": None,
                "hardmute_role_id": None,
                "max_warnings": 3,
                "auto_action": "kick",
                "ban_message_channel_id": None,
                "ban_message_enabled": False,
                "ban_message_content": "User {user} has been banned from {guild}.",
                "dm_settings": {
                    "ban": True,
                    "kick": True,
                    "timeout": True,
                    "mute": True,
                    "warn": True
                }
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    # PERMISSION CHECKS
    def has_mod_permission(self, member: discord.Member, permission: str) -> bool:
        """Check if member has specific moderation permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, f'permissions.mod.{permission}') or
                permissions_cog.has_permission(member, 'permissions.mod.omni') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    # LOGGING FUNCTIONS
    async def log_moderation_action(self, action: str, guild: discord.Guild = None, moderator: Union[discord.Member, discord.User] = None, target: Union[discord.Member, discord.User] = None, reason: str = "", duration: str = ""):
        """Log moderation actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Moderation {action}"
                details_parts = []
                
                if target:
                    details_parts.append(f"Target: {target.name} ({target.id})")
                if reason:
                    details_parts.append(f"Reason: {reason}")
                if duration:
                    details_parts.append(f"Duration: {duration}")
                if moderator:
                    details_parts.append(f"Moderator: {moderator.name} ({moderator.id})")
                
                details = " - ".join(details_parts)
                
                await self.bot.log.log(
                    LogLevel.INFO,
                    log_message,
                    guild,
                    moderator,
                    LogType.COG,
                    file_override="moderation_cog"
                )
                
                # Also log to general log
                await self.bot.log.log(
                    LogLevel.INFO,
                    f"{log_message} - {details}" if details else log_message,
                    guild,
                    moderator,
                    LogType.GENERAL
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log moderation action: {e}")

    async def log_suspicious_activity(self, message: discord.Message):
        """Log suspicious user activity using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                details = f"User: {message.author.name} ({message.author.id}) - Channel: #{message.channel.name} - Content: {message.content[:200]}"
                
                await self.bot.log.log(
                    LogLevel.INFO,
                    "Monitored user activity",
                    message.guild,
                    message.author,
                    LogType.COG,
                    file_override="moderation_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log suspicious activity: {e}")

    async def send_moderation_log(self, guild: discord.Guild, embed: discord.Embed):
        """Send moderation log to configured channel"""
        guild_config = self._get_guild_config(guild.id)
        
        if guild_config["modlog_channel_id"]:
            channel = guild.get_channel(guild_config["modlog_channel_id"])
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass

    async def send_dm_notification(self, user: Union[discord.Member, discord.User], action: str, reason: str, guild: discord.Guild, duration: str = ""):
        """Send DM notification to user"""
        guild_config = self._get_guild_config(guild.id)
        
        if not guild_config["dm_settings"].get(action, False):
            return
        
        try:
            embed = discord.Embed(
                title=f"Moderation Action: {action.title()}",
                description=f"You have been {action}ed in **{guild.name}**",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
            if duration:
                embed.add_field(name="Duration", value=duration, inline=False)
            
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

    # UTILITY FUNCTIONS
    def parse_time(self, time_str: str) -> Optional[timedelta]:
        """Parse time string into timedelta"""
        if not time_str or time_str.lower() in ['permanent', 'perm', '0']:
            return None
        
        time_regex = re.compile(r'(\d+)([smhdw])')
        matches = time_regex.findall(time_str.lower())
        
        if not matches:
            return None
        
        total_seconds = 0
        for amount, unit in matches:
            amount = int(amount)
            if unit == 's':
                total_seconds += amount
            elif unit == 'm':
                total_seconds += amount * 60
            elif unit == 'h':
                total_seconds += amount * 3600
            elif unit == 'd':
                total_seconds += amount * 86400
            elif unit == 'w':
                total_seconds += amount * 604800
        
        return timedelta(seconds=total_seconds)

    def format_timedelta(self, td: timedelta) -> str:
        """Format timedelta into readable string"""
        days = td.days
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds:
            parts.append(f"{seconds}s")
        
        return " ".join(parts) if parts else "0s"

    # EVENT LISTENERS
    @commands.Cog.listener()
    async def on_message(self, message):
        """Monitor messages from users with monitor role"""
        if message.author.bot:
            return
        
        guild_config = self._get_guild_config(message.guild.id)
        monitor_role_id = guild_config.get("monitor_role_id")
        
        if not monitor_role_id:
            return
        
        # Check if user has monitor role
        if any(role.id == monitor_role_id for role in message.author.roles):
            await self.log_suspicious_activity(message)
            
            # Send to monitor channel if configured
            monitor_channel_id = guild_config.get("monitor_channel_id")
            if monitor_channel_id:
                channel = message.guild.get_channel(monitor_channel_id)
                if channel:
                    embed = discord.Embed(
                        title="🔍 Monitored User Activity",
                        description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}",
                        color=discord.Color.orange(),
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="Message Content", value=message.content[:1024] if message.content else "*No content*", inline=False)
                    embed.set_footer(text=f"User ID: {message.author.id}")
                    
                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass

    @tasks.loop(minutes=5)
    async def check_unbans(self):
        """Check for temporary bans that should be lifted"""
        try:
            db = self._load_db()
            current_time = datetime.now()
            
            unbans_to_process = []
            
            for guild_id, temp_bans in db["temp_bans"].items():
                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    continue
                
                for user_id, ban_data in list(temp_bans.items()):
                    unban_time = datetime.fromisoformat(ban_data["unban_at"])
                    if current_time >= unban_time:
                        unbans_to_process.append((guild, int(user_id), ban_data))
                        del temp_bans[user_id]
            
            if unbans_to_process:
                self._save_db(db)
                
                for guild, user_id, ban_data in unbans_to_process:
                    try:
                        await guild.unban(discord.Object(id=user_id), reason="Temporary ban expired")
                        
                        # Log the unban
                        await self.log_moderation_action(
                            "auto-unban",
                            guild,
                            guild.me,
                            discord.Object(id=user_id),
                            "Temporary ban expired"
                        )
                        
                        # Send moderation log
                        embed = discord.Embed(
                            title="🔓 User Auto-Unbanned",
                            description=f"<@{user_id}> has been automatically unbanned.",
                            color=discord.Color.green(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="Reason", value="Temporary ban expired", inline=False)
                        embed.add_field(name="Original Ban Reason", value=ban_data.get("reason", "No reason"), inline=False)
                        
                        await self.send_moderation_log(guild, embed)
                        
                    except discord.NotFound:
                        pass  # User not banned
                    except discord.Forbidden:
                        pass  # No permission to unban
                    except Exception as e:
                        print(f"Error processing auto-unban: {e}")
        
        except Exception as e:
            print(f"Error in check_unbans task: {e}")

    @check_unbans.before_loop
    async def before_check_unbans(self):
        await self.bot.wait_until_ready()

    # ==================== SLASH COMMANDS ====================
    # USER MODERATION COMMANDS GROUP
    user_group = app_commands.Group(name="user", description="User moderation commands")

    @user_group.command(name="ban", description="Ban a user")
    @app_commands.describe(
        user="User to ban",
        reason="Reason for the ban",
        duration="Duration of ban (e.g., 1d, 2h, permanent)",
        delete_messages="Delete messages from last X days (0-7)"
    )
    async def ban_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided", duration: str = "permanent", delete_messages: int = 0):
        await self._ban_user(interaction, user, reason, duration, delete_messages)

    @user_group.command(name="unban", description="Unban a user")
    @app_commands.describe(user_id="User ID to unban")
    async def unban_slash(self, interaction: discord.Interaction, user_id: str):
        await self._unban_user(interaction, user_id)

    @user_group.command(name="kick", description="Kick a user")
    @app_commands.describe(user="User to kick", reason="Reason for the kick")
    async def kick_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await self._kick_user(interaction, user, reason)

    @user_group.command(name="timeout", description="Timeout a user")
    @app_commands.describe(
        user="User to timeout",
        duration="Duration of timeout (e.g., 10m, 1h)",
        reason="Reason for the timeout"
    )
    async def timeout_slash(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason provided"):
        await self._timeout_user(interaction, user, duration, reason)

    @user_group.command(name="untimeout", description="Remove timeout from a user")
    @app_commands.describe(user="User to remove timeout from")
    async def untimeout_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._untimeout_user(interaction, user)

    @user_group.command(name="mute", description="Mute a user")
    @app_commands.describe(user="User to mute", reason="Reason for the mute")
    async def mute_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await self._mute_user(interaction, user, reason)

    @user_group.command(name="unmute", description="Unmute a user")
    @app_commands.describe(user="User to unmute")
    async def unmute_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._unmute_user(interaction, user)

    @user_group.command(name="warn", description="Warn a user")
    @app_commands.describe(user="User to warn", reason="Reason for the warning")
    async def warn_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await self._warn_user(interaction, user, reason)

    @user_group.command(name="warnings", description="View warnings for a user")
    @app_commands.describe(user="User to check warnings for")
    async def warnings_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._view_warnings(interaction, user)

    @user_group.command(name="clearwarnings", description="Clear warnings for a user")
    @app_commands.describe(user="User to clear warnings for")
    async def clearwarnings_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._clear_warnings(interaction, user)

    @user_group.command(name="nick", description="Set a user's nickname")
    @app_commands.describe(user="User to change nickname", nickname="New nickname")
    async def nick_slash(self, interaction: discord.Interaction, user: discord.Member, nickname: str = None):
        await self._set_nickname(interaction, user, nickname)

    @user_group.command(name="userinfo", description="Get information about a user")
    @app_commands.describe(user="User to get information about")
    async def userinfo_slash(self, interaction: discord.Interaction, user: discord.Member = None):
        await self._user_info(interaction, user)

    # CHANNEL MANAGEMENT COMMANDS GROUP
    channel_group = app_commands.Group(name="channel", description="Channel management commands")

    @channel_group.command(name="purge", description="Purge messages in current channel")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    async def purge_slash(self, interaction: discord.Interaction, amount: int):
        await self._purge_messages(interaction, amount)

    @channel_group.command(name="purgeuser", description="Purge messages from a specific user")
    @app_commands.describe(user="User whose messages to delete", amount="Number of messages to check (1-100)")
    async def purgeuser_slash(self, interaction: discord.Interaction, user: discord.Member, amount: int = 50):
        await self._purge_user_messages(interaction, user, amount)

    @channel_group.command(name="purgeuserglobal", description="Purge messages from a user across the server")
    @app_commands.describe(user="User whose messages to delete", amount="Number of messages to check per channel")
    async def purgeuserglobal_slash(self, interaction: discord.Interaction, user: discord.Member, amount: int = 50):
        await self._purge_user_global(interaction, user, amount)

    @channel_group.command(name="purgebot", description="Purge bot messages in current channel")
    @app_commands.describe(amount="Number of messages to check (1-100)")
    async def purgebot_slash(self, interaction: discord.Interaction, amount: int = 50):
        await self._purge_bot_messages(interaction, amount)

    @channel_group.command(name="lock", description="Lock the current channel")
    @app_commands.describe(reason="Reason for locking")
    async def lock_slash(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        await self._lock_channel(interaction, reason)

    @channel_group.command(name="unlock", description="Unlock the current channel")
    async def unlock_slash(self, interaction: discord.Interaction):
        await self._unlock_channel(interaction)

    @channel_group.command(name="slowmode", description="Set slowmode for current channel")
    @app_commands.describe(seconds="Slowmode duration in seconds (0 to disable)")
    async def slowmode_slash(self, interaction: discord.Interaction, seconds: int):
        await self._set_slowmode(interaction, seconds)

    @channel_group.command(name="mediaonly", description="Make channel media-only")
    @app_commands.describe(enabled="Enable or disable media-only mode")
    async def mediaonly_slash(self, interaction: discord.Interaction, enabled: bool):
        await self._set_media_only(interaction, enabled)

    @channel_group.command(name="deletemessage", description="Delete a message by link")
    @app_commands.describe(message_link="Discord message link")
    async def deletemessage_slash(self, interaction: discord.Interaction, message_link: str):
        await self._delete_message(interaction, message_link)

    # ADVANCED MODERATION COMMANDS GROUP
    advanced_group = app_commands.Group(name="advanced", description="Advanced moderation commands")

    @advanced_group.command(name="hardmute", description="Hard mute a user (removes all roles)")
    @app_commands.describe(user="User to hard mute", reason="Reason for hard mute")
    async def hardmute_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await self._hardmute_user(interaction, user, reason)

    @advanced_group.command(name="unhardmute", description="Remove hard mute from a user")
    @app_commands.describe(user="User to remove hard mute from")
    async def unhardmute_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._unhardmute_user(interaction, user)

    @advanced_group.command(name="softban", description="Soft ban a user (ban then immediately unban)")
    @app_commands.describe(user="User to soft ban", reason="Reason for soft ban")
    async def softban_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        await self._softban_user(interaction, user, reason)

    @advanced_group.command(name="massban", description="Ban multiple users at once")
    @app_commands.describe(user_ids="Space-separated list of user IDs", reason="Reason for mass ban")
    async def massban_slash(self, interaction: discord.Interaction, user_ids: str, reason: str = "Mass ban"):
        await self._mass_ban(interaction, user_ids, reason)

    # CONFIGURATION COMMANDS GROUP
    config_group = app_commands.Group(name="modconfig", description="Moderation configuration commands")

    @config_group.command(name="logchannel", description="Set the command log channel")
    @app_commands.describe(channel="Channel for command logs")
    async def logchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await self._set_log_channel(interaction, channel)

    @config_group.command(name="modlog", description="Set the moderation log channel")
    @app_commands.describe(channel="Channel for moderation logs")
    async def modlog_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await self._set_modlog_channel(interaction, channel)

    @config_group.command(name="monitor-channel", description="Set the channel for monitored messages")
    @app_commands.describe(channel="Channel for monitored user messages")
    async def monitor_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await self._set_monitor_channel(interaction, channel)

    @config_group.command(name="monitor-role", description="Set the role to monitor messages from")
    @app_commands.describe(role="Role to monitor")
    async def monitor_role_slash(self, interaction: discord.Interaction, role: discord.Role = None):
        await self._set_monitor_role(interaction, role)

    @config_group.command(name="muterole", description="Set the mute role")
    @app_commands.describe(role="Role to use for muting")
    async def muterole_slash(self, interaction: discord.Interaction, role: discord.Role = None):
        await self._set_mute_role(interaction, role)

    @config_group.command(name="maxwarnings", description="Set maximum warnings before auto-action")
    @app_commands.describe(amount="Maximum number of warnings")
    async def maxwarnings_slash(self, interaction: discord.Interaction, amount: int):
        await self._set_max_warnings(interaction, amount)

    @config_group.command(name="setautoaction", description="Set auto-action for max warnings")
    @app_commands.describe(action="Action to take when max warnings reached")
    @app_commands.choices(action=[
        app_commands.Choice(name="None", value="none"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Mute", value="mute"),
        app_commands.Choice(name="Timeout", value="timeout")
    ])
    async def setautoaction_slash(self, interaction: discord.Interaction, action: str):
        await self._set_auto_action(interaction, action)

    @config_group.command(name="setupmute", description="Automatically create and setup mute role")
    async def setupmute_slash(self, interaction: discord.Interaction):
        await self._setup_mute_role(interaction)
        
    @config_group.command(name="setuphardmute", description="Automatically create and setup hardmute role")
    async def setuphardmute_slash(self, interaction: discord.Interaction):
        await self._setup_hardmute_role(interaction)

    @config_group.command(name="banmessage-channel", description="Set ban message channel")
    @app_commands.describe(channel="Channel for ban messages")
    async def banmessage_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await self._set_ban_message_channel(interaction, channel)

    @config_group.command(name="banmessage-toggle", description="Toggle ban message sending")
    @app_commands.describe(enabled="Enable or disable ban messages")
    async def banmessage_toggle_slash(self, interaction: discord.Interaction, enabled: bool):
        await self._toggle_ban_message(interaction, enabled)

    @config_group.command(name="senddm", description="Configure DM notifications for punishments")
    @app_commands.describe(
        punishment="Type of punishment",
        enabled="Enable or disable DM notifications"
    )
    @app_commands.choices(punishment=[
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Timeout", value="timeout"),
        app_commands.Choice(name="Mute", value="mute"),
        app_commands.Choice(name="Warn", value="warn")
    ])
    async def senddm_slash(self, interaction: discord.Interaction, punishment: str, enabled: bool):
        await self._configure_dm(interaction, punishment, enabled)

    # MONITORING COMMANDS GROUP
    monitor_group = app_commands.Group(name="monitor", description="User monitoring commands")

    @monitor_group.command(name="add", description="Add monitoring role to a member")
    @app_commands.describe(user="User to add monitoring to")
    async def monitor_add_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._add_monitor(interaction, user)

    @monitor_group.command(name="remove", description="Remove monitoring role from a member")
    @app_commands.describe(user="User to remove monitoring from")
    async def monitor_remove_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._remove_monitor(interaction, user)

    # PREFIX COMMANDS (shortened for brevity, but include all the same functionality)
    @commands.group(name="mod", invoke_without_command=True)
    async def mod_prefix(self, ctx):
        """Moderation commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Moderation Commands",
                description="Use `/user`, `/channel`, `/advanced`, `/modconfig`, or `/monitor` command groups",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            
    # SERVER INFO COMMANDS GROUP
    serverinfo_group = app_commands.Group(name="serverinfo", description="Server information commands")

    @serverinfo_group.command(name="settings", description="View current moderation settings")
    async def modsettings_slash(self, interaction: discord.Interaction):
        await self._view_mod_settings(interaction)

    @serverinfo_group.command(name="stats", description="View moderation statistics")
    async def modstats_slash(self, interaction: discord.Interaction):
        await self._view_mod_stats(interaction)

    @serverinfo_group.command(name="membercount", description="View server member statistics")
    async def membercount_slash(self, interaction: discord.Interaction):
        await self._view_member_count(interaction)

    # ROLE MANAGEMENT COMMANDS GROUP  
    role_group = app_commands.Group(name="role", description="Role management commands")

    @role_group.command(name="add", description="Add role to a user")
    @app_commands.describe(user="User to add role to", role="Role to add")
    async def role_add_slash(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        await self._add_role(interaction, user, role)

    @role_group.command(name="remove", description="Remove role from a user")
    @app_commands.describe(user="User to remove role from", role="Role to remove")
    async def role_remove_slash(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):
        await self._remove_role(interaction, user, role)

    @role_group.command(name="massadd", description="Add role to multiple users")
    @app_commands.describe(role="Role to add", user_ids="Space-separated list of user IDs")
    async def role_massadd_slash(self, interaction: discord.Interaction, role: discord.Role, user_ids: str):
        await self._mass_add_role(interaction, role, user_ids)

    @role_group.command(name="massremove", description="Remove role from multiple users")
    @app_commands.describe(role="Role to remove", user_ids="Space-separated list of user IDs")
    async def role_massremove_slash(self, interaction: discord.Interaction, role: discord.Role, user_ids: str):
        await self._mass_remove_role(interaction, role, user_ids)

    # LOOKUP COMMANDS GROUP
    lookup_group = app_commands.Group(name="lookup", description="Advanced lookup commands")

    @lookup_group.command(name="user", description="Advanced user lookup by ID")
    @app_commands.describe(user_id="User ID to lookup")
    async def lookup_user_slash(self, interaction: discord.Interaction, user_id: str):
        await self._lookup_user(interaction, user_id)

    @lookup_group.command(name="modhistory", description="View moderation history for a user")
    @app_commands.describe(user="User to check moderation history for")
    async def modhistory_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._view_mod_history(interaction, user)

    @lookup_group.command(name="cases", description="Search moderation cases")
    @app_commands.describe(moderator="Filter by moderator", action="Filter by action type")
    async def cases_slash(self, interaction: discord.Interaction, moderator: discord.Member = None, action: str = None):
        await self._search_cases(interaction, moderator, action)

    # CLEANUP COMMANDS GROUP
    cleanup_group = app_commands.Group(name="cleanup", description="Server cleanup commands")

    @cleanup_group.command(name="inactive", description="List inactive members")
    @app_commands.describe(days="Days of inactivity to check for")
    async def cleanup_inactive_slash(self, interaction: discord.Interaction, days: int = 30):
        await self._list_inactive_members(interaction, days)

    @cleanup_group.command(name="noroles", description="List members with no roles")
    async def cleanup_noroles_slash(self, interaction: discord.Interaction):
        await self._list_no_role_members(interaction)

    @cleanup_group.command(name="duplicatenicks", description="Find members with duplicate nicknames")
    async def cleanup_dupenicks_slash(self, interaction: discord.Interaction):
        await self._find_duplicate_nicks(interaction)

    # ==================== IMPLEMENTATION METHODS ====================
    async def _view_mod_settings(self, ctx_or_interaction):
        """View current moderation settings"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'view'):
            await respond("❌ You don't have permission to view moderation settings.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        
        embed = discord.Embed(
            title="⚙️ Moderation Settings",
            description=f"Current settings for **{guild.name}**",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        # Channels
        log_channel = guild.get_channel(guild_config.get("log_channel_id")) if guild_config.get("log_channel_id") else None
        modlog_channel = guild.get_channel(guild_config.get("modlog_channel_id")) if guild_config.get("modlog_channel_id") else None
        monitor_channel = guild.get_channel(guild_config.get("monitor_channel_id")) if guild_config.get("monitor_channel_id") else None
        ban_msg_channel = guild.get_channel(guild_config.get("ban_message_channel_id")) if guild_config.get("ban_message_channel_id") else None
        
        embed.add_field(
            name="📊 Channels",
            value=f"**Log:** {log_channel.mention if log_channel else 'Not set'}\n"
                f"**Modlog:** {modlog_channel.mention if modlog_channel else 'Not set'}\n"
                f"**Monitor:** {monitor_channel.mention if monitor_channel else 'Not set'}\n"
                f"**Ban Messages:** {ban_msg_channel.mention if ban_msg_channel else 'Not set'}",
            inline=False
        )
        
        # Roles
        mute_role = guild.get_role(guild_config.get("mute_role_id")) if guild_config.get("mute_role_id") else None
        monitor_role = guild.get_role(guild_config.get("monitor_role_id")) if guild_config.get("monitor_role_id") else None
        hardmute_role = guild.get_role(guild_config.get("hardmute_role_id")) if guild_config.get("hardmute_role_id") else None
        
        embed.add_field(
            name="🏷️ Roles",
            value=f"**Mute:** {mute_role.mention if mute_role else 'Not set'}\n"
                f"**Monitor:** {monitor_role.mention if monitor_role else 'Not set'}\n"
                f"**Hardmute:** {hardmute_role.mention if hardmute_role else 'Not set'}",
            inline=False
        )
        
        # Settings
        embed.add_field(
            name="⚙️ Settings",
            value=f"**Max Warnings:** {guild_config.get('max_warnings', 3)}\n"
                f"**Auto Action:** {guild_config.get('auto_action', 'none').title()}\n"
                f"**Ban Messages:** {'Enabled' if guild_config.get('ban_message_enabled', False) else 'Disabled'}",
            inline=False
        )
        
        # DM Settings
        dm_settings = guild_config.get("dm_settings", {})
        dm_status = []
        for action, enabled in dm_settings.items():
            dm_status.append(f"**{action.title()}:** {'✅' if enabled else '❌'}")
        
        embed.add_field(
            name="💬 DM Notifications",
            value="\n".join(dm_status) if dm_status else "No settings configured",
            inline=False
        )
        
        await respond(embed=embed, ephemeral=True)

    async def _view_mod_stats(self, ctx_or_interaction):
        """View moderation statistics"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'view'):
            await respond("❌ You don't have permission to view moderation statistics.", ephemeral=True)
            return

        db = self._load_db()
        guild_id_str = str(guild.id)
        
        # Count warnings
        total_warnings = 0
        users_with_warnings = 0
        for user_warnings in db["warnings"].values():
            if guild_id_str in user_warnings:
                user_warnings_count = len(user_warnings[guild_id_str])
                if user_warnings_count > 0:
                    total_warnings += user_warnings_count
                    users_with_warnings += 1
        
        # Count temp bans
        temp_bans = len(db["temp_bans"].get(guild_id_str, {}))
        
        # Count locked channels
        locked_channels = len(db["locked_channels"].get(guild_id_str, {}))
        
        # Count hardmuted users
        hardmuted_users = len(db["hardmuted_users"].get(guild_id_str, {}))
        
        embed = discord.Embed(
            title="📊 Moderation Statistics",
            description=f"Statistics for **{guild.name}**",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        embed.add_field(name="⚠️ Total Warnings", value=str(total_warnings), inline=True)
        embed.add_field(name="👥 Users with Warnings", value=str(users_with_warnings), inline=True)
        embed.add_field(name="⏰ Active Temp Bans", value=str(temp_bans), inline=True)
        embed.add_field(name="🔒 Locked Channels", value=str(locked_channels), inline=True)
        embed.add_field(name="🔇 Hardmuted Users", value=str(hardmuted_users), inline=True)
        embed.add_field(name="👤 Total Members", value=str(guild.member_count), inline=True)
        
        await respond(embed=embed, ephemeral=True)

    async def _view_member_count(self, ctx_or_interaction):
        """View server member statistics"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'view'):
            await respond("❌ You don't have permission to view server information.", ephemeral=True)
            return

        total_members = guild.member_count
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        bot_count = sum(1 for m in guild.members if m.bot)
        human_count = total_members - bot_count
        
        # Count by status
        online = sum(1 for m in guild.members if m.status == discord.Status.online)
        idle = sum(1 for m in guild.members if m.status == discord.Status.idle)
        dnd = sum(1 for m in guild.members if m.status == discord.Status.dnd)
        offline = sum(1 for m in guild.members if m.status == discord.Status.offline)
        
        embed = discord.Embed(
            title="👥 Member Statistics",
            description=f"Member information for **{guild.name}**",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        embed.add_field(name="📊 Total Members", value=str(total_members), inline=True)
        embed.add_field(name="👤 Humans", value=str(human_count), inline=True)
        embed.add_field(name="🤖 Bots", value=str(bot_count), inline=True)
        
        embed.add_field(
            name="🔵 Status Breakdown",
            value=f"🟢 Online: {online}\n🟡 Idle: {idle}\n🔴 DND: {dnd}\n⚫ Offline: {offline}",
            inline=False
        )
        
        embed.set_footer(text=f"Online: {online_members}/{total_members}")
        
        await respond(embed=embed, ephemeral=True)

    async def _add_role(self, ctx_or_interaction, user: discord.Member, role: discord.Role):
        """Add role to a user"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'roles'):
            await respond("❌ You don't have permission to manage roles.", ephemeral=True)
            return

        if role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot assign a role higher than or equal to your highest role.", ephemeral=True)
            return

        if role in user.roles:
            await respond(f"❌ {user.mention} already has the {role.mention} role.", ephemeral=True)
            return

        try:
            await user.add_roles(role, reason=f"Role added by {member}")
            
            embed = discord.Embed(
                title="✅ Role Added",
                description=f"Added {role.mention} to {user.mention}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("add_role", guild, member, user, f"Added role {role.name}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to manage this role or user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error adding role: {e}", ephemeral=True)

    async def _remove_role(self, ctx_or_interaction, user: discord.Member, role: discord.Role):
        """Remove role from a user"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'roles'):
            await respond("❌ You don't have permission to manage roles.", ephemeral=True)
            return

        if role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot remove a role higher than or equal to your highest role.", ephemeral=True)
            return

        if role not in user.roles:
            await respond(f"❌ {user.mention} doesn't have the {role.mention} role.", ephemeral=True)
            return

        try:
            await user.remove_roles(role, reason=f"Role removed by {member}")
            
            embed = discord.Embed(
                title="✅ Role Removed",
                description=f"Removed {role.mention} from {user.mention}",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("remove_role", guild, member, user, f"Removed role {role.name}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to manage this role or user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error removing role: {e}", ephemeral=True)

    async def _mass_add_role(self, ctx_or_interaction, role: discord.Role, user_ids: str):
        """Add role to multiple users"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
            followup = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send
            followup = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'roles'):
            await respond("❌ You don't have permission to manage roles.", ephemeral=True)
            return

        if role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot assign a role higher than or equal to your highest role.", ephemeral=True)
            return

        # Parse user IDs
        id_list = user_ids.split()
        if len(id_list) > 10:
            await respond("❌ Maximum 10 users can be processed at once.", ephemeral=True)
            return

        await respond("🔄 Processing mass role addition...", ephemeral=True)

        success_count = 0
        failed_count = 0
        failed_users = []

        for user_id_str in id_list:
            try:
                user_id = int(user_id_str)
                target_user = guild.get_member(user_id)
                if not target_user:
                    failed_count += 1
                    failed_users.append(f"{user_id_str} (not found)")
                    continue

                if role in target_user.roles:
                    failed_count += 1
                    failed_users.append(f"{target_user.display_name} (already has role)")
                    continue

                await target_user.add_roles(role, reason=f"Mass role addition by {member}")
                success_count += 1

            except ValueError:
                failed_count += 1
                failed_users.append(f"{user_id_str} (invalid ID)")
            except discord.Forbidden:
                failed_count += 1
                failed_users.append(f"{user_id_str} (no permission)")
            except Exception:
                failed_count += 1
                failed_users.append(f"{user_id_str} (error)")

        embed = discord.Embed(
            title="✅ Mass Role Addition Complete",
            description=f"Added {role.mention} to users",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        embed.add_field(name="Successful", value=str(success_count), inline=True)
        embed.add_field(name="Failed", value=str(failed_count), inline=True)

        if failed_users:
            embed.add_field(name="Failed Users", value="\n".join(failed_users[:5]), inline=False)

        await followup(embed=embed, ephemeral=True)
        
        # Log action
        await self.log_moderation_action("mass_add_role", guild, member, None, f"Added {role.name} to {success_count} users")

    async def _mass_remove_role(self, ctx_or_interaction, role: discord.Role, user_ids: str):
        """Remove role from multiple users"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
            followup = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send
            followup = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'roles'):
            await respond("❌ You don't have permission to manage roles.", ephemeral=True)
            return

        if role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot remove a role higher than or equal to your highest role.", ephemeral=True)
            return

        # Parse user IDs
        id_list = user_ids.split()
        if len(id_list) > 10:
            await respond("❌ Maximum 10 users can be processed at once.", ephemeral=True)
            return

        await respond("🔄 Processing mass role removal...", ephemeral=True)

        success_count = 0
        failed_count = 0
        failed_users = []

        for user_id_str in id_list:
            try:
                user_id = int(user_id_str)
                target_user = guild.get_member(user_id)
                if not target_user:
                    failed_count += 1
                    failed_users.append(f"{user_id_str} (not found)")
                    continue

                if role not in target_user.roles:
                    failed_count += 1
                    failed_users.append(f"{target_user.display_name} (doesn't have role)")
                    continue

                await target_user.remove_roles(role, reason=f"Mass role removal by {member}")
                success_count += 1

            except ValueError:
                failed_count += 1
                failed_users.append(f"{user_id_str} (invalid ID)")
            except discord.Forbidden:
                failed_count += 1
                failed_users.append(f"{user_id_str} (no permission)")
            except Exception:
                failed_count += 1
                failed_users.append(f"{user_id_str} (error)")

        embed = discord.Embed(
            title="✅ Mass Role Removal Complete",
            description=f"Removed {role.mention} from users",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        embed.add_field(name="Successful", value=str(success_count), inline=True)
        embed.add_field(name="Failed", value=str(failed_count), inline=True)

        if failed_users:
            embed.add_field(name="Failed Users", value="\n".join(failed_users[:5]), inline=False)

        await followup(embed=embed, ephemeral=True)
        
        # Log action
        await self.log_moderation_action("mass_remove_role", guild, member, None, f"Removed {role.name} from {success_count} users")

    async def _lookup_user(self, ctx_or_interaction, user_id: str):
        """Advanced user lookup by ID"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'lookup'):
            await respond("❌ You don't have permission to lookup users.", ephemeral=True)
            return

        try:
            user_id_int = int(user_id)
            
            # Try to get member from guild first
            target_user = guild.get_member(user_id_int)
            if not target_user:
                # Try to fetch user from Discord
                try:
                    target_user = await self.bot.fetch_user(user_id_int)
                    is_member = False
                except discord.NotFound:
                    await respond("❌ User not found.", ephemeral=True)
                    return
            else:
                is_member = True

            embed = discord.Embed(
                title=f"🔍 User Lookup: {target_user.display_name if is_member else target_user.name}",
                color=target_user.color if is_member and target_user.color != discord.Color.default() else discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            embed.set_thumbnail(url=target_user.display_avatar.url)
            embed.add_field(name="Username", value=f"{target_user.name}#{target_user.discriminator}", inline=True)
            embed.add_field(name="User ID", value=target_user.id, inline=True)
            embed.add_field(name="In Server", value="✅" if is_member else "❌", inline=True)
            embed.add_field(name="Account Created", value=target_user.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
            
            if is_member:
                embed.add_field(name="Nickname", value=target_user.nick or "None", inline=True)
                embed.add_field(name="Joined Server", value=target_user.joined_at.strftime("%Y-%m-%d %H:%M:%S") if target_user.joined_at else "Unknown", inline=True)
                embed.add_field(name="Status", value=str(target_user.status).title(), inline=True)
                
                roles = [role.mention for role in target_user.roles[1:]]  # Exclude @everyone
                embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles) if roles else "None", inline=False)

            await respond(embed=embed, ephemeral=True)
            
        except ValueError:
            await respond("❌ Invalid user ID.", ephemeral=True)

    async def _view_mod_history(self, ctx_or_interaction, user: discord.Member):
        """View comprehensive moderation history for a user"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'lookup'):
            await respond("❌ You don't have permission to view moderation history.", ephemeral=True)
            return

        db = self._load_db()
        user_id_str = str(user.id)
        guild_id_str = str(guild.id)
        
        embed = discord.Embed(
            title=f"📋 Moderation History: {user.display_name}",
            description=f"Complete moderation history for {user.mention}",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        
        # Get warnings
        warnings = db["warnings"].get(user_id_str, {}).get(guild_id_str, [])
        embed.add_field(name="⚠️ Warnings", value=str(len(warnings)), inline=True)
        
        # Check if currently temp banned
        temp_banned = str(user.id) in db["temp_bans"].get(guild_id_str, {})
        embed.add_field(name="⏰ Temp Banned", value="✅" if temp_banned else "❌", inline=True)
        
        # Check if currently hardmuted
        hardmuted = str(user.id) in db["hardmuted_users"].get(guild_id_str, {})
        embed.add_field(name="🔇 Hard Muted", value="✅" if hardmuted else "❌", inline=True)
        
        # Recent warnings (last 5)
        if warnings:
            recent_warnings = warnings[-5:]
            warning_text = []
            for warning in recent_warnings:
                moderator = guild.get_member(warning["moderator"])
                mod_name = moderator.display_name if moderator else "Unknown"
                timestamp = datetime.fromisoformat(warning["timestamp"]).strftime("%m/%d")
                warning_text.append(f"#{warning['id']} - {warning['reason'][:50]}... by {mod_name} ({timestamp})")
            
            embed.add_field(
                name="Recent Warnings",
                value="\n".join(warning_text) if warning_text else "None",
                inline=False
            )
        
        embed.set_footer(text=f"User ID: {user.id}")
        await respond(embed=embed, ephemeral=True)

    async def _search_cases(self, ctx_or_interaction, moderator: discord.Member = None, action: str = None):
        """Search moderation cases"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'lookup'):
            await respond("❌ You don't have permission to search moderation cases.", ephemeral=True)
            return

        db = self._load_db()
        guild_id_str = str(guild.id)
        
        cases = []
        
        # Search through warnings
        for user_id, user_warnings in db["warnings"].items():
            if guild_id_str in user_warnings:
                for warning in user_warnings[guild_id_str]:
                    if moderator and warning["moderator"] != moderator.id:
                        continue
                    if action and action.lower() != "warn":
                        continue
                    
                    cases.append({
                        "type": "Warning",
                        "user_id": user_id,
                        "moderator": warning["moderator"],
                        "reason": warning["reason"],
                        "timestamp": warning["timestamp"]
                    })
        
        # Sort by timestamp (newest first)
        cases.sort(key=lambda x: x["timestamp"], reverse=True)
        
        embed = discord.Embed(
            title="🔍 Moderation Cases",
            description=f"Found {len(cases)} matching cases",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        if cases:
            for i, case in enumerate(cases[:10]):  # Show first 10
                case_user = guild.get_member(int(case["user_id"]))
                user_name = case_user.display_name if case_user else f"User ID: {case['user_id']}"
                mod = guild.get_member(case["moderator"])
                mod_name = mod.display_name if mod else "Unknown"
                timestamp = datetime.fromisoformat(case["timestamp"]).strftime("%Y-%m-%d %H:%M")
                
                embed.add_field(
                    name=f"{case['type']} #{i+1}",
                    value=f"**User:** {user_name}\n**Moderator:** {mod_name}\n**Reason:** {case['reason'][:100]}...\n**Date:** {timestamp}",
                    inline=False
                )
        
        if len(cases) > 10:
            embed.add_field(name="...", value=f"And {len(cases) - 10} more cases", inline=False)
        
        await respond(embed=embed, ephemeral=True)

    async def _list_inactive_members(self, ctx_or_interaction, days: int):
        """List inactive members"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
            followup = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send
            followup = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'cleanup'):
            await respond("❌ You don't have permission to perform cleanup operations.", ephemeral=True)
            return

        if days < 1 or days > 365:
            await respond("❌ Days must be between 1 and 365.", ephemeral=True)
            return

        await respond("🔄 Checking member activity, this may take a moment...", ephemeral=True)

        # Use timezone-aware datetime to match Discord's joined_at timestamps
        from datetime import timezone
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        inactive_members = []

        for guild_member in guild.members:
            if guild_member.bot:
                continue
            
            # Check if user has been inactive (this is a simple check based on join date)
            if guild_member.joined_at and guild_member.joined_at < cutoff_date:
                # Simple heuristic: if they joined long ago and have default pfp or no roles
                if len(guild_member.roles) <= 1 or guild_member.display_avatar == guild_member.default_avatar:
                    inactive_members.append(guild_member)

        embed = discord.Embed(
            title="😴 Inactive Members",
            description=f"Found {len(inactive_members)} potentially inactive members (>{days} days)",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )

        if inactive_members:
            member_list = []
            for guild_member in inactive_members[:20]:  # Show first 20
                joined = guild_member.joined_at.strftime("%Y-%m-%d") if guild_member.joined_at else "Unknown"
                member_list.append(f"{guild_member.display_name} (ID: {guild_member.id}) - Joined: {joined}")
            
            embed.add_field(
                name="Members",
                value="\n".join(member_list) if member_list else "None",
                inline=False
            )
            
            if len(inactive_members) > 20:
                embed.add_field(name="...", value=f"And {len(inactive_members) - 20} more members", inline=False)

        await followup(embed=embed, ephemeral=True)

    async def _list_no_role_members(self, ctx_or_interaction):
        """List members with no roles"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'cleanup'):
            await respond("❌ You don't have permission to perform cleanup operations.", ephemeral=True)
            return

        no_role_members = [guild_member for guild_member in guild.members if len(guild_member.roles) <= 1 and not guild_member.bot]

        embed = discord.Embed(
            title="🏷️ Members Without Roles",
            description=f"Found {len(no_role_members)} members with no roles",
            color=discord.Color.yellow(),
            timestamp=datetime.now()
        )

        if no_role_members:
            member_list = []
            for guild_member in no_role_members[:20]:  # Show first 20
                joined = guild_member.joined_at.strftime("%Y-%m-%d") if guild_member.joined_at else "Unknown"
                member_list.append(f"{guild_member.display_name} (ID: {guild_member.id}) - Joined: {joined}")
            
            embed.add_field(
                name="Members",
                value="\n".join(member_list) if member_list else "None",
                inline=False
            )
            
            if len(no_role_members) > 20:
                embed.add_field(name="...", value=f"And {len(no_role_members) - 20} more members", inline=False)

        await respond(embed=embed, ephemeral=True)

    async def _find_duplicate_nicks(self, ctx_or_interaction):
        """Find members with duplicate nicknames"""
        if hasattr(ctx_or_interaction, 'response'):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'cleanup'):
            await respond("❌ You don't have permission to perform cleanup operations.", ephemeral=True)
            return

        nick_counts = {}
        for guild_member in guild.members:
            if guild_member.bot:
                continue
            
            display_name = guild_member.display_name.lower()
            if display_name not in nick_counts:
                nick_counts[display_name] = []
            nick_counts[display_name].append(guild_member)

        duplicates = {nick: members for nick, members in nick_counts.items() if len(members) > 1}

        embed = discord.Embed(
            title="👥 Duplicate Nicknames",
            description=f"Found {len(duplicates)} sets of duplicate nicknames",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )

        if duplicates:
            duplicate_list = []
            for nick, members in list(duplicates.items())[:10]:  # Show first 10
                member_names = [f"{guild_member.display_name} ({guild_member.id})" for guild_member in members]
                duplicate_list.append(f"**{nick}:** {', '.join(member_names)}")
            
            embed.add_field(
                name="Duplicates",
                value="\n".join(duplicate_list) if duplicate_list else "None",
                inline=False
            )
            
            if len(duplicates) > 10:
                embed.add_field(name="...", value=f"And {len(duplicates) - 10} more duplicate sets", inline=False)

        await respond(embed=embed, ephemeral=True)

    async def _ban_user(self, ctx_or_interaction, user: discord.Member, reason: str, duration: str, delete_messages: int):
        """Ban a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'ban'):
            await respond("❌ You don't have permission to ban users.", ephemeral=True)
            return

        if user.top_role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot ban someone with a higher or equal role.", ephemeral=True)
            return

        # Parse duration
        time_delta = self.parse_time(duration)
        is_temp = time_delta is not None
        
        # Validate delete_messages
        if delete_messages < 0 or delete_messages > 7:
            await respond("❌ Delete messages must be between 0 and 7 days.", ephemeral=True)
            return

        try:
            # Send DM before ban
            await self.send_dm_notification(user, "ban", reason, guild, self.format_timedelta(time_delta) if time_delta else "Permanent")
            
            # Ban the user
            await guild.ban(user, reason=reason, delete_message_days=delete_messages)
            
            # Handle temporary ban
            if is_temp:
                db = self._load_db()
                guild_id_str = str(guild.id)
                
                if guild_id_str not in db["temp_bans"]:
                    db["temp_bans"][guild_id_str] = {}
                
                db["temp_bans"][guild_id_str][str(user.id)] = {
                    "banned_at": datetime.now().isoformat(),
                    "unban_at": (datetime.now() + time_delta).isoformat(),
                    "reason": reason,
                    "moderator": member.id
                }
                self._save_db(db)
            
            # Create embed
            embed = discord.Embed(
                title="🔨 User Banned",
                description=f"{user.mention} has been banned.",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.add_field(name="Duration", value=self.format_timedelta(time_delta) if time_delta else "Permanent", inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action(
                "ban",
                guild,
                member,
                user,
                reason,
                self.format_timedelta(time_delta) if time_delta else "Permanent"
            )
            
            # Send to moderation log
            await self.send_moderation_log(guild, embed)
            
            # Send ban message if configured
            guild_config = self._get_guild_config(guild.id)
            if guild_config["ban_message_enabled"] and guild_config["ban_message_channel_id"]:
                ban_channel = guild.get_channel(guild_config["ban_message_channel_id"])
                if ban_channel:
                    ban_msg = guild_config["ban_message_content"].format(user=user.name, guild=guild.name)
                    ban_embed = discord.Embed(
                        title="User Banned",
                        description=ban_msg,
                        color=discord.Color.red()
                    )
                    try:
                        await ban_channel.send(embed=ban_embed)
                    except discord.Forbidden:
                        pass
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to ban this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error banning user: {e}", ephemeral=True)

    async def _unban_user(self, ctx_or_interaction, user_id: str):
        """Unban a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'ban'):
            await respond("❌ You don't have permission to unban users.", ephemeral=True)
            return

        try:
            user_id_int = int(user_id)
            user = discord.Object(id=user_id_int)
            
            await guild.unban(user, reason=f"Unbanned by {member}")
            
            # Remove from temp bans if exists
            db = self._load_db()
            guild_id_str = str(guild.id)
            if guild_id_str in db["temp_bans"] and user_id in db["temp_bans"][guild_id_str]:
                del db["temp_bans"][guild_id_str][user_id]
                self._save_db(db)
            
            embed = discord.Embed(
                title="🔓 User Unbanned",
                description=f"User with ID {user_id} has been unbanned.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user_id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("unban", guild, member, user)
            await self.send_moderation_log(guild, embed)
            
        except ValueError:
            await respond("❌ Invalid user ID.", ephemeral=True)
        except discord.NotFound:
            await respond("❌ User not found in ban list.", ephemeral=True)
        except discord.Forbidden:
            await respond("❌ I don't have permission to unban users.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error unbanning user: {e}", ephemeral=True)

    async def _kick_user(self, ctx_or_interaction, user: discord.Member, reason: str):
        """Kick a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'kick'):
            await respond("❌ You don't have permission to kick users.", ephemeral=True)
            return

        if user.top_role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot kick someone with a higher or equal role.", ephemeral=True)
            return

        try:
            await self.send_dm_notification(user, "kick", reason, guild)
            await guild.kick(user, reason=reason)
            
            embed = discord.Embed(
                title="👢 User Kicked",
                description=f"{user.mention} has been kicked.",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("kick", guild, member, user, reason)
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to kick this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error kicking user: {e}", ephemeral=True)

    async def _timeout_user(self, ctx_or_interaction, user: discord.Member, duration: str, reason: str):
        """Timeout a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'timeout'):
            await respond("❌ You don't have permission to timeout users.", ephemeral=True)
            return

        if user.top_role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot timeout someone with a higher or equal role.", ephemeral=True)
            return

        time_delta = self.parse_time(duration)
        if not time_delta:
            await respond("❌ Invalid duration format. Use formats like 10m, 1h, 2d.", ephemeral=True)
            return

        if time_delta > timedelta(days=28):
            await respond("❌ Timeout duration cannot exceed 28 days.", ephemeral=True)
            return

        try:
            until = datetime.now() + time_delta
            await self.send_dm_notification(user, "timeout", reason, guild, self.format_timedelta(time_delta))
            await user.timeout(until, reason=reason)
            
            embed = discord.Embed(
                title="⏰ User Timed Out",
                description=f"{user.mention} has been timed out.",
                color=discord.Color.yellow(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Duration", value=self.format_timedelta(time_delta), inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("timeout", guild, member, user, reason, self.format_timedelta(time_delta))
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to timeout this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error timing out user: {e}", ephemeral=True)

    async def _untimeout_user(self, ctx_or_interaction, user: discord.Member):
        """Remove timeout from a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'timeout'):
            await respond("❌ You don't have permission to remove timeouts.", ephemeral=True)
            return

        if not user.is_timed_out():
            await respond("❌ This user is not timed out.", ephemeral=True)
            return

        try:
            await user.timeout(None, reason=f"Timeout removed by {member}")
            
            embed = discord.Embed(
                title="⏰ Timeout Removed",
                description=f"{user.mention} is no longer timed out.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("untimeout", guild, member, user)
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to remove timeout from this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error removing timeout: {e}", ephemeral=True)

    async def _mute_user(self, ctx_or_interaction, user: discord.Member, reason: str):
        """Mute a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            # Defer to prevent timeout
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'mute'):
            await respond("❌ You don't have permission to mute users.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        mute_role_id = guild_config.get("mute_role_id")
        
        if not mute_role_id:
            await respond("❌ No mute role configured. Use `/modconfig setupmute` to create one.", ephemeral=True)
            return

        mute_role = guild.get_role(mute_role_id)
        if not mute_role:
            await respond("❌ Mute role not found. Please reconfigure it.", ephemeral=True)
            return

        if mute_role in user.roles:
            await respond("❌ This user is already muted.", ephemeral=True)
            return

        try:
            await self.send_dm_notification(user, "mute", reason, guild)
            await user.add_roles(mute_role, reason=reason)
            
            embed = discord.Embed(
                title="🔇 User Muted",
                description=f"{user.mention} has been muted.",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("mute", guild, member, user, reason)
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to mute this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error muting user: {e}", ephemeral=True)

    async def _unmute_user(self, ctx_or_interaction, user: discord.Member):
        """Unmute a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            # Defer to prevent timeout
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'mute'):
            await respond("❌ You don't have permission to unmute users.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        mute_role_id = guild_config.get("mute_role_id")
        
        if not mute_role_id:
            await respond("❌ No mute role configured.", ephemeral=True)
            return

        mute_role = guild.get_role(mute_role_id)
        if not mute_role:
            await respond("❌ Mute role not found.", ephemeral=True)
            return

        if mute_role not in user.roles:
            await respond("❌ This user is not muted.", ephemeral=True)
            return

        try:
            await user.remove_roles(mute_role, reason=f"Unmuted by {member}")
            
            embed = discord.Embed(
                title="🔊 User Unmuted",
                description=f"{user.mention} has been unmuted.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("unmute", guild, member, user)
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to unmute this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error unmuting user: {e}", ephemeral=True)

    async def _warn_user(self, ctx_or_interaction, user: discord.Member, reason: str):
        """Warn a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'warn'):
            await respond("❌ You don't have permission to warn users.", ephemeral=True)
            return

        # Add warning to database
        db = self._load_db()
        user_id_str = str(user.id)
        guild_id_str = str(guild.id)
        
        if user_id_str not in db["warnings"]:
            db["warnings"][user_id_str] = {}
        
        if guild_id_str not in db["warnings"][user_id_str]:
            db["warnings"][user_id_str][guild_id_str] = []
        
        warning = {
            "reason": reason,
            "moderator": member.id,
            "timestamp": datetime.now().isoformat(),
            "id": len(db["warnings"][user_id_str][guild_id_str]) + 1
        }
        
        db["warnings"][user_id_str][guild_id_str].append(warning)
        self._save_db(db)
        
        warning_count = len(db["warnings"][user_id_str][guild_id_str])
        
        # Send DM notification
        await self.send_dm_notification(user, "warn", reason, guild)
        
        embed = discord.Embed(
            title="⚠️ User Warned",
            description=f"{user.mention} has been warned.",
            color=discord.Color.yellow(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        embed.add_field(name="Warning Count", value=f"{warning_count}", inline=True)
        embed.set_footer(text=f"User ID: {user.id}")
        
        await respond(embed=embed)
        
        # Log action
        await self.log_moderation_action("warn", guild, member, user, reason)
        await self.send_moderation_log(guild, embed)
        
        # Check for auto-action
        guild_config = self._get_guild_config(guild.id)
        max_warnings = guild_config.get("max_warnings", 3)
        auto_action = guild_config.get("auto_action", "none")
        
        if warning_count >= max_warnings and auto_action != "none":
            await self._execute_auto_action(guild, user, auto_action, member, f"Reached maximum warnings ({max_warnings})")

    async def _execute_auto_action(self, guild: discord.Guild, user: discord.Member, action: str, moderator: discord.Member, reason: str):
        """Execute auto-action for reaching max warnings"""
        try:
            if action == "kick":
                await guild.kick(user, reason=reason)
            elif action == "ban":
                await guild.ban(user, reason=reason)
            elif action == "mute":
                guild_config = self._get_guild_config(guild.id)
                mute_role_id = guild_config.get("mute_role_id")
                if mute_role_id:
                    mute_role = guild.get_role(mute_role_id)
                    if mute_role:
                        await user.add_roles(mute_role, reason=reason)
            elif action == "timeout":
                await user.timeout(datetime.now() + timedelta(hours=24), reason=reason)
            
            # Log auto-action
            await self.log_moderation_action(f"auto-{action}", guild, moderator, user, reason)
            
        except Exception as e:
            print(f"Error executing auto-action: {e}")

    async def _view_warnings(self, ctx_or_interaction, user: discord.Member):
        """View warnings for a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        db = self._load_db()
        user_id_str = str(user.id)
        guild_id_str = str(guild.id)
        
        warnings = db["warnings"].get(user_id_str, {}).get(guild_id_str, [])
        
        if not warnings:
            embed = discord.Embed(
                title="⚠️ User Warnings",
                description=f"{user.mention} has no warnings.",
                color=discord.Color.green()
            )
            await respond(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title="⚠️ User Warnings",
            description=f"{user.mention} has {len(warnings)} warning(s)",
            color=discord.Color.yellow()
        )
        
        for i, warning in enumerate(warnings[-10:]):  # Show last 10 warnings
            moderator = guild.get_member(warning["moderator"])
            mod_name = moderator.display_name if moderator else "Unknown"
            timestamp = datetime.fromisoformat(warning["timestamp"]).strftime("%Y-%m-%d %H:%M")
            
            embed.add_field(
                name=f"Warning #{warning['id']}",
                value=f"**Reason:** {warning['reason']}\n**By:** {mod_name}\n**Date:** {timestamp}",
                inline=False
            )
        
        embed.set_footer(text=f"User ID: {user.id}")
        await respond(embed=embed, ephemeral=True)

    async def _clear_warnings(self, ctx_or_interaction, user: discord.Member):
        """Clear warnings for a user implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'warn'):
            await respond("❌ You don't have permission to clear warnings.", ephemeral=True)
            return

        db = self._load_db()
        user_id_str = str(user.id)
        guild_id_str = str(guild.id)
        
        if user_id_str in db["warnings"] and guild_id_str in db["warnings"][user_id_str]:
            warning_count = len(db["warnings"][user_id_str][guild_id_str])
            db["warnings"][user_id_str][guild_id_str] = []
            self._save_db(db)
            
            embed = discord.Embed(
                title="✅ Warnings Cleared",
                description=f"Cleared {warning_count} warning(s) for {user.mention}.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("clear_warnings", guild, member, user)
            await self.send_moderation_log(guild, embed)
        else:
            await respond(f"❌ {user.mention} has no warnings to clear.", ephemeral=True)

    async def _setup_mute_role(self, ctx_or_interaction):
        """Setup mute role automatically"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            # Defer immediately to prevent timeout
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to setup mute role.", ephemeral=True)
            return

        try:
            # Check if mute role already exists
            config = self._load_config()
            guild_config = self._get_guild_config(guild.id)
            existing_mute_role_id = guild_config.get("mute_role_id")
            
            if existing_mute_role_id:
                existing_role = guild.get_role(existing_mute_role_id)
                if existing_role:
                    await respond(f"❌ Mute role already exists: {existing_role.mention}", ephemeral=True)
                    return
            
            # Create mute role
            mute_role = await guild.create_role(
                name="Muted",
                color=discord.Color.dark_grey(),
                reason="Automatic mute role setup"
            )
            
            # Send initial status message
            await respond(f"✅ Created mute role {mute_role.mention}. Now updating channel permissions...", ephemeral=True)
            
            # Set permissions for all channels with rate limit handling
            updated_channels = 0
            failed_channels = 0
            
            for channel in guild.channels:
                try:
                    if isinstance(channel, discord.TextChannel):
                        await channel.set_permissions(mute_role, send_messages=False, add_reactions=False)
                    elif isinstance(channel, discord.VoiceChannel):
                        await channel.set_permissions(mute_role, speak=False)
                    updated_channels += 1
                    
                    # Small delay to help with rate limiting
                    if updated_channels % 5 == 0:
                        await asyncio.sleep(0.5)
                        
                except discord.Forbidden:
                    failed_channels += 1
                    continue
                except discord.HTTPException:
                    # Handle rate limits and other HTTP errors
                    failed_channels += 1
                    await asyncio.sleep(1)
                    continue
            
            # Save to config
            guild_config["mute_role_id"] = mute_role.id
            config["guilds"][str(guild.id)] = guild_config
            self._save_config(config)
            
            # Create final embed
            embed = discord.Embed(
                title="✅ Mute Role Setup Complete",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Role Created", 
                value=mute_role.mention, 
                inline=False
            )
            embed.add_field(
                name="Channels Updated", 
                value=f"{updated_channels} channels", 
                inline=True
            )
            
            if failed_channels > 0:
                embed.add_field(
                    name="Failed Updates", 
                    value=f"{failed_channels} channels (permissions or rate limits)", 
                    inline=True
                )
            
            # Send final update
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action(
                "setup_mute_role", 
                guild, 
                member, 
                None, 
                f"Created mute role and updated {updated_channels} channels"
            )
            
        except Exception as e:
            try:
                await respond(f"❌ Error setting up mute role: {e}", ephemeral=True)
            except:
                # If we can't respond, at least log the error
                print(f"Failed to setup mute role in {guild.name}: {e}")


    async def _setup_hardmute_role(self, ctx_or_interaction):
        """Setup hardmute role automatically"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            # Defer immediately to prevent timeout
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to setup hardmute role.", ephemeral=True)
            return

        try:
            # Check if hardmute role already exists
            config = self._load_config()
            guild_config = self._get_guild_config(guild.id)
            existing_hardmute_role_id = guild_config.get("hardmute_role_id")
            
            if existing_hardmute_role_id:
                existing_role = guild.get_role(existing_hardmute_role_id)
                if existing_role:
                    await respond(f"❌ Hardmute role already exists: {existing_role.mention}", ephemeral=True)
                    return
            
            # Create hardmute role
            hardmute_role = await guild.create_role(
                name="Hardmuted",
                color=discord.Color.dark_red(),
                reason="Automatic hardmute role setup"
            )
            
            # Send initial status message
            await respond(f"✅ Created hardmute role {hardmute_role.mention}. Now updating channel permissions...", ephemeral=True)
            
            # Set permissions for all channels with rate limit handling
            updated_channels = 0
            failed_channels = 0
            
            for channel in guild.channels:
                try:
                    if isinstance(channel, discord.TextChannel):
                        # More restrictive permissions for hardmute
                        await channel.set_permissions(
                            hardmute_role,
                            send_messages=False,
                            add_reactions=False,
                            create_public_threads=False,
                            create_private_threads=False,
                            send_messages_in_threads=False,
                            use_external_emojis=False,
                            use_external_stickers=False
                        )
                    elif isinstance(channel, discord.VoiceChannel):
                        await channel.set_permissions(
                            hardmute_role,
                            speak=False,
                            connect=False,
                            use_voice_activation=False,
                            stream=False
                        )
                    elif isinstance(channel, discord.StageChannel):
                        await channel.set_permissions(
                            hardmute_role,
                            speak=False,
                            connect=False,
                            request_to_speak=False
                        )
                    elif isinstance(channel, discord.ForumChannel):
                        await channel.set_permissions(
                            hardmute_role,
                            send_messages=False,
                            create_public_threads=False,
                            add_reactions=False
                        )
                    
                    updated_channels += 1
                    
                    # Small delay to help with rate limiting
                    if updated_channels % 5 == 0:
                        await asyncio.sleep(0.5)
                        
                except discord.Forbidden:
                    failed_channels += 1
                    continue
                except discord.HTTPException:
                    # Handle rate limits and other HTTP errors
                    failed_channels += 1
                    await asyncio.sleep(1)
                    continue
            
            # Save to config
            guild_config["hardmute_role_id"] = hardmute_role.id
            config["guilds"][str(guild.id)] = guild_config
            self._save_config(config)
            
            # Create final embed
            embed = discord.Embed(
                title="✅ Hardmute Role Setup Complete",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Role Created", 
                value=hardmute_role.mention, 
                inline=False
            )
            embed.add_field(
                name="Channels Updated", 
                value=f"{updated_channels} channels", 
                inline=True
            )
            
            if failed_channels > 0:
                embed.add_field(
                    name="Failed Updates", 
                    value=f"{failed_channels} channels (permissions or rate limits)", 
                    inline=True
                )
            
            embed.add_field(
                name="Permissions Set",
                value="• No messaging/reactions\n• No voice/video\n• No thread creation\n• No connection to voice channels",
                inline=False
            )
            
            # Send final update
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action(
                "setup_hardmute_role", 
                guild, 
                member, 
                None, 
                f"Created hardmute role and updated {updated_channels} channels"
            )
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to create roles or modify channel permissions.", ephemeral=True)
        except Exception as e:
            try:
                await respond(f"❌ Error setting up hardmute role: {e}", ephemeral=True)
            except:
                # If we can't respond, at least log the error
                print(f"Failed to setup hardmute role in {guild.name}: {e}")

    async def _purge_messages(self, ctx_or_interaction, amount: int):
        """Purge a specified number of messages"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'purge'):
            await respond("❌ You don't have permission to purge messages.", ephemeral=True)
            return

        if amount < 1 or amount > 100:
            await respond("❌ Amount must be between 1 and 100.", ephemeral=True)
            return

        try:
            # Use discord.utils.utcnow() for timezone-aware datetime
            cutoff_time = discord.utils.utcnow() - timedelta(days=14)
            
            def check(m):
                return m.created_at > cutoff_time
            
            deleted = await channel.purge(limit=amount, check=check)
            
            embed = discord.Embed(
                title="🧹 Messages Purged",
                description=f"Purged {len(deleted)} messages from {channel.mention}.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("purge", channel.guild, member, None, f"{len(deleted)} messages in #{channel.name}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to delete messages.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error purging messages: {e}", ephemeral=True)

    async def _purge_user_messages(self, ctx_or_interaction, user: discord.Member, amount: int):
        """Purge messages from a specific user"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'purge'):
            await respond("❌ You don't have permission to purge messages.", ephemeral=True)
            return

        if amount < 1 or amount > 100:
            await respond("❌ Amount must be between 1 and 100.", ephemeral=True)
            return

        try:
            # Use discord.utils.utcnow() for timezone-aware datetime
            cutoff_time = discord.utils.utcnow() - timedelta(days=14)
            
            def check(m):
                return m.author == user and m.created_at > cutoff_time
            
            deleted = await channel.purge(limit=amount, check=check)
            
            embed = discord.Embed(
                title="🧹 User Messages Purged",
                description=f"Purged {len(deleted)} messages from {user.mention} in {channel.mention}.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("purge_user", channel.guild, member, user, f"{len(deleted)} messages in #{channel.name}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to delete messages.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error purging messages: {e}", ephemeral=True)

    async def _purge_user_global(self, ctx_or_interaction, user: discord.Member, amount: int):
        """Purge messages from a user across the entire server"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'purge'):
            await respond("❌ You don't have permission to purge messages.", ephemeral=True)
            return

        if amount < 1 or amount > 100:
            await respond("❌ Amount must be between 1 and 100.", ephemeral=True)
            return

        await respond("🔄 Purging messages globally, this may take a moment...", ephemeral=True)

        total_deleted = 0
        channels_affected = 0

        try:
            # Use discord.utils.utcnow() for timezone-aware datetime
            cutoff_time = discord.utils.utcnow() - timedelta(days=14)
            
            for channel in guild.text_channels:
                try:
                    def check(m):
                        return m.author == user and m.created_at > cutoff_time
                    
                    deleted = await channel.purge(limit=amount, check=check)
                    if deleted:
                        total_deleted += len(deleted)
                        channels_affected += 1
                        
                    # Small delay to help with rate limiting
                    await asyncio.sleep(0.1)
                        
                except discord.Forbidden:
                    continue
                except Exception:
                    continue

            embed = discord.Embed(
                title="🧹 Global User Messages Purged",
                description=f"Purged {total_deleted} messages from {user.mention} across {channels_affected} channels.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("global_purge_user", guild, member, user, f"{total_deleted} messages across {channels_affected} channels")
            
        except Exception as e:
            await respond(f"❌ Error during global purge: {e}", ephemeral=True)

    async def _purge_bot_messages(self, ctx_or_interaction, amount: int):
        """Purge bot messages"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'purge'):
            await respond("❌ You don't have permission to purge messages.", ephemeral=True)
            return

        if amount < 1 or amount > 100:
            await respond("❌ Amount must be between 1 and 100.", ephemeral=True)
            return

        try:
            # Use discord.utils.utcnow() for timezone-aware datetime
            cutoff_time = discord.utils.utcnow() - timedelta(days=14)
            
            def check(m):
                return m.author.bot and m.created_at > cutoff_time
            
            deleted = await channel.purge(limit=amount, check=check)
            
            embed = discord.Embed(
                title="🤖 Bot Messages Purged",
                description=f"Purged {len(deleted)} bot messages from {channel.mention}.",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("purge_bots", channel.guild, member, None, f"{len(deleted)} bot messages in #{channel.name}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to delete messages.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error purging bot messages: {e}", ephemeral=True)

    async def _set_slowmode(self, ctx_or_interaction, seconds: int):
        """Set slowmode for channel"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'slowmode'):
            await respond("❌ You don't have permission to set slowmode.", ephemeral=True)
            return

        if seconds < 0 or seconds > 21600:  # Discord's max is 6 hours
            await respond("❌ Slowmode must be between 0 and 21600 seconds (6 hours).", ephemeral=True)
            return

        try:
            await channel.edit(slowmode_delay=seconds)
            
            if seconds == 0:
                description = f"Slowmode disabled in {channel.mention}."
            else:
                description = f"Slowmode set to {seconds} seconds in {channel.mention}."
            
            embed = discord.Embed(
                title="⏱️ Slowmode Updated",
                description=description,
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Duration", value=f"{seconds} seconds", inline=True)
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("slowmode", channel.guild, member, None, f"#{channel.name} set to {seconds}s")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to edit this channel.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error setting slowmode: {e}", ephemeral=True)

    async def _set_media_only(self, ctx_or_interaction, enabled: bool):
        """Set media-only mode for channel"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'mediaonly'):
            await respond("❌ You don't have permission to set media-only mode.", ephemeral=True)
            return

        try:
            # Set permissions for @everyone role
            everyone_role = channel.guild.default_role
            
            if enabled:
                await channel.set_permissions(everyone_role, 
                                            send_messages=False, 
                                            attach_files=True,
                                            embed_links=True)
                description = f"{channel.mention} is now media-only."
            else:
                await channel.set_permissions(everyone_role, 
                                            send_messages=None, 
                                            attach_files=None,
                                            embed_links=None)
                description = f"Media-only mode disabled for {channel.mention}."
            
            embed = discord.Embed(
                title="📷 Media-Only Mode Updated",
                description=description,
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Status", value="Enabled" if enabled else "Disabled", inline=True)
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("media_only", channel.guild, member, None, f"#{channel.name} {'enabled' if enabled else 'disabled'}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to edit channel permissions.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error setting media-only mode: {e}", ephemeral=True)

    async def _delete_message(self, ctx_or_interaction, message_link: str):
        """Delete a message by link"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'msgdel'):
            await respond("❌ You don't have permission to delete messages.", ephemeral=True)
            return

        try:
            # Parse message link
            link_parts = message_link.split('/')
            if len(link_parts) < 3:
                await respond("❌ Invalid message link format.", ephemeral=True)
                return
            
            channel_id = int(link_parts[-2])
            message_id = int(link_parts[-1])
            
            channel = guild.get_channel(channel_id)
            if not channel:
                await respond("❌ Channel not found.", ephemeral=True)
                return
            
            message = await channel.fetch_message(message_id)
            if not message:
                await respond("❌ Message not found.", ephemeral=True)
                return
            
            await message.delete()
            
            embed = discord.Embed(
                title="🗑️ Message Deleted",
                description=f"Message deleted from {channel.mention}.",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Original Author", value=message.author.mention, inline=True)
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("delete_message", guild, member, message.author, f"Message in #{channel.name}")
            
        except ValueError:
            await respond("❌ Invalid message link format.", ephemeral=True)
        except discord.NotFound:
            await respond("❌ Message not found.", ephemeral=True)
        except discord.Forbidden:
            await respond("❌ I don't have permission to delete this message.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error deleting message: {e}", ephemeral=True)

    async def _hardmute_user(self, ctx_or_interaction, user: discord.Member, reason: str):
        """Hard mute a user (removes all roles)"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            # Defer to prevent timeout
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'hardmute'):
            await respond("❌ You don't have permission to hard mute users.", ephemeral=True)
            return

        if user.top_role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot hard mute someone with a higher or equal role.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        hardmute_role_id = guild_config.get("hardmute_role_id")
        
        if not hardmute_role_id:
            await respond("❌ No hardmute role configured. Use `/modconfig setuphardmute` to create one.", ephemeral=True)
            return

        hardmute_role = guild.get_role(hardmute_role_id)
        if not hardmute_role:
            await respond("❌ Hardmute role not found. Please reconfigure it.", ephemeral=True)
            return

        # Check if user is already hardmuted
        db = self._load_db()
        guild_id_str = str(guild.id)
        
        if guild_id_str in db["hardmuted_users"] and str(user.id) in db["hardmuted_users"][guild_id_str]:
            await respond("❌ This user is already hard muted.", ephemeral=True)
            return

        try:
            # Store user's roles before removing them
            if guild_id_str not in db["hardmuted_users"]:
                db["hardmuted_users"][guild_id_str] = {}
            
            user_roles = [role.id for role in user.roles if role != guild.default_role]
            db["hardmuted_users"][guild_id_str][str(user.id)] = {
                "roles": user_roles,
                "hardmuted_by": member.id,
                "hardmuted_at": datetime.now().isoformat(),
                "reason": reason
            }
            self._save_db(db)
            
            await self.send_dm_notification(user, "hardmute", reason, guild)
            await user.edit(roles=[hardmute_role], reason=f"Hardmuted by {member}: {reason}")
            
            embed = discord.Embed(
                title="🔇 User Hard Muted",
                description=f"{user.mention} has been hard muted.",
                color=discord.Color.dark_red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.add_field(name="Roles Removed", value=str(len(user_roles)), inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("hardmute", guild, member, user, reason)
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to modify this user's roles.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error hard muting user: {e}", ephemeral=True)

    async def _unhardmute_user(self, ctx_or_interaction, user: discord.Member):
        """Remove hard mute from a user"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            # Defer to prevent timeout
            await ctx_or_interaction.response.defer(ephemeral=True)
            respond = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'hardmute'):
            await respond("❌ You don't have permission to remove hard mutes.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        hardmute_role_id = guild_config.get("hardmute_role_id")
        
        if not hardmute_role_id:
            await respond("❌ No hardmute role configured.", ephemeral=True)
            return

        hardmute_role = guild.get_role(hardmute_role_id)
        if not hardmute_role:
            await respond("❌ Hardmute role not found.", ephemeral=True)
            return

        # Check if user is hardmuted in database
        db = self._load_db()
        guild_id_str = str(guild.id)
        
        if guild_id_str not in db["hardmuted_users"] or str(user.id) not in db["hardmuted_users"][guild_id_str]:
            await respond("❌ This user is not hard muted.", ephemeral=True)
            return

        try:
            # Get stored roles
            hardmute_data = db["hardmuted_users"][guild_id_str][str(user.id)]
            stored_role_ids = hardmute_data["roles"]
            
            # Get valid roles that still exist
            roles_to_restore = []
            missing_roles = 0
            
            for role_id in stored_role_ids:
                role = guild.get_role(role_id)
                if role:
                    roles_to_restore.append(role)
                else:
                    missing_roles += 1
            
            # Add back the default role
            roles_to_restore.append(guild.default_role)
            
            await user.edit(roles=roles_to_restore, reason=f"Hard mute removed by {member}")
            
            # Remove from database
            del db["hardmuted_users"][guild_id_str][str(user.id)]
            self._save_db(db)
            
            embed = discord.Embed(
                title="🔊 Hard Mute Removed",
                description=f"{user.mention} is no longer hard muted.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Roles Restored", value=str(len(roles_to_restore) - 1), inline=True)
            
            if missing_roles > 0:
                embed.add_field(name="Missing Roles", value=f"{missing_roles} roles no longer exist", inline=True)
            
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed, ephemeral=True)
            
            # Log action
            await self.log_moderation_action("unhardmute", guild, member, user)
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to modify this user's roles.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error removing hard mute: {e}", ephemeral=True)

    async def _softban_user(self, ctx_or_interaction, user: discord.Member, reason: str):
        """Soft ban a user (ban then immediately unban)"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'ban'):
            await respond("❌ You don't have permission to soft ban users.", ephemeral=True)
            return

        if user.top_role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot soft ban someone with a higher or equal role.", ephemeral=True)
            return

        try:
            await guild.ban(user, reason=f"Softban by {member}: {reason}", delete_message_days=7)
            await guild.unban(discord.Object(id=user.id), reason=f"Softban (auto-unban) by {member}")
            
            embed = discord.Embed(
                title="⚡ User Soft Banned",
                description=f"{user.mention} has been soft banned (banned and immediately unbanned).",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            embed.add_field(name="Messages Deleted", value="7 days", inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("softban", guild, member, user, reason)
            await self.send_moderation_log(guild, embed)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to ban/unban users.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error soft banning user: {e}", ephemeral=True)

    async def _mass_ban(self, ctx_or_interaction, user_ids: str, reason: str):
        """Ban multiple users at once"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
            followup = ctx_or_interaction.followup.send
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send
            followup = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'ban'):
            await respond("❌ You don't have permission to ban users.", ephemeral=True)
            return

        # Parse user IDs
        id_list = user_ids.split()
        if len(id_list) > 10:
            await respond("❌ Maximum 10 users can be banned at once.", ephemeral=True)
            return

        await respond("🔄 Processing mass ban, this may take a moment...", ephemeral=True)

        banned_count = 0
        failed_count = 0
        failed_users = []

        for user_id_str in id_list:
            try:
                user_id = int(user_id_str)
                user = discord.Object(id=user_id)
                await guild.ban(user, reason=f"Mass ban by {member}: {reason}")
                banned_count += 1
            except ValueError:
                failed_count += 1
                failed_users.append(f"{user_id_str} (invalid ID)")
            except discord.NotFound:
                failed_count += 1
                failed_users.append(f"{user_id_str} (user not found)")
            except discord.Forbidden:
                failed_count += 1
                failed_users.append(f"{user_id_str} (no permission)")
            except Exception as e:
                failed_count += 1
                failed_users.append(f"{user_id_str} (error: {str(e)[:50]})")

        embed = discord.Embed(
            title="⚡ Mass Ban Complete",
            description=f"Mass ban operation completed.",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        embed.add_field(name="Successfully Banned", value=str(banned_count), inline=True)
        embed.add_field(name="Failed", value=str(failed_count), inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        
        if failed_users:
            embed.add_field(name="Failed Users", value="\n".join(failed_users[:5]), inline=False)
            if len(failed_users) > 5:
                embed.add_field(name="...", value=f"And {len(failed_users) - 5} more", inline=False)

        await followup(embed=embed, ephemeral=True)
        
        # Log action
        await self.log_moderation_action("mass_ban", guild, member, None, f"{banned_count} users banned - {reason}")

    # Configuration methods
    async def _set_log_channel(self, ctx_or_interaction, channel: discord.TextChannel = None):
        """Set the log channel"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if channel:
            guild_config["log_channel_id"] = channel.id
            description = f"Log channel set to {channel.mention}."
        else:
            guild_config["log_channel_id"] = None
            description = "Log channel disabled."
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Log Channel Updated",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _set_modlog_channel(self, ctx_or_interaction, channel: discord.TextChannel = None):
        """Set the moderation log channel"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if channel:
            guild_config["modlog_channel_id"] = channel.id
            description = f"Moderation log channel set to {channel.mention}."
        else:
            guild_config["modlog_channel_id"] = None
            description = "Moderation log channel disabled."
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Moderation Log Channel Updated",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _set_monitor_channel(self, ctx_or_interaction, channel: discord.TextChannel = None):
        """Set the monitor channel"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if channel:
            guild_config["monitor_channel_id"] = channel.id
            description = f"Monitor channel set to {channel.mention}."
        else:
            guild_config["monitor_channel_id"] = None
            description = "Monitor channel disabled."
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Monitor Channel Updated",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _set_monitor_role(self, ctx_or_interaction, role: discord.Role = None):
        """Set the monitor role"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if role:
            guild_config["monitor_role_id"] = role.id
            description = f"Monitor role set to {role.mention}."
        else:
            guild_config["monitor_role_id"] = None
            description = "Monitor role disabled."
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Monitor Role Updated",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _set_mute_role(self, ctx_or_interaction, role: discord.Role = None):
        """Set the mute role"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if role:
            guild_config["mute_role_id"] = role.id
            description = f"Mute role set to {role.mention}."
        else:
            guild_config["mute_role_id"] = None
            description = "Mute role disabled."
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Mute Role Updated",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _set_max_warnings(self, ctx_or_interaction, amount: int):
        """Set maximum warnings before auto-action"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        if amount < 1 or amount > 20:
            await respond("❌ Maximum warnings must be between 1 and 20.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        guild_config["max_warnings"] = amount
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Max Warnings Updated",
            description=f"Maximum warnings before auto-action set to {amount}.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _set_auto_action(self, ctx_or_interaction, action: str):
        """Set auto-action for max warnings"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        guild_config["auto_action"] = action
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Auto-Action Updated",
            description=f"Auto-action for max warnings set to: {action.title()}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _set_ban_message_channel(self, ctx_or_interaction, channel: discord.TextChannel = None):
        """Set ban message channel"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if channel:
            guild_config["ban_message_channel_id"] = channel.id
            description = f"Ban message channel set to {channel.mention}."
        else:
            guild_config["ban_message_channel_id"] = None
            description = "Ban message channel disabled."
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Ban Message Channel Updated",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _toggle_ban_message(self, ctx_or_interaction, enabled: bool):
        """Toggle ban message sending"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        guild_config["ban_message_enabled"] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ Ban Messages Updated",
            description=f"Ban messages {'enabled' if enabled else 'disabled'}.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _configure_dm(self, ctx_or_interaction, punishment: str, enabled: bool):
        """Configure DM notifications for punishments"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'config'):
            await respond("❌ You don't have permission to configure moderation settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        guild_config["dm_settings"][punishment] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        embed = discord.Embed(
            title="⚙️ DM Notifications Updated",
            description=f"DM notifications for {punishment} {'enabled' if enabled else 'disabled'}.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Moderator", value=member.mention, inline=True)
        
        await respond(embed=embed)

    async def _add_monitor(self, ctx_or_interaction, user: discord.Member):
        """Add monitoring role to a member"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'monitor'):
            await respond("❌ You don't have permission to manage monitoring.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        monitor_role_id = guild_config.get("monitor_role_id")
        
        if not monitor_role_id:
            await respond("❌ No monitor role configured. Set one first with `/modconfig monitor-role`.", ephemeral=True)
            return

        monitor_role = guild.get_role(monitor_role_id)
        if not monitor_role:
            await respond("❌ Monitor role not found. Please reconfigure it.", ephemeral=True)
            return

        if monitor_role in user.roles:
            await respond("❌ This user is already being monitored.", ephemeral=True)
            return

        try:
            await user.add_roles(monitor_role, reason=f"Monitoring added by {member}")
            
            embed = discord.Embed(
                title="👁️ User Monitoring Added",
                description=f"{user.mention} is now being monitored.",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("add_monitor", guild, member, user)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to add roles to this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error adding monitoring: {e}", ephemeral=True)

    async def _remove_monitor(self, ctx_or_interaction, user: discord.Member):
        """Remove monitoring role from a member"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'monitor'):
            await respond("❌ You don't have permission to manage monitoring.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        monitor_role_id = guild_config.get("monitor_role_id")
        
        if not monitor_role_id:
            await respond("❌ No monitor role configured.", ephemeral=True)
            return

        monitor_role = guild.get_role(monitor_role_id)
        if not monitor_role:
            await respond("❌ Monitor role not found.", ephemeral=True)
            return

        if monitor_role not in user.roles:
            await respond("❌ This user is not being monitored.", ephemeral=True)
            return

        try:
            await user.remove_roles(monitor_role, reason=f"Monitoring removed by {member}")
            
            embed = discord.Embed(
                title="👁️ User Monitoring Removed",
                description=f"{user.mention} is no longer being monitored.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("remove_monitor", guild, member, user)
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to remove roles from this user.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error removing monitoring: {e}", ephemeral=True)
            
            
    async def _set_nickname(self, ctx_or_interaction, user: discord.Member, nickname: str = None):
        """Set a user's nickname implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'nick'):
            await respond("❌ You don't have permission to change nicknames.", ephemeral=True)
            return

        if user.top_role >= member.top_role and member != guild.owner:
            await respond("❌ You cannot change the nickname of someone with a higher or equal role.", ephemeral=True)
            return

        try:
            old_nick = user.display_name
            await user.edit(nick=nickname, reason=f"Nickname changed by {member}")
            
            embed = discord.Embed(
                title="📝 Nickname Changed",
                description=f"{user.mention}'s nickname has been updated.",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Old Nickname", value=old_nick or "None", inline=True)
            embed.add_field(name="New Nickname", value=nickname or "None", inline=True)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action(
                "nickname_change", 
                guild, 
                member, 
                user, 
                f"Changed from '{old_nick}' to '{nickname or 'None'}'"
            )
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to change this user's nickname.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error changing nickname: {e}", ephemeral=True)

            
    async def _user_info(self, ctx_or_interaction, user: discord.Member = None):
        """Get user info implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        target = user or member
        
        embed = discord.Embed(
            title=f"User Information: {target.display_name}",
            color=target.color if target.color != discord.Color.default() else discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Username", value=f"{target.name}#{target.discriminator}", inline=True)
        embed.add_field(name="User ID", value=target.id, inline=True)
        embed.add_field(name="Nickname", value=target.nick or "None", inline=True)
        embed.add_field(name="Account Created", value=target.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
        embed.add_field(name="Joined Server", value=target.joined_at.strftime("%Y-%m-%d %H:%M:%S") if target.joined_at else "Unknown", inline=False)
        
        roles = [role.mention for role in target.roles[1:]]  # Exclude @everyone
        embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles) if roles else "None", inline=False)
        
        await respond(embed=embed, ephemeral=True)

    async def _lock_channel(self, ctx_or_interaction, reason: str):
        """Lock channel implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'lock'):
            await respond("❌ You don't have permission to lock channels.", ephemeral=True)
            return

        try:
            # Store original permissions
            db = self._load_db()
            guild_id_str = str(guild.id)
            
            if guild_id_str not in db["locked_channels"]:
                db["locked_channels"][guild_id_str] = {}
            
            # Get @everyone role
            everyone_role = guild.default_role
            original_perms = channel.overwrites_for(everyone_role)
            
            # Store original permissions
            db["locked_channels"][guild_id_str][str(channel.id)] = {
                "original_send_messages": original_perms.send_messages,
                "locked_by": member.id,
                "locked_at": datetime.now().isoformat(),
                "reason": reason
            }
            self._save_db(db)
            
            # Lock the channel
            await channel.set_permissions(everyone_role, send_messages=False)
            
            embed = discord.Embed(
                title="🔒 Channel Locked",
                description=f"{channel.mention} has been locked.",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=True)
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("lock_channel", guild, member, None, f"#{channel.name} - {reason}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to modify channel permissions.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error locking channel: {e}", ephemeral=True)

    async def _unlock_channel(self, ctx_or_interaction):
        """Unlock channel implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_mod_permission(member, 'lock'):
            await respond("❌ You don't have permission to unlock channels.", ephemeral=True)
            return

        try:
            # Get stored permissions
            db = self._load_db()
            guild_id_str = str(guild.id)
            
            if guild_id_str not in db["locked_channels"] or str(channel.id) not in db["locked_channels"][guild_id_str]:
                await respond("❌ This channel is not locked or lock data not found.", ephemeral=True)
                return
            
            lock_data = db["locked_channels"][guild_id_str][str(channel.id)]
            
            # Restore original permissions
            everyone_role = guild.default_role
            original_send = lock_data["original_send_messages"]
            
            await channel.set_permissions(everyone_role, send_messages=original_send)
            
            # Remove from database
            del db["locked_channels"][guild_id_str][str(channel.id)]
            self._save_db(db)
            
            embed = discord.Embed(
                title="🔓 Channel Unlocked",
                description=f"{channel.mention} has been unlocked.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Moderator", value=member.mention, inline=True)
            
            await respond(embed=embed)
            
            # Log action
            await self.log_moderation_action("unlock_channel", guild, member, None, f"#{channel.name}")
            
        except discord.Forbidden:
            await respond("❌ I don't have permission to modify channel permissions.", ephemeral=True)
        except Exception as e:
            await respond(f"❌ Error unlocking channel: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
