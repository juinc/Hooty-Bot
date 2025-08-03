"""
Discord WelcomeCog - Welcome & Goodbye Message System

OVERVIEW:
A flexible welcome/goodbye system for Discord servers.  
Sends custom messages (with embed support) to channels and DMs on member join/leave.  
Supports per-guild config, message variables, logging, and both slash and prefix commands.

SETUP:
- No manual setup required – auto-creates config at src/config/joins_config.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.welcome.admin' or Administrator

COMMANDS (Slash & Prefix):
/welcome enable/disable                  - Enable/disable the welcome system (admin)
/welcome setchannel <channel>            - Set the channel for welcome/goodbye messages (admin)
/welcome setlogchannel <channel>         - Set the join/leave log channel (admin)
/welcome setmessage                      - Configure welcome message (modal, admin)
/welcome setleavingmessage               - Configure leaving message (modal, admin)
/welcome setdm                           - Configure welcome DM (modal, admin)
/welcome setleavingdm                    - Configure leaving DM (modal, admin)
/welcome toggle <on/off>                 - Enable/disable welcome messages (admin)
/welcome toggleleaving <on/off>          - Enable/disable leaving messages (admin)
/welcome toggledm <on/off>               - Enable/disable welcome DMs (admin)
/welcome toggleleavingdm <on/off>        - Enable/disable leaving DMs (admin)
/welcome test                            - Test all welcome messages (admin)
/welcome config                          - View current configuration

Prefix commands: !welcome <subcommand> (same as above)

COMMAND EXPLANATIONS:
- enable/disable: Enable or disable the entire welcome system.
- setchannel/setlogchannel: Set the channel for welcome/goodbye or log messages.
- setmessage/setleavingmessage/setdm/setleavingdm: Configure message content and embed (modal for slash).
- toggle/toggleleaving/toggledm/toggleleavingdm: Enable/disable each message type.
- test: Send test messages to check configuration.
- config: Show all current settings and message statuses.

FEATURES:
• Customizable welcome/goodbye messages (channel and DM)
• Embed support for all messages (title, description, color, footer)
• Per-guild enable/disable and per-message toggles
• Message variables: {user}, {user_name}, {guild}, {member_count}
• Logging to LoggingCog (if present)
• Permission checks (if PermissionsCog present)
• Persistent, per-guild config (JSON)
• Both slash and prefix command support
• Modal-based message configuration (slash)

USAGE BY OTHER COGS:
# Access welcome config for integrations
welcome_cog = bot.get_cog('WelcomeCog')
if welcome_cog:
    config = welcome_cog._load_config()
    guild_config = welcome_cog._get_guild_config(guild.id)
    welcome_message = guild_config["welcome"]["content"]
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

class MessageConfigModal(discord.ui.Modal):
    def __init__(self, cog, message_type: str, current_config: dict):
        super().__init__(title=f"Configure {message_type.title()} Message", timeout=300)
        self.cog = cog
        self.message_type = message_type
        
        # Add text inputs based on current config
        self.message_content = discord.ui.TextInput(
            label="Message Content",
            placeholder="Enter message content (use {user} for mention, {user_name} for name)",
            default=current_config.get("content", ""),
            required=False,
            max_length=2000,
            style=discord.TextStyle.paragraph
        )
        
        self.embed_title = discord.ui.TextInput(
            label="Embed Title",
            placeholder="Enter embed title (leave empty for no embed)",
            default=current_config.get("embed", {}).get("title", ""),
            required=False,
            max_length=256
        )
        
        self.embed_description = discord.ui.TextInput(
            label="Embed Description",
            placeholder="Enter embed description",
            default=current_config.get("embed", {}).get("description", ""),
            required=False,
            max_length=4000,
            style=discord.TextStyle.paragraph
        )
        
        # Format color for display (convert int to hex if it exists)
        current_color = current_config.get("embed", {}).get("color")
        color_display = ""
        if current_color is not None and isinstance(current_color, int):
            color_display = f"#{current_color:06x}"
        elif current_color:
            color_display = str(current_color)
        
        self.embed_color = discord.ui.TextInput(
            label="Embed Color",
            placeholder="Enter hex color (e.g., #ff0000) or leave empty for default",
            default=color_display,
            required=False,
            max_length=7
        )
        
        self.embed_footer = discord.ui.TextInput(
            label="Embed Footer",
            placeholder="Enter embed footer text",
            default=current_config.get("embed", {}).get("footer", ""),
            required=False,
            max_length=2048
        )
        
        self.add_item(self.message_content)
        self.add_item(self.embed_title)
        self.add_item(self.embed_description)
        self.add_item(self.embed_color)
        self.add_item(self.embed_footer)

    async def on_submit(self, interaction: discord.Interaction):
        # Parse color
        color = None
        if self.embed_color.value.strip():
            try:
                color_str = self.embed_color.value.strip()
                if color_str.startswith("#"):
                    color = int(color_str[1:], 16)
                else:
                    color = int(color_str, 16)
                
                # Validate color range (Discord's limit is 0xFFFFFF = 16777215)
                if color < 0 or color > 16777215:
                    await interaction.response.send_message("❌ Color value must be between 0 and 16777215 (0x000000 to 0xFFFFFF)", ephemeral=True)
                    return
                    
            except ValueError:
                await interaction.response.send_message("❌ Invalid color format. Use hex format like #ff0000 or ff0000", ephemeral=True)
                return
        
        # Build config
        config = {
            "content": self.message_content.value,
            "has_embed": bool(self.embed_title.value or self.embed_description.value),
            "embed": {
                "title": self.embed_title.value,
                "description": self.embed_description.value,
                "color": color,
                "footer": self.embed_footer.value
            }
        }
        
        # Save config
        await self.cog._save_message_config(interaction, self.message_type, config)

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = "src/config"
        
        # Ensure directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # File path
        self.joins_config_path = os.path.join(self.config_dir, "joins_config.json")
        
        # Initialize config file
        self._init_config_file()

    def _init_config_file(self):
        """Initialize config file with default settings"""
        default_config = {
            "guilds": {}
        }
        
        if not os.path.exists(self.joins_config_path):
            with open(self.joins_config_path, 'w') as f:
                json.dump(default_config, f, indent=4)

    def _load_config(self) -> dict:
        """Load welcome configuration from file"""
        try:
            with open(self.joins_config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_config_file()
            with open(self.joins_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save welcome configuration to file"""
        with open(self.joins_config_path, 'w') as f:
            json.dump(data, f, indent=4)

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create guild welcome configuration"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "enabled": True,  # Cog enabled by default
                "welcome_channel_id": None,
                "log_channel_id": None,
                "welcome": {
                    "enabled": False,
                    "content": "Welcome {user} to {guild}!",
                    "has_embed": True,
                    "embed": {
                        "title": "Welcome!",
                        "description": "Welcome {user} to **{guild}**!\nWe now have {member_count} members!",
                        "color": 3447003,  # Blue
                        "footer": "Enjoy your stay!"
                    }
                },
                "leaving": {
                    "enabled": False,
                    "content": "{user_name} has left the server.",
                    "has_embed": True,
                    "embed": {
                        "title": "Goodbye!",
                        "description": "**{user_name}** has left {guild}.\nWe now have {member_count} members.",
                        "color": 15158332,  # Red
                        "footer": "We'll miss you!"
                    }
                },
                "welcome_dm": {
                    "enabled": False,
                    "content": "Welcome to {guild}, {user_name}!",
                    "has_embed": True,
                    "embed": {
                        "title": "Welcome!",
                        "description": "Hello {user_name}! Welcome to **{guild}**!\n\nFeel free to explore and have fun!",
                        "color": 3447003,  # Blue
                        "footer": "Sent from {guild}"
                    }
                },
                "leaving_dm": {
                    "enabled": False,
                    "content": "Goodbye {user_name}!",
                    "has_embed": True,
                    "embed": {
                        "title": "Goodbye!",
                        "description": "Thanks for being part of **{guild}**, {user_name}!\n\nYou're always welcome back!",
                        "color": 15158332,  # Red
                        "footer": "Sent from {guild}"
                    }
                }
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    def has_welcome_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has welcome admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.welcome.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_welcome_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log welcome actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Welcome {action}"
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
                    file_override="welcome_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log welcome action: {e}")

    def _format_message(self, content: str, user: discord.Member, guild: discord.Guild) -> str:
        """Format message content with variable replacements"""
        replacements = {
            "{user}": user.mention,
            "{user_name}": user.display_name,
            "{guild}": guild.name,
            "{member_count}": str(guild.member_count)
        }
        
        for placeholder, replacement in replacements.items():
            content = content.replace(placeholder, replacement)
        
        return content

    def _create_embed(self, embed_config: dict, user: discord.Member, guild: discord.Guild) -> discord.Embed:
        """Create an embed from configuration"""
        embed = discord.Embed()
        
        if embed_config.get("title"):
            embed.title = self._format_message(embed_config["title"], user, guild)
        
        if embed_config.get("description"):
            embed.description = self._format_message(embed_config["description"], user, guild)
        
        # Validate and set color
        color = embed_config.get("color")
        if color is not None:
            try:
                # Ensure color is an integer and within valid range
                if isinstance(color, str):
                    if color.startswith("#"):
                        color = int(color[1:], 16)
                    else:
                        color = int(color, 16)
                
                # Validate range
                if isinstance(color, int) and 0 <= color <= 16777215:
                    embed.color = discord.Color(color)
                else:
                    # Use default blue if invalid
                    embed.color = discord.Color.blue()
            except (ValueError, TypeError):
                # Use default blue if color parsing fails
                embed.color = discord.Color.blue()
        
        if embed_config.get("footer"):
            embed.set_footer(text=self._format_message(embed_config["footer"], user, guild))
        
        # Add user avatar as thumbnail
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.timestamp = datetime.now()
        
        return embed

    async def _send_message(self, channel: discord.TextChannel, message_config: dict, user: discord.Member, guild: discord.Guild):
        """Send a welcome/goodbye message"""
        content = None
        embed = None
        
        if message_config.get("content"):
            content = self._format_message(message_config["content"], user, guild)
        
        if message_config.get("has_embed") and message_config.get("embed"):
            embed = self._create_embed(message_config["embed"], user, guild)
        
        if content or embed:
            try:
                await channel.send(content=content, embed=embed)
            except discord.Forbidden:
                pass  # No permission to send messages
            except discord.HTTPException as e:
                print(f"Failed to send welcome message: {e}")

    async def _send_dm(self, user: discord.Member, message_config: dict, guild: discord.Guild):
        """Send a DM to the user"""
        content = None
        embed = None
        
        if message_config.get("content"):
            content = self._format_message(message_config["content"], user, guild)
        
        if message_config.get("has_embed") and message_config.get("embed"):
            embed = self._create_embed(message_config["embed"], user, guild)
        
        if content or embed:
            try:
                await user.send(content=content, embed=embed)
            except discord.Forbidden:
                pass  # User has DMs disabled
            except discord.HTTPException as e:
                print(f"Failed to send welcome DM: {e}")

    # ==================== SLASH COMMANDS ====================
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Handle member join events"""
        guild_config = self._get_guild_config(member.guild.id)
        
        # Check if cog is enabled for this guild
        if not guild_config.get("enabled", True):
            return
        
        # Log the join
        await self.log_welcome_action("member_join", member.guild, member, f"Guild: {member.guild.name}")
        
        # Send welcome message
        if guild_config["welcome"]["enabled"] and guild_config["welcome_channel_id"]:
            channel = member.guild.get_channel(guild_config["welcome_channel_id"])
            if channel:
                await self._send_message(channel, guild_config["welcome"], member, member.guild)
        
        # Send welcome DM
        if guild_config["welcome_dm"]["enabled"]:
            await self._send_dm(member, guild_config["welcome_dm"], member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Handle member leave events"""
        guild_config = self._get_guild_config(member.guild.id)
        
        # Check if cog is enabled for this guild
        if not guild_config.get("enabled", True):
            return
        
        # Log the leave
        await self.log_welcome_action("member_leave", member.guild, member, f"Guild: {member.guild.name}")
        
        # Send leaving message
        if guild_config["leaving"]["enabled"] and guild_config["welcome_channel_id"]:
            channel = member.guild.get_channel(guild_config["welcome_channel_id"])
            if channel:
                await self._send_message(channel, guild_config["leaving"], member, member.guild)
        
        # Send leaving DM
        if guild_config["leaving_dm"]["enabled"]:
            await self._send_dm(member, guild_config["leaving_dm"], member.guild)

    # SLASH COMMANDS
    welcome_group = app_commands.Group(name="welcome", description="Welcome system commands")

    @welcome_group.command(name="enable", description="Enable the welcome system for this server")
    async def enable_slash(self, interaction: discord.Interaction):
        """Enable the welcome system"""
        await self._toggle_cog(interaction, True)

    @welcome_group.command(name="disable", description="Disable the welcome system for this server")
    async def disable_slash(self, interaction: discord.Interaction):
        """Disable the welcome system"""
        await self._toggle_cog(interaction, False)

    @welcome_group.command(name="setchannel", description="Set the welcome/goodbye messages channel")
    @app_commands.describe(channel="Channel for welcome and goodbye messages")
    async def setchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Set the welcome channel"""
        await self._set_channel(interaction, channel)

    @welcome_group.command(name="setlogchannel", description="Set the join/leave log channel")
    @app_commands.describe(channel="Channel for join/leave logs")
    async def setlogchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Set the log channel"""
        await self._set_log_channel(interaction, channel)

    @welcome_group.command(name="setmessage", description="Configure welcome message")
    async def setmessage_slash(self, interaction: discord.Interaction):
        """Configure welcome message with modal"""
        await self._configure_message(interaction, "welcome")

    @welcome_group.command(name="setleavingmessage", description="Configure leaving message")
    async def setleavingmessage_slash(self, interaction: discord.Interaction):
        """Configure leaving message with modal"""
        await self._configure_message(interaction, "leaving")

    @welcome_group.command(name="setdm", description="Configure welcome DM")
    async def setdm_slash(self, interaction: discord.Interaction):
        """Configure welcome DM with modal"""
        await self._configure_message(interaction, "welcome_dm")

    @welcome_group.command(name="setleavingdm", description="Configure leaving DM")
    async def setleavingdm_slash(self, interaction: discord.Interaction):
        """Configure leaving DM with modal"""
        await self._configure_message(interaction, "leaving_dm")

    @welcome_group.command(name="toggle", description="Toggle welcome messages")
    @app_commands.describe(enabled="Enable or disable welcome messages")
    async def toggle_slash(self, interaction: discord.Interaction, enabled: bool):
        """Toggle welcome messages"""
        await self._toggle_message(interaction, "welcome", enabled)

    @welcome_group.command(name="toggleleaving", description="Toggle leaving messages")
    @app_commands.describe(enabled="Enable or disable leaving messages")
    async def toggleleaving_slash(self, interaction: discord.Interaction, enabled: bool):
        """Toggle leaving messages"""
        await self._toggle_message(interaction, "leaving", enabled)

    @welcome_group.command(name="toggledm", description="Toggle welcome DMs")
    @app_commands.describe(enabled="Enable or disable welcome DMs")
    async def toggledm_slash(self, interaction: discord.Interaction, enabled: bool):
        """Toggle welcome DMs"""
        await self._toggle_message(interaction, "welcome_dm", enabled)

    @welcome_group.command(name="toggleleavingdm", description="Toggle leaving DMs")
    @app_commands.describe(enabled="Enable or disable leaving DMs")
    async def toggleleavingdm_slash(self, interaction: discord.Interaction, enabled: bool):
        """Toggle leaving DMs"""
        await self._toggle_message(interaction, "leaving_dm", enabled)

    @welcome_group.command(name="test", description="Test welcome messages")
    async def test_slash(self, interaction: discord.Interaction):
        """Test welcome messages"""
        await self._test_welcome(interaction)

    @welcome_group.command(name="config", description="View current welcome configuration")
    async def config_slash(self, interaction: discord.Interaction):
        """View current configuration"""
        await self._view_config(interaction)

    # ==================== PREFIX COMMANDS ====================
    @commands.group(name="welcome", invoke_without_command=True)
    async def welcome_prefix(self, ctx):
        """Welcome system commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="👋 Welcome System Commands",
                description="Available commands for managing welcome/goodbye messages",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="System Control",
                value="• `enable` - Enable welcome system\n• `disable` - Disable welcome system",
                inline=False
            )
            embed.add_field(
                name="Channel Setup",
                value="• `setchannel <channel>` - Set welcome/goodbye channel\n• `setlogchannel <channel>` - Set join/leave log channel",
                inline=False
            )
            embed.add_field(
                name="Message Configuration",
                value="• `setmessage` - Configure welcome message\n• `setleavingmessage` - Configure leaving message\n• `setdm` - Configure welcome DM\n• `setleavingdm` - Configure leaving DM",
                inline=False
            )
            embed.add_field(
                name="Toggle Commands",
                value="• `toggle <true/false>` - Toggle welcome messages\n• `toggleleaving <true/false>` - Toggle leaving messages\n• `toggledm <true/false>` - Toggle welcome DMs\n• `toggleleavingdm <true/false>` - Toggle leaving DMs",
                inline=False
            )
            embed.add_field(
                name="Other Commands",
                value="• `test` - Test all welcome messages\n• `config` - View current configuration",
                inline=False
            )
            await ctx.send(embed=embed)

    @welcome_prefix.command(name="enable")
    async def enable_prefix(self, ctx):
        """Enable the welcome system"""
        await self._toggle_cog(ctx, True)

    @welcome_prefix.command(name="disable")
    async def disable_prefix(self, ctx):
        """Disable the welcome system"""
        await self._toggle_cog(ctx, False)

    @welcome_prefix.command(name="setchannel")
    async def setchannel_prefix(self, ctx, channel: discord.TextChannel = None):
        """Set the welcome channel"""
        await self._set_channel(ctx, channel)

    @welcome_prefix.command(name="setlogchannel")
    async def setlogchannel_prefix(self, ctx, channel: discord.TextChannel = None):
        """Set the log channel"""
        await self._set_log_channel(ctx, channel)

    @welcome_prefix.command(name="setmessage")
    async def setmessage_prefix(self, ctx):
        """Configure welcome message"""
        await self._configure_message(ctx, "welcome")

    @welcome_prefix.command(name="setleavingmessage")
    async def setleavingmessage_prefix(self, ctx):
        """Configure leaving message"""
        await self._configure_message(ctx, "leaving")

    @welcome_prefix.command(name="setdm")
    async def setdm_prefix(self, ctx):
        """Configure welcome DM"""
        await self._configure_message(ctx, "welcome_dm")

    @welcome_prefix.command(name="setleavingdm")
    async def setleavingdm_prefix(self, ctx):
        """Configure leaving DM"""
        await self._configure_message(ctx, "leaving_dm")

    @welcome_prefix.command(name="toggle")
    async def toggle_prefix(self, ctx, enabled: bool):
        """Toggle welcome messages"""
        await self._toggle_message(ctx, "welcome", enabled)

    @welcome_prefix.command(name="toggleleaving")
    async def toggleleaving_prefix(self, ctx, enabled: bool):
        """Toggle leaving messages"""
        await self._toggle_message(ctx, "leaving", enabled)

    @welcome_prefix.command(name="toggledm")
    async def toggledm_prefix(self, ctx, enabled: bool):
        """Toggle welcome DMs"""
        await self._toggle_message(ctx, "welcome_dm", enabled)

    @welcome_prefix.command(name="toggleleavingdm")
    async def toggleleavingdm_prefix(self, ctx, enabled: bool):
        """Toggle leaving DMs"""
        await self._toggle_message(ctx, "leaving_dm", enabled)

    @welcome_prefix.command(name="test")
    async def test_prefix(self, ctx):
        """Test welcome messages"""
        await self._test_welcome(ctx)

    @welcome_prefix.command(name="config")
    async def config_prefix(self, ctx):
        """View current configuration"""
        await self._view_config(ctx)

    # ==================== IMPLEMENTATION METHODS ====================
    async def _toggle_cog(self, ctx_or_interaction, enabled: bool):
        """Toggle the entire welcome cog on/off"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_welcome_admin_permission(member):
            await respond("❌ You don't have permission to configure welcome settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        guild_config["enabled"] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        # Log the cog toggle action
        action = "enabled" if enabled else "disabled"
        await self.log_welcome_action(f"cog_{action}", guild, member, f"Welcome system {action}")
        
        status = "enabled" if enabled else "disabled"
        embed = discord.Embed(
            title=f"✅ Welcome System {status.title()}",
            description=f"The welcome system has been {status} for this server.",
            color=discord.Color.green() if enabled else discord.Color.red()
        )
        
        await respond(embed=embed)

    async def _set_channel(self, ctx_or_interaction, channel: discord.TextChannel):
        """Set welcome channel implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_welcome_admin_permission(member):
            await respond("❌ You don't have permission to configure welcome settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if channel:
            guild_config["welcome_channel_id"] = channel.id
            embed = discord.Embed(
                title="✅ Welcome Channel Set",
                description=f"Welcome and goodbye messages will be sent to {channel.mention}",
                color=discord.Color.green()
            )
            await self.log_welcome_action("channel_set", guild, member, f"Channel: {channel.name}")
        else:
            guild_config["welcome_channel_id"] = None
            embed = discord.Embed(
                title="✅ Welcome Channel Removed",
                description="Welcome and goodbye messages are now disabled",
                color=discord.Color.green()
            )
            await self.log_welcome_action("channel_removed", guild, member)
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        await respond(embed=embed)

    async def _set_log_channel(self, ctx_or_interaction, channel: discord.TextChannel):
        """Set log channel implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_welcome_admin_permission(member):
            await respond("❌ You don't have permission to configure welcome settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if channel:
            guild_config["log_channel_id"] = channel.id
            embed = discord.Embed(
                title="✅ Log Channel Set",
                description=f"Join/leave logs will be sent to {channel.mention}",
                color=discord.Color.green()
            )
            await self.log_welcome_action("log_channel_set", guild, member, f"Channel: {channel.name}")
        else:
            guild_config["log_channel_id"] = None
            embed = discord.Embed(
                title="✅ Log Channel Removed",
                description="Join/leave logs will only be written to file",
                color=discord.Color.green()
            )
            await self.log_welcome_action("log_channel_removed", guild, member)
        
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        await respond(embed=embed)

    async def _configure_message(self, ctx_or_interaction, message_type: str):
        """Configure message using modal"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild

        if not self.has_welcome_admin_permission(member):
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message("❌ You don't have permission to configure welcome settings.", ephemeral=True)
            else:
                await ctx_or_interaction.send("❌ You don't have permission to configure welcome settings.")
            return

        guild_config = self._get_guild_config(guild.id)
        current_config = guild_config.get(message_type, {})
        
        modal = MessageConfigModal(self, message_type, current_config)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_modal(modal)
        else:
            # For prefix commands, we can't use modals, so provide instructions
            embed = discord.Embed(
                title="Message Configuration",
                description=f"To configure {message_type.replace('_', ' ')} messages, please use the slash command version:\n`/welcome {message_type.replace('_', '')}`",
                color=discord.Color.blue()
            )
            await ctx_or_interaction.send(embed=embed)

    async def _save_message_config(self, interaction: discord.Interaction, message_type: str, config: dict):
        """Save message configuration from modal"""
        config_data = self._load_config()
        guild_config = self._get_guild_config(interaction.guild.id)
        
        guild_config[message_type] = config
        config_data["guilds"][str(interaction.guild.id)] = guild_config
        self._save_config(config_data)
        
        # Log the configuration change
        await self.log_welcome_action("message_configured", interaction.guild, interaction.user, f"Type: {message_type}")
        
        embed = discord.Embed(
            title="✅ Message Configuration Saved",
            description=f"{message_type.replace('_', ' ').title()} message has been configured.",
            color=discord.Color.green()
        )
        
        # Show preview
        if config.get("content"):
            embed.add_field(name="Content", value=config["content"][:1024], inline=False)
        
        if config.get("has_embed") and config.get("embed", {}).get("title"):
            embed.add_field(name="Embed Title", value=config["embed"]["title"][:1024], inline=True)
        
        if config.get("has_embed") and config.get("embed", {}).get("description"):
            embed.add_field(name="Embed Description", value=config["embed"]["description"][:1024], inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _toggle_message(self, ctx_or_interaction, message_type: str, enabled: bool):
        """Toggle message type"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_welcome_admin_permission(member):
            await respond("❌ You don't have permission to configure welcome settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        guild_config[message_type]["enabled"] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        # Log the toggle action
        action = "enabled" if enabled else "disabled"
        await self.log_welcome_action(f"message_{action}", guild, member, f"Type: {message_type}")
        
        status = "enabled" if enabled else "disabled"
        embed = discord.Embed(
            title=f"✅ {message_type.replace('_', ' ').title()} {status.title()}",
            description=f"{message_type.replace('_', ' ').title()} messages have been {status}.",
            color=discord.Color.green() if enabled else discord.Color.red()
        )
        
        await respond(embed=embed)

    async def _test_welcome(self, ctx_or_interaction):
        """Test welcome messages"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_welcome_admin_permission(member):
            await respond("❌ You don't have permission to test welcome settings.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)
        
        # Log the test action
        await self.log_welcome_action("test_messages", guild, member)
        
        # Test welcome message
        if guild_config["welcome"]["enabled"] and guild_config["welcome_channel_id"]:
            channel = guild.get_channel(guild_config["welcome_channel_id"])
            if channel:
                await self._send_message(channel, guild_config["welcome"], member, guild)
        
        # Test welcome DM
        if guild_config["welcome_dm"]["enabled"]:
            await self._send_dm(member, guild_config["welcome_dm"], guild)
        
        embed = discord.Embed(
            title="✅ Test Messages Sent",
            description="Test welcome messages have been sent (if enabled).",
            color=discord.Color.green()
        )
        
        await respond(embed=embed, ephemeral=True)

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
            title="👋 Welcome System Configuration",
            color=discord.Color.blue()
        )
        
        # System status
        system_status = "🟢 Enabled" if guild_config.get("enabled", True) else "🔴 Disabled"
        embed.add_field(
            name="System Status",
            value=system_status,
            inline=False
        )
        
        # Channel settings
        welcome_channel = guild.get_channel(guild_config["welcome_channel_id"]) if guild_config["welcome_channel_id"] else None
        log_channel = guild.get_channel(guild_config["log_channel_id"]) if guild_config["log_channel_id"] else None
        
        embed.add_field(
            name="Channels",
            value=f"Welcome: {welcome_channel.mention if welcome_channel else 'Not set'}\nLogs: {log_channel.mention if log_channel else 'Not set'}",
            inline=False
        )
        
        # Message statuses
        statuses = []
        for msg_type in ["welcome", "leaving", "welcome_dm", "leaving_dm"]:
            status = "🟢 Enabled" if guild_config[msg_type]["enabled"] else "🔴 Disabled"
            statuses.append(f"{msg_type.replace('_', ' ').title()}: {status}")
        
        embed.add_field(
            name="Message Status",
            value="\n".join(statuses),
            inline=False
        )
        
        embed.add_field(
            name="Available Variables",
            value="`{user}` - User mention\n`{user_name}` - User display name\n`{guild}` - Server name\n`{member_count}` - Member count",
            inline=False
        )
        
        await respond(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
