"""
Discord AutorolesReactionRolesCog - Autoroles & Reaction Roles System

OVERVIEW:
A robust cog for automatic role assignment and reaction-based role management.  
Handles autoroles for new members, reaction roles on messages, full sync after downtime, and per-guild configuration.  
Supports both slash and prefix commands.

SETUP:
- No manual setup required – auto-creates config/database files:
- Config: src/config/autoroles_config.json, src/config/reaction_roles_config.json
- Database: src/database/autoroles_db.json, src/database/reaction_roles_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.autorole.admin' or 'permissions.reactionrole.admin' or Administrator

COMMANDS (Slash & Prefix):
/roles toggle-autoroles <on/off>         - Enable/disable autoroles (admin)
/roles toggle-reaction-roles <on/off>    - Enable/disable reaction roles (admin)
/roles status                            - Show status of both systems
/roles force-sync                        - Manually sync all autoroles and reaction roles (admin)

Autoroles:
  /autoroles add <role>                  - Add a role to autoroles (admin)
  /autoroles remove <role>               - Remove a role from autoroles (admin)
  /autoroles list                        - List all autoroles

Reaction Roles:
  /reactionroles create <message_link>   - Register a message for reaction roles (admin)
  /reactionroles add <message_link> <emoji> <role> - Add a reaction role (admin)
  /reactionroles remove <message_link>   - Remove all reaction roles from a message (admin)

Prefix commands: !autoroles, !reactionroles (same subcommands as above)

COMMAND EXPLANATIONS:
- toggle-autoroles/toggle-reaction-roles: Enable/disable each system for your server.
- status: Show if each system is enabled and last sync time.
- force-sync: Manually sync all autoroles and reaction roles for all members/messages.
- autoroles add/remove/list: Manage roles automatically given to new members.
- reactionroles create/add/remove: Manage reaction roles on any bot message.

FEATURES:
• Autoroles: auto-assign roles to new members
• Reaction roles: assign/remove roles based on message reactions
• Full sync after downtime (fixes missed joins/reactions)
• Manual force-sync command for admins
• Per-guild enable/disable for each system
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Persistent, per-guild config and role data (JSON)
• Both slash and prefix command support
• Cleans up deleted roles/messages automatically

USAGE BY OTHER COGS:
# Access autoroles or reaction roles data for integrations
cog = bot.get_cog('AutorolesReactionRolesCog')
if cog:
    autoroles = cog._load_json(cog.autoroles_db_path).get(str(guild.id), [])
    reaction_roles = cog._load_json(cog.reaction_roles_db_path)
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
import asyncio
from datetime import datetime, timezone
from typing import Optional, Union
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

class AutorolesReactionRolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = "src/database"
        self.config_dir = "src/config"
        
        # Ensure directories exist
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs("src/logs", exist_ok=True)
        
        # File paths
        self.autoroles_config_path = os.path.join(self.config_dir, "autoroles_config.json")
        self.reaction_roles_config_path = os.path.join(self.config_dir, "reaction_roles_config.json")
        self.autoroles_db_path = os.path.join(self.data_dir, "autoroles_db.json")
        self.reaction_roles_db_path = os.path.join(self.data_dir, "reaction_roles_db.json")
        self.sync_status_path = os.path.join(self.data_dir, "roles_sync_status.json")
        
        # Initialize data files
        self._init_data_files()
        
        # Track if initial sync has been completed
        self.initial_sync_completed = False

    def _init_data_files(self):
        """Initialize all data files with default values if they don't exist"""
        default_autoroles_config = {
            "guild_settings": {}  # Per-guild settings
        }
        
        default_reaction_roles_config = {
            "guild_settings": {}  # Per-guild settings
        }
        
        default_autoroles_db = {}
        default_reaction_roles_db = {}
        default_sync_status = {
            "last_online": None,
            "last_sync": None,
            "startup_time": datetime.now(timezone.utc).isoformat()
        }
        
        files_to_init = [
            (self.autoroles_config_path, default_autoroles_config),
            (self.reaction_roles_config_path, default_reaction_roles_config),
            (self.autoroles_db_path, default_autoroles_db),
            (self.reaction_roles_db_path, default_reaction_roles_db),
            (self.sync_status_path, default_sync_status)
        ]
        
        for file_path, default_data in files_to_init:
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    json.dump(default_data, f, indent=4)

    def _load_json(self, file_path: str) -> dict:
        """Load JSON data from file"""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_json(self, file_path: str, data: dict):
        """Save JSON data to file"""
        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving JSON file {file_path}: {e}")

    def _update_sync_status(self, key: str, value):
        """Update sync status file"""
        sync_status = self._load_json(self.sync_status_path)
        sync_status[key] = value
        self._save_json(self.sync_status_path, sync_status)

    def _get_last_online_time(self) -> Optional[datetime]:
        """Get the last known online time"""
        sync_status = self._load_json(self.sync_status_path)
        last_online = sync_status.get("last_online")
        if last_online:
            try:
                return datetime.fromisoformat(last_online)
            except ValueError:
                return None
        return None

    def _set_online_time(self):
        """Set the current time as online time"""
        current_time = datetime.now(timezone.utc).isoformat()
        self._update_sync_status("last_online", current_time)

    # ==================== SYNC FUNCTIONALITY ====================

    async def perform_startup_sync(self):
        """Perform sync operations when bot starts up"""
        if self.initial_sync_completed:
            return
            
        await self.bot.wait_until_ready()
        
        try:
            last_online = self._get_last_online_time()
            current_time = datetime.now(timezone.utc)
            
            if last_online:
                offline_duration = current_time - last_online
                await self.log_autoroles_action(
                    "startup_sync_initiated", None, None,
                    f"Bot was offline for {offline_duration}. Starting sync process."
                )
                
                # Sync autoroles for all guilds
                await self._sync_autoroles_for_offline_members(last_online)
                
                # Sync reaction roles for all guilds
                await self._sync_reaction_roles_for_offline_changes()
                
                await self.log_autoroles_action(
                    "startup_sync_completed", None, None,
                    "All role syncing operations completed."
                )
            else:
                await self.log_autoroles_action(
                    "first_startup", None, None,
                    "First bot startup detected. No sync needed."
                )
            
            # Update sync status
            self._update_sync_status("last_sync", current_time.isoformat())
            self._set_online_time()
            self.initial_sync_completed = True
            
        except Exception as e:
            await self.log_autoroles_error(
                f"Startup sync failed: {str(e)}", None, None
            )

    async def _sync_autoroles_for_offline_members(self, last_online: datetime):
        """Sync autoroles for members who joined while bot was offline"""
        autoroles_db = self._load_json(self.autoroles_db_path)
        
        for guild in self.bot.guilds:
            if not self.is_autoroles_enabled(guild.id):
                continue
                
            guild_id = str(guild.id)
            if guild_id not in autoroles_db or not autoroles_db[guild_id]:
                continue
            
            # Get autoroles for this guild
            autorole_ids = autoroles_db[guild_id]
            autoroles = [guild.get_role(role_id) for role_id in autorole_ids]
            autoroles = [role for role in autoroles if role is not None]
            
            if not autoroles:
                continue
            
            # Find members who joined after last online time
            members_to_sync = []
            for member in guild.members:
                if member.joined_at and member.joined_at.replace(tzinfo=timezone.utc) > last_online:
                    # Check if member is missing any autoroles
                    missing_roles = [role for role in autoroles if role not in member.roles]
                    if missing_roles:
                        members_to_sync.append((member, missing_roles))
            
            # Apply missing autoroles
            synced_count = 0
            for member, missing_roles in members_to_sync:
                try:
                    await member.add_roles(*missing_roles, reason="Autoroles sync after offline period")
                    synced_count += 1
                    role_names = [role.name for role in missing_roles]
                    await self.log_autoroles_action(
                        "offline_sync_autorole", guild, member,
                        f"Applied missing autoroles: {', '.join(role_names)}"
                    )
                except discord.HTTPException as e:
                    await self.log_autoroles_error(
                        f"Failed to sync autoroles for {member.name}: {e}",
                        guild, member
                    )
            
            if synced_count > 0:
                await self.log_autoroles_action(
                    "autoroles_sync_summary", guild, None,
                    f"Synced autoroles for {synced_count} members who joined while offline"
                )

    async def _sync_reaction_roles_for_offline_changes(self):
        """Sync reaction roles for changes that happened while offline"""
        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        
        for message_id, data in reaction_roles_db.items():
            try:
                guild = self.bot.get_guild(data["guild_id"])
                if not guild or not self.is_reaction_roles_enabled(guild.id):
                    continue
                
                channel = guild.get_channel(data["channel_id"])
                if not channel:
                    continue
                
                try:
                    message = await channel.fetch_message(int(message_id))
                except discord.NotFound:
                    # Message was deleted, clean it up
                    del reaction_roles_db[message_id]
                    continue
                
                # Sync each reaction
                synced_users = 0
                for emoji, role_id in data["reactions"].items():
                    role = guild.get_role(role_id)
                    if not role:
                        continue
                    
                    # Find the reaction on the message
                    reaction = None
                    for msg_reaction in message.reactions:
                        if str(msg_reaction.emoji) == emoji:
                            reaction = msg_reaction
                            break
                    
                    if not reaction:
                        continue
                    
                    # Get users who reacted
                    try:
                        users_with_reaction = set()
                        async for user in reaction.users():
                            if user != self.bot.user:
                                users_with_reaction.add(user.id)
                        
                        # Get members who should have the role (have reaction)
                        # and members who shouldn't have the role (no reaction)
                        members_with_role = set(member.id for member in role.members)
                        
                        # Add role to users who have reaction but not role
                        for user_id in users_with_reaction:
                            if user_id not in members_with_role:
                                member = guild.get_member(user_id)
                                if member:
                                    try:
                                        await member.add_roles(role, reason="Reaction role sync after offline period")
                                        synced_users += 1
                                        await self.log_reaction_roles_action(
                                            "offline_sync_add", guild, member,
                                            f"Added role {role.name} for reaction {emoji}"
                                        )
                                    except discord.HTTPException as e:
                                        await self.log_reaction_roles_error(
                                            f"Failed to add role {role.name} to {member.name}: {e}",
                                            guild, member
                                        )
                        
                        # Remove role from users who don't have reaction but have role
                        for member in role.members:
                            if member.id not in users_with_reaction:
                                try:
                                    await member.remove_roles(role, reason="Reaction role sync after offline period")
                                    synced_users += 1
                                    await self.log_reaction_roles_action(
                                        "offline_sync_remove", guild, member,
                                        f"Removed role {role.name} for missing reaction {emoji}"
                                    )
                                except discord.HTTPException as e:
                                    await self.log_reaction_roles_error(
                                        f"Failed to remove role {role.name} from {member.name}: {e}",
                                        guild, member
                                    )
                    
                    except discord.HTTPException:
                        continue
                
                if synced_users > 0:
                    await self.log_reaction_roles_action(
                        "reaction_roles_sync_summary", guild, None,
                        f"Synced roles for {synced_users} users on message {message_id}"
                    )
                    
            except Exception as e:
                await self.log_reaction_roles_error(
                    f"Failed to sync reaction roles for message {message_id}: {e}",
                    None, None
                )
        
        # Save any cleanup changes
        self._save_json(self.reaction_roles_db_path, reaction_roles_db)

    @commands.command(name="force-sync-roles")
    async def force_sync_roles(self, ctx):
        """Manually trigger a role sync (Admin only)"""
        if not (self.has_autorole_admin_permission(ctx.author) or self.has_reactionrole_admin_permission(ctx.author)):
            await ctx.send("❌ You don't have permission to force sync roles.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🔄 Force Syncing Roles",
            description="Manually syncing all autoroles and reaction roles...",
            color=discord.Color.blue()
        )
        message = await ctx.send(embed=embed)
        
        try:
            # Sync autoroles (treat all members as if they joined recently)
            fake_old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)  # Very old date
            await self._sync_autoroles_for_offline_members(fake_old_time)
            
            # Sync reaction roles
            await self._sync_reaction_roles_for_offline_changes()
            
            await self.log_autoroles_action(
                "manual_sync_completed", ctx.guild, ctx.author,
                "Manual role sync completed successfully"
            )
            
            embed = discord.Embed(
                title="✅ Role Sync Complete",
                description="All autoroles and reaction roles have been synced successfully!",
                color=discord.Color.green()
            )
            await message.edit(embed=embed)
            
        except Exception as e:
            await self.log_autoroles_error(
                f"Manual sync failed: {str(e)}", ctx.guild, ctx.author
            )
            
            embed = discord.Embed(
                title="❌ Sync Failed",
                description=f"Role sync failed: {str(e)}",
                color=discord.Color.red()
            )
            await message.edit(embed=embed)

    roles_group = app_commands.Group(name="roles", description="Autoroles and Reaction Roles management")

    @roles_group.command(name="force-sync", description="Manually trigger a role sync (Admin only)")
    async def force_sync_roles_slash(self, interaction: discord.Interaction):
        """Manually trigger a role sync (Admin only)"""
        if not (self.has_autorole_admin_permission(interaction.user) or self.has_reactionrole_admin_permission(interaction.user)):
            await interaction.response.send_message("❌ You don't have permission to force sync roles.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🔄 Force Syncing Roles",
            description="Manually syncing all autoroles and reaction roles...",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)
        
        try:
            # Sync autoroles (treat all members as if they joined recently)
            fake_old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)  # Very old date
            await self._sync_autoroles_for_offline_members(fake_old_time)
            
            # Sync reaction roles
            await self._sync_reaction_roles_for_offline_changes()
            
            await self.log_autoroles_action(
                "manual_sync_completed", interaction.guild, interaction.user,
                "Manual role sync completed successfully"
            )
            
            embed = discord.Embed(
                title="✅ Role Sync Complete",
                description="All autoroles and reaction roles have been synced successfully!",
                color=discord.Color.green()
            )
            await interaction.edit_original_response(embed=embed)
            
        except Exception as e:
            await self.log_autoroles_error(
                f"Manual sync failed: {str(e)}", interaction.guild, interaction.user
            )
            
            embed = discord.Embed(
                title="❌ Sync Failed",
                description=f"Role sync failed: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed)

    # ==================== EVENT LISTENERS ====================

    @commands.Cog.listener()
    async def on_ready(self):
        """Triggered when bot is ready - perform startup sync"""
        # Delay to ensure all guilds are loaded
        await asyncio.sleep(5)
        await self.perform_startup_sync()

    @commands.Cog.listener()
    async def on_disconnect(self):
        """Update offline time when bot disconnects"""
        self._set_online_time()

    @commands.Cog.listener()
    async def on_resumed(self):
        """Handle reconnection after disconnect"""
        # Only perform sync if we were offline for a significant time
        last_online = self._get_last_online_time()
        if last_online:
            offline_duration = datetime.now(timezone.utc) - last_online
            if offline_duration.total_seconds() > 300:  # 5 minutes
                await self.perform_startup_sync()
        self._set_online_time()

    # ==================== TOGGLE SYSTEM ====================

    def is_autoroles_enabled(self, guild_id: int) -> bool:
        """Check if autoroles is enabled for a guild"""
        config = self._load_json(self.autoroles_config_path)
        guild_config = config.get("guild_settings", {}).get(str(guild_id), {})
        return guild_config.get("autoroles_enabled", True)  # Default to enabled

    def set_autoroles_enabled(self, guild_id: int, enabled: bool):
        """Set autoroles enabled status for a guild"""
        config = self._load_json(self.autoroles_config_path)
        if "guild_settings" not in config:
            config["guild_settings"] = {}
        if str(guild_id) not in config["guild_settings"]:
            config["guild_settings"][str(guild_id)] = {}
        
        config["guild_settings"][str(guild_id)]["autoroles_enabled"] = enabled
        self._save_json(self.autoroles_config_path, config)

    def is_reaction_roles_enabled(self, guild_id: int) -> bool:
        """Check if reaction roles is enabled for a guild"""
        config = self._load_json(self.reaction_roles_config_path)
        guild_config = config.get("guild_settings", {}).get(str(guild_id), {})
        return guild_config.get("reaction_roles_enabled", True)  # Default to enabled

    def set_reaction_roles_enabled(self, guild_id: int, enabled: bool):
        """Set reaction roles enabled status for a guild"""
        config = self._load_json(self.reaction_roles_config_path)
        if "guild_settings" not in config:
            config["guild_settings"] = {}
        if str(guild_id) not in config["guild_settings"]:
            config["guild_settings"][str(guild_id)] = {}
        
        config["guild_settings"][str(guild_id)]["reaction_roles_enabled"] = enabled
        self._save_json(self.reaction_roles_config_path, config)

    async def autoroles_check(self, interaction: discord.Interaction) -> bool:
        """Check if autoroles is enabled before running commands"""
        if not self.is_autoroles_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The autoroles system is currently disabled in this server!", 
                ephemeral=True
            )
            return False
        return True

    async def reaction_roles_check(self, interaction: discord.Interaction) -> bool:
        """Check if reaction roles is enabled before running commands"""
        if not self.is_reaction_roles_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The reaction roles system is currently disabled in this server!", 
                ephemeral=True
            )
            return False
        return True

    # ==================== LOGGING SYSTEM ====================

    async def log_autoroles_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log autoroles actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Autoroles {action}"
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
                    file_override="autoroles_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log autoroles action: {e}")

    async def log_autoroles_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log autoroles errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Autoroles Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="autoroles_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log autoroles error: {e}")

    async def log_reaction_roles_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log reaction roles actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Reaction Roles {action}"
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
                    file_override="reaction_roles_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log reaction roles action: {e}")

    async def log_reaction_roles_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log reaction roles errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Reaction Roles Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="reaction_roles_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log reaction roles error: {e}")

    # ==================== PERMISSION CHECKS ====================

    def has_autorole_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has autorole admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.autorole.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def has_reactionrole_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has reaction role admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.reactionrole.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    # ==================== UTILITY METHODS ====================

    def _parse_message_link(self, message_link: str) -> tuple:
        """Parse a Discord message link and return guild_id, channel_id, message_id"""
        pattern = r'https://discord\.com/channels/(\d+)/(\d+)/(\d+)'
        match = re.match(pattern, message_link)
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
        return None, None, None

    async def _get_message_from_link(self, message_link: str) -> Optional[discord.Message]:
        """Get a Discord message from a message link"""
        guild_id, channel_id, message_id = self._parse_message_link(message_link)
        if not all([guild_id, channel_id, message_id]):
            return None
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return None
        
        try:
            message = await channel.fetch_message(message_id)
            return message
        except discord.NotFound:
            return None

    # ==================== TOGGLE COMMANDS ====================
    @roles_group.command(name="toggle-autoroles", description="Toggle the autoroles system on/off (Admin only)")
    @app_commands.describe(enabled="Whether to enable or disable the autoroles system")
    async def toggle_autoroles(self, interaction: discord.Interaction, enabled: bool):
        """Toggle autoroles system"""
        if not self.has_autorole_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to toggle the autoroles system!", 
                ephemeral=True
            )
            return
        
        current_status = self.is_autoroles_enabled(interaction.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await interaction.response.send_message(
                f"ℹ️ The autoroles system is already {status_text} in this server!", 
                ephemeral=True
            )
            return
        
        self.set_autoroles_enabled(interaction.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_autoroles_action(
            "system_toggled", 
            interaction.guild, 
            interaction.user,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Autoroles System {status_text.title()}",
            description=f"The autoroles system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    @roles_group.command(name="toggle-reaction-roles", description="Toggle the reaction roles system on/off (Admin only)")
    @app_commands.describe(enabled="Whether to enable or disable the reaction roles system")
    async def toggle_reaction_roles(self, interaction: discord.Interaction, enabled: bool):
        """Toggle reaction roles system"""
        if not self.has_reactionrole_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to toggle the reaction roles system!", 
                ephemeral=True
            )
            return
        
        current_status = self.is_reaction_roles_enabled(interaction.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await interaction.response.send_message(
                f"ℹ️ The reaction roles system is already {status_text} in this server!", 
                ephemeral=True
            )
            return
        
        self.set_reaction_roles_enabled(interaction.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_reaction_roles_action(
            "system_toggled", 
            interaction.guild, 
            interaction.user,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Reaction Roles System {status_text.title()}",
            description=f"The reaction roles system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    @roles_group.command(name="status", description="Check the status of role systems")
    async def roles_status(self, interaction: discord.Interaction):
        """Check status of both role systems"""
        autoroles_enabled = self.is_autoroles_enabled(interaction.guild.id)
        reaction_roles_enabled = self.is_reaction_roles_enabled(interaction.guild.id)
        
        autoroles_emoji = "✅" if autoroles_enabled else "❌"
        reaction_roles_emoji = "✅" if reaction_roles_enabled else "❌"
        
        autoroles_text = "enabled" if autoroles_enabled else "disabled"
        reaction_roles_text = "enabled" if reaction_roles_enabled else "disabled"
        
        # Get sync status
        sync_status = self._load_json(self.sync_status_path)
        last_sync = sync_status.get("last_sync")
        if last_sync:
            try:
                last_sync_time = datetime.fromisoformat(last_sync)
                sync_text = f"<t:{int(last_sync_time.timestamp())}:R>"
            except ValueError:
                sync_text = "Unknown"
        else:
            sync_text = "Never"
        
        embed = discord.Embed(
            title="🎭 Role Systems Status",
            color=0x0099ff
        )
        
        embed.add_field(
            name=f"{autoroles_emoji} Autoroles",
            value=f"Currently **{autoroles_text}**",
            inline=True
        )
        
        embed.add_field(
            name=f"{reaction_roles_emoji} Reaction Roles",
            value=f"Currently **{reaction_roles_text}**",
            inline=True
        )
        
        embed.add_field(
            name="🔄 Last Sync",
            value=sync_text,
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    # ==================== AUTOROLES COMMANDS ====================

    @commands.group(name="autoroles", invoke_without_command=True)
    async def autoroles_prefix(self, ctx):
        """Autoroles management commands"""
        if not self.is_autoroles_enabled(ctx.guild.id):
            await ctx.send("❌ The autoroles system is currently disabled in this server!")
            return
            
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Autoroles Commands",
                description="Use `autoroles add <role>`, `autoroles remove <role>`, or `autoroles list`",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)

    @app_commands.command(name="autoroles", description="Autoroles management")
    @app_commands.describe(
        action="Action to perform",
        role="Role to add or remove (not needed for list)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list")
    ])
    async def autoroles_slash(self, interaction: discord.Interaction, action: str, role: discord.Role = None):
        """Autoroles management slash command"""
        if not await self.autoroles_check(interaction):
            return
            
        if action == "add":
            await self._autoroles_add(interaction, role)
        elif action == "remove":
            await self._autoroles_remove(interaction, role)
        elif action == "list":
            await self._autoroles_list(interaction)

    @autoroles_prefix.command(name="add")
    async def autoroles_add_prefix(self, ctx, *, role: discord.Role):
        """Add a role to autoroles"""
        if not self.is_autoroles_enabled(ctx.guild.id):
            await ctx.send("❌ The autoroles system is currently disabled in this server!")
            return
        await self._autoroles_add(ctx, role)

    @autoroles_prefix.command(name="remove")
    async def autoroles_remove_prefix(self, ctx, *, role: discord.Role):
        """Remove a role from autoroles"""
        if not self.is_autoroles_enabled(ctx.guild.id):
            await ctx.send("❌ The autoroles system is currently disabled in this server!")
            return
        await self._autoroles_remove(ctx, role)

    @autoroles_prefix.command(name="list")
    async def autoroles_list_prefix(self, ctx):
        """List all autoroles"""
        if not self.is_autoroles_enabled(ctx.guild.id):
            await ctx.send("❌ The autoroles system is currently disabled in this server!")
            return
        await self._autoroles_list(ctx)

    async def _autoroles_add(self, ctx_or_interaction, role: discord.Role):
        """Add a role to autoroles"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_autorole_admin_permission(member):
            await respond("❌ You don't have permission to manage autoroles.", ephemeral=True)
            return

        if not role:
            await respond("❌ Please specify a role to add.", ephemeral=True)
            return

        autoroles_db = self._load_json(self.autoroles_db_path)
        guild_id = str(guild.id)
        
        if guild_id not in autoroles_db:
            autoroles_db[guild_id] = []
        
        if role.id in autoroles_db[guild_id]:
            await respond(f"❌ {role.mention} is already in autoroles.", ephemeral=True)
            return
        
        autoroles_db[guild_id].append(role.id)
        self._save_json(self.autoroles_db_path, autoroles_db)
        
        await self.log_autoroles_action(
            "role_added", guild, member, f"Role: {role.name} ({role.id})"
        )
        
        embed = discord.Embed(
            title="✅ Autorole Added",
            description=f"{role.mention} has been added to autoroles.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

    async def _autoroles_remove(self, ctx_or_interaction, role: discord.Role):
        """Remove a role from autoroles"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_autorole_admin_permission(member):
            await respond("❌ You don't have permission to manage autoroles.", ephemeral=True)
            return

        if not role:
            await respond("❌ Please specify a role to remove.", ephemeral=True)
            return

        autoroles_db = self._load_json(self.autoroles_db_path)
        guild_id = str(guild.id)
        
        if guild_id not in autoroles_db or role.id not in autoroles_db[guild_id]:
            await respond(f"❌ {role.mention} is not in autoroles.", ephemeral=True)
            return
        
        autoroles_db[guild_id].remove(role.id)
        self._save_json(self.autoroles_db_path, autoroles_db)
        
        await self.log_autoroles_action(
            "role_removed", guild, member, f"Role: {role.name} ({role.id})"
        )
        
        embed = discord.Embed(
            title="✅ Autorole Removed",
            description=f"{role.mention} has been removed from autoroles.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

    async def _autoroles_list(self, ctx_or_interaction):
        """List all autoroles"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        autoroles_db = self._load_json(self.autoroles_db_path)
        guild_id = str(guild.id)
        
        if guild_id not in autoroles_db or not autoroles_db[guild_id]:
            embed = discord.Embed(
                title="Autoroles",
                description="No autoroles configured for this server.",
                color=discord.Color.blue()
            )
            await respond(embed=embed)
            return
        
        roles = []
        for role_id in autoroles_db[guild_id]:
            role = guild.get_role(role_id)
            if role:
                roles.append(role.mention)
            else:
                # Clean up deleted roles
                autoroles_db[guild_id].remove(role_id)
        
        self._save_json(self.autoroles_db_path, autoroles_db)
        
        if not roles:
            embed = discord.Embed(
                title="Autoroles",
                description="No autoroles configured for this server.",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="Autoroles",
                description="\n".join(roles),
                color=discord.Color.blue()
            )
        
        await respond(embed=embed)

    # ==================== REACTION ROLES COMMANDS ====================

    @commands.group(name="reactionroles", invoke_without_command=True)
    async def reactionroles_prefix(self, ctx):
        """Reaction roles management commands"""
        if not self.is_reaction_roles_enabled(ctx.guild.id):
            await ctx.send("❌ The reaction roles system is currently disabled in this server!")
            return
            
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Reaction Roles Commands",
                description="Use `reactionroles create <message_link>`, `reactionroles add <message_link> <emoji> <role>`, or `reactionroles remove <message_link>`",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)

    @app_commands.command(name="reactionroles", description="Reaction roles management")
    @app_commands.describe(
        action="Action to perform",
        message_link="Discord message link",
        emoji="Emoji for the reaction role",
        role="Role to assign"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="create", value="create"),
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove")
    ])
    async def reactionroles_slash(self, interaction: discord.Interaction, action: str, message_link: str, emoji: str = None, role: discord.Role = None):
        """Reaction roles management slash command"""
        if not await self.reaction_roles_check(interaction):
            return
            
        if action == "create":
            await self._reactionroles_create(interaction, message_link)
        elif action == "add":
            await self._reactionroles_add(interaction, message_link, emoji, role)
        elif action == "remove":
            await self._reactionroles_remove(interaction, message_link)

    @reactionroles_prefix.command(name="create")
    async def reactionroles_create_prefix(self, ctx, message_link: str):
        """Create/initialize a reaction role message"""
        if not self.is_reaction_roles_enabled(ctx.guild.id):
            await ctx.send("❌ The reaction roles system is currently disabled in this server!")
            return
        await self._reactionroles_create(ctx, message_link)

    @reactionroles_prefix.command(name="add")
    async def reactionroles_add_prefix(self, ctx, message_link: str, emoji: str, *, role: discord.Role):
        """Add a reaction role to a message"""
        if not self.is_reaction_roles_enabled(ctx.guild.id):
            await ctx.send("❌ The reaction roles system is currently disabled in this server!")
            return
        await self._reactionroles_add(ctx, message_link, emoji, role)

    @reactionroles_prefix.command(name="remove")
    async def reactionroles_remove_prefix(self, ctx, message_link: str):
        """Remove all reaction roles from a message"""
        if not self.is_reaction_roles_enabled(ctx.guild.id):
            await ctx.send("❌ The reaction roles system is currently disabled in this server!")
            return
        await self._reactionroles_remove(ctx, message_link)

    async def _reactionroles_create(self, ctx_or_interaction, message_link: str):
        """Create/initialize a reaction role message"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_reactionrole_admin_permission(member):
            await respond("❌ You don't have permission to manage reaction roles.", ephemeral=True)
            return

        message = await self._get_message_from_link(message_link)
        if not message:
            await respond("❌ Invalid message link or message not found.", ephemeral=True)
            return

        if message.author != self.bot.user:
            await respond("❌ Can only add reaction roles to bot messages.", ephemeral=True)
            return

        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        message_id = str(message.id)
        
        if message_id in reaction_roles_db:
            await respond("❌ This message already has reaction roles configured.", ephemeral=True)
            return

        reaction_roles_db[message_id] = {
            "guild_id": guild.id,
            "channel_id": message.channel.id,
            "reactions": {}
        }
        self._save_json(self.reaction_roles_db_path, reaction_roles_db)

        await self.log_reaction_roles_action(
            "message_setup", guild, member, f"Message ID: {message.id}"
        )

        embed = discord.Embed(
            title="✅ Reaction Role Message Created",
            description=f"Message [here]({message.jump_url}) is now ready for reaction roles.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

    async def _reactionroles_add(self, ctx_or_interaction, message_link: str, emoji: str, role: discord.Role):
        """Add a reaction role to a message"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_reactionrole_admin_permission(member):
            await respond("❌ You don't have permission to manage reaction roles.", ephemeral=True)
            return

        if not emoji or not role:
            await respond("❌ Please specify both an emoji and a role.", ephemeral=True)
            return

        message = await self._get_message_from_link(message_link)
        if not message:
            await respond("❌ Invalid message link or message not found.", ephemeral=True)
            return

        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        message_id = str(message.id)
        
        if message_id not in reaction_roles_db:
            await respond("❌ This message is not configured for reaction roles. Use `reactionroles create` first.", ephemeral=True)
            return

        # Try to add the reaction to verify emoji is valid
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            await respond("❌ Invalid emoji or unable to add reaction.", ephemeral=True)
            return

        reaction_roles_db[message_id]["reactions"][emoji] = role.id
        self._save_json(self.reaction_roles_db_path, reaction_roles_db)

        await self.log_reaction_roles_action(
            "reaction_added", guild, member, f"Message ID: {message.id}, Emoji: {emoji}, Role: {role.name} ({role.id})"
        )

        embed = discord.Embed(
            title="✅ Reaction Role Added",
            description=f"Reaction {emoji} → {role.mention} added to [message]({message.jump_url})",
            color=discord.Color.green()
        )
        await respond(embed=embed)

    async def _reactionroles_remove(self, ctx_or_interaction, message_link: str):
        """Remove all reaction roles from a message"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_reactionrole_admin_permission(member):
            await respond("❌ You don't have permission to manage reaction roles.", ephemeral=True)
            return

        message = await self._get_message_from_link(message_link)
        if not message:
            await respond("❌ Invalid message link or message not found.", ephemeral=True)
            return

        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        message_id = str(message.id)
        
        if message_id not in reaction_roles_db:
            await respond("❌ This message doesn't have reaction roles configured.", ephemeral=True)
            return

        # Clear all reactions from the message
        try:
            await message.clear_reactions()
        except discord.HTTPException:
            pass

        del reaction_roles_db[message_id]
        self._save_json(self.reaction_roles_db_path, reaction_roles_db)

        await self.log_reaction_roles_action(
            "message_cleared", guild, member, f"Message ID: {message.id}"
        )

        embed = discord.Embed(
            title="✅ Reaction Roles Removed",
            description=f"All reaction roles removed from [message]({message.jump_url})",
            color=discord.Color.green()
        )
        await respond(embed=embed)

    # ==================== EVENT LISTENERS ====================
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Handle autoroles when a member joins"""
        if not self.is_autoroles_enabled(member.guild.id):
            return

        autoroles_db = self._load_json(self.autoroles_db_path)
        guild_id = str(member.guild.id)
        
        if guild_id not in autoroles_db:
            return

        roles_to_add = []
        for role_id in autoroles_db[guild_id]:
            role = member.guild.get_role(role_id)
            if role:
                roles_to_add.append(role)

        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Autoroles")
                role_names = [role.name for role in roles_to_add]
                await self.log_autoroles_action(
                    "roles_assigned", member.guild, member,
                    f"Roles: {', '.join(role_names)}"
                )
            except discord.HTTPException as e:
                await self.log_autoroles_error(
                    f"Failed to assign autoroles to {member.name}: {e}", 
                    member.guild, member
                )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reaction role additions"""
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild or not self.is_reaction_roles_enabled(guild.id):
            return

        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        message_id = str(payload.message_id)
        
        if message_id not in reaction_roles_db:
            return

        emoji = str(payload.emoji)
        if emoji not in reaction_roles_db[message_id]["reactions"]:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        role_id = reaction_roles_db[message_id]["reactions"][emoji]
        role = guild.get_role(role_id)
        if not role:
            return

        try:
            await member.add_roles(role, reason="Reaction role")
            await self.log_reaction_roles_action(
                "role_assigned", guild, member, f"Role: {role.name} ({role.id}), Emoji: {emoji}"
            )
        except discord.HTTPException as e:
            await self.log_reaction_roles_error(
                f"Failed to assign reaction role {role.name} to {member.name}: {e}",
                guild, member
            )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Handle reaction role removals"""
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild or not self.is_reaction_roles_enabled(guild.id):
            return

        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        message_id = str(payload.message_id)
        
        if message_id not in reaction_roles_db:
            return

        emoji = str(payload.emoji)
        if emoji not in reaction_roles_db[message_id]["reactions"]:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        role_id = reaction_roles_db[message_id]["reactions"][emoji]
        role = guild.get_role(role_id)
        if not role:
            return

        try:
            await member.remove_roles(role, reason="Reaction role removed")
            await self.log_reaction_roles_action(
                "role_removed", guild, member, f"Role: {role.name} ({role.id}), Emoji: {emoji}"
            )
        except discord.HTTPException as e:
            await self.log_reaction_roles_error(
                f"Failed to remove reaction role {role.name} from {member.name}: {e}",
                guild, member
            )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        """Clean up autoroles and reaction roles when a role is deleted"""
        # Clean autoroles
        autoroles_db = self._load_json(self.autoroles_db_path)
        guild_id = str(role.guild.id)
        
        if guild_id in autoroles_db and role.id in autoroles_db[guild_id]:
            autoroles_db[guild_id].remove(role.id)
            self._save_json(self.autoroles_db_path, autoroles_db)
            
            await self.log_autoroles_action(
                "role_cleanup", role.guild, None, f"Removed deleted role: {role.name} ({role.id})"
            )

        # Clean reaction roles
        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        messages_to_update = []
        
        for message_id, data in reaction_roles_db.items():
            if data["guild_id"] == role.guild.id:
                reactions_to_remove = []
                for emoji, role_id in data["reactions"].items():
                    if role_id == role.id:
                        reactions_to_remove.append(emoji)
                
                for emoji in reactions_to_remove:
                    del data["reactions"][emoji]
                    messages_to_update.append((message_id, emoji))
        
        if messages_to_update:
            self._save_json(self.reaction_roles_db_path, reaction_roles_db)
            
            await self.log_reaction_roles_action(
                "role_cleanup", role.guild, None, f"Removed deleted role: {role.name} ({role.id})"
            )
            
            # Remove reactions from messages
            for message_id, emoji in messages_to_update:
                try:
                    channel = self.bot.get_channel(reaction_roles_db[message_id]["channel_id"])
                    if channel:
                        message = await channel.fetch_message(int(message_id))
                        await message.remove_reaction(emoji, self.bot.user)
                except (discord.NotFound, discord.HTTPException):
                    pass

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Clean up reaction roles when a message is deleted"""
        reaction_roles_db = self._load_json(self.reaction_roles_db_path)
        message_id = str(message.id)
        
        if message_id in reaction_roles_db:
            del reaction_roles_db[message_id]
            self._save_json(self.reaction_roles_db_path, reaction_roles_db)
            
            await self.log_reaction_roles_action(
                "message_cleanup", message.guild, None, f"Cleaned up deleted message: {message.id}"
            )

async def setup(bot):
    await bot.add_cog(AutorolesReactionRolesCog(bot))
