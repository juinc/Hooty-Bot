"""
Discord LevelsCog - Advanced Leveling & Auto-Role System

OVERVIEW:
A comprehensive leveling system for Discord servers.  
Tracks text and voice XP, assigns roles as rewards, supports auto-role for new members, and provides full admin control and logging.

SETUP:
- No manual setup required – auto-creates config/database files:
- Config: src/config/levels_config.json
- Database: src/database/levels_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.levels.admin' or Administrator

COMMANDS (Slash & Prefix):
/level toggle [on/off]                - Enable/disable the leveling system (admin)
/level status                         - Show system status and level 0 auto-role info
/level setlevel0role <role>           - Set auto-role for new members (admin)
/level removelevel0role               - Remove auto-role for new members (admin)
/level setlevel0removal <on/off>      - Toggle removing level 0 role on level up (admin)
/level checklevel0roles               - Check/assign missing level 0 roles (admin)
/level rank [user] [type]             - Show your or another user's rank (text/voice/both)
/level leaderboard [type] [page]      - Show server leaderboard (text/voice/combined)
/level setreward <level> <type> <role> [permanent] - Set a role reward for a level (admin)
/level removereward <level> <type> <role>          - Remove a role reward (admin)
/level rewards [type] [level]         - View all level rewards
/level set <user> <level> <type>      - Set a user's level and update their roles (admin)
/level embedtoggle                    - Toggle level up embeds (admin)
/level config [embed options]         - View or configure level up embed settings (admin)

Prefix commands: !level, !lvl (same subcommands as above)

COMMAND EXPLANATIONS:
- toggle: Enable/disable the leveling system for your server.
- status: Show if leveling is enabled and auto-role info.
- setlevel0role/removelevel0role: Set/remove auto-role for new members.
- setlevel0removal: Toggle if level 0 role is removed on level up.
- checklevel0roles: Assign missing level 0 roles to true level 0s.
- rank: Show a user's level, XP, rank, and progress.
- leaderboard: Show top users by XP/level.
- setreward/removereward: Manage role rewards for reaching levels.
- rewards: View all configured level rewards.
- set: Set a user's level and update their roles.
- embedtoggle/config: Toggle or configure level up embed messages.

FEATURES:
• Tracks text and voice XP/levels for all users
• Assigns roles as rewards for reaching levels (permanent or temporary)
• Auto-role for new members (level 0 role)
• Optionally removes level 0 role on level up
• Smart role management: auto-add/remove on level changes
• Customizable level up embed messages (title, description, color, channel, show rewards)
• Leaderboards and user rank/progress
• Per-server persistent config and stats (JSON)
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Both slash and prefix command support
• Background tasks for auto-saving and missed role checks

USAGE BY OTHER COGS:

# Access or modify a user's level/XP
levels_cog = bot.get_cog('LevelsCog')
if levels_cog:
    user_data = levels_cog.get_user_data(guild.id, user.id)
    # Read or modify XP/level
    user_data["text_xp"] += 100
    user_data["text_level"] = levels_cog.calculate_level(user_data["text_xp"])
    levels_cog.save_levels_db()

# Award XP for custom events
await levels_cog.add_text_xp(member, channel)
await levels_cog.add_voice_xp(member, minutes)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import random
import math
from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any, List
import os
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

class LevelsCog(commands.Cog):
    """Comprehensive leveling system with text and voice chat levels"""
    
    def __init__(self, bot):
        self.bot = bot
        self.levels_db_file = "src/database/levels_db.json"
        self.levels_config_file = "src/config/levels_config.json"
        
        # Ensure directories exist
        os.makedirs("src/database", exist_ok=True)
        os.makedirs("src/logs", exist_ok=True)
        
        # Load data
        self.levels_db = self.load_levels_db()
        self.config = self.load_config()
        
        # Cooldown tracking
        self.text_cooldowns = {}  # {user_id: last_xp_time}
        self.voice_sessions = {}  # {user_id: {'start_time': datetime, 'channel': voice_channel}}
        
        # Start background tasks
        self.save_data_task.start()
        self.check_missed_joins_task.start()
        
        # Immediately check for missing level 0 roles on startup
        self.bot.loop.create_task(self.assign_level_0_roles_on_startup())

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.save_data_task.cancel()
        self.check_missed_joins_task.cancel()
        self.save_levels_db()

    def is_leveling_enabled(self, guild_id: int) -> bool:
        """Check if leveling is enabled for a guild"""
        guild_config = self.config.get("guild_settings", {}).get(str(guild_id), {})
        return guild_config.get("leveling_enabled", True)  # Default to enabled

    def set_leveling_enabled(self, guild_id: int, enabled: bool):
        """Set leveling enabled status for a guild"""
        if "guild_settings" not in self.config:
            self.config["guild_settings"] = {}
        if str(guild_id) not in self.config["guild_settings"]:
            self.config["guild_settings"][str(guild_id)] = {}
        
        self.config["guild_settings"][str(guild_id)]["leveling_enabled"] = enabled
        self.save_config()

    async def leveling_check(self, interaction: discord.Interaction) -> bool:
        """Check if leveling is enabled before running commands"""
        if not self.is_leveling_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The leveling system is currently disabled in this server!", 
                ephemeral=True
            )
            return False
        return True

    async def log_levels_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log levels actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Levels {action}"
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
                    file_override="levels_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log levels action: {e}")

    async def log_levels_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log levels errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Levels Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="levels_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log levels error: {e}")

    async def log_levels_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log levels warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Levels Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="levels_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log levels warning: {e}")

    def load_levels_db(self) -> Dict[str, Any]:
        """Load levels database from JSON file"""
        try:
            if os.path.exists(self.levels_db_file):
                with open(self.levels_db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            # Use asyncio to schedule the logging since we can't await in __init__
            asyncio.create_task(self.log_levels_error(f"Error loading levels database: {e}"))
        return {}

    def save_levels_db(self):
        """Save levels database to JSON file"""
        try:
            with open(self.levels_db_file, 'w', encoding='utf-8') as f:
                json.dump(self.levels_db, f, indent=2, ensure_ascii=False)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_levels_error(f"Error saving levels database: {e}"))

    def load_config(self) -> Dict[str, Any]:
        """Load levels configuration from JSON file, do not overwrite on error."""
        default_config = {
            "guild_settings": {},
            "xp_rates": {
                "text_xp_min": 15,
                "text_xp_max": 25,
                "voice_xp_per_minute": 10,
                "cooldown_seconds": 60
            },
            "level_up_embed": {
                "enabled": True,
                "title": "🎉 Level Up!",
                "description": "{user} reached **level {level}** in {type}!",
                "color": 0x00ff00,
                "fallback_channel": None,
                "show_rewards": True,
                "thumbnail": "user_avatar"
            },
            "rewards": {
                "text": {},
                "voice": {}
            },
            "disabled_channels": [],
            "multipliers": {
                "weekend": 1.5,
                "events": 1.0
            },
            "level_0_role": None,
            "remove_level_0_role_on_levelup": True
        }
        config = None
        try:
            if os.path.exists(self.levels_config_file):
                with open(self.levels_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    config = self.migrate_rewards_format(config)
                    # Ensure all guilds have default structure
                    for guild_id in config:
                        if guild_id != "guild_settings":
                            for key, value in default_config.items():
                                if key not in config[guild_id] and key != "guild_settings":
                                    config[guild_id][key] = value
                    if "guild_settings" not in config:
                        config["guild_settings"] = {}
            else:
                # File does not exist, write default config
                with open(self.levels_config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=2, ensure_ascii=False)
                config = default_config
        except Exception as e:
            # Log error, but do NOT overwrite file
            asyncio.create_task(self.log_levels_error(f"Error loading levels config: {e}"))
            if config is None:
                config = default_config.copy()
        return config

    def save_config(self):
        """Save levels configuration to JSON file, only if config is valid."""
        try:
            # Validate config before saving
            json.dumps(self.config)
            with open(self.levels_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            # Log error, do NOT overwrite file
            asyncio.create_task(self.log_levels_error(f"Error saving levels config: {e}"))

    def migrate_rewards_format(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate old reward format to new format with permanence settings"""
        for guild_id, guild_config in config.items():
            if guild_id == "guild_settings":  # Skip the guild_settings key
                continue
            if "rewards" in guild_config:
                for level_type in ["text", "voice"]:
                    if level_type in guild_config["rewards"]:
                        for level_str, rewards in guild_config["rewards"][level_type].items():
                            # Check if already in new format
                            if rewards and isinstance(rewards[0], dict):
                                continue
                            
                            # Convert old format [role_id, role_id] to new format
                            new_rewards = []
                            for role_id in rewards:
                                new_rewards.append({
                                    "role_id": role_id,
                                    "permanent": True  # Default to permanent for existing rewards
                                })
                            guild_config["rewards"][level_type][level_str] = new_rewards
        return config

    def get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        """Get configuration for a specific guild"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.config:
            self.config[guild_id_str] = {
                "xp_rates": {
                    "text_xp_min": 15,
                    "text_xp_max": 25,
                    "voice_xp_per_minute": 10,
                    "cooldown_seconds": 60
                },
                "level_up_embed": {
                    "enabled": True,
                    "title": "🎉 Level Up!",
                    "description": "{user} reached **level {level}** in {type}!",
                    "color": 0x00ff00,
                    "fallback_channel": None,
                    "show_rewards": True,
                    "thumbnail": "user_avatar"
                },
                "rewards": {
                    "text": {},
                    "voice": {}
                },
                "disabled_channels": [],
                "multipliers": {
                    "weekend": 1.5,
                    "events": 1.0
                },
                "level_0_role": None,
                "remove_level_0_role_on_levelup": True  # NEW: Default to True
            }
        return self.config[guild_id_str]

    def get_user_data(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        """Get user level data"""
        guild_id_str = str(guild_id)
        user_id_str = str(user_id)
        
        if guild_id_str not in self.levels_db:
            self.levels_db[guild_id_str] = {}
        
        if user_id_str not in self.levels_db[guild_id_str]:
            self.levels_db[guild_id_str][user_id_str] = {
                "text_xp": 0,
                "voice_xp": 0,
                "text_level": 0,
                "voice_level": 0,
                "last_text_xp": 0,
                "voice_time_start": None,
                "total_voice_minutes": 0
            }
        
        return self.levels_db[guild_id_str][user_id_str]

    def has_levels_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has levels admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.levels.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def calculate_level(self, xp: int) -> int:
        """Calculate level from XP"""
        if xp < 0:
            return 0
        return int(math.sqrt(xp / 100))

    def calculate_xp_for_level(self, level: int) -> int:
        """Calculate XP required for a specific level"""
        return level * level * 100

    def calculate_xp_for_next_level(self, current_level: int) -> int:
        """Calculate XP required for next level"""
        return self.calculate_xp_for_level(current_level + 1)
    
    # Assign level 0 roles to missing members on startup
    async def assign_level_0_roles_on_startup(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)  # Give time for all guilds/members to cache
        for guild in self.bot.guilds:
            if self.is_leveling_enabled(guild.id):
                assigned_count = await self.check_and_assign_missing_level_0_roles(guild)
                if assigned_count > 0:
                    await self.log_levels_action(
                        "startup_level_0_check",
                        guild,
                        None,
                        f"Assigned level 0 role to {assigned_count} members on startup"
                    )

    async def assign_level_0_role(self, member: discord.Member) -> bool:
        """Assign level 0 role to a member if configured"""
        if member.bot:
            return False
        
        guild_config = self.get_guild_config(member.guild.id)
        level_0_role_id = guild_config.get("level_0_role")
        
        if not level_0_role_id:
            return False
        
        role = member.guild.get_role(level_0_role_id)
        if not role:
            await self.log_levels_warning(
                f"Level 0 role {level_0_role_id} not found in guild {member.guild.name}",
                member.guild
            )
            return False
        
        if role in member.roles:
            return False  # Already has the role
        
        try:
            await member.add_roles(role, reason="Level 0 auto-role assignment")
            await self.log_levels_action(
                "level_0_role_assigned", 
                member.guild, 
                member, 
                f"Assigned role: {role.name}"
            )
            return True
        except discord.Forbidden:
            await self.log_levels_error(
                f"No permission to assign level 0 role {role.name} to {member.name}",
                member.guild,
                member
            )
            return False
        except Exception as e:
            await self.log_levels_error(
                f"Error assigning level 0 role to {member.name}: {e}",
                member.guild,
                member
            )
            return False

    async def remove_level_0_role(self, member: discord.Member) -> bool:
        """Remove level 0 role from a member if they have it"""
        if member.bot:
            return False
        
        guild_config = self.get_guild_config(member.guild.id)
        level_0_role_id = guild_config.get("level_0_role")
        
        if not level_0_role_id:
            return False
        
        role = member.guild.get_role(level_0_role_id)
        if not role:
            return False
        
        if role not in member.roles:
            return False  # Doesn't have the role
        
        try:
            await member.remove_roles(role, reason="Level 0 role removed on level up")
            await self.log_levels_action(
                "level_0_role_removed_on_levelup", 
                member.guild, 
                member, 
                f"Removed level 0 role: {role.name}"
            )
            return True
        except discord.Forbidden:
            await self.log_levels_error(
                f"No permission to remove level 0 role {role.name} from {member.name}",
                member.guild,
                member
            )
            return False
        except Exception as e:
            await self.log_levels_error(
                f"Error removing level 0 role from {member.name}: {e}",
                member.guild,
                member
            )
            return False

    async def check_and_assign_missing_level_0_roles(self, guild: discord.Guild) -> int:
        """Check for members missing level 0 role and assign/remove it based on config"""
        guild_config = self.get_guild_config(guild.id)
        level_0_role_id = guild_config.get("level_0_role")
        remove_on_levelup = guild_config.get("remove_level_0_role_on_levelup", True)

        if not level_0_role_id:
            return 0

        role = guild.get_role(level_0_role_id)
        if not role:
            await self.log_levels_warning(
                f"Level 0 role {level_0_role_id} not found in guild {guild.name}",
                guild
            )
            return 0

        assigned_count = 0
        removed_count = 0

        for member in guild.members:
            if member.bot:
                continue

            user_data = self.get_user_data(guild.id, member.id)
            text_level = user_data["text_level"]
            voice_level = user_data["voice_level"]

            if not remove_on_levelup:
                # Give the role to everyone who doesn't have it
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Level 0 auto-role assignment (removal disabled)")
                        assigned_count += 1
                        await self.log_levels_action(
                            "level_0_role_assigned_missed",
                            guild,
                            member,
                            f"Assigned missed role: {role.name} (removal disabled)"
                        )
                    except Exception as e:
                        await self.log_levels_error(
                            f"Error assigning missed level 0 role to {member.name}: {e}",
                            guild,
                            member
                        )
            else:
                # Only assign to true level 0s, and remove from others
                if text_level == 0 and voice_level == 0:
                    if role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Missed level 0 auto-role assignment")
                            assigned_count += 1
                            await self.log_levels_action(
                                "level_0_role_assigned_missed",
                                guild,
                                member,
                                f"Assigned missed role: {role.name}"
                            )
                        except Exception as e:
                            await self.log_levels_error(
                                f"Error assigning missed level 0 role to {member.name}: {e}",
                                guild,
                                member
                            )
                else:
                    if role in member.roles:
                        try:
                            await member.remove_roles(role, reason="Level 0 role removed (not level 0 anymore, removal enabled)")
                            removed_count += 1
                            await self.log_levels_action(
                                "level_0_role_removed_missed",
                                guild,
                                member,
                                f"Removed level 0 role: {role.name} (not level 0 anymore, removal enabled)"
                            )
                        except Exception as e:
                            await self.log_levels_error(
                                f"Error removing level 0 role from {member.name}: {e}",
                                guild,
                                member
                            )

        if assigned_count > 0 or removed_count > 0:
            await self.log_levels_action(
                "level_0_role_batch_update",
                guild,
                None,
                f"Assigned level 0 role to {assigned_count} members, removed from {removed_count} members"
            )

        return assigned_count

    def get_expected_roles_for_level(self, guild_id: int, level_type: str, target_level: int) -> List[Dict[str, Any]]:
        """Get all roles a user should have at a specific level"""
        guild_config = self.get_guild_config(guild_id)
        rewards = guild_config["rewards"][level_type]
        
        expected_roles = []
        
        for level in range(1, target_level + 1):
            level_str = str(level)
            if level_str in rewards:
                for reward in rewards[level_str]:
                    role_info = {
                        "role_id": reward["role_id"],
                        "level": level,
                        "permanent": reward.get("permanent", True)
                    }
                    
                    # For permanent roles, add them
                    if reward.get("permanent", True):
                        expected_roles.append(role_info)
                    # For temporary roles, only add if it's the highest level with that role
                    else:
                        # Check if this temporary role appears in any higher level
                        appears_higher = False
                        for higher_level in range(level + 1, target_level + 1):
                            higher_level_str = str(higher_level)
                            if higher_level_str in rewards:
                                for higher_reward in rewards[higher_level_str]:
                                    if higher_reward["role_id"] == reward["role_id"]:
                                        appears_higher = True
                                        break
                                if appears_higher:
                                    break
                        
                        # Only add temporary role if it doesn't appear at a higher level
                        # or if it's the highest level with this role
                        if not appears_higher:
                            # Remove any previous instance of this role from lower levels
                            expected_roles = [r for r in expected_roles if r["role_id"] != reward["role_id"]]
                            expected_roles.append(role_info)
        
        return expected_roles

    def get_all_level_reward_roles(self, guild_id: int, level_type: str) -> List[int]:
        """Get all role IDs that are used as level rewards"""
        guild_config = self.get_guild_config(guild_id)
        rewards = guild_config["rewards"][level_type]
        
        all_role_ids = set()
        for level_rewards in rewards.values():
            for reward in level_rewards:
                all_role_ids.add(reward["role_id"])
        
        return list(all_role_ids)

    async def update_user_roles_for_level(self, member: discord.Member, level_type: str, new_level: int) -> Dict[str, List[discord.Role]]:
        """Update user's roles based on their new level"""
        guild_config = self.get_guild_config(member.guild.id)
        
        # Get expected roles for the new level
        expected_role_info = self.get_expected_roles_for_level(member.guild.id, level_type, new_level)
        expected_role_ids = [info["role_id"] for info in expected_role_info]
        
        # Get all role IDs that are used as level rewards for this type
        all_reward_role_ids = self.get_all_level_reward_roles(member.guild.id, level_type)
        
        # Determine current level reward roles the user has
        current_reward_roles = [role for role in member.roles if role.id in all_reward_role_ids]
        current_reward_role_ids = [role.id for role in current_reward_roles]
        
        # Calculate roles to add and remove
        roles_to_add = []
        roles_to_remove = []
        
        # Roles to add: expected roles they don't have
        for role_id in expected_role_ids:
            if role_id not in current_reward_role_ids:
                role = member.guild.get_role(role_id)
                if role:
                    roles_to_add.append(role)
        
        # Roles to remove: current reward roles they shouldn't have
        for role_id in current_reward_role_ids:
            if role_id not in expected_role_ids:
                role = member.guild.get_role(role_id)
                if role:
                    roles_to_remove.append(role)
        
        # Apply role changes
        changes = {"added": [], "removed": []}
        
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason=f"Level set to {new_level} for {level_type}")
                changes["removed"] = roles_to_remove
            except discord.Forbidden:
                await self.log_levels_action(
                    "role_update_failed", member.guild, member,
                    f"No permission to remove roles when setting {level_type} level to {new_level}"
                )
        
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason=f"Level set to {new_level} for {level_type}")
                changes["added"] = roles_to_add
            except discord.Forbidden:
                await self.log_levels_action(
                    "role_update_failed", member.guild, member,
                    f"No permission to add roles when setting {level_type} level to {new_level}"
                )
        
        # Log the changes
        if changes["added"] or changes["removed"]:
            log_parts = []
            if changes["added"]:
                added_names = [role.name for role in changes["added"]]
                log_parts.append(f"Added: {', '.join(added_names)}")
            if changes["removed"]:
                removed_names = [role.name for role in changes["removed"]]
                log_parts.append(f"Removed: {', '.join(removed_names)}")
            
            await self.log_levels_action(
                "roles_updated", member.guild, member,
                f"Level set to {new_level} for {level_type} - {' | '.join(log_parts)}"
            )
        
        return changes

    async def add_text_xp(self, member: discord.Member, channel: discord.TextChannel):
        """Add XP for text messages"""
        if member.bot:
            return
        
        # Check if leveling is enabled
        if not self.is_leveling_enabled(member.guild.id):
            return
        
        guild_config = self.get_guild_config(member.guild.id)
        
        # Check if channel is disabled
        if channel.id in guild_config.get("disabled_channels", []):
            return
        
        # Check cooldown
        now = datetime.utcnow().timestamp()
        user_cooldown = self.text_cooldowns.get(member.id, 0)
        cooldown_seconds = guild_config["xp_rates"]["cooldown_seconds"]
        
        if now - user_cooldown < cooldown_seconds:
            return
        
        # Calculate XP
        min_xp = guild_config["xp_rates"]["text_xp_min"]
        max_xp = guild_config["xp_rates"]["text_xp_max"]
        base_xp = random.randint(min_xp, max_xp)
        
        # Apply multipliers
        final_xp = base_xp
        if datetime.utcnow().weekday() >= 5:  # Weekend
            final_xp *= guild_config["multipliers"]["weekend"]
        
        final_xp = int(final_xp)
        
        # Update user data
        user_data = self.get_user_data(member.guild.id, member.id)
        old_level = user_data["text_level"]
        user_data["text_xp"] += final_xp
        user_data["last_text_xp"] = now
        
        new_level = self.calculate_level(user_data["text_xp"])
        user_data["text_level"] = new_level
        
        # Update cooldown
        self.text_cooldowns[member.id] = now
        
        # Check for level up
        if new_level > old_level:
            await self.handle_level_up(member, "text", old_level, new_level, channel)
            
            await self.log_levels_action(
                "level_up", member.guild, member,
                f"Text level {old_level} -> {new_level} (XP: {user_data['text_xp']})"
            )

    async def add_voice_xp(self, member: discord.Member, minutes: float):
        """Add XP for voice activity"""
        if member.bot:
            return
        
        # Check if leveling is enabled
        if not self.is_leveling_enabled(member.guild.id):
            return
        
        guild_config = self.get_guild_config(member.guild.id)
        
        # Calculate XP
        base_xp = minutes * guild_config["xp_rates"]["voice_xp_per_minute"]
        
        # Apply multipliers
        final_xp = base_xp
        if datetime.utcnow().weekday() >= 5:  # Weekend
            final_xp *= guild_config["multipliers"]["weekend"]
        
        final_xp = int(final_xp)
        
        # Update user data
        user_data = self.get_user_data(member.guild.id, member.id)
        old_level = user_data["voice_level"]
        user_data["voice_xp"] += final_xp
        user_data["total_voice_minutes"] += minutes
        
        new_level = self.calculate_level(user_data["voice_xp"])
        user_data["voice_level"] = new_level
        
        # Check for level up
        if new_level > old_level:
            # For voice level ups, we need to find a suitable channel
            channel = self.find_suitable_channel_for_voice_levelup(member)
            await self.handle_level_up(member, "voice", old_level, new_level, channel)
            
            await self.log_levels_action(
                "level_up", member.guild, member,
                f"Voice level {old_level} -> {new_level} (XP: {user_data['voice_xp']})"
            )

    def find_suitable_channel_for_voice_levelup(self, member: discord.Member) -> Optional[discord.TextChannel]:
        """Find a suitable channel to send voice level up embed"""
        guild_config = self.get_guild_config(member.guild.id)
        
        # First, try configured fallback channel
        fallback_channel_id = guild_config["level_up_embed"].get("fallback_channel")
        if fallback_channel_id:
            channel = member.guild.get_channel(fallback_channel_id)
            if channel and channel.permissions_for(member.guild.me).send_messages:
                return channel
        
        # Try to find a general/chat channel
        for channel in member.guild.text_channels:
            if (channel.permissions_for(member.guild.me).send_messages and
                any(keyword in channel.name.lower() for keyword in ['general', 'chat', 'main', 'lobby'])):
                return channel
        
        # Fall back to any channel the bot can send messages in
        for channel in member.guild.text_channels:
            if channel.permissions_for(member.guild.me).send_messages:
                return channel
        
        return None

    async def handle_level_up(self, member: discord.Member, level_type: str, old_level: int, new_level: int, channel: Optional[discord.TextChannel] = None):
        """Handle level up events"""
        guild_config = self.get_guild_config(member.guild.id)
        
        # NEW: Check if we should remove level 0 role when leveling up from 0
        if (old_level == 0 and new_level > 0 and 
            guild_config.get("remove_level_0_role_on_levelup", True)):
            await self.remove_level_0_role(member)
        
        # Give rewards and handle removals
        await self.give_level_rewards(member, level_type, old_level, new_level)
        
        # Send level up embed
        if guild_config["level_up_embed"]["enabled"] and channel:
            await self.send_level_up_embed(member, level_type, new_level, channel)

    async def give_level_rewards(self, member: discord.Member, level_type: str, old_level: int, new_level: int):
        """Give role rewards for reaching a level and remove temporary rewards from previous levels"""
        guild_config = self.get_guild_config(member.guild.id)
        rewards = guild_config["rewards"][level_type]
        
        # Remove temporary rewards from previous levels
        roles_to_remove = []
        for prev_level in range(old_level + 1, new_level):  # Levels between old and new
            prev_level_str = str(prev_level)
            if prev_level_str in rewards:
                for reward in rewards[prev_level_str]:
                    if not reward.get("permanent", True):  # Remove non-permanent rewards
                        role = member.guild.get_role(reward["role_id"])
                        if role and role in member.roles:
                            roles_to_remove.append(role)
        
        # Also remove temporary rewards from all previous levels if they exist
        for prev_level in range(1, new_level):
            prev_level_str = str(prev_level)
            if prev_level_str in rewards:
                for reward in rewards[prev_level_str]:
                    if not reward.get("permanent", True):  # Remove non-permanent rewards
                        role = member.guild.get_role(reward["role_id"])
                        if role and role in member.roles and role not in roles_to_remove:
                            roles_to_remove.append(role)
        
        # Remove temporary roles
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason=f"Temporary rewards removed after reaching level {new_level} {level_type}")
                
                role_names = ", ".join([role.name for role in roles_to_remove])
                await self.log_levels_action(
                    "temporary_rewards_removed", member.guild, member,
                    f"Level {new_level} {level_type}: Removed temporary rewards: {role_names}"
                )
            except discord.Forbidden:
                await self.log_levels_action(
                    "reward_removal_failed", member.guild, member,
                    f"No permission to remove temporary rewards for level {new_level} {level_type}"
                )
        
        # Add new level rewards
        level_str = str(new_level)
        if level_str in rewards:
            roles_to_add = []
            for reward in rewards[level_str]:
                role = member.guild.get_role(reward["role_id"])
                if role and role not in member.roles:
                    roles_to_add.append(role)
            
            if roles_to_add:
                try:
                    await member.add_roles(*roles_to_add, reason=f"Level {new_level} {level_type} reward")
                    
                    role_names = ", ".join([role.name for role in roles_to_add])
                    await self.log_levels_action(
                        "reward_given", member.guild, member,
                        f"Level {new_level} {level_type} rewards: {role_names}"
                    )
                except discord.Forbidden:
                    await self.log_levels_action(
                        "reward_failed", member.guild, member,
                        f"No permission to give level {new_level} {level_type} rewards"
                    )

    async def send_level_up_embed(self, member: discord.Member, level_type: str, level: int, channel: discord.TextChannel):
        """Send level up embed in the specified channel"""
        guild_config = self.get_guild_config(member.guild.id)
        embed_config = guild_config["level_up_embed"]
        
        # Create embed
        title = embed_config["title"]
        description = embed_config["description"].format(
            user=member.mention,
            level=level,
            type=level_type.title()
        )
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=embed_config["color"],
            timestamp=datetime.utcnow()
        )
        
        # Set thumbnail
        if embed_config["thumbnail"] == "user_avatar":
            embed.set_thumbnail(url=member.display_avatar.url)
        elif embed_config["thumbnail"] == "guild_icon":
            embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        
        # Add level info
        user_data = self.get_user_data(member.guild.id, member.id)
        current_xp = user_data[f"{level_type}_xp"]
        next_level_xp = self.calculate_xp_for_next_level(level)
        current_level_xp = self.calculate_xp_for_level(level)
        progress_xp = current_xp - current_level_xp
        needed_xp = next_level_xp - current_level_xp
        
        embed.add_field(
            name="Level Progress",
            value=f"**Level:** {level}\n**XP:** {current_xp:,}\n**Progress:** {progress_xp}/{needed_xp}",
            inline=True
        )
        
        # Show rewards if enabled
        if embed_config["show_rewards"]:
            rewards = guild_config["rewards"][level_type].get(str(level), [])
            if rewards:
                reward_lines = []
                for reward in rewards:
                    role = member.guild.get_role(reward["role_id"])
                    if role:
                        permanence = "🔒 Permanent" if reward.get("permanent", True) else "⏰ Temporary"
                        reward_lines.append(f"{role.mention} ({permanence})")
                
                if reward_lines:
                    embed.add_field(
                        name="🎁 Rewards Unlocked",
                        value="\n".join(reward_lines),
                        inline=True
                    )
        
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    @tasks.loop(minutes=5)
    async def save_data_task(self):
        """Periodically save data"""
        self.save_levels_db()

    @save_data_task.before_loop
    async def before_save_data_task(self):
        """Wait until bot is ready"""
        await self.bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def check_missed_joins_task(self):
        """Periodically check for missed level 0 role assignments"""
        for guild in self.bot.guilds:
            if self.is_leveling_enabled(guild.id):
                assigned_count = await self.check_and_assign_missing_level_0_roles(guild)
                if assigned_count > 0:
                    await self.log_levels_action(
                        "periodic_level_0_check",
                        guild,
                        None,
                        f"Assigned level 0 role to {assigned_count} members during periodic check"
                    )

    @check_missed_joins_task.before_loop
    async def before_check_missed_joins_task(self):
        """Wait until bot is ready"""
        await self.bot.wait_until_ready()
        # Wait an additional 30 seconds to ensure everything is loaded
        await asyncio.sleep(30)

    # ==================== EVENT LISTENERS ====================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle new member joins - assign level 0 role"""
        if member.bot:
            return
        
        # Check if leveling is enabled
        if not self.is_leveling_enabled(member.guild.id):
            return
        
        # Assign level 0 role
        await self.assign_level_0_role(member)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle text XP gain"""
        if not message.guild or message.author.bot:
            return
        
        # Check if message has content
        if not message.content or len(message.content.strip()) < 3:
            return
        
        await self.add_text_xp(message.author, message.channel)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Handle voice XP gain"""
        if member.bot:
            return
        
        # Check if leveling is enabled
        if not self.is_leveling_enabled(member.guild.id):
            return
        
        now = datetime.utcnow()
        
        # User joined voice
        if not before.channel and after.channel:
            if not after.self_mute and not after.self_deaf:
                self.voice_sessions[member.id] = {
                    'start_time': now,
                    'channel': after.channel
                }
        
        # User left voice
        elif before.channel and not after.channel:
            if member.id in self.voice_sessions:
                session = self.voice_sessions.pop(member.id)
                start_time = session['start_time']
                duration = (now - start_time).total_seconds() / 60  # Convert to minutes
                
                if duration >= 1:  # At least 1 minute
                    await self.add_voice_xp(member, duration)
        
        # User changed state (mute/unmute, deaf/undeaf)
        elif before.channel and after.channel:
            # If user was in session and became muted/deafened
            if (member.id in self.voice_sessions and 
                (after.self_mute or after.self_deaf) and 
                not (before.self_mute or before.self_deaf)):
                
                session = self.voice_sessions.pop(member.id)
                start_time = session['start_time']
                duration = (now - start_time).total_seconds() / 60
                
                if duration >= 1:
                    await self.add_voice_xp(member, duration)
            
            # If user unmuted/undeafened
            elif (member.id not in self.voice_sessions and 
                  not (after.self_mute or after.self_deaf) and 
                  (before.self_mute or before.self_deaf)):
                
                self.voice_sessions[member.id] = {
                    'start_time': now,
                    'channel': after.channel
                }
                
    @commands.Cog.listener()
    async def on_ready(self):
        # On ready, check for missing level 0 roles (redundant with assign_level_0_roles_on_startup, but safe)
        await self.assign_level_0_roles_on_startup()

    # ==================== SLASH COMMAND GROUPS ====================

    level_group = app_commands.Group(name="level", description="Leveling system commands")

    @level_group.command(name="toggle", description="Toggle the leveling system on/off (Admin only)")
    @app_commands.describe(enabled="Whether to enable or disable the leveling system")
    async def toggle_leveling(self, interaction: discord.Interaction, enabled: bool):
        """Toggle leveling system"""
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to toggle the leveling system!", 
                ephemeral=True
            )
            return
        
        current_status = self.is_leveling_enabled(interaction.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await interaction.response.send_message(
                f"ℹ️ The leveling system is already {status_text} in this server!", 
                ephemeral=True
            )
            return
        
        self.set_leveling_enabled(interaction.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_levels_action(
            "leveling_toggled", 
            interaction.guild, 
            interaction.user,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Leveling System {status_text.title()}",
            description=f"The leveling system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="status", description="Check if the leveling system is enabled")
    async def leveling_status(self, interaction: discord.Interaction):
        """Check leveling status"""
        enabled = self.is_leveling_enabled(interaction.guild.id)
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        # Get level 0 role info
        guild_config = self.get_guild_config(interaction.guild.id)
        level_0_role_id = guild_config.get("level_0_role")
        remove_on_levelup = guild_config.get("remove_level_0_role_on_levelup", True)
        
        embed = discord.Embed(
            title=f"{status_emoji} Leveling System Status",
            description=f"The leveling system is currently **{status_text}** in this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        if level_0_role_id:
            role = interaction.guild.get_role(level_0_role_id)
            if role:
                removal_text = "✅ Removed when leveling up" if remove_on_levelup else "❌ Not removed when leveling up"
                embed.add_field(
                    name="🎯 Level 0 Auto-Role",
                    value=f"{role.mention} - Automatically assigned to new members\n{removal_text}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="⚠️ Level 0 Auto-Role",
                    value="Configured but role not found! Please update the configuration.",
                    inline=False
                )
        else:
            embed.add_field(
                name="🎯 Level 0 Auto-Role",
                value="Not configured - Use `/level setlevel0role` to set up",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="setlevel0role", description="Set the auto-role for new members (Admin only)")
    @app_commands.describe(role="Role to automatically assign to new members")
    async def set_level_0_role(self, interaction: discord.Interaction, role: discord.Role):
        """Set level 0 auto-role"""
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to configure level 0 role!", 
                ephemeral=True
            )
            return
        
        if role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(
                "❌ You cannot set a level 0 role higher than your highest role!", 
                ephemeral=True
            )
            return
        
        if not interaction.guild.me.top_role > role:
            await interaction.response.send_message(
                "❌ I cannot assign this role as it's higher than or equal to my highest role!", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        guild_config = self.get_guild_config(interaction.guild.id)
        guild_config["level_0_role"] = role.id
        self.save_config()
        
        await self.log_levels_action(
            "level_0_role_set",
            interaction.guild,
            interaction.user,
            f"Set level 0 role to: {role.name}"
        )
        
        # Check for members who need the role assigned
        assigned_count = await self.check_and_assign_missing_level_0_roles(interaction.guild)
        
        embed = discord.Embed(
            title="✅ Level 0 Auto-Role Set",
            description=f"**{role.mention}** will now be automatically assigned to new members!",
            color=0x00ff00
        )
        
        if assigned_count > 0:
            embed.add_field(
                name="🔄 Retroactive Assignment",
                value=f"Assigned the role to **{assigned_count}** existing level 0 members who didn't have it.",
                inline=False
            )
        
        removal_status = guild_config.get("remove_level_0_role_on_levelup", True)
        removal_text = "✅ Will be removed" if removal_status else "❌ Will not be removed"
        
        embed.add_field(
            name="ℹ️ How it works",
            value=f"• New members get this role when they join\n• Existing level 0 members get it during periodic checks\n• Bot checks for missed assignments every 6 hours\n• **Level up behavior:** {removal_text} when users level up from 0",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)

    @level_group.command(name="removelevel0role", description="Remove the auto-role for new members (Admin only)")
    async def remove_level_0_role_command(self, interaction: discord.Interaction):
        """Remove level 0 auto-role"""
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to configure level 0 role!", 
                ephemeral=True
            )
            return
        
        guild_config = self.get_guild_config(interaction.guild.id)
        current_role_id = guild_config.get("level_0_role")
        
        if not current_role_id:
            await interaction.response.send_message(
                "ℹ️ No level 0 auto-role is currently configured!", 
                ephemeral=True
            )
            return
        
        current_role = interaction.guild.get_role(current_role_id)
        role_name = current_role.name if current_role else f"Unknown Role ({current_role_id})"
        
        guild_config["level_0_role"] = None
        self.save_config()
        
        await self.log_levels_action(
            "level_0_role_removed",
            interaction.guild,
            interaction.user,
            f"Removed level 0 role: {role_name}"
        )
        
        embed = discord.Embed(
            title="✅ Level 0 Auto-Role Removed",
            description=f"**{role_name}** will no longer be automatically assigned to new members.",
            color=0xff9900
        )
        
        embed.add_field(
            name="ℹ️ Note",
            value="This doesn't remove the role from existing members. If you want to remove it from everyone, you'll need to do that manually.",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="setlevel0removal", description="Toggle removing level 0 role when leveling up (Admin only)")
    @app_commands.describe(enabled="Whether to remove level 0 role when users level up from 0")
    async def set_level_0_removal(self, interaction: discord.Interaction, enabled: bool):
        """Set level 0 role removal on level up"""
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to configure level 0 role settings!", 
                ephemeral=True
            )
            return
        
        guild_config = self.get_guild_config(interaction.guild.id)
        current_setting = guild_config.get("remove_level_0_role_on_levelup", True)
        
        if current_setting == enabled:
            status_text = "enabled" if enabled else "disabled"
            await interaction.response.send_message(
                f"ℹ️ Level 0 role removal on level up is already **{status_text}**!", 
                ephemeral=True
            )
            return
        
        guild_config["remove_level_0_role_on_levelup"] = enabled
        self.save_config()
        
        await self.log_levels_action(
            "level_0_removal_toggled",
            interaction.guild,
            interaction.user,
            f"Level 0 role removal on level up: {'enabled' if enabled else 'disabled'}"
        )
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        embed = discord.Embed(
            title=f"{status_emoji} Level 0 Role Removal {status_text.title()}",
            description=f"Level 0 role removal when leveling up has been **{status_text}**.",
            color=0x00ff00 if enabled else 0xff9900
        )
        
        level_0_role_id = guild_config.get("level_0_role")
        if level_0_role_id:
            role = interaction.guild.get_role(level_0_role_id)
            if role:
                if enabled:
                    embed.add_field(
                        name="✅ What this means",
                        value=f"When users level up from 0 to 1 (in either text or voice), **{role.mention}** will be automatically removed from them.",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="❌ What this means",
                        value=f"Users will keep **{role.mention}** even after leveling up from 0. The role will only be removed manually or through other means.",
                        inline=False
                    )
        else:
            embed.add_field(
                name="ℹ️ Note",
                value="No level 0 role is currently configured. Use `/level setlevel0role` to set one up first.",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="checklevel0roles", description="Check and assign missing level 0 roles (Admin only)")
    async def check_level_0_roles(self, interaction: discord.Interaction):
        """Manually check and assign missing level 0 roles"""
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to run this command!", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        guild_config = self.get_guild_config(interaction.guild.id)
        level_0_role_id = guild_config.get("level_0_role")
        
        if not level_0_role_id:
            await interaction.followup.send("❌ No level 0 auto-role is configured!")
            return
        
        role = interaction.guild.get_role(level_0_role_id)
        if not role:
            await interaction.followup.send("❌ The configured level 0 role was not found!")
            return
        
        assigned_count = await self.check_and_assign_missing_level_0_roles(interaction.guild)
        
        embed = discord.Embed(
            title="🔍 Level 0 Role Check Complete",
            color=0x00ff00
        )
        
        if assigned_count > 0:
            embed.description = f"✅ Assigned **{role.mention}** to **{assigned_count}** level 0 members who were missing it."
        else:
            embed.description = f"✅ All level 0 members already have the **{role.mention}** role."
        
        embed.add_field(
            name="ℹ️ Note",
            value="This command only assigns the role to members who are actually at level 0 in both text and voice chat.",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)

    @level_group.command(name="rank", description="Show your or another user's rank")
    @app_commands.describe(
        user="User to check rank for (defaults to yourself)",
        level_type="Type of level to show"
    )
    @app_commands.choices(level_type=[
        app_commands.Choice(name="Both", value="both"),
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Voice", value="voice")
    ])
    async def rank_slash(self, interaction: discord.Interaction, 
                        user: discord.Member = None,
                        level_type: app_commands.Choice[str] = None):
        """Show user's rank"""
        if not await self.leveling_check(interaction):
            return
            
        target_user = user or interaction.user
        type_filter = level_type.value if level_type else "both"
        
        user_data = self.get_user_data(interaction.guild.id, target_user.id)
        
        embed = discord.Embed(
            title=f"📊 {target_user.display_name}'s Rank",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        if type_filter in ["both", "text"]:
            text_level = user_data["text_level"]
            text_xp = user_data["text_xp"]
            next_level_xp = self.calculate_xp_for_next_level(text_level)
            current_level_xp = self.calculate_xp_for_level(text_level)
            progress_xp = text_xp - current_level_xp
            needed_xp = next_level_xp - current_level_xp
            
            # Calculate rank
            guild_data = self.levels_db.get(str(interaction.guild.id), {})
            text_ranks = sorted(
                [(uid, data["text_xp"]) for uid, data in guild_data.items()],
                key=lambda x: x[1], reverse=True
            )
            text_rank = next((i + 1 for i, (uid, _) in enumerate(text_ranks) if uid == str(target_user.id)), "N/A")
            
            progress_bar = self.create_progress_bar(progress_xp, needed_xp)
            
            embed.add_field(
                name="💬 Text Chat",
                value=f"**Level:** {text_level}\n"
                      f"**Rank:** #{text_rank}\n"
                      f"**XP:** {text_xp:,}\n"
                      f"**Progress:** {progress_bar}\n"
                      f"`{progress_xp}/{needed_xp} XP to level {text_level + 1}`",
                inline=False
            )
        
        if type_filter in ["both", "voice"]:
            voice_level = user_data["voice_level"]
            voice_xp = user_data["voice_xp"]
            voice_minutes = user_data["total_voice_minutes"]
            next_level_xp = self.calculate_xp_for_next_level(voice_level)
            current_level_xp = self.calculate_xp_for_level(voice_level)
            progress_xp = voice_xp - current_level_xp
            needed_xp = next_level_xp - current_level_xp
            
            # Calculate rank
            guild_data = self.levels_db.get(str(interaction.guild.id), {})
            voice_ranks = sorted(
                [(uid, data["voice_xp"]) for uid, data in guild_data.items()],
                key=lambda x: x[1], reverse=True
            )
            voice_rank = next((i + 1 for i, (uid, _) in enumerate(voice_ranks) if uid == str(target_user.id)), "N/A")
            
            progress_bar = self.create_progress_bar(progress_xp, needed_xp)
            
            hours = int(voice_minutes // 60)
            minutes = int(voice_minutes % 60)
            
            embed.add_field(
                name="🎤 Voice Chat",
                value=f"**Level:** {voice_level}\n"
                      f"**Rank:** #{voice_rank}\n"
                      f"**XP:** {voice_xp:,}\n"
                      f"**Time:** {hours}h {minutes}m\n"
                      f"**Progress:** {progress_bar}\n"
                      f"`{progress_xp}/{needed_xp} XP to level {voice_level + 1}`",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)

    def create_progress_bar(self, current: int, total: int, length: int = 10) -> str:
        """Create a progress bar"""
        if total == 0:
            filled = length
        else:
            filled = int((current / total) * length)
        
        bar = "█" * filled + "░" * (length - filled)
        return f"{bar} {(current/total*100):.1f}%" if total > 0 else f"{bar} 100.0%"

    @level_group.command(name="leaderboard", description="Show the server leaderboard")
    @app_commands.describe(
        level_type="Type of leaderboard to show",
        page="Page number (10 users per page)"
    )
    @app_commands.choices(level_type=[
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Voice", value="voice"),
        app_commands.Choice(name="Combined", value="combined")
    ])
    async def leaderboard_slash(self, interaction: discord.Interaction,
                               level_type: app_commands.Choice[str] = None,
                               page: int = 1):
        """Show server leaderboard"""
        if not await self.leveling_check(interaction):
            return
            
        await interaction.response.defer()
        
        type_filter = level_type.value if level_type else "combined"
        page = max(1, page)
        
        guild_data = self.levels_db.get(str(interaction.guild.id), {})
        if not guild_data:
            await interaction.followup.send("No level data found for this server!")
            return
        
        # Sort users based on type
        if type_filter == "text":
            sorted_users = sorted(
                guild_data.items(),
                key=lambda x: x[1]["text_xp"],
                reverse=True
            )
            title = "💬 Text Chat Leaderboard"
        elif type_filter == "voice":
            sorted_users = sorted(
                guild_data.items(),
                key=lambda x: x[1]["voice_xp"],
                reverse=True
            )
            title = "🎤 Voice Chat Leaderboard"
        else:  # combined
            sorted_users = sorted(
                guild_data.items(),
                key=lambda x: x[1]["text_xp"] + x[1]["voice_xp"],
                reverse=True
            )
            title = "🏆 Combined Leaderboard"
        
        # Pagination
        per_page = 10
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_users = sorted_users[start_idx:end_idx]
        
        if not page_users:
            await interaction.followup.send("No users found on this page!")
            return
        
        embed = discord.Embed(title=title, color=0x00ff00)
        
        description_lines = []
        for i, (user_id, data) in enumerate(page_users, start=start_idx + 1):
            user = self.bot.get_user(int(user_id))
            user_name = user.display_name if user else f"Unknown User ({user_id})"
            
            if type_filter == "text":
                level = data["text_level"]
                xp = data["text_xp"]
            elif type_filter == "voice":
                level = data["voice_level"]
                xp = data["voice_xp"]
                minutes = data["total_voice_minutes"]
                hours = int(minutes // 60)
                mins = int(minutes % 60)
                user_name += f" ({hours}h {mins}m)"
            else:  # combined
                level = max(data["text_level"], data["voice_level"])
                xp = data["text_xp"] + data["voice_xp"]
            
            rank_emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"**{i}.**"
            description_lines.append(f"{rank_emoji} {user_name}\n`Level {level} • {xp:,} XP`")
        
        embed.description = "\n\n".join(description_lines)
        
        # Add pagination info
        total_pages = math.ceil(len(sorted_users) / per_page)
        embed.set_footer(text=f"Page {page}/{total_pages} • {len(sorted_users)} total users")
        
        await interaction.followup.send(embed=embed)

    @level_group.command(name="setreward", description="Set a role reward for reaching a level")
    @app_commands.describe(
        level="Level to set reward for",
        role="Role to give as reward",
        level_type="Type of level (text or voice)",
        permanent="Whether the reward should be permanent or removed when user levels up further"
    )
    @app_commands.choices(level_type=[
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Voice", value="voice")
    ])
    async def setreward_slash(self, interaction: discord.Interaction,
                             level: int,
                             role: discord.Role,
                             level_type: app_commands.Choice[str],
                             permanent: bool = True):
        """Set level reward"""
        if not await self.leveling_check(interaction):
            return
            
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to manage level rewards!", ephemeral=True)
            return
        
        if level < 1 or level > 100:
            await interaction.response.send_message("Level must be between 1 and 100!", ephemeral=True)
            return
        
        if role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message("You cannot set rewards for roles higher than your highest role!", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(interaction.guild.id)
        rewards = guild_config["rewards"][level_type.value]
        
        level_str = str(level)
        if level_str not in rewards:
            rewards[level_str] = []
        
        # Check if role already exists as a reward
        for existing_reward in rewards[level_str]:
            if existing_reward["role_id"] == role.id:
                await interaction.response.send_message(f"Role {role.mention} is already a reward for level {level}!", ephemeral=True)
                return
        
        # Add new reward
        rewards[level_str].append({
            "role_id": role.id,
            "permanent": permanent
        })
        self.save_config()
        
        await self.log_levels_action(
            "reward_set", interaction.guild, interaction.user,
            f"Level {level} {level_type.value} reward: {role.name} ({'permanent' if permanent else 'temporary'})"
        )
        
        permanence_text = "**permanent**" if permanent else "**temporary**"
        embed = discord.Embed(
            title="✅ Reward Set",
            description=f"Role {role.mention} will now be given at **level {level}** for **{level_type.value}** chat!\n\n**Type:** {permanence_text}",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="removereward", description="Remove a role reward from a level")
    @app_commands.describe(
        level="Level to remove reward from",
        role="Role to remove as reward",
        level_type="Type of level (text or voice)"
    )
    @app_commands.choices(level_type=[
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Voice", value="voice")
    ])
    async def removereward_slash(self, interaction: discord.Interaction,
                                level: int,
                                role: discord.Role,
                                level_type: app_commands.Choice[str]):
        """Remove level reward"""
        if not await self.leveling_check(interaction):
            return
            
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to manage level rewards!", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(interaction.guild.id)
        rewards = guild_config["rewards"][level_type.value]
        
        level_str = str(level)
        if level_str in rewards:
            # Find and remove the reward
            for i, reward in enumerate(rewards[level_str]):
                if reward["role_id"] == role.id:
                    rewards[level_str].pop(i)
                    break
            else:
                await interaction.response.send_message(f"Role {role.mention} is not a reward for level {level}!", ephemeral=True)
                return
            
            # Remove empty list
            if not rewards[level_str]:
                del rewards[level_str]
            
            self.save_config()
            
            await self.log_levels_action(
                "reward_removed", interaction.guild, interaction.user,
                f"Level {level} {level_type.value} reward removed: {role.name}"
            )
            
            embed = discord.Embed(
                title="✅ Reward Removed",
                description=f"Role {role.mention} is no longer a reward for **level {level}** in **{level_type.value}** chat!",
                color=0xff9900
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f"Role {role.mention} is not a reward for level {level}!", ephemeral=True)

    @level_group.command(name="rewards", description="View all level rewards")
    @app_commands.describe(
        level_type="Type of level rewards to show",
        level="Specific level to show rewards for (optional)"
    )
    @app_commands.choices(level_type=[
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Voice", value="voice"),
        app_commands.Choice(name="Both", value="both")
    ])
    async def rewards_slash(self, interaction: discord.Interaction,
                           level_type: app_commands.Choice[str] = None,
                           level: int = None):
        """View level rewards"""
        if not await self.leveling_check(interaction):
            return
            
        await interaction.response.defer()
        
        guild_config = self.get_guild_config(interaction.guild.id)
        type_filter = level_type.value if level_type else "both"
        
        embed = discord.Embed(title="🎁 Level Rewards", color=0x00ff00)
        
        types_to_show = ["text", "voice"] if type_filter == "both" else [type_filter]
        
        for ltype in types_to_show:
            rewards = guild_config["rewards"][ltype]
            
            if level:
                # Show specific level
                level_str = str(level)
                if level_str in rewards:
                    reward_lines = []
                    for reward in rewards[level_str]:
                        role = interaction.guild.get_role(reward["role_id"])
                        if role:
                            permanence = "🔒" if reward.get("permanent", True) else "⏰"
                            reward_lines.append(f"{permanence} {role.mention}")
                    
                    if reward_lines:
                        embed.add_field(
                            name=f"{ltype.title()} Level {level}",
                            value="\n".join(reward_lines),
                            inline=False
                        )
            else:
                # Show all levels
                if rewards:
                    reward_text = []
                    for level_str in sorted(rewards.keys(), key=int):
                        level_rewards = []
                        for reward in rewards[level_str]:
                            role = interaction.guild.get_role(reward["role_id"])
                            if role:
                                permanence = "🔒" if reward.get("permanent", True) else "⏰"
                                level_rewards.append(f"{permanence} {role.name}")
                        
                        if level_rewards:
                            reward_text.append(f"**Level {level_str}:** {', '.join(level_rewards)}")
                    
                    if reward_text:
                        # Split into chunks if too long
                        chunk_size = 1024
                        text = "\n".join(reward_text)
                        if len(text) <= chunk_size:
                            embed.add_field(
                                name=f"{ltype.title()} Chat Rewards",
                                value=text,
                                inline=False
                            )
                        else:
                            # Split into multiple fields
                            chunks = []
                            current_chunk = ""
                            for line in reward_text:
                                if len(current_chunk + line + "\n") <= chunk_size:
                                    current_chunk += line + "\n"
                                else:
                                    if current_chunk:
                                        chunks.append(current_chunk.strip())
                                    current_chunk = line + "\n"
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            
                            for i, chunk in enumerate(chunks):
                                field_name = f"{ltype.title()} Chat Rewards" + (f" (Part {i+1})" if len(chunks) > 1 else "")
                                embed.add_field(name=field_name, value=chunk, inline=False)
        
        if not embed.fields:
            embed.description = "No rewards configured."
        else:
            embed.set_footer(text="🔒 = Permanent reward | ⏰ = Temporary reward (removed when leveling up)")
        
        await interaction.followup.send(embed=embed)

    @level_group.command(name="set", description="Set a user's level and update their roles")
    @app_commands.describe(
        user="User to set level for",
        level="Level to set",
        level_type="Type of level to set"
    )
    @app_commands.choices(level_type=[
        app_commands.Choice(name="Text", value="text"),
        app_commands.Choice(name="Voice", value="voice")
    ])
    async def set_level_slash(self, interaction: discord.Interaction,
                             user: discord.Member,
                             level: int,
                             level_type: app_commands.Choice[str]):
        """Set user's level and update their roles automatically"""
        if not await self.leveling_check(interaction):
            return
            
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to set user levels!", ephemeral=True)
            return
        
        if level < 0 or level > 1000:
            await interaction.response.send_message("Level must be between 0 and 1000!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        user_data = self.get_user_data(interaction.guild.id, user.id)
        old_level = user_data[f"{level_type.value}_level"]
        
        # Calculate XP for the level
        new_xp = self.calculate_xp_for_level(level)
        user_data[f"{level_type.value}_xp"] = new_xp
        user_data[f"{level_type.value}_level"] = level
        
        self.save_levels_db()
        
        # Update user's roles based on new level
        role_changes = await self.update_user_roles_for_level(user, level_type.value, level)
        
        await self.log_levels_action(
            "level_set", interaction.guild, interaction.user,
            f"Set {user.name}'s {level_type.value} level from {old_level} to {level}"
        )
        
        # Create response embed
        embed = discord.Embed(
            title="✅ Level Set",
            description=f"Set {user.mention}'s **{level_type.value}** level to **{level}** (was {old_level})",
            color=0x00ff00
        )
        
        # Add role change information
        if role_changes["added"] or role_changes["removed"]:
            role_info = []
            
            if role_changes["added"]:
                added_mentions = [role.mention for role in role_changes["added"]]
                role_info.append(f"**Added:** {', '.join(added_mentions)}")
            
            if role_changes["removed"]:
                removed_mentions = [role.mention for role in role_changes["removed"]]
                role_info.append(f"**Removed:** {', '.join(removed_mentions)}")
            
            embed.add_field(
                name="🎭 Role Changes",
                value="\n".join(role_info),
                inline=False
            )
        else:
            embed.add_field(
                name="🎭 Role Changes",
                value="No role changes were needed",
                inline=False
            )
        
        # Add current level info
        current_xp = user_data[f"{level_type.value}_xp"]
        next_level_xp = self.calculate_xp_for_next_level(level)
        current_level_xp = self.calculate_xp_for_level(level)
        progress_xp = current_xp - current_level_xp
        needed_xp = next_level_xp - current_level_xp
        
        embed.add_field(
            name="📊 Level Info",
            value=f"**XP:** {current_xp:,}\n**Next Level:** {progress_xp}/{needed_xp} XP",
            inline=True
        )
        
        await interaction.followup.send(embed=embed)

    @level_group.command(name="embedtoggle", description="Toggle level up embeds")
    async def toggle_embeds_slash(self, interaction: discord.Interaction):
        """Toggle level up embeds"""
        if not await self.leveling_check(interaction):
            return
            
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to configure level embeds!", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(interaction.guild.id)
        current_state = guild_config["level_up_embed"]["enabled"]
        guild_config["level_up_embed"]["enabled"] = not current_state
        
        self.save_config()
        
        status = "enabled" if not current_state else "disabled"
        embed = discord.Embed(
            title="⚙️ Level Up Embeds",
            description=f"Level up embeds have been **{status}**!",
            color=0x00ff00 if not current_state else 0xff9900
        )
        await interaction.response.send_message(embed=embed)

    @level_group.command(name="config", description="Configure level up embed settings")
    @app_commands.describe(
        title="Embed title",
        description="Embed description (use {user}, {level}, {type} placeholders)",
        color="Embed color (hex)",
        fallback_channel="Fallback channel for voice level ups",
        show_rewards="Show rewards in embed"
    )
    async def config_embeds_slash(self, interaction: discord.Interaction,
                                 title: str = None,
                                 description: str = None,
                                 color: str = None,
                                 fallback_channel: discord.TextChannel = None,
                                 show_rewards: bool = None):
        """Configure embed settings"""
        if not await self.leveling_check(interaction):
            return
            
        if not self.has_levels_admin_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to configure level embeds!", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(interaction.guild.id)
        embed_config = guild_config["level_up_embed"]
        changes = []
        
        if title:
            embed_config["title"] = title
            changes.append(f"Title: {title}")
        
        if description:
            embed_config["description"] = description
            changes.append(f"Description: {description}")
        
        if color:
            try:
                if color.startswith("#"):
                    color = color[1:]
                color_int = int(color, 16)
                embed_config["color"] = color_int
                changes.append(f"Color: #{color}")
            except ValueError:
                await interaction.response.send_message("Invalid color format! Use hex format like #ff0000", ephemeral=True)
                return
        
        if fallback_channel:
            embed_config["fallback_channel"] = fallback_channel.id
            changes.append(f"Fallback channel: {fallback_channel.mention}")
        
        if show_rewards is not None:
            embed_config["show_rewards"] = show_rewards
            changes.append(f"Show rewards: {show_rewards}")
        
        if changes:
            self.save_config()
            
            embed = discord.Embed(
                title="⚙️ Embed Configuration Updated",
                description="\n".join(changes),
                color=0x00ff00
            )
            await interaction.response.send_message(embed=embed)
        else:
            # Show current config
            embed = discord.Embed(title="⚙️ Current Embed Configuration", color=0x0099ff)
            embed.add_field(name="Title", value=embed_config["title"], inline=False)
            embed.add_field(name="Description", value=embed_config["description"], inline=False)
            embed.add_field(name="Color", value=f"#{embed_config['color']:06x}", inline=True)
            embed.add_field(name="Enabled", value=embed_config["enabled"], inline=True)
            embed.add_field(name="Show Rewards", value=embed_config["show_rewards"], inline=True)
            
            if embed_config["fallback_channel"]:
                ch = interaction.guild.get_channel(embed_config["fallback_channel"])
                embed.add_field(name="Fallback Channel", value=ch.mention if ch else "Unknown", inline=True)
            
            embed.add_field(
                name="ℹ️ Behavior",
                value="• Text level ups: Sent in the channel where the message was sent\n• Voice level ups: Sent in fallback channel or any suitable channel\n• Set command: Automatically updates user roles",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed)

    # ==================== PREFIX COMMANDS ====================

    @commands.group(name="level", aliases=['lvl'], invoke_without_command=True)
    async def level(self, ctx):
        """Leveling system commands"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
            
        embed = discord.Embed(title="📊 Leveling System", color=0x00ff00)
        embed.add_field(
            name="User Commands",
            value="rank, leaderboard, rewards",
            inline=False
        )
        embed.add_field(
            name="Admin Commands",
            value="toggle, setreward, removereward, set, embedtoggle, config, setlevel0role, removelevel0role, setlevel0removal, checklevel0roles",
            inline=False
        )
        embed.add_field(
            name="Slash Commands",
            value="Use `/level` for organized slash commands!",
            inline=False
        )
        embed.add_field(
            name="Features",
            value="🔒 **Permanent rewards** - Keep forever\n⏰ **Temporary rewards** - Removed when leveling up\n📍 **Smart embeds** - Sent in message channel\n🎭 **Auto role updates** - Set command updates roles\n⚙️ **Toggle system** - Enable/disable per server\n🎯 **Level 0 auto-role** - Assigned to new members\n🚮 **Smart role removal** - Level 0 role removed when leveling up",
            inline=False
        )
        await ctx.send(embed=embed)

    @level.command(name="toggle")
    async def toggle_leveling_prefix(self, ctx, enabled: bool = None):
        """Toggle leveling system (Admin only)"""
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to toggle the leveling system!")
            return
        
        if enabled is None:
            current_status = self.is_leveling_enabled(ctx.guild.id)
            status_text = "enabled" if current_status else "disabled"
            status_emoji = "✅" if current_status else "❌"
            
            embed = discord.Embed(
                title=f"{status_emoji} Leveling System Status",
                description=f"The leveling system is currently **{status_text}** in this server.",
                color=0x00ff00 if current_status else 0xff0000
            )
            await ctx.send(embed=embed)
            return
        
        current_status = self.is_leveling_enabled(ctx.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await ctx.send(f"ℹ️ The leveling system is already {status_text} in this server!")
            return
        
        self.set_leveling_enabled(ctx.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_levels_action(
            "leveling_toggled", 
            ctx.guild, 
            ctx.author,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Leveling System {status_text.title()}",
            description=f"The leveling system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await ctx.send(embed=embed)

    @level.command(name="status")
    async def status_prefix(self, ctx):
        """Check leveling status"""
        enabled = self.is_leveling_enabled(ctx.guild.id)
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        # Get level 0 role info
        guild_config = self.get_guild_config(ctx.guild.id)
        level_0_role_id = guild_config.get("level_0_role")
        remove_on_levelup = guild_config.get("remove_level_0_role_on_levelup", True)
        
        embed = discord.Embed(
            title=f"{status_emoji} Leveling System Status",
            description=f"The leveling system is currently **{status_text}** in this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        if level_0_role_id:
            role = ctx.guild.get_role(level_0_role_id)
            if role:
                removal_text = "✅ Removed when leveling up" if remove_on_levelup else "❌ Not removed when leveling up"
                embed.add_field(
                    name="🎯 Level 0 Auto-Role",
                    value=f"{role.mention} - Automatically assigned to new members\n{removal_text}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="⚠️ Level 0 Auto-Role",
                    value="Configured but role not found! Please update the configuration.",
                    inline=False
                )
        else:
            embed.add_field(
                name="🎯 Level 0 Auto-Role",
                value="Not configured - Use `!level setlevel0role` to set up",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @level.command(name="setlevel0role")
    async def set_level_0_role_prefix(self, ctx, role: discord.Role):
        """Set level 0 auto-role (Admin only)"""
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure level 0 role!")
            return
        
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send("❌ You cannot set a level 0 role higher than your highest role!")
            return
        
        if not ctx.guild.me.top_role > role:
            await ctx.send("❌ I cannot assign this role as it's higher than or equal to my highest role!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        guild_config["level_0_role"] = role.id
        self.save_config()
        
        await self.log_levels_action(
            "level_0_role_set",
            ctx.guild,
            ctx.author,
            f"Set level 0 role to: {role.name}"
        )
        
        # Check for members who need the role assigned
        assigned_count = await self.check_and_assign_missing_level_0_roles(ctx.guild)
        
        embed = discord.Embed(
            title="✅ Level 0 Auto-Role Set",
            description=f"**{role.mention}** will now be automatically assigned to new members!",
            color=0x00ff00
        )
        
        if assigned_count > 0:
            embed.add_field(
                name="🔄 Retroactive Assignment",
                value=f"Assigned the role to **{assigned_count}** existing level 0 members who didn't have it.",
                inline=False
            )
        
        removal_status = guild_config.get("remove_level_0_role_on_levelup", True)
        removal_text = "✅ Will be removed" if removal_status else "❌ Will not be removed"
        
        embed.add_field(
            name="ℹ️ How it works",
            value=f"• New members get this role when they join\n• Existing level 0 members get it during periodic checks\n• Bot checks for missed assignments every 6 hours\n• **Level up behavior:** {removal_text} when users level up from 0",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @level.command(name="removelevel0role")
    async def remove_level_0_role_prefix(self, ctx):
        """Remove level 0 auto-role (Admin only)"""
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure level 0 role!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        current_role_id = guild_config.get("level_0_role")
        
        if not current_role_id:
            await ctx.send("ℹ️ No level 0 auto-role is currently configured!")
            return
        
        current_role = ctx.guild.get_role(current_role_id)
        role_name = current_role.name if current_role else f"Unknown Role ({current_role_id})"
        
        guild_config["level_0_role"] = None
        self.save_config()
        
        await self.log_levels_action(
            "level_0_role_removed",
            ctx.guild,
            ctx.author,
            f"Removed level 0 role: {role_name}"
        )
        
        embed = discord.Embed(
            title="✅ Level 0 Auto-Role Removed",
            description=f"**{role_name}** will no longer be automatically assigned to new members.",
            color=0xff9900
        )
        
        embed.add_field(
            name="ℹ️ Note",
            value="This doesn't remove the role from existing members. If you want to remove it from everyone, you'll need to do that manually.",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @level.command(name="setlevel0removal")
    async def set_level_0_removal_prefix(self, ctx, enabled: bool):
        """Toggle removing level 0 role when leveling up (Admin only)"""
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure level 0 role settings!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        current_setting = guild_config.get("remove_level_0_role_on_levelup", True)
        
        if current_setting == enabled:
            status_text = "enabled" if enabled else "disabled"
            await ctx.send(f"ℹ️ Level 0 role removal on level up is already **{status_text}**!")
            return
        
        guild_config["remove_level_0_role_on_levelup"] = enabled
        self.save_config()
        
        await self.log_levels_action(
            "level_0_removal_toggled",
            ctx.guild,
            ctx.author,
            f"Level 0 role removal on level up: {'enabled' if enabled else 'disabled'}"
        )
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        embed = discord.Embed(
            title=f"{status_emoji} Level 0 Role Removal {status_text.title()}",
            description=f"Level 0 role removal when leveling up has been **{status_text}**.",
            color=0x00ff00 if enabled else 0xff9900
        )
        
        level_0_role_id = guild_config.get("level_0_role")
        if level_0_role_id:
            role = ctx.guild.get_role(level_0_role_id)
            if role:
                if enabled:
                    embed.add_field(
                        name="✅ What this means",
                        value=f"When users level up from 0 to 1 (in either text or voice), **{role.mention}** will be automatically removed from them.",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="❌ What this means",
                        value=f"Users will keep **{role.mention}** even after leveling up from 0. The role will only be removed manually or through other means.",
                        inline=False
                    )
        else:
            embed.add_field(
                name="ℹ️ Note",
                value="No level 0 role is currently configured. Use `!level setlevel0role` to set one up first.",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @level.command(name="checklevel0roles")
    async def check_level_0_roles_prefix(self, ctx):
        """Manually check and assign missing level 0 roles (Admin only)"""
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to run this command!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        level_0_role_id = guild_config.get("level_0_role")
        
        if not level_0_role_id:
            await ctx.send("❌ No level 0 auto-role is configured!")
            return
        
        role = ctx.guild.get_role(level_0_role_id)
        if not role:
            await ctx.send("❌ The configured level 0 role was not found!")
            return
        
        assigned_count = await self.check_and_assign_missing_level_0_roles(ctx.guild)
        
        embed = discord.Embed(
            title="🔍 Level 0 Role Check Complete",
            color=0x00ff00
        )
        
        if assigned_count > 0:
            embed.description = f"✅ Assigned **{role.mention}** to **{assigned_count}** level 0 members who were missing it."
        else:
            embed.description = f"✅ All level 0 members already have the **{role.mention}** role."
        
        embed.add_field(
            name="ℹ️ Note",
            value="This command only assigns the role to members who are actually at level 0 in both text and voice chat.",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @level.command(name="rank")
    async def rank_prefix(self, ctx, user: discord.Member = None, level_type: str = "both"):
        """Show user's rank"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        target_user = user or ctx.author
        type_filter = level_type.lower()
        
        if type_filter not in ["both", "text", "voice"]:
            await ctx.send("Invalid level type! Use `both`, `text`, or `voice`.")
            return
        
        user_data = self.get_user_data(ctx.guild.id, target_user.id)
        
        embed = discord.Embed(
            title=f"📊 {target_user.display_name}'s Rank",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        if type_filter in ["both", "text"]:
            text_level = user_data["text_level"]
            text_xp = user_data["text_xp"]
            next_level_xp = self.calculate_xp_for_next_level(text_level)
            current_level_xp = self.calculate_xp_for_level(text_level)
            progress_xp = text_xp - current_level_xp
            needed_xp = next_level_xp - current_level_xp
            
            # Calculate rank
            guild_data = self.levels_db.get(str(ctx.guild.id), {})
            text_ranks = sorted(
                [(uid, data["text_xp"]) for uid, data in guild_data.items()],
                key=lambda x: x[1], reverse=True
            )
            text_rank = next((i + 1 for i, (uid, _) in enumerate(text_ranks) if uid == str(target_user.id)), "N/A")
            
            progress_bar = self.create_progress_bar(progress_xp, needed_xp)
            
            embed.add_field(
                name="💬 Text Chat",
                value=f"**Level:** {text_level}\n"
                      f"**Rank:** #{text_rank}\n"
                      f"**XP:** {text_xp:,}\n"
                      f"**Progress:** {progress_bar}\n"
                      f"`{progress_xp}/{needed_xp} XP to level {text_level + 1}`",
                inline=False
            )
        
        if type_filter in ["both", "voice"]:
            voice_level = user_data["voice_level"]
            voice_xp = user_data["voice_xp"]
            voice_minutes = user_data["total_voice_minutes"]
            next_level_xp = self.calculate_xp_for_next_level(voice_level)
            current_level_xp = self.calculate_xp_for_level(voice_level)
            progress_xp = voice_xp - current_level_xp
            needed_xp = next_level_xp - current_level_xp
            
            # Calculate rank
            guild_data = self.levels_db.get(str(ctx.guild.id), {})
            voice_ranks = sorted(
                [(uid, data["voice_xp"]) for uid, data in guild_data.items()],
                key=lambda x: x[1], reverse=True
            )
            voice_rank = next((i + 1 for i, (uid, _) in enumerate(voice_ranks) if uid == str(target_user.id)), "N/A")
            
            progress_bar = self.create_progress_bar(progress_xp, needed_xp)
            
            hours = int(voice_minutes // 60)
            minutes = int(voice_minutes % 60)
            
            embed.add_field(
                name="🎤 Voice Chat",
                value=f"**Level:** {voice_level}\n"
                      f"**Rank:** #{voice_rank}\n"
                      f"**XP:** {voice_xp:,}\n"
                      f"**Time:** {hours}h {minutes}m\n"
                      f"**Progress:** {progress_bar}\n"
                      f"`{progress_xp}/{needed_xp} XP to level {voice_level + 1}`",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @level.command(name="leaderboard", aliases=["lb"])
    async def leaderboard_prefix(self, ctx, level_type: str = "combined", page: int = 1):
        """Show server leaderboard"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        type_filter = level_type.lower()
        if type_filter not in ["text", "voice", "combined"]:
            await ctx.send("Invalid level type! Use `text`, `voice`, or `combined`.")
            return
        
        page = max(1, page)
        
        guild_data = self.levels_db.get(str(ctx.guild.id), {})
        if not guild_data:
            await ctx.send("No level data found for this server!")
            return
        
        # Sort users based on type
        if type_filter == "text":
            sorted_users = sorted(
                guild_data.items(),
                key=lambda x: x[1]["text_xp"],
                reverse=True
            )
            title = "💬 Text Chat Leaderboard"
        elif type_filter == "voice":
            sorted_users = sorted(
                guild_data.items(),
                key=lambda x: x[1]["voice_xp"],
                reverse=True
            )
            title = "🎤 Voice Chat Leaderboard"
        else:  # combined
            sorted_users = sorted(
                guild_data.items(),
                key=lambda x: x[1]["text_xp"] + x[1]["voice_xp"],
                reverse=True
            )
            title = "🏆 Combined Leaderboard"
        
        # Pagination
        per_page = 10
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_users = sorted_users[start_idx:end_idx]
        
        if not page_users:
            await ctx.send("No users found on this page!")
            return
        
        embed = discord.Embed(title=title, color=0x00ff00)
        
        description_lines = []
        for i, (user_id, data) in enumerate(page_users, start=start_idx + 1):
            user = self.bot.get_user(int(user_id))
            user_name = user.display_name if user else f"Unknown User ({user_id})"
            
            if type_filter == "text":
                level = data["text_level"]
                xp = data["text_xp"]
            elif type_filter == "voice":
                level = data["voice_level"]
                xp = data["voice_xp"]
                minutes = data["total_voice_minutes"]
                hours = int(minutes // 60)
                mins = int(minutes % 60)
                user_name += f" ({hours}h {mins}m)"
            else:  # combined
                level = max(data["text_level"], data["voice_level"])
                xp = data["text_xp"] + data["voice_xp"]
            
            rank_emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"**{i}.**"
            description_lines.append(f"{rank_emoji} {user_name}\n`Level {level} • {xp:,} XP`")
        
        embed.description = "\n\n".join(description_lines)
        
        # Add pagination info
        total_pages = math.ceil(len(sorted_users) / per_page)
        embed.set_footer(text=f"Page {page}/{total_pages} • {len(sorted_users)} total users")
        
        await ctx.send(embed=embed)

    @level.command(name="setreward")
    async def setreward_prefix(self, ctx, level: int, level_type: str, role: discord.Role, permanent: bool = True):
        """Set level reward (Admin only)"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("You don't have permission to manage level rewards!")
            return
        
        if level_type.lower() not in ["text", "voice"]:
            await ctx.send("Invalid level type! Use `text` or `voice`.")
            return
        
        if level < 1 or level > 100:
            await ctx.send("Level must be between 1 and 100!")
            return
        
        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send("You cannot set rewards for roles higher than your highest role!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        rewards = guild_config["rewards"][level_type.lower()]
        
        level_str = str(level)
        if level_str not in rewards:
            rewards[level_str] = []
        
        # Check if role already exists as a reward
        for existing_reward in rewards[level_str]:
            if existing_reward["role_id"] == role.id:
                await ctx.send(f"Role {role.mention} is already a reward for level {level}!")
                return
        
        # Add new reward
        rewards[level_str].append({
            "role_id": role.id,
            "permanent": permanent
        })
        self.save_config()
        
        await self.log_levels_action(
            "reward_set", ctx.guild, ctx.author,
            f"Level {level} {level_type.lower()} reward: {role.name} ({'permanent' if permanent else 'temporary'})"
        )
        
        permanence_text = "**permanent**" if permanent else "**temporary**"
        embed = discord.Embed(
            title="✅ Reward Set",
            description=f"Role {role.mention} will now be given at **level {level}** for **{level_type.lower()}** chat!\n\n**Type:** {permanence_text}",
            color=0x00ff00
        )
        await ctx.send(embed=embed)

    @level.command(name="removereward")
    async def removereward_prefix(self, ctx, level: int, level_type: str, role: discord.Role):
        """Remove level reward (Admin only)"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("You don't have permission to manage level rewards!")
            return
        
        if level_type.lower() not in ["text", "voice"]:
            await ctx.send("Invalid level type! Use `text` or `voice`.")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        rewards = guild_config["rewards"][level_type.lower()]
        
        level_str = str(level)
        if level_str in rewards:
            # Find and remove the reward
            for i, reward in enumerate(rewards[level_str]):
                if reward["role_id"] == role.id:
                    rewards[level_str].pop(i)
                    break
            else:
                await ctx.send(f"Role {role.mention} is not a reward for level {level}!")
                return
            
            # Remove empty list
            if not rewards[level_str]:
                del rewards[level_str]
            
            self.save_config()
            
            await self.log_levels_action(
                "reward_removed", ctx.guild, ctx.author,
                f"Level {level} {level_type.lower()} reward removed: {role.name}"
            )
            
            embed = discord.Embed(
                title="✅ Reward Removed",
                description=f"Role {role.mention} is no longer a reward for **level {level}** in **{level_type.lower()}** chat!",
                color=0xff9900
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Role {role.mention} is not a reward for level {level}!")

    @level.command(name="rewards")
    async def rewards_prefix(self, ctx, level_type: str = "both", level: int = None):
        """View level rewards"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        type_filter = level_type.lower()
        
        if type_filter not in ["text", "voice", "both"]:
            await ctx.send("Invalid level type! Use `text`, `voice`, or `both`.")
            return
        
        embed = discord.Embed(title="🎁 Level Rewards", color=0x00ff00)
        
        types_to_show = ["text", "voice"] if type_filter == "both" else [type_filter]
        
        for ltype in types_to_show:
            rewards = guild_config["rewards"][ltype]
            
            if level:
                # Show specific level
                level_str = str(level)
                if level_str in rewards:
                    reward_lines = []
                    for reward in rewards[level_str]:
                        role = ctx.guild.get_role(reward["role_id"])
                        if role:
                            permanence = "🔒" if reward.get("permanent", True) else "⏰"
                            reward_lines.append(f"{permanence} {role.mention}")
                    
                    if reward_lines:
                        embed.add_field(
                            name=f"{ltype.title()} Level {level}",
                            value="\n".join(reward_lines),
                            inline=False
                        )
            else:
                # Show all levels
                if rewards:
                    reward_text = []
                    for level_str in sorted(rewards.keys(), key=int):
                        level_rewards = []
                        for reward in rewards[level_str]:
                            role = ctx.guild.get_role(reward["role_id"])
                            if role:
                                permanence = "🔒" if reward.get("permanent", True) else "⏰"
                                level_rewards.append(f"{permanence} {role.name}")
                        
                        if level_rewards:
                            reward_text.append(f"**Level {level_str}:** {', '.join(level_rewards)}")
                    
                    if reward_text:
                        # Split into chunks if too long
                        chunk_size = 1024
                        text = "\n".join(reward_text)
                        if len(text) <= chunk_size:
                            embed.add_field(
                                name=f"{ltype.title()} Chat Rewards",
                                value=text,
                                inline=False
                            )
                        else:
                            # Split into multiple fields
                            chunks = []
                            current_chunk = ""
                            for line in reward_text:
                                if len(current_chunk + line + "\n") <= chunk_size:
                                    current_chunk += line + "\n"
                                else:
                                    if current_chunk:
                                        chunks.append(current_chunk.strip())
                                    current_chunk = line + "\n"
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            
                            for i, chunk in enumerate(chunks):
                                field_name = f"{ltype.title()} Chat Rewards" + (f" (Part {i+1})" if len(chunks) > 1 else "")
                                embed.add_field(name=field_name, value=chunk, inline=False)
        
        if not embed.fields:
            embed.description = "No rewards configured."
        else:
            embed.set_footer(text="🔒 = Permanent reward | ⏰ = Temporary reward (removed when leveling up)")
        
        await ctx.send(embed=embed)

    @level.command(name="set")
    async def set_level_prefix(self, ctx, user: discord.Member, level: int, level_type: str):
        """Set user's level and update their roles (Admin only)"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("You don't have permission to set user levels!")
            return
        
        if level_type.lower() not in ["text", "voice"]:
            await ctx.send("Invalid level type! Use `text` or `voice`.")
            return
        
        if level < 0 or level > 1000:
            await ctx.send("Level must be between 0 and 1000!")
            return
        
        user_data = self.get_user_data(ctx.guild.id, user.id)
        old_level = user_data[f"{level_type.lower()}_level"]
        
        # Calculate XP for the level
        new_xp = self.calculate_xp_for_level(level)
        user_data[f"{level_type.lower()}_xp"] = new_xp
        user_data[f"{level_type.lower()}_level"] = level
        
        self.save_levels_db()
        
        # Update user's roles based on new level
        role_changes = await self.update_user_roles_for_level(user, level_type.lower(), level)
        
        await self.log_levels_action(
            "level_set", ctx.guild, ctx.author,
            f"Set {user.name}'s {level_type.lower()} level from {old_level} to {level}"
        )
        
        # Create response embed
        embed = discord.Embed(
            title="✅ Level Set",
            description=f"Set {user.mention}'s **{level_type.lower()}** level to **{level}** (was {old_level})",
            color=0x00ff00
        )
        
        # Add role change information
        if role_changes["added"] or role_changes["removed"]:
            role_info = []
            
            if role_changes["added"]:
                added_mentions = [role.mention for role in role_changes["added"]]
                role_info.append(f"**Added:** {', '.join(added_mentions)}")
            
            if role_changes["removed"]:
                removed_mentions = [role.mention for role in role_changes["removed"]]
                role_info.append(f"**Removed:** {', '.join(removed_mentions)}")
            
            embed.add_field(
                name="🎭 Role Changes",
                value="\n".join(role_info),
                inline=False
            )
        else:
            embed.add_field(
                name="🎭 Role Changes",
                value="No role changes were needed",
                inline=False
            )
        
        # Add current level info
        current_xp = user_data[f"{level_type.lower()}_xp"]
        next_level_xp = self.calculate_xp_for_next_level(level)
        current_level_xp = self.calculate_xp_for_level(level)
        progress_xp = current_xp - current_level_xp
        needed_xp = next_level_xp - current_level_xp
        
        embed.add_field(
            name="📊 Level Info",
            value=f"**XP:** {current_xp:,}\n**Next Level:** {progress_xp}/{needed_xp} XP",
            inline=True
        )
        
        await ctx.send(embed=embed)

    @level.command(name="embedtoggle")
    async def toggle_embeds_prefix(self, ctx):
        """Toggle level up embeds (Admin only)"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        if not self.has_levels_admin_permission(ctx.author):
            await ctx.send("You don't have permission to configure level embeds!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        current_state = guild_config["level_up_embed"]["enabled"]
        guild_config["level_up_embed"]["enabled"] = not current_state
        
        self.save_config()
        
        status = "enabled" if not current_state else "disabled"
        embed = discord.Embed(
            title="⚙️ Level Up Embeds",
            description=f"Level up embeds have been **{status}**!",
            color=0x00ff00 if not current_state else 0xff9900
        )
        await ctx.send(embed=embed)

    @level.command(name="config")
    async def config_embeds_prefix(self, ctx):
        """View current embed configuration"""
        if not self.is_leveling_enabled(ctx.guild.id):
            await ctx.send("❌ The leveling system is currently disabled in this server!")
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        embed_config = guild_config["level_up_embed"]
        
        embed = discord.Embed(title="⚙️ Current Embed Configuration", color=0x0099ff)
        embed.add_field(name="Title", value=embed_config["title"], inline=False)
        embed.add_field(name="Description", value=embed_config["description"], inline=False)
        embed.add_field(name="Color", value=f"#{embed_config['color']:06x}", inline=True)
        embed.add_field(name="Enabled", value=embed_config["enabled"], inline=True)
        embed.add_field(name="Show Rewards", value=embed_config["show_rewards"], inline=True)
        
        if embed_config["fallback_channel"]:
            ch = ctx.guild.get_channel(embed_config["fallback_channel"])
            embed.add_field(name="Fallback Channel", value=ch.mention if ch else "Unknown", inline=True)
        
        embed.add_field(
            name="ℹ️ Behavior",
            value="• Text level ups: Sent in the channel where the message was sent\n• Voice level ups: Sent in fallback channel or any suitable channel\n• Set command: Automatically updates user roles",
            inline=False
        )
        
        await ctx.send(embed=embed)

    # Error handling
    @level.error
    async def level_error(self, ctx, error):
        await self.log_levels_error(f"Level command error: {error}", ctx.guild, ctx.author)
        
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing required argument: `{error.param.name}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument provided: {error}")
        else:
            await ctx.send(f"An error occurred: {error}")

async def setup(bot):
    await bot.add_cog(LevelsCog(bot))
