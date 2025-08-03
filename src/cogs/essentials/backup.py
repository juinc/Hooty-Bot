"""
Discord Backup Cog - Automated Bot Data Backup System

OVERVIEW:
Provides automated and manual backup functionality for Discord bot data. Creates compressed ZIP backups
of specified directories with configurable scheduling and retention policies.

SETUP:
- No manual setup required - auto-creates directories and config files
- Backup sources: src/database, src/logs, src/config  
- Backup destination: src/backups/
- Config file: src/config/backup_config.json
- Requires: PermissionsCog (optional), LoggingCog (optional)

PERMISSIONS:
- Commands require 'permissions.backup.admin' or 'permissions.omni' or Administrator
- Uses guild-specific enable/disable system

COMMANDS:
/backup enable          - Enable backup system for this server
/backup disable         - Disable backup system for this server  
/backup config          - View current backup configuration and status
/backup create          - Create manual backup immediately
/backup list            - List existing backups with sizes and dates
/backup delete <name>   - Delete specific backup file
/backup set-interval <hours>  - Set auto backup interval (1-168 hours)
/backup set-max <count>       - Set max backups to keep (1-50)  
/backup toggle-auto     - Toggle automatic backups on/off

All commands also available as prefix commands: !backup <subcommand>

FEATURES:
• Automatic scheduled backups (configurable interval, default 24h)
• Manual backup creation with instant feedback
• ZIP compression with file size reporting  
• Automatic cleanup of old backups based on retention limit
• Per-guild enable/disable functionality
• Both slash and prefix command support
• Integration with permissions and logging systems
• Timestamp-based backup file naming (backup_YYYYMMDD_HHMMSS.zip)
• Real-time backup status and configuration viewing
• Error handling and detailed logging of all backup operations

DEFAULT SETTINGS:
- Backup interval: 24 hours
- Max backups: 7 
- Auto backup: Enabled
- System status: Enabled per guild
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import zipfile
from datetime import datetime, timedelta
from typing import Optional, Union, List
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

class BackupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = "src/config"
        self.backup_dir = "src/backups"
        
        # Directories to backup
        self.backup_sources = [
            "src/database",
            "src/logs", 
            "src/config"
        ]
        
        # Ensure directories exist
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        
        # File path
        self.backup_config_path = os.path.join(self.config_dir, "backup_config.json")
        
        # Initialize config file
        self._init_config_file()
        
        # Start the backup scheduler
        self.backup_scheduler.start()

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.backup_scheduler.cancel()

    def _init_config_file(self):
        """Initialize config file with default settings"""
        default_config = {
            "guilds": {},
            "global_settings": {
                "backup_interval_hours": 24,  # Default 24 hours
                "max_backups": 7,  # Keep 7 backups by default
                "auto_backup_enabled": True
            }
        }
        
        if not os.path.exists(self.backup_config_path):
            with open(self.backup_config_path, 'w') as f:
                json.dump(default_config, f, indent=4)

    def _load_config(self) -> dict:
        """Load backup configuration from file"""
        try:
            with open(self.backup_config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_config_file()
            with open(self.backup_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save backup configuration to file"""
        with open(self.backup_config_path, 'w') as f:
            json.dump(data, f, indent=4)

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create guild backup configuration"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "enabled": True,
                "auto_backup": True,
                "last_backup": None
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    def has_backup_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has backup admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.backup.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_backup_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log backup actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Backup {action}"
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
                    file_override="backup_cog"
                )
            except Exception as e:
                print(f"Failed to log backup action: {e}")

    def _is_enabled(self, guild_id: int) -> bool:
        """Check if backup cog is enabled for a guild"""
        guild_config = self._get_guild_config(guild_id)
        return guild_config.get("enabled", True)

    async def _check_enabled(self, ctx_or_interaction) -> bool:
        """Check if cog is enabled and respond if not"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self._is_enabled(guild.id):
            await respond("❌ Backup commands are currently disabled in this server.", ephemeral=True)
            return False
        return True

    def _get_backup_filename(self) -> str:
        """Generate backup filename with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"backup_{timestamp}.zip"

    def _get_existing_backups(self) -> List[str]:
        """Get list of existing backup files"""
        if not os.path.exists(self.backup_dir):
            return []
        
        backups = []
        for file in os.listdir(self.backup_dir):
            if file.startswith("backup_") and file.endswith(".zip"):
                backups.append(file)
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: os.path.getctime(os.path.join(self.backup_dir, x)), reverse=True)
        return backups

    async def _create_backup(self, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None) -> tuple[bool, str]:
        """Create a backup of specified directories"""
        try:
            backup_filename = self._get_backup_filename()
            backup_path = os.path.join(self.backup_dir, backup_filename)
            
            # Create zip file
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for source_dir in self.backup_sources:
                    if os.path.exists(source_dir):
                        for root, dirs, files in os.walk(source_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                # Create archive path relative to source directory
                                arcname = os.path.relpath(file_path, os.path.dirname(source_dir))
                                zipf.write(file_path, arcname)
            
            # Check if backup was created successfully
            if os.path.exists(backup_path):
                file_size = os.path.getsize(backup_path)
                
                # Clean up old backups
                await self._cleanup_old_backups()
                
                # Log the successful backup
                size_mb = file_size / (1024 * 1024)
                await self.log_backup_action(
                    "created", 
                    guild, 
                    user, 
                    f"File: {backup_filename}, Size: {size_mb:.2f}MB"
                )
                
                return True, f"Backup created successfully: {backup_filename} ({size_mb:.2f}MB)"
            else:
                return False, "Failed to create backup file"
                
        except Exception as e:
            await self.log_backup_action("failed", guild, user, f"Error: {str(e)}")
            return False, f"Backup failed: {str(e)}"

    async def _cleanup_old_backups(self):
        """Remove old backups based on max_backups setting"""
        config = self._load_config()
        max_backups = config["global_settings"]["max_backups"]
        
        existing_backups = self._get_existing_backups()
        
        if len(existing_backups) > max_backups:
            backups_to_remove = existing_backups[max_backups:]
            
            for backup_file in backups_to_remove:
                backup_path = os.path.join(self.backup_dir, backup_file)
                try:
                    os.remove(backup_path)
                    await self.log_backup_action(
                        "cleanup", 
                        None, 
                        None, 
                        f"Removed old backup: {backup_file}"
                    )
                except Exception as e:
                    await self.log_backup_action(
                        "cleanup_failed", 
                        None, 
                        None, 
                        f"Failed to remove {backup_file}: {str(e)}"
                    )

    @tasks.loop(hours=1)  # Check every hour
    async def backup_scheduler(self):
        """Scheduled backup task"""
        try:
            config = self._load_config()
            global_settings = config["global_settings"]
            
            if not global_settings.get("auto_backup_enabled", True):
                return
            
            interval_hours = global_settings.get("backup_interval_hours", 24)
            
            # Check if it's time for a backup
            last_backup_file = None
            existing_backups = self._get_existing_backups()
            
            if existing_backups:
                last_backup_file = existing_backups[0]  # Most recent
                last_backup_path = os.path.join(self.backup_dir, last_backup_file)
                last_backup_time = datetime.fromtimestamp(os.path.getctime(last_backup_path))
                
                time_since_backup = datetime.now() - last_backup_time
                
                if time_since_backup.total_seconds() < (interval_hours * 3600):
                    return  # Not time yet
            
            # Create automatic backup
            success, message = await self._create_backup()
            
            if success:
                await self.log_backup_action(
                    "auto_created", 
                    None, 
                    None, 
                    f"Scheduled backup completed - {message}"
                )
            else:
                await self.log_backup_action(
                    "auto_failed", 
                    None, 
                    None, 
                    f"Scheduled backup failed - {message}"
                )
                
        except Exception as e:
            await self.log_backup_action(
                "scheduler_error", 
                None, 
                None, 
                f"Scheduler error: {str(e)}"
            )

    @backup_scheduler.before_loop
    async def before_backup_scheduler(self):
        """Wait for bot to be ready before starting scheduler"""
        await self.bot.wait_until_ready()

    # SLASH COMMANDS
    backup_group = app_commands.Group(name="backup", description="Backup management commands")

    @backup_group.command(name="enable", description="Enable backup system for this server")
    async def enable_slash(self, interaction: discord.Interaction):
        """Enable backup system"""
        await self._toggle_backup(interaction, True)

    @backup_group.command(name="disable", description="Disable backup system for this server")
    async def disable_slash(self, interaction: discord.Interaction):
        """Disable backup system"""
        await self._toggle_backup(interaction, False)

    @backup_group.command(name="config", description="View backup configuration")
    async def config_slash(self, interaction: discord.Interaction):
        """View current configuration"""
        await self._view_config(interaction)

    @backup_group.command(name="create", description="Create a manual backup")
    async def create_slash(self, interaction: discord.Interaction):
        """Create manual backup"""
        if not await self._check_enabled(interaction):
            return
        await self._manual_backup(interaction)

    @backup_group.command(name="list", description="List existing backups")
    async def list_slash(self, interaction: discord.Interaction):
        """List backups"""
        if not await self._check_enabled(interaction):
            return
        await self._list_backups(interaction)

    @backup_group.command(name="delete", description="Delete a specific backup")
    @app_commands.describe(backup_name="Name of the backup file to delete")
    async def delete_slash(self, interaction: discord.Interaction, backup_name: str):
        """Delete specific backup"""
        if not await self._check_enabled(interaction):
            return
        await self._delete_backup(interaction, backup_name)

    @backup_group.command(name="set-interval", description="Set backup interval in hours")
    @app_commands.describe(hours="Backup interval in hours (1-168)")
    async def set_interval_slash(self, interaction: discord.Interaction, hours: int):
        """Set backup interval"""
        await self._set_interval(interaction, hours)

    @backup_group.command(name="set-max", description="Set maximum number of backups to keep")
    @app_commands.describe(max_backups="Maximum number of backups (1-50)")
    async def set_max_slash(self, interaction: discord.Interaction, max_backups: int):
        """Set max backups"""
        await self._set_max_backups(interaction, max_backups)

    @backup_group.command(name="toggle-auto", description="Toggle automatic backups on/off")
    async def toggle_auto_slash(self, interaction: discord.Interaction):
        """Toggle auto backups"""
        await self._toggle_auto_backup(interaction)

    # PREFIX COMMANDS
    @commands.group(name="backup", invoke_without_command=True)
    async def backup_prefix(self, ctx):
        """Backup management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="💾 Backup Commands",
                description="Available backup management commands",
                color=discord.Color.green()
            )
            embed.add_field(
                name="System Control",
                value="• `enable` - Enable backup system\n• `disable` - Disable backup system\n• `config` - View configuration",
                inline=False
            )
            embed.add_field(
                name="Backup Management",
                value="• `create` - Create manual backup\n• `list` - List existing backups\n• `delete <name>` - Delete specific backup",
                inline=False
            )
            embed.add_field(
                name="Settings",
                value="• `set-interval <hours>` - Set backup interval\n• `set-max <count>` - Set max backups\n• `toggle-auto` - Toggle automatic backups",
                inline=False
            )
            await ctx.send(embed=embed)

    @backup_prefix.command(name="enable")
    async def enable_prefix(self, ctx):
        """Enable backup system"""
        await self._toggle_backup(ctx, True)

    @backup_prefix.command(name="disable")
    async def disable_prefix(self, ctx):
        """Disable backup system"""
        await self._toggle_backup(ctx, False)

    @backup_prefix.command(name="config")
    async def config_prefix(self, ctx):
        """View current configuration"""
        await self._view_config(ctx)

    @backup_prefix.command(name="create")
    async def create_prefix(self, ctx):
        """Create manual backup"""
        if not await self._check_enabled(ctx):
            return
        await self._manual_backup(ctx)

    @backup_prefix.command(name="list")
    async def list_prefix(self, ctx):
        """List backups"""
        if not await self._check_enabled(ctx):
            return
        await self._list_backups(ctx)

    @backup_prefix.command(name="delete")
    async def delete_prefix(self, ctx, *, backup_name: str):
        """Delete specific backup"""
        if not await self._check_enabled(ctx):
            return
        await self._delete_backup(ctx, backup_name)

    @backup_prefix.command(name="set-interval")
    async def set_interval_prefix(self, ctx, hours: int):
        """Set backup interval"""
        await self._set_interval(ctx, hours)

    @backup_prefix.command(name="set-max")
    async def set_max_prefix(self, ctx, max_backups: int):
        """Set max backups"""
        await self._set_max_backups(ctx, max_backups)

    @backup_prefix.command(name="toggle-auto")
    async def toggle_auto_prefix(self, ctx):
        """Toggle auto backups"""
        await self._toggle_auto_backup(ctx)

    # IMPLEMENTATION METHODS
    async def _toggle_backup(self, ctx_or_interaction, enabled: bool):
        """Toggle backup system on/off"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_backup_admin_permission(member):
            await respond("❌ You don't have permission to configure backup settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        guild_config["enabled"] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        action = "enabled" if enabled else "disabled"
        await self.log_backup_action(f"system_{action}", guild, member, f"Backup system {action}")
        
        status = "enabled" if enabled else "disabled"
        embed = discord.Embed(
            title=f"✅ Backup System {status.title()}",
            description=f"Backup system has been {status} for this server.",
            color=discord.Color.green() if enabled else discord.Color.red()
        )
        
        await respond(embed=embed)

    async def _view_config(self, ctx_or_interaction):
        """View current configuration"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        global_settings = config["global_settings"]
        
        embed = discord.Embed(
            title="💾 Backup Configuration",
            color=discord.Color.green()
        )
        
        # System status
        system_status = "🟢 Enabled" if guild_config.get("enabled", True) else "🔴 Disabled"
        auto_backup_status = "🟢 Enabled" if global_settings.get("auto_backup_enabled", True) else "🔴 Disabled"
        
        embed.add_field(
            name="System Status",
            value=f"**Backup System:** {system_status}\n**Auto Backup:** {auto_backup_status}",
            inline=False
        )
        
        # Settings
        interval = global_settings.get("backup_interval_hours", 24)
        max_backups = global_settings.get("max_backups", 7)
        
        embed.add_field(
            name="Settings",
            value=f"**Backup Interval:** {interval} hours\n**Max Backups:** {max_backups}",
            inline=True
        )
        
        # Backup info
        existing_backups = self._get_existing_backups()
        backup_count = len(existing_backups)
        
        if existing_backups:
            latest_backup = existing_backups[0]
            latest_path = os.path.join(self.backup_dir, latest_backup)
            latest_time = datetime.fromtimestamp(os.path.getctime(latest_path))
            
            embed.add_field(
                name="Backup Status",
                value=f"**Total Backups:** {backup_count}\n**Latest:** <t:{int(latest_time.timestamp())}:R>",
                inline=True
            )
        else:
            embed.add_field(
                name="Backup Status",
                value="**Total Backups:** 0\n**Latest:** None",
                inline=True
            )
        
        # Backup sources
        sources = ", ".join([src.replace("src/", "") for src in self.backup_sources])
        embed.add_field(
            name="Backup Sources",
            value=sources,
            inline=False
        )
        
        await respond(embed=embed, ephemeral=True)

    async def _manual_backup(self, ctx_or_interaction):
        """Create manual backup"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_backup_admin_permission(member):
            await respond("❌ You don't have permission to create backups.", ephemeral=True)
            return

        # Show loading message
        embed = discord.Embed(
            title="💾 Creating Backup...",
            description="Please wait while I create a backup of your data.",
            color=discord.Color.blue()
        )
        await respond(embed=embed)

        # Create backup
        success, message = await self._create_backup(guild, member)

        # Update response
        if success:
            result_embed = discord.Embed(
                title="✅ Backup Created Successfully",
                description=message,
                color=discord.Color.green()
            )
        else:
            result_embed = discord.Embed(
                title="❌ Backup Failed",
                description=message,
                color=discord.Color.red()
            )

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.edit_original_response(embed=result_embed)
        else:
            await ctx_or_interaction.send(embed=result_embed)

    async def _list_backups(self, ctx_or_interaction):
        """List existing backups"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        await self.log_backup_action("list_viewed", guild, user)

        existing_backups = self._get_existing_backups()

        embed = discord.Embed(
            title="💾 Backup List",
            color=discord.Color.blue()
        )

        if not existing_backups:
            embed.description = "No backups found."
        else:
            backup_info = []
            for backup_file in existing_backups[:10]:  # Show max 10
                backup_path = os.path.join(self.backup_dir, backup_file)
                file_size = os.path.getsize(backup_path) / (1024 * 1024)  # MB
                creation_time = datetime.fromtimestamp(os.path.getctime(backup_path))
                
                backup_info.append(
                    f"**{backup_file}**\n"
                    f"Size: {file_size:.2f}MB\n"
                    f"Created: <t:{int(creation_time.timestamp())}:F>\n"
                )

            embed.description = "\n".join(backup_info)
            
            if len(existing_backups) > 10:
                embed.set_footer(text=f"Showing 10 of {len(existing_backups)} backups")

        await respond(embed=embed, ephemeral=True)

    async def _delete_backup(self, ctx_or_interaction, backup_name: str):
        """Delete specific backup"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_backup_admin_permission(member):
            await respond("❌ You don't have permission to delete backups.", ephemeral=True)
            return

        backup_path = os.path.join(self.backup_dir, backup_name)

        if not os.path.exists(backup_path) or not backup_name.startswith("backup_"):
            await respond("❌ Backup file not found.", ephemeral=True)
            return

        try:
            os.remove(backup_path)
            await self.log_backup_action("deleted", guild, member, f"Deleted backup: {backup_name}")
            
            embed = discord.Embed(
                title="✅ Backup Deleted",
                description=f"Successfully deleted backup: `{backup_name}`",
                color=discord.Color.green()
            )
        except Exception as e:
            await self.log_backup_action("delete_failed", guild, member, f"Failed to delete {backup_name}: {str(e)}")
            
            embed = discord.Embed(
                title="❌ Delete Failed", 
                description=f"Failed to delete backup: {str(e)}",
                color=discord.Color.red()
            )

        await respond(embed=embed)

    async def _set_interval(self, ctx_or_interaction, hours: int):
        """Set backup interval"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_backup_admin_permission(member):
            await respond("❌ You don't have permission to modify backup settings.", ephemeral=True)
            return

        if not 1 <= hours <= 168:  # 1 hour to 1 week
            await respond("❌ Backup interval must be between 1 and 168 hours.", ephemeral=True)
            return

        config = self._load_config()
        config["global_settings"]["backup_interval_hours"] = hours
        self._save_config(config)

        await self.log_backup_action("interval_changed", guild, member, f"New interval: {hours} hours")

        embed = discord.Embed(
            title="✅ Backup Interval Updated",
            description=f"Backup interval set to {hours} hours.",
            color=discord.Color.green()
        )

        await respond(embed=embed)

    async def _set_max_backups(self, ctx_or_interaction, max_backups: int):
        """Set maximum backups"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_backup_admin_permission(member):
            await respond("❌ You don't have permission to modify backup settings.", ephemeral=True)
            return

        if not 1 <= max_backups <= 50:
            await respond("❌ Maximum backups must be between 1 and 50.", ephemeral=True)
            return

        config = self._load_config()
        config["global_settings"]["max_backups"] = max_backups
        self._save_config(config)

        await self.log_backup_action("max_backups_changed", guild, member, f"New max: {max_backups}")

        # Clean up excess backups if needed
        await self._cleanup_old_backups()

        embed = discord.Embed(
            title="✅ Max Backups Updated",
            description=f"Maximum backups set to {max_backups}.",
            color=discord.Color.green()
        )

        await respond(embed=embed)

    async def _toggle_auto_backup(self, ctx_or_interaction):
        """Toggle automatic backups"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_backup_admin_permission(member):
            await respond("❌ You don't have permission to modify backup settings.", ephemeral=True)
            return

        config = self._load_config()
        current_status = config["global_settings"].get("auto_backup_enabled", True)
        new_status = not current_status
        
        config["global_settings"]["auto_backup_enabled"] = new_status
        self._save_config(config)

        action = "enabled" if new_status else "disabled"
        await self.log_backup_action(f"auto_backup_{action}", guild, member)

        embed = discord.Embed(
            title=f"✅ Automatic Backups {action.title()}",
            description=f"Automatic backups have been {action}.",
            color=discord.Color.green() if new_status else discord.Color.orange()
        )

        await respond(embed=embed)

async def setup(bot):
    await bot.add_cog(BackupCog(bot))