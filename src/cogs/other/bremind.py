"""
Discord BumpRemindCog - Automated Bump Reminder System

OVERVIEW:
Automates bump reminders for Disboard/BumpBot and similar bots. Tracks bump cooldowns, sends reminders to configured channels, supports role pings, and can update channel topics with bump timers. Fully configurable per-server.

SETUP:
- No manual setup required – auto-creates config file at src/config/bremind_config.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.bremind.admin' or Administrator

COMMANDS:
/bremind toggle [on/off]                - Enable or disable bump reminders
/bremind status                         - Show detailed system status
/bremind config                         - Show current configuration
/bremind message <msg> [embed opts]     - Set reminder message (plain or embed)
/bremind role [role]                    - Set or clear ping role for reminders
/bremind channel add <channel>          - Add a channel for reminders
/bremind channel remove <channel>       - Remove a channel from reminders
/bremind channel list                   - List all reminder channels
/bremind channel clear                  - Remove all reminder channels
/bremind channelstatus [on/off]         - Enable/disable channel topic bump timers
/bremind test                           - Send a test bump reminder

Prefix commands: !bremind <subcommand> (same functionality)

FEATURES:
• Detects successful bumps from Disboard/BumpBot (and others, easily extendable)
• Sends bump reminders to one or more channels after 2h cooldown
• Supports custom reminder messages (plain or embed, with {role} placeholder)
• Optional role ping for reminders
• Channel topic auto-updates with bump timer/status (optional)
• All settings configurable via commands (channels, message, role, embed, etc.)
• Per-server persistent config (JSON)
• Admin-only configuration and test commands
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Both slash and prefix command support
"""

import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
from datetime import datetime, timedelta
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

class BumpRemindCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/bremind_config.json"
        self.config = self.load_config()
        self.bump_timers = {}  # guild_id: datetime when next bump is available
        self.reminder_tasks = {}  # guild_id: asyncio.Task for pending reminders
        self.channel_status_update.start()

    def load_config(self):
        """Load configuration from file"""
        try:
            if not os.path.exists("src/config"):
                os.makedirs("src/config")
            
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    # Convert saved bump times back to datetime objects
                    for guild_id, config in data.items():
                        if "last_bump_time" in config and config["last_bump_time"]:
                            try:
                                config["last_bump_time"] = datetime.fromisoformat(config["last_bump_time"])
                                # Calculate next bump time
                                next_bump = config["last_bump_time"] + timedelta(hours=2)
                                if next_bump > datetime.now():
                                    self.bump_timers[int(guild_id)] = next_bump
                            except:
                                config["last_bump_time"] = None
                    return data
            return {}
        except Exception as e:
            print(f"Error loading bump remind config: {e}")
            return {}

    def save_config(self):
        """Save configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            # Convert datetime objects to strings for JSON serialization
            save_data = {}
            for guild_id, config in self.config.items():
                save_data[guild_id] = config.copy()
                if "last_bump_time" in config and config["last_bump_time"]:
                    save_data[guild_id]["last_bump_time"] = config["last_bump_time"].isoformat()
            
            with open(self.config_file, 'w') as f:
                json.dump(save_data, f, indent=2)
        except Exception as e:
            print(f"Error saving bump remind config: {e}")

    def get_guild_config(self, guild_id: int):
        """Get configuration for a specific guild"""
        guild_id = str(guild_id)
        if guild_id not in self.config:
            self.config[guild_id] = {
                "enabled": False,
                "channels": [],
                "ping_role": None,
                "message": "🔄 Time to bump the server! {role}",
                "embed": False,
                "embed_title": "Bump Reminder",
                "embed_description": "Time to bump the server! {role}",
                "embed_color": 0x00ff00,
                "channel_status_enabled": False,
                "last_bump_time": None
            }
            self.save_config()
        return self.config[guild_id]

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has bump remind admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.bremind.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_bremind_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log bump remind actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Bump Remind {action}"
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
                    file_override="bremind_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log bump remind action: {e}")

    # ==================== EVENT LISTENERS ====================
    @commands.Cog.listener()
    async def on_message(self, message):
        """Detect bump messages"""
        if message.author.bot and message.guild:
            await self.detect_bump(message)

    async def detect_bump(self, message):
        """Detect if a message is a successful bump"""
        config = self.get_guild_config(message.guild.id)
        if not config["enabled"]:
            return

        # Common bump bot IDs and success indicators
        bump_detection = {
            302050872383242240: {  # Disboard
                "content": ["bump done! :thumbsup:", "bump done!"],
                "embed_descriptions": ["successfully bumped", "bump done"],
                "name": "Disboard"
            },
            716390085896962058: {  # BumpBot
                "content": ["successfully bumped"],
                "embed_descriptions": ["successfully bumped"],
                "name": "BumpBot"
            },
            # Add more bump bots as needed
        }

        if message.author.id in bump_detection:
            detection_config = bump_detection[message.author.id]
            message_content = message.content.lower()
            
            # Check message content
            for success_msg in detection_config.get("content", []):
                if success_msg.lower() in message_content:
                    await self.handle_successful_bump(message.guild, message.author, detection_config["name"])
                    return

            # Check embeds
            if message.embeds and "embed_descriptions" in detection_config:
                for embed in message.embeds:
                    embed_text = ""
                    if embed.description:
                        embed_text += embed.description.lower()
                    if embed.title:
                        embed_text += embed.title.lower()
                    
                    for success_msg in detection_config["embed_descriptions"]:
                        if success_msg.lower() in embed_text:
                            await self.handle_successful_bump(message.guild, message.author, detection_config["name"])
                            return

    async def handle_successful_bump(self, guild, bump_bot, bot_name):
        """Handle a successful bump"""
        config = self.get_guild_config(guild.id)
        
        # Cancel any existing reminder task
        if guild.id in self.reminder_tasks:
            self.reminder_tasks[guild.id].cancel()

        # Set bump time and timer
        bump_time = datetime.now()
        next_bump_time = bump_time + timedelta(hours=2)
        
        config["last_bump_time"] = bump_time
        self.bump_timers[guild.id] = next_bump_time
        self.save_config()

        await self.log_bremind_action(
            "bump detected", 
            guild, 
            details=f"bot: {bot_name}, next available: {next_bump_time.strftime('%H:%M:%S')}"
        )

        # Schedule reminder task
        self.reminder_tasks[guild.id] = asyncio.create_task(self.schedule_reminder(guild))

    async def schedule_reminder(self, guild):
        """Schedule and send bump reminder after 2 hours"""
        try:
            await asyncio.sleep(2 * 60 * 60)  # 2 hours
            await self.send_bump_reminder(guild)
        except asyncio.CancelledError:
            # Task was cancelled (new bump detected)
            await self.log_bremind_action("reminder cancelled", guild, details="new bump detected")

    async def send_bump_reminder(self, guild):
        """Send bump reminder to configured channels"""
        config = self.get_guild_config(guild.id)
        if not config["enabled"]:
            await self.log_bremind_action("reminder skipped", guild, details="system disabled")
            return

        # Remove from active timers
        if guild.id in self.bump_timers:
            del self.bump_timers[guild.id]
        if guild.id in self.reminder_tasks:
            del self.reminder_tasks[guild.id]

        # Get role mention
        role_mention = ""
        role_name = "none"
        if config["ping_role"]:
            role = guild.get_role(config["ping_role"])
            if role:
                role_mention = role.mention
                role_name = role.name

        # Send to all configured channels
        sent_count = 0
        failed_channels = []
        
        for channel_id in config["channels"]:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    if config["embed"]:
                        embed = discord.Embed(
                            title=config["embed_title"],
                            description=config["embed_description"].replace("{role}", role_mention),
                            color=config["embed_color"]
                        )
                        await channel.send(embed=embed)
                    else:
                        message_text = config["message"].replace("{role}", role_mention)
                        await channel.send(message_text)
                    
                    sent_count += 1
                except Exception as e:
                    failed_channels.append(f"{channel.name}: {str(e)}")

        # Log results
        if sent_count > 0:
            details = f"sent to {sent_count} channels, role: {role_name}"
            if failed_channels:
                details += f", failed: {len(failed_channels)}"
            await self.log_bremind_action("reminder sent", guild, details=details)
        
        if failed_channels:
            await self.log_bremind_action(
                "reminder send failures", 
                guild, 
                details=f"failed channels: {', '.join(failed_channels[:3])}"  # Limit details length
            )

    @tasks.loop(minutes=1)
    async def channel_status_update(self):
        """Update channel status for all guilds"""
        for guild_id_str, config in self.config.items():
            if not config.get("enabled", False) or not config.get("channel_status_enabled", False):
                continue

            guild_id = int(guild_id_str)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            # Calculate time until next bump
            if guild_id in self.bump_timers:
                next_bump = self.bump_timers[guild_id]
                now = datetime.now()
                
                if now >= next_bump:
                    status = "Ready to bump!"
                else:
                    time_left = next_bump - now
                    hours, remainder = divmod(int(time_left.total_seconds()), 3600)
                    minutes, _ = divmod(remainder, 60)
                    status = f"Next bump: {hours}h {minutes}m"
            else:
                status = "Ready to bump!"

            # Update channel topics for configured channels
            for channel_id in config["channels"]:
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        current_topic = channel.topic or ""
                        # Remove old bump status from topic
                        lines = current_topic.split('\n')
                        filtered_lines = [line for line in lines if not line.startswith("🔄")]
                        
                        # Add new status
                        new_topic = '\n'.join(filtered_lines)
                        if new_topic:
                            new_topic += f"\n🔄 {status}"
                        else:
                            new_topic = f"🔄 {status}"
                        
                        # Discord topic limit is 1024 characters
                        if len(new_topic) <= 1024 and new_topic != current_topic:
                            await channel.edit(topic=new_topic)
                    except:
                        pass  # Ignore errors (might not have permission)

    @channel_status_update.before_loop
    async def before_channel_status_update(self):
        await self.bot.wait_until_ready()

    # ==================== COMMANDS ====================
    # Hybrid Command Group
    @commands.hybrid_group(name="bremind", invoke_without_command=True)
    async def bremind(self, ctx):
        """Bump reminder configuration commands"""
        if ctx.invoked_subcommand is None:
            config = self.get_guild_config(ctx.guild.id)
            
            embed = discord.Embed(
                title="🔄 Bump Reminder Configuration",
                color=0x00ff00 if config["enabled"] else 0xff0000
            )
            
            # System status
            status_emoji = "✅" if config["enabled"] else "⏸️"
            embed.add_field(
                name=f"{status_emoji} System Status", 
                value="**Enabled**" if config["enabled"] else "**Disabled**", 
                inline=True
            )
            
            # Channel status
            channel_status_emoji = "✅" if config.get("channel_status_enabled", False) else "❌"
            embed.add_field(
                name=f"{channel_status_emoji} Channel Status", 
                value="Enabled" if config.get("channel_status_enabled", False) else "Disabled", 
                inline=True
            )
            
            # Show next bump time
            if ctx.guild.id in self.bump_timers:
                next_bump = self.bump_timers[ctx.guild.id]
                time_left = next_bump - datetime.now()
                if time_left.total_seconds() > 0:
                    hours, remainder = divmod(int(time_left.total_seconds()), 3600)
                    minutes, _ = divmod(remainder, 60)
                    embed.add_field(
                        name="⏰ Next Bump", 
                        value=f"{hours}h {minutes}m", 
                        inline=True
                    )
                else:
                    embed.add_field(name="⏰ Next Bump", value="Ready now!", inline=True)
            else:
                embed.add_field(name="⏰ Next Bump", value="Ready now!", inline=True)
            
            # Show channels
            channels = []
            for channel_id in config["channels"]:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    channels.append(channel.mention)
            
            embed.add_field(
                name="📺 Channels", 
                value="\n".join(channels) if channels else "None configured", 
                inline=False
            )
            
            # Show ping role
            if config["ping_role"]:
                role = ctx.guild.get_role(config["ping_role"])
                embed.add_field(
                    name="🔔 Ping Role", 
                    value=role.mention if role else "Role not found", 
                    inline=True
                )
            
            # Message type
            message_type = "Embed" if config["embed"] else "Text"
            embed.add_field(
                name="💬 Message Type",
                value=message_type,
                inline=True
            )
            
            embed.add_field(
                name="📋 Commands", 
                value="`/bremind toggle` - Enable/disable system\n"
                        "`/bremind status` - Show detailed status\n"
                        "`/bremind config` - Show configuration\n"
                        "`/bremind message` - Set reminder message\n"
                        "`/bremind role` - Set ping role\n"
                        "`/bremind channel` - Manage channels", 
                inline=False
            )
            
            if not config["enabled"]:
                embed.add_field(
                    name="ℹ️ Note",
                    value="System is disabled. Use `/bremind toggle` to enable.",
                    inline=False
                )
            
            await ctx.send(embed=embed)

    @bremind.command(name="toggle")
    @discord.app_commands.describe(enabled="Enable or disable the bump reminder system")
    async def bremind_toggle(self, ctx, enabled: Optional[bool] = None):
        """Toggle bump reminders on/off (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure bump reminder settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        # If no argument provided, toggle current state
        if enabled is None:
            enabled = not config["enabled"]
        
        old_state = config["enabled"]
        config["enabled"] = enabled
        self.save_config()

        # Cancel reminder tasks if disabling
        if not enabled and ctx.guild.id in self.reminder_tasks:
            self.reminder_tasks[ctx.guild.id].cancel()
            del self.reminder_tasks[ctx.guild.id]

        # Create response embed
        if enabled:
            embed = discord.Embed(
                title="✅ Bump Reminders Enabled",
                description="The bump reminder system is now active and will detect bumps and send reminders.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Bump Reminders Disabled",
                description="The bump reminder system is now disabled. No bump detection or reminders will occur.",
                color=discord.Color.orange()
            )

        embed.add_field(
            name="Status Change",
            value=f"{'Enabled' if old_state else 'Disabled'} → {'Enabled' if enabled else 'Disabled'}",
            inline=True
        )

        await ctx.send(embed=embed)

        # Log the change
        details = f"enabled: {enabled}"
        if old_state != enabled:
            details += f" (was: {old_state})"
        
        await self.log_bremind_action("toggled system state", ctx.guild, ctx.author, details)

    @bremind.command(name="status")
    async def bremind_status(self, ctx):
        """Show detailed bump reminder status"""
        config = self.get_guild_config(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        if is_enabled:
            embed = discord.Embed(
                title="✅ Bump Reminder System Status",
                description="The bump reminder system is currently **enabled**.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Bump Reminder System Status", 
                description="The bump reminder system is currently **disabled**.",
                color=discord.Color.orange()
            )

        # Channels count
        channel_count = len(config["channels"])
        embed.add_field(
            name="📺 Configured Channels",
            value=f"{channel_count} channels",
            inline=True
        )

        # Role info
        role_text = "None"
        if config["ping_role"]:
            role = ctx.guild.get_role(config["ping_role"])
            role_text = role.mention if role else "Role not found"
        
        embed.add_field(
            name="🔔 Ping Role",
            value=role_text,
            inline=True
        )

        # Channel status
        channel_status = "Enabled" if config.get("channel_status_enabled", False) else "Disabled"
        embed.add_field(
            name="📊 Channel Status Updates",
            value=channel_status,
            inline=True
        )

        # Last bump info
        if config.get("last_bump_time"):
            last_bump = config["last_bump_time"]
            if isinstance(last_bump, str):
                last_bump = datetime.fromisoformat(last_bump)
            
            embed.add_field(
                name="🕒 Last Bump",
                value=f"<t:{int(last_bump.timestamp())}:R>",
                inline=True
            )

        # Next bump timer
        if ctx.guild.id in self.bump_timers:
            next_bump = self.bump_timers[ctx.guild.id]
            time_left = next_bump - datetime.now()
            if time_left.total_seconds() > 0:
                embed.add_field(
                    name="⏰ Next Bump Available",
                    value=f"<t:{int(next_bump.timestamp())}:R>",
                    inline=True
                )
            else:
                embed.add_field(
                    name="⏰ Next Bump Available",
                    value="Ready now!",
                    inline=True
                )

        # Message format
        message_format = "Embed" if config["embed"] else "Plain text"
        embed.add_field(
            name="💬 Message Format",
            value=message_format,
            inline=True
        )

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="While disabled, no bump detection or reminders will occur.",
                inline=False
            )

        await ctx.send(embed=embed)

    @bremind.command(name="config")
    async def bremind_config(self, ctx):
        """Show current bump reminder configuration"""
        config = self.get_guild_config(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        embed = discord.Embed(
            title="🔄 Bump Reminder Configuration",
            color=0x00ff00 if is_enabled else 0x808080
        )

        # System status
        status_emoji = "✅" if is_enabled else "⏸️"
        embed.add_field(
            name=f"{status_emoji} System Status",
            value=f"**{'Enabled' if is_enabled else 'Disabled'}**",
            inline=True
        )

        # Show all channels with details
        if config["channels"]:
            channel_list = []
            for channel_id in config["channels"]:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    channel_list.append(f"• {channel.mention}")
                else:
                    channel_list.append(f"• Unknown Channel ({channel_id})")
            
            embed.add_field(
                name="📺 Reminder Channels",
                value="\n".join(channel_list) if channel_list else "None configured",
                inline=False
            )
        else:
            embed.add_field(
                name="📺 Reminder Channels",
                value="None configured",
                inline=False
            )

        # Current message preview
        if config["embed"]:
            embed.add_field(
                name="💬 Message Format",
                value=f"**Embed**\nTitle: {config['embed_title']}\nDescription: {config['embed_description'][:100]}{'...' if len(config['embed_description']) > 100 else ''}",
                inline=False
            )
        else:
            message_preview = config['message'][:100] + ('...' if len(config['message']) > 100 else '')
            embed.add_field(
                name="💬 Message Format",
                value=f"**Plain Text**\n{message_preview}",
                inline=False
            )

        # Additional settings
        settings_text = []
        settings_text.append(f"Channel Status: {'Enabled' if config.get('channel_status_enabled', False) else 'Disabled'}")
        
        if config["ping_role"]:
            role = ctx.guild.get_role(config["ping_role"])
            settings_text.append(f"Ping Role: {role.mention if role else 'Role not found'}")
        else:
            settings_text.append("Ping Role: None")

        embed.add_field(
            name="⚙️ Settings",
            value="\n".join(settings_text),
            inline=False
        )

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="System is disabled. Use `/bremind toggle` to enable.",
                inline=False
            )

        await ctx.send(embed=embed)

    @bremind.command(name="message")
    @discord.app_commands.describe(
        message="The message to send for bump reminders (use {role} for role mention)",
        use_embed="Whether to send as an embed",
        embed_title="Title for the embed (if using embed)",
        embed_description="Description for the embed (if using embed)",
        embed_color="Color for the embed in hex format (e.g., #00ff00)"
    )
    async def set_message(self, ctx, message: str, use_embed: bool = False, 
                            embed_title: str = "Bump Reminder", 
                            embed_description: str = None, embed_color: str = "#00ff00"):
        """Set the bump reminder message (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure bump reminder settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        old_format = "embed" if config["embed"] else "text"
        
        if use_embed:
            config["embed"] = True
            config["embed_title"] = embed_title
            config["embed_description"] = embed_description or message
            
            # Parse color
            try:
                if embed_color.startswith("#"):
                    embed_color = embed_color[1:]
                config["embed_color"] = int(embed_color, 16)
            except:
                config["embed_color"] = 0x00ff00
            
            format_details = f"embed (title: {embed_title})"
        else:
            config["message"] = message
            config["embed"] = False
            format_details = "text message"
        
        self.save_config()

        embed = discord.Embed(
            title="✅ Message Updated",
            description="Bump reminder message has been configured successfully!",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Format Change",
            value=f"{old_format} → {'embed' if use_embed else 'text'}",
            inline=True
        )

        await ctx.send(embed=embed)
        await self.log_bremind_action("message updated", ctx.guild, ctx.author, format_details)

    @bremind.command(name="role")
    @discord.app_commands.describe(role="The role to ping for bump reminders (leave empty to remove)")
    async def set_role(self, ctx, role: discord.Role = None):
        """Set the role to ping for bump reminders (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure bump reminder settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        old_role_id = config["ping_role"]
        old_role = ctx.guild.get_role(old_role_id) if old_role_id else None
        
        if role is None:
            config["ping_role"] = None
            embed = discord.Embed(
                title="✅ Ping Role Removed",
                description="No role will be pinged for bump reminders.",
                color=discord.Color.green()
            )
            details = f"removed role (was: {old_role.name if old_role else 'none'})"
        else:
            config["ping_role"] = role.id
            embed = discord.Embed(
                title="✅ Ping Role Set",
                description=f"Bump reminders will ping {role.mention}",
                color=discord.Color.green()
            )
            details = f"set to {role.name} (was: {old_role.name if old_role else 'none'})"
        
        if old_role:
            embed.add_field(
                name="Role Change",
                value=f"{old_role.mention if old_role else 'None'} → {role.mention if role else 'None'}",
                inline=True
            )
        
        self.save_config()
        await ctx.send(embed=embed)
        await self.log_bremind_action("ping role updated", ctx.guild, ctx.author, details)

    @bremind.group(name="channel", invoke_without_command=True)
    async def bremind_channel(self, ctx):
        """Channel management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="📺 Channel Management",
                description="Use the subcommands to manage bump reminder channels:",
                color=0x00ff00
            )
            embed.add_field(
                name="Available Commands",
                value="`/bremind channel add <channel>` - Add a channel\n"
                        "`/bremind channel remove <channel>` - Remove a channel\n"
                        "`/bremind channel list` - List all channels\n"
                        "`/bremind channel clear` - Remove all channels",
                inline=False
            )
            await ctx.send(embed=embed)

    @bremind_channel.command(name="add")
    @discord.app_commands.describe(channel="The channel to add for bump reminders")
    async def add_channel(self, ctx, channel: discord.TextChannel = None):
        """Add a channel for bump reminders (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure bump reminder settings.", ephemeral=True)
            return

        channel = channel or ctx.channel
        config = self.get_guild_config(ctx.guild.id)
        
        if channel.id not in config["channels"]:
            config["channels"].append(channel.id)
            self.save_config()
            
            embed = discord.Embed(
                title="✅ Channel Added",
                description=f"Added {channel.mention} to bump reminder channels.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Total Channels",
                value=f"{len(config['channels'])} configured",
                inline=True
            )
            
            await ctx.send(embed=embed)
            await self.log_bremind_action("channel added", ctx.guild, ctx.author, f"channel: {channel.name}")
        else:
            await ctx.send(f"❌ {channel.mention} is already configured for bump reminders.", ephemeral=True)

    @bremind_channel.command(name="remove")
    @discord.app_commands.describe(channel="The channel to remove from bump reminders")
    async def remove_channel(self, ctx, channel: discord.TextChannel = None):
        """Remove a channel from bump reminders (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure bump reminder settings.", ephemeral=True)
            return

        channel = channel or ctx.channel
        config = self.get_guild_config(ctx.guild.id)
        
        if channel.id in config["channels"]:
            config["channels"].remove(channel.id)
            self.save_config()
            
            embed = discord.Embed(
                title="✅ Channel Removed",
                description=f"Removed {channel.mention} from bump reminder channels.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Remaining Channels",
                value=f"{len(config['channels'])} configured",
                inline=True
            )
            
            await ctx.send(embed=embed)
            await self.log_bremind_action("channel removed", ctx.guild, ctx.author, f"channel: {channel.name}")
        else:
            await ctx.send(f"❌ {channel.mention} is not configured for bump reminders.", ephemeral=True)

    @bremind_channel.command(name="list")
    async def list_channels(self, ctx):
        """List all bump reminder channels"""
        config = self.get_guild_config(ctx.guild.id)
        
        if not config["channels"]:
            embed = discord.Embed(
                title="📺 Bump Reminder Channels",
                description="No channels are currently configured for bump reminders.",
                color=0xff9900
            )
            embed.add_field(
                name="Add Channels",
                value="Use `/bremind channel add` to add channels.",
                inline=False
            )
            await ctx.send(embed=embed)
            return

        channels = []
        for i, channel_id in enumerate(config["channels"], 1):
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                channels.append(f"{i}. {channel.mention}")
            else:
                channels.append(f"{i}. Unknown Channel ({channel_id})")

        embed = discord.Embed(
            title="📺 Bump Reminder Channels",
            description="\n".join(channels),
            color=0x00ff00
        )
        
        embed.add_field(
            name="Total Count",
            value=f"{len(config['channels'])} channels configured",
            inline=True
        )
        
        if config.get("channel_status_enabled", False):
            embed.add_field(
                name="Status Updates",
                value="Enabled - channel topics show bump timers",
                inline=True
            )

        await ctx.send(embed=embed)

    @bremind_channel.command(name="clear")
    async def clear_channels(self, ctx):
        """Remove all channels from bump reminders (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure bump reminder settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        if not config["channels"]:
            await ctx.send("❌ No channels are currently configured.", ephemeral=True)
            return

        channel_count = len(config["channels"])
        config["channels"] = []
        self.save_config()

        embed = discord.Embed(
            title="✅ All Channels Cleared",
            description=f"Removed all {channel_count} channels from bump reminders.",
            color=discord.Color.green()
        )

        await ctx.send(embed=embed)
        await self.log_bremind_action("all channels cleared", ctx.guild, ctx.author, f"removed {channel_count} channels")

    @bremind.command(name="channelstatus")
    @discord.app_commands.describe(enabled="Enable or disable channel status updates")
    async def toggle_channel_status(self, ctx, enabled: Optional[bool] = None):
        """Toggle channel status updates on/off (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure bump reminder settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        # If no argument provided, toggle current state
        if enabled is None:
            enabled = not config.get("channel_status_enabled", False)

        old_state = config.get("channel_status_enabled", False)
        config["channel_status_enabled"] = enabled
        self.save_config()

        if enabled:
            embed = discord.Embed(
                title="✅ Channel Status Enabled",
                description="Channel topics will now show bump timer status.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Channel Status Disabled",
                description="Channel topics will no longer show bump timer status.",
                color=discord.Color.orange()
            )

        embed.add_field(
            name="Status Change",
            value=f"{'Enabled' if old_state else 'Disabled'} → {'Enabled' if enabled else 'Disabled'}",
            inline=True
        )

        await ctx.send(embed=embed)

        details = f"enabled: {enabled}"
        if old_state != enabled:
            details += f" (was: {old_state})"
        
        await self.log_bremind_action("channel status toggled", ctx.guild, ctx.author, details)

    @bremind.command(name="test")
    async def test_reminder(self, ctx):
        """Send a test bump reminder (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        if not config["enabled"]:
            await ctx.send("❌ Bump reminders are currently disabled. Enable them first with `/bremind toggle`.", ephemeral=True)
            return

        if not config["channels"]:
            await ctx.send("❌ No channels are configured for bump reminders. Add channels first with `/bremind channel add`.", ephemeral=True)
            return

        await ctx.send("🔄 Sending test bump reminder...", ephemeral=True)
        await self.send_bump_reminder(ctx.guild)
        await self.log_bremind_action("test reminder sent", ctx.guild, ctx.author)

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.channel_status_update.cancel()
        # Cancel all pending reminder tasks
        for task in self.reminder_tasks.values():
            task.cancel()

async def setup(bot):
    await bot.add_cog(BumpRemindCog(bot))
