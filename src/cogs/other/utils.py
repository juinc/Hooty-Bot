"""
Discord UtilityCog - General Utility & Info Commands

OVERVIEW:
A collection of useful utility commands for Discord servers.  
Includes role info, role permission diagnosis, avatar viewing/downloading, URL shortener, and per-role custom info.  
Supports both slash and prefix commands, per-guild enable/disable, and logging.

SETUP:
- No manual setup required – auto-creates config at src/config/util_config.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.util.admin' or Administrator

COMMANDS (Slash & Prefix):
/utils enable/disable                 - Enable/disable utility commands (admin)
/utils config                         - View current utility configuration
/utils role-info <role>               - Show info about a role
/utils add-role-info <role> <info>    - Add custom info to a role (admin)
/utils remove-role-info <role>        - Remove custom info from a role (admin)
/utils diag-role <role>               - Diagnose all permissions for a role
/utils avatar [user]                  - Show a user's avatar (with download links)
/utils shorten <url>                  - Shorten a URL using TinyURL

Prefix commands: !util <subcommand> (same as above)

COMMAND EXPLANATIONS:
- enable/disable: Enable or disable all utility commands for your server.
- config: Show system status and custom role info stats.
- role-info: Show all info about a role, including custom info and members.
- add/remove-role-info: Add or remove custom info for a role (admin only).
- diag-role: Show all permissions for a role, grouped by category.
- avatar: Show a user's avatar with download links (PNG/JPG/WebP/GIF).
- shorten: Shorten a URL using TinyURL.

FEATURES:
• Role info, custom info, and permission diagnosis
• Avatar viewing and download links (all formats)
• URL shortener (TinyURL)
• Per-guild enable/disable
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Persistent, per-guild config (JSON)
• Both slash and prefix command support

USAGE BY OTHER COGS:
# Access custom role info or config for integrations
util_cog = bot.get_cog('UtilityCog')
if util_cog:
    config = util_cog._load_config()
    guild_config = util_cog._get_guild_config(guild.id)
    custom_info = guild_config["role_info"].get(str(role.id), "")
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import aiohttp
from typing import Optional, Union, Dict, List
from urllib.parse import urlparse
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

class AvatarView(discord.ui.View):
    def __init__(self, user: Union[discord.Member, discord.User]):
        super().__init__(timeout=300)
        self.user = user
        
        # Add format buttons
        formats = [
            ("PNG", "png"),
            ("JPG", "jpg"),
            ("WebP", "webp")
        ]
        
        # Add GIF option if avatar is animated
        if user.display_avatar.is_animated():
            formats.append(("GIF", "gif"))
        
        for name, format_type in formats:
            button = discord.ui.Button(
                label=f"Download {name}",
                style=discord.ButtonStyle.secondary
            )
            button.callback = self.create_download_callback(format_type)
            self.add_item(button)

    def create_download_callback(self, format_type: str):
        async def download_callback(interaction: discord.Interaction):
            avatar_url = self.user.display_avatar.with_format(format_type).with_size(1024).url
            
            embed = discord.Embed(
                title=f"{self.user.display_name}'s Avatar ({format_type.upper()})",
                color=discord.Color.blue()
            )
            embed.set_image(url=avatar_url)
            embed.add_field(
                name="Download Link",
                value=f"[Click here to download]({avatar_url})",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        return download_callback

class UtilityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = "src/config"
        
        # Ensure directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # File path
        self.util_config_path = os.path.join(self.config_dir, "util_config.json")
        
        # Initialize config file
        self._init_config_file()

    def _init_config_file(self):
        """Initialize config file with default settings"""
        default_config = {
            "guilds": {}
        }
        
        if not os.path.exists(self.util_config_path):
            with open(self.util_config_path, 'w') as f:
                json.dump(default_config, f, indent=4)

    def _load_config(self) -> dict:
        """Load utility configuration from file"""
        try:
            with open(self.util_config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_config_file()
            with open(self.util_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save utility configuration to file"""
        with open(self.util_config_path, 'w') as f:
            json.dump(data, f, indent=4)

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create guild utility configuration"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "enabled": True,  # Utility cog enabled by default
                "role_info": {}
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    def has_util_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has utility admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.util.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_utility_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log utility actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Utility {action}"
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
                    file_override="utility_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log utility action: {e}")

    def _format_permissions(self, permissions: discord.Permissions) -> Dict[str, List[str]]:
        """Format permissions into categories"""
        permission_categories = {
            "General": [
                ("Create Instant Invite", permissions.create_instant_invite),
                ("Change Nickname", permissions.change_nickname),
                ("Manage Nicknames", permissions.manage_nicknames),
                ("Use External Emojis", permissions.external_emojis),
                ("Use External Stickers", permissions.external_stickers),
                ("Add Reactions", permissions.add_reactions),
                ("Use Application Commands", permissions.use_application_commands),
            ],
            "Text Permissions": [
                ("Send Messages", permissions.send_messages),
                ("Send Messages in Threads", permissions.send_messages_in_threads),
                ("Create Public Threads", permissions.create_public_threads),
                ("Create Private Threads", permissions.create_private_threads),
                ("Embed Links", permissions.embed_links),
                ("Attach Files", permissions.attach_files),
                ("Read Message History", permissions.read_message_history),
                ("Mention Everyone", permissions.mention_everyone),
                ("Use Text-to-Speech", permissions.send_tts_messages),
                ("Manage Messages", permissions.manage_messages),
                ("Manage Threads", permissions.manage_threads),
            ],
            "Voice Permissions": [
                ("Connect", permissions.connect),
                ("Speak", permissions.speak),
                ("Mute Members", permissions.mute_members),
                ("Deafen Members", permissions.deafen_members),
                ("Move Members", permissions.move_members),
                ("Use Voice Activation", permissions.use_voice_activation),
                ("Priority Speaker", permissions.priority_speaker),
                ("Stream", permissions.stream),
                ("Start Activities", permissions.use_embedded_activities),
                ("Use Soundboard", permissions.use_soundboard),
                ("Use External Sounds", permissions.use_external_sounds),
            ],
            "Management": [
                ("Manage Channels", permissions.manage_channels),
                ("Manage Guild", permissions.manage_guild),
                ("Manage Roles", permissions.manage_roles),
                ("Manage Webhooks", permissions.manage_webhooks),
                ("Manage Emojis and Stickers", permissions.manage_emojis_and_stickers),
                ("Manage Events", permissions.manage_events),
                ("View Audit Log", permissions.view_audit_log),
                ("View Guild Insights", permissions.view_guild_insights),
            ],
            "Moderation": [
                ("Kick Members", permissions.kick_members),
                ("Ban Members", permissions.ban_members),
                ("Timeout Members", permissions.moderate_members),
                ("Administrator", permissions.administrator),
            ],
            "Advanced": [
                ("Request to Speak", permissions.request_to_speak),
                ("Manage Expressions", permissions.manage_expressions),
            ]
        }
        
        formatted = {}
        for category, perms in permission_categories.items():
            enabled = []
            disabled = []
            
            for name, has_perm in perms:
                if has_perm:
                    enabled.append(f"✅ {name}")
                else:
                    disabled.append(f"❌ {name}")
            
            if enabled or disabled:
                formatted[category] = enabled + disabled
        
        return formatted

    async def _shorten_url(self, url: str) -> Optional[str]:
        """Shorten a URL using TinyURL service"""
        try:
            # Validate URL
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return None
            
            # Use TinyURL API
            api_url = f"http://tinyurl.com/api-create.php?url={url}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        shortened = await response.text()
                        # TinyURL returns the shortened URL directly
                        if shortened.startswith("http"):
                            return shortened
            
            return None
        except Exception:
            return None

    def _is_enabled(self, guild_id: int) -> bool:
        """Check if utility cog is enabled for a guild"""
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
            await respond("❌ Utility commands are currently disabled in this server.", ephemeral=True)
            return False
        return True

    # ==================== SLASH COMMANDS ====================
    util_group = app_commands.Group(name="utils", description="Utility commands")

    @util_group.command(name="enable", description="Enable utility commands for this server")
    async def enable_slash(self, interaction: discord.Interaction):
        """Enable utility commands"""
        await self._toggle_utils(interaction, True)

    @util_group.command(name="disable", description="Disable utility commands for this server")
    async def disable_slash(self, interaction: discord.Interaction):
        """Disable utility commands"""
        await self._toggle_utils(interaction, False)

    @util_group.command(name="config", description="View utility configuration")
    async def config_slash(self, interaction: discord.Interaction):
        """View current configuration"""
        await self._view_config(interaction)

    @util_group.command(name="role-info", description="Get information about a role")
    @app_commands.describe(role="Role to get information about")
    async def role_info_slash(self, interaction: discord.Interaction, role: discord.Role):
        """Get role information"""
        if not await self._check_enabled(interaction):
            return
        await self._role_info(interaction, role)

    @util_group.command(name="add-role-info", description="Add custom information for a role")
    @app_commands.describe(
        role="Role to add information for",
        content="Custom information to add"
    )
    async def add_role_info_slash(self, interaction: discord.Interaction, role: discord.Role, content: str):
        """Add custom role information"""
        if not await self._check_enabled(interaction):
            return
        await self._add_role_info(interaction, role, content)

    @util_group.command(name="remove-role-info", description="Remove custom information for a role")
    @app_commands.describe(role="Role to remove information from")
    async def remove_role_info_slash(self, interaction: discord.Interaction, role: discord.Role):
        """Remove custom role information"""
        if not await self._check_enabled(interaction):
            return
        await self._remove_role_info(interaction, role)

    @util_group.command(name="diag-role", description="Diagnose role permissions")
    @app_commands.describe(role="Role to diagnose permissions for")
    async def diag_role_slash(self, interaction: discord.Interaction, role: discord.Role):
        """Diagnose role permissions"""
        if not await self._check_enabled(interaction):
            return
        await self._diag_role(interaction, role)

    @util_group.command(name="avatar", description="Get user's avatar")
    @app_commands.describe(user="User to get avatar for (defaults to yourself)")
    async def avatar_slash(self, interaction: discord.Interaction, user: discord.Member = None):
        """Get user avatar"""
        if not await self._check_enabled(interaction):
            return
        await self._avatar(interaction, user)

    @util_group.command(name="shorten", description="Shorten a URL")
    @app_commands.describe(url="URL to shorten")
    async def shorten_slash(self, interaction: discord.Interaction, url: str):
        """Shorten a URL"""
        if not await self._check_enabled(interaction):
            return
        await self._shorten(interaction, url)

    # ==================== PREFIX COMMANDS ====================
    @commands.group(name="util", invoke_without_command=True)
    async def util_prefix(self, ctx):
        """Utility commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🔧 Utility Commands",
                description="Available utility commands",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="System Control",
                value="• `enable` - Enable utility commands\n• `disable` - Disable utility commands\n• `config` - View configuration",
                inline=False
            )
            embed.add_field(
                name="Role Commands",
                value="• `role-info <role>` - Get role information\n• `add-role-info <role> <content>` - Add custom role info (admin)\n• `remove-role-info <role>` - Remove custom role info (admin)\n• `diag-role <role>` - Diagnose role permissions",
                inline=False
            )
            embed.add_field(
                name="Other Commands",
                value="• `avatar [user]` - Get user avatar\n• `shorten <url>` - Shorten a URL",
                inline=False
            )
            await ctx.send(embed=embed)

    @util_prefix.command(name="enable")
    async def enable_prefix(self, ctx):
        """Enable utility commands"""
        await self._toggle_utils(ctx, True)

    @util_prefix.command(name="disable")
    async def disable_prefix(self, ctx):
        """Disable utility commands"""
        await self._toggle_utils(ctx, False)

    @util_prefix.command(name="config")
    async def config_prefix(self, ctx):
        """View current configuration"""
        await self._view_config(ctx)

    @util_prefix.command(name="role-info", aliases=["roleinfo"])
    async def role_info_prefix(self, ctx, *, role: discord.Role):
        """Get role information"""
        if not await self._check_enabled(ctx):
            return
        await self._role_info(ctx, role)

    @util_prefix.command(name="add-role-info", aliases=["addroleinfo"])
    async def add_role_info_prefix(self, ctx, role: discord.Role, *, content: str):
        """Add custom role information"""
        if not await self._check_enabled(ctx):
            return
        await self._add_role_info(ctx, role, content)

    @util_prefix.command(name="remove-role-info", aliases=["removeroleinfo"])
    async def remove_role_info_prefix(self, ctx, *, role: discord.Role):
        """Remove custom role information"""
        if not await self._check_enabled(ctx):
            return
        await self._remove_role_info(ctx, role)

    @util_prefix.command(name="diag-role", aliases=["diagrole"])
    async def diag_role_prefix(self, ctx, *, role: discord.Role):
        """Diagnose role permissions"""
        if not await self._check_enabled(ctx):
            return
        await self._diag_role(ctx, role)

    @util_prefix.command(name="avatar", aliases=["av"])
    async def avatar_prefix(self, ctx, user: discord.Member = None):
        """Get user avatar"""
        if not await self._check_enabled(ctx):
            return
        await self._avatar(ctx, user)

    @util_prefix.command(name="shorten")
    async def shorten_prefix(self, ctx, *, url: str):
        """Shorten a URL"""
        if not await self._check_enabled(ctx):
            return
        await self._shorten(ctx, url)

    # ==================== IMPLEMENTATION METHODS ====================
    async def _toggle_utils(self, ctx_or_interaction, enabled: bool):
        """Toggle utility commands on/off"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_util_admin_permission(member):
            await respond("❌ You don't have permission to configure utility settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        guild_config["enabled"] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        # Log the toggle action
        action = "enabled" if enabled else "disabled"
        await self.log_utility_action(f"cog_{action}", guild, member, f"Utility commands {action}")
        
        status = "enabled" if enabled else "disabled"
        embed = discord.Embed(
            title=f"✅ Utility Commands {status.title()}",
            description=f"Utility commands have been {status} for this server.",
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

        guild_config = self._get_guild_config(guild.id)
        
        embed = discord.Embed(
            title="🔧 Utility Configuration",
            color=discord.Color.blue()
        )
        
        # System status
        system_status = "🟢 Enabled" if guild_config.get("enabled", True) else "🔴 Disabled"
        embed.add_field(
            name="System Status",
            value=system_status,
            inline=False
        )
        
        # Role info statistics
        role_info_count = len(guild_config.get("role_info", {}))
        embed.add_field(
            name="Custom Role Information",
            value=f"{role_info_count} role(s) have custom information",
            inline=False
        )
        
        # Available commands
        embed.add_field(
            name="Available Commands",
            value="• Role information and management\n• Avatar viewing and downloading\n• URL shortening\n• Role permission diagnosis",
            inline=False
        )
        
        await respond(embed=embed, ephemeral=True)

    async def _role_info(self, ctx_or_interaction, role: discord.Role):
        """Role information implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        # Log the action
        await self.log_utility_action("role_info_viewed", guild, user, f"Role: {role.name} ({role.id})")

        # Get custom role info
        guild_config = self._get_guild_config(guild.id)
        custom_info = guild_config["role_info"].get(str(role.id), "")

        embed = discord.Embed(
            title=f"📋 Role Information: {role.name}",
            color=role.color if role.color != discord.Color.default() else discord.Color.blue()
        )

        # Basic information
        embed.add_field(
            name="Basic Info",
            value=f"**Name:** {role.name}\n**ID:** {role.id}\n**Color:** {role.color}\n**Position:** {role.position}\n**Members:** {len(role.members)}",
            inline=True
        )

        # Role settings
        settings = []
        if role.hoist:
            settings.append("🔸 Displayed separately")
        if role.mentionable:
            settings.append("🔸 Mentionable")
        if role.managed:
            settings.append("🔸 Managed by integration")
        if role.is_premium_subscriber():
            settings.append("🔸 Premium subscriber role")
        if role.is_bot_managed():
            settings.append("🔸 Bot role")
        if role.is_integration():
            settings.append("🔸 Integration role")

        if settings:
            embed.add_field(
                name="Settings",
                value="\n".join(settings),
                inline=True
            )

        # Creation date
        embed.add_field(
            name="Created",
            value=f"<t:{int(role.created_at.timestamp())}:F>\n<t:{int(role.created_at.timestamp())}:R>",
            inline=False
        )

        # Custom information
        if custom_info:
            embed.add_field(
                name="Custom Information",
                value=custom_info[:1024],
                inline=False
            )

        # Permission count
        permissions = role.permissions
        total_perms = len([p for p in permissions if p[1]])
        embed.add_field(
            name="Permissions",
            value=f"{total_perms} permissions granted\nUse `/utils diag-role` for detailed analysis",
            inline=True
        )

        # Role members (show first few)
        if role.members:
            member_list = [member.display_name for member in role.members[:10]]
            if len(role.members) > 10:
                member_list.append(f"... and {len(role.members) - 10} more")
            
            embed.add_field(
                name="Members",
                value=", ".join(member_list)[:1024],
                inline=False
            )

        embed.set_footer(text=f"Role ID: {role.id}")

        await respond(embed=embed)

    async def _add_role_info(self, ctx_or_interaction, role: discord.Role, content: str):
        """Add custom role information implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_util_admin_permission(member):
            await respond("❌ You don't have permission to add role information.", ephemeral=True)
            return

        if len(content) > 1024:
            await respond("❌ Custom information cannot exceed 1024 characters.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        # Check if role already has custom info (for logging purposes)
        had_previous_info = str(role.id) in guild_config["role_info"]
        previous_content = guild_config["role_info"].get(str(role.id), "")
        
        guild_config["role_info"][str(role.id)] = content
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        # Log the action
        action = "role_info_updated" if had_previous_info else "role_info_added"
        log_details = f"Role: {role.name} ({role.id})"
        if had_previous_info:
            log_details += f" - Previous: '{previous_content[:100]}{'...' if len(previous_content) > 100 else ''}'"
        log_details += f" - New: '{content[:100]}{'...' if len(content) > 100 else ''}'"
        
        await self.log_utility_action(action, guild, member, log_details)

        embed = discord.Embed(
            title=f"✅ Role Information {'Updated' if had_previous_info else 'Added'}",
            description=f"Custom information {'updated' if had_previous_info else 'added'} for {role.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Content", value=content[:1024], inline=False)

        await respond(embed=embed)

    async def _remove_role_info(self, ctx_or_interaction, role: discord.Role):
        """Remove custom role information implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_util_admin_permission(member):
            await respond("❌ You don't have permission to remove role information.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if str(role.id) not in guild_config["role_info"]:
            await respond("❌ This role doesn't have any custom information to remove.", ephemeral=True)
            return

        # Store the content for logging
        removed_content = guild_config["role_info"][str(role.id)]
        
        # Remove the custom info
        del guild_config["role_info"][str(role.id)]
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        # Log the action
        log_details = f"Role: {role.name} ({role.id}) - Removed: '{removed_content[:100]}{'...' if len(removed_content) > 100 else ''}'"
        await self.log_utility_action("role_info_removed", guild, member, log_details)

        embed = discord.Embed(
            title="✅ Role Information Removed",
            description=f"Custom information removed for {role.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Removed Content", value=removed_content[:1024], inline=False)

        await respond(embed=embed)

    async def _diag_role(self, ctx_or_interaction, role: discord.Role):
        """Role diagnosis implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        # Log the action
        await self.log_utility_action("role_diagnosed", guild, user, f"Role: {role.name} ({role.id})")

        permissions = role.permissions
        formatted_perms = self._format_permissions(permissions)

        # Create embeds for each category
        embeds = []
        
        # Main embed
        main_embed = discord.Embed(
            title=f"🔍 Role Diagnosis: {role.name}",
            description=f"Detailed permission analysis for {role.mention}",
            color=role.color if role.color != discord.Color.default() else discord.Color.blue()
        )
        
        total_perms = len([p for p in permissions if p[1]])
        main_embed.add_field(
            name="Summary",
            value=f"**Total Permissions:** {total_perms}/38\n**Administrator:** {'Yes' if permissions.administrator else 'No'}",
            inline=False
        )

        if permissions.administrator:
            main_embed.add_field(
                name="⚠️ Administrator Role",
                value="This role has administrator permissions, granting access to all server functions.",
                inline=False
            )

        embeds.append(main_embed)

        # Category embeds
        for category, perms in formatted_perms.items():
            if perms:
                embed = discord.Embed(
                    title=f"{category} Permissions",
                    description="\n".join(perms[:20]),  # Limit to 20 per embed
                    color=role.color if role.color != discord.Color.default() else discord.Color.blue()
                )
                embeds.append(embed)

        # Send first embed, then follow up with others
        await respond(embed=embeds[0])
        
        if len(embeds) > 1:
            for embed in embeds[1:]:
                if isinstance(ctx_or_interaction, discord.Interaction):
                    await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx_or_interaction.send(embed=embed)

    async def _avatar(self, ctx_or_interaction, user: Union[discord.Member, discord.User] = None):
        """Avatar implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            if user is None:
                user = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            requester = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            if user is None:
                user = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            requester = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        # Log the action
        await self.log_utility_action("avatar_viewed", guild, requester, f"Target: {user.name} ({user.id})")

        embed = discord.Embed(
            title=f"🖼️ {user.display_name}'s Avatar",
            color=discord.Color.blue()
        )
        
        # Default avatar
        embed.set_image(url=user.display_avatar.with_size(1024).url)
        
        # Avatar info
        embed.add_field(
            name="Avatar Info",
            value=f"**Animated:** {'Yes' if user.display_avatar.is_animated() else 'No'}\n**Format:** {'GIF' if user.display_avatar.is_animated() else 'PNG/JPG/WebP'}",
            inline=True
        )
        
        # Direct link
        embed.add_field(
            name="Direct Link",
            value=f"[Click here]({user.display_avatar.with_size(1024).url})",
            inline=True
        )

        # Server avatar vs global avatar
        if isinstance(user, discord.Member) and user.avatar != user.guild_avatar:
            if user.guild_avatar:
                embed.add_field(
                    name="Server Avatar",
                    value=f"[Server Specific]({user.guild_avatar.with_size(1024).url})",
                    inline=True
                )

        view = AvatarView(user)
        await respond(embed=embed, view=view)

    async def _shorten(self, ctx_or_interaction, url: str):
        """URL shortener implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            user = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        # Validate URL format
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)

        if not url_pattern.match(url):
            await respond("❌ Please provide a valid URL (must start with http:// or https://)", ephemeral=True)
            return

        # Show loading message
        embed = discord.Embed(
            title="🔗 Shortening URL...",
            description="Please wait while I shorten your URL.",
            color=discord.Color.blue()
        )
        await respond(embed=embed)

        # Shorten URL
        shortened = await self._shorten_url(url)

        # Log the action
        success = shortened is not None
        log_details = f"URL: {url[:100]}{'...' if len(url) > 100 else ''} - Success: {success}"
        if success:
            log_details += f" - Shortened: {shortened}"
        await self.log_utility_action("url_shortened", guild, user, log_details)

        if shortened:
            result_embed = discord.Embed(
                title="✅ URL Shortened",
                color=discord.Color.green()
            )
            result_embed.add_field(
                name="Original URL",
                value=f"```{url[:100]}{'...' if len(url) > 100 else ''}```",
                inline=False
            )
            result_embed.add_field(
                name="Shortened URL",
                value=f"[{shortened}]({shortened})",
                inline=False
            )
            result_embed.add_field(
                name="Copy",
                value=f"```{shortened}```",
                inline=False
            )
        else:
            result_embed = discord.Embed(
                title="❌ Failed to Shorten URL",
                description="Unable to shorten the provided URL. Please check if the URL is valid and accessible.",
                color=discord.Color.red()
            )

        # Edit the original message
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.edit_original_response(embed=result_embed)
        else:
            # For prefix commands, send a new message
            await ctx_or_interaction.send(embed=result_embed)

async def setup(bot):
    await bot.add_cog(UtilityCog(bot))
