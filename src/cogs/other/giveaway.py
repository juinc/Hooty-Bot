"""
Discord GiveawayCog - Advanced Giveaway System

OVERVIEW:
A full-featured, persistent giveaway system for Discord servers.  
Supports timed giveaways, multiple winners, rerolls, logging, and full admin control.

SETUP:
- No manual setup required – auto-creates config/database files:
- Config: src/config/giveaway_config.json
- Database: src/database/giveaway_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.giveaway.admin' or Administrator

COMMANDS (Slash & Prefix):
/giveaway toggle [on/off]           - Enable/disable the giveaway system (admin)
/giveaway status                    - Show system status and stats
/giveaway config                    - Show current configuration (admin)
/giveaway create <prize> <duration> [winners] [channel] - Create a new giveaway (admin)
/giveaway list [status] [limit]     - List giveaways (filter by status)
/giveaway end <id>                  - End a giveaway early (admin)
/giveaway cancel <id>               - Cancel an active giveaway (admin)
/giveaway reroll <id>               - Reroll winners for an ended giveaway (admin)
/giveaway setconfig <setting> <val> - Change config (emoji, max winners, log channel, durations) (admin)

Prefix commands: !giveaway, !gw (same subcommands as above)

COMMAND EXPLANATIONS:
- toggle: Enable/disable the system for your server.
- status: Show active/ended/cancelled giveaways and config summary.
- config: Show all current settings (emoji, max winners, log channel, durations).
- create: Start a new giveaway (set prize, duration, winners, channel).
- list: List recent giveaways, filter by status (active, ended, cancelled, all).
- end: End a giveaway early and pick winners.
- cancel: Cancel an active giveaway.
- reroll: Pick new winners for an ended giveaway.
- setconfig: Change emoji, max winners, log channel, min/max duration.

FEATURES:
• Timed giveaways with automatic ending and winner selection
• Multiple winners, reroll, and cancel support
• Custom emoji for entry reactions
• Per-server config: emoji, max winners, log channel, durations, timezone
• Logging to both LoggingCog and a configurable log channel
• Persistent, per-server and per-giveaway storage (JSON)
• Both slash and prefix command support
• Permission checks (if PermissionsCog present)
• All actions logged for audit/history
• Background task for auto-ending giveaways

USAGE BY OTHER COGS:

# Access giveaway data for custom integrations
giveaway_cog = bot.get_cog('GiveawayCog')
if giveaway_cog:
    # List all active giveaways in a guild
    active = [g for g in giveaway_cog.giveaways.values() if g['guild_id'] == guild.id and g['status'] == 'active']
    # Create a custom embed for a giveaway
    embed = await giveaway_cog.create_giveaway_embed(active[0]) if active else None
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
import pytz
from typing import Optional, Union, List, Dict, Any
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
    

class GiveawayCog(commands.Cog):
    """Comprehensive giveaway system with full management capabilities"""
    
    def __init__(self, bot):
        self.bot = bot
        self.giveaway_db_file = "src/database/giveaway_db.json"
        self.giveaway_config_file = "src/config/giveaway_config.json"
        
        # Load data
        self.giveaways = self.load_giveaways()
        self.config = self.load_config()
        
        # Start background task
        self.check_giveaways.start()

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.check_giveaways.cancel()

    def load_giveaways(self) -> Dict[str, Any]:
        """Load giveaway data from JSON file"""
        try:
            if not os.path.exists("src/database"):
                os.makedirs("src/database")
            
            if os.path.exists(self.giveaway_db_file):
                with open(self.giveaway_db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading giveaways: {e}")
        return {}

    def save_giveaways(self):
        """Save giveaway data to JSON file"""
        try:
            os.makedirs(os.path.dirname(self.giveaway_db_file), exist_ok=True)
            with open(self.giveaway_db_file, 'w', encoding='utf-8') as f:
                json.dump(self.giveaways, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving giveaways: {e}")

    def load_config(self) -> Dict[str, Any]:
        """Load giveaway configuration from JSON file"""
        try:
            if not os.path.exists("src/config"):
                os.makedirs("src/config")
            
            if os.path.exists(self.giveaway_config_file):
                with open(self.giveaway_config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading giveaway config: {e}")
        return {}

    def save_config(self):
        """Save giveaway configuration to JSON file"""
        try:
            os.makedirs(os.path.dirname(self.giveaway_config_file), exist_ok=True)
            with open(self.giveaway_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving giveaway config: {e}")

    def get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        """Get configuration for a specific guild"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.config:
            self.config[guild_id_str] = {
                "enabled": False,
                "default_emoji": "🎉",
                "log_channel": None,
                "default_timezone": "UTC",
                "max_winners": 10,
                "min_duration": 60,  # 1 minute
                "max_duration": 2592000  # 30 days
            }
            self.save_config()
        return self.config[guild_id_str]

    def has_giveaway_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has giveaway admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.giveaway.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_giveaway_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log giveaway actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Giveaway {action}"
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
                    file_override="giveaway_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log giveaway action: {e}")
        
        # Also log to configured log channel if available
        if guild:
            config = self.get_guild_config(guild.id)
            if config.get("log_channel"):
                log_channel = guild.get_channel(config["log_channel"])
                if log_channel:
                    try:
                        embed = discord.Embed(
                            title="🎉 Giveaway Action",
                            description=f"**Action:** {action}\n**User:** {user.mention if user else 'System'}\n**Details:** {details}",
                            color=0x00ff00,
                            timestamp=datetime.utcnow()
                        )
                        await log_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Failed to send to log channel: {e}")

    def parse_time(self, time_str: str) -> int:
        """Parse time string and return seconds"""
        time_regex = re.compile(r'(\d+)([smhdw])')
        total_seconds = 0
        
        matches = time_regex.findall(time_str.lower())
        if not matches:
            raise ValueError("Invalid time format")
        
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
        
        return total_seconds

    def format_time_remaining(self, end_time: datetime) -> str:
        """Format time remaining until end time"""
        now = datetime.utcnow()
        if end_time <= now:
            return "Ended"
        
        delta = end_time - now
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds and not (days or hours):
            parts.append(f"{seconds}s")
        
        return " ".join(parts) if parts else "Less than a minute"

    async def create_giveaway_embed(self, giveaway_data: Dict[str, Any], status: str = "active") -> discord.Embed:
        """Create an embed for a giveaway"""
        prize = giveaway_data['prize']
        end_time = datetime.fromisoformat(giveaway_data['end_time'])
        host_id = giveaway_data['host_id']
        winners_count = giveaway_data.get('winners_count', 1)
        
        if status == "active":
            color = 0x00ff00
            title = "🎉 **GIVEAWAY** 🎉"
            time_text = f"Ends: <t:{int(end_time.timestamp())}:R>"
        elif status == "ended":
            color = 0xff0000
            title = "🎉 **GIVEAWAY ENDED** 🎉"
            time_text = f"Ended: <t:{int(end_time.timestamp())}:R>"
        elif status == "cancelled":
            color = 0x808080
            title = "❌ **GIVEAWAY CANCELLED** ❌"
            time_text = f"Was ending: <t:{int(end_time.timestamp())}:R>"
        else:
            color = 0x0099ff
            title = "🎉 **GIVEAWAY** 🎉"
            time_text = f"Ends: <t:{int(end_time.timestamp())}:R>"

        embed = discord.Embed(title=title, description=f"**Prize:** {prize}", color=color)
        embed.add_field(name="Time", value=time_text, inline=True)
        embed.add_field(name="Winners", value=str(winners_count), inline=True)
        embed.add_field(name="Hosted by", value=f"<@{host_id}>", inline=True)
        
        if status == "active":
            guild_id = giveaway_data.get('guild_id')
            if guild_id:
                config = self.get_guild_config(guild_id)
                emoji = config.get('default_emoji', '🎉')
            else:
                emoji = '🎉'
            embed.add_field(
                name="How to enter", 
                value=f"React with {emoji} to enter!", 
                inline=False
            )
        
        embed.set_footer(text=f"Giveaway ID: {giveaway_data.get('id', 'Unknown')}")
        
        return embed

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        """Check for giveaways that need to be ended"""
        now = datetime.utcnow()
        
        for giveaway_id, giveaway_data in list(self.giveaways.items()):
            if giveaway_data.get('status') != 'active':
                continue
            
            # Check if the guild has giveaways enabled
            guild_id = giveaway_data.get('guild_id')
            if guild_id:
                config = self.get_guild_config(guild_id)
                if not config.get('enabled', False):
                    continue
                
            end_time = datetime.fromisoformat(giveaway_data['end_time'])
            if now >= end_time:
                try:
                    await self.end_giveaway(giveaway_id)
                except Exception as e:
                    print(f"Error ending giveaway {giveaway_id}: {e}")

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        """Wait until bot is ready before checking giveaways"""
        await self.bot.wait_until_ready()

    async def end_giveaway(self, giveaway_id: str, early: bool = False) -> Dict[str, Any]:
        """End a giveaway and pick winners"""
        if giveaway_id not in self.giveaways:
            raise ValueError("Giveaway not found")
        
        giveaway_data = self.giveaways[giveaway_id]
        if giveaway_data.get('status') != 'active':
            raise ValueError("Giveaway is not active")
        
        # Get the message
        guild = self.bot.get_guild(giveaway_data['guild_id'])
        if not guild:
            raise ValueError("Guild not found")
        
        channel = guild.get_channel(giveaway_data['channel_id'])
        if not channel:
            raise ValueError("Channel not found")
        
        try:
            message = await channel.fetch_message(giveaway_data['message_id'])
        except discord.NotFound:
            raise ValueError("Giveaway message not found")
        
        # Get reactions
        config = self.get_guild_config(guild.id)
        emoji = config.get('default_emoji', '🎉')
        reaction = None
        for r in message.reactions:
            if str(r.emoji) == emoji:
                reaction = r
                break
        
        winners = []
        if reaction and reaction.count > 1:  # Subtract 1 for bot's reaction
            users = []
            async for user in reaction.users():
                if not user.bot and user.id != giveaway_data['host_id']:
                    users.append(user)
            
            winners_count = min(giveaway_data.get('winners_count', 1), len(users))
            if users:
                winners = random.sample(users, winners_count)
        
        # Update giveaway data
        giveaway_data['status'] = 'ended'
        giveaway_data['winners'] = [{'id': w.id, 'name': str(w)} for w in winners]
        giveaway_data['ended_at'] = datetime.utcnow().isoformat()
        giveaway_data['ended_early'] = early
        
        self.save_giveaways()
        
        # Create result embed
        embed = await self.create_giveaway_embed(giveaway_data, "ended")
        
        if winners:
            winner_mentions = ", ".join([w.mention for w in winners])
            embed.add_field(name="🎊 Winners", value=winner_mentions, inline=False)
            
            # Log winners
            winner_info = ", ".join([f"{w.name} ({w.id})" for w in winners])
            await self.log_giveaway_action(
                "ended" if not early else "ended early", 
                guild, 
                details=f"giveaway: {giveaway_id}, winners: {winner_info}"
            )
        else:
            embed.add_field(name="😢 No Winners", value="No valid entries found", inline=False)
            await self.log_giveaway_action(
                "ended" if not early else "ended early", 
                guild, 
                details=f"giveaway: {giveaway_id}, no winners"
            )
        
        # Update message
        await message.edit(embed=embed)
        
        # Send winner announcement
        if winners:
            winner_text = ", ".join([w.mention for w in winners])
            prize = giveaway_data['prize']
            
            announcement = f"🎉 Congratulations {winner_text}! You won **{prize}**!"
            if len(announcement) > 2000:
                announcement = f"🎉 Congratulations to the {len(winners)} winner(s) of **{prize}**!"
            
            await channel.send(announcement)
        
        return {
            'giveaway_data': giveaway_data,
            'winners': winners,
            'message': message
        }

    # ==================== SLASH COMMANDS ====================
    # Hybrid Command Group
    @commands.hybrid_group(name="giveaway", aliases=['gw'], invoke_without_command=True)
    async def giveaway(self, ctx):
        """Giveaway management commands"""
        if ctx.invoked_subcommand is None:
            config = self.get_guild_config(ctx.guild.id)
            
            embed = discord.Embed(
                title="🎉 Giveaway System",
                color=0x00ff00 if config.get("enabled", False) else 0xff0000
            )
            
            # System status
            status_emoji = "✅" if config.get("enabled", False) else "⏸️"
            embed.add_field(
                name=f"{status_emoji} System Status",
                value="**Enabled**" if config.get("enabled", False) else "**Disabled**",
                inline=True
            )
            
            # Active giveaways count
            active_count = sum(1 for g in self.giveaways.values() 
                                if g.get('guild_id') == ctx.guild.id and g.get('status') == 'active')
            embed.add_field(
                name="🎯 Active Giveaways",
                value=f"**{active_count}**",
                inline=True
            )
            
            # Default emoji
            embed.add_field(
                name="😀 Default Emoji",
                value=config.get('default_emoji', '🎉'),
                inline=True
            )
            
            embed.add_field(
                name="📋 Commands",
                value="`/giveaway toggle` - Enable/disable system\n"
                        "`/giveaway status` - Show detailed status\n"
                        "`/giveaway config` - Show configuration\n"
                        "`/giveaway create` - Create a giveaway\n"
                        "`/giveaway list` - List giveaways",
                inline=False
            )
            
            if not config.get("enabled", False):
                embed.add_field(
                    name="ℹ️ Note",
                    value="System is disabled. Use `/giveaway toggle` to enable.",
                    inline=False
                )
            
            await ctx.send(embed=embed)

    @giveaway.command(name="toggle")
    @discord.app_commands.describe(enabled="Enable or disable the giveaway system")
    async def giveaway_toggle(self, ctx, enabled: Optional[bool] = None):
        """Toggle giveaway system on/off (Admin only)"""
        if not self.has_giveaway_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure giveaway settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        # If no argument provided, toggle current state
        if enabled is None:
            enabled = not config.get("enabled", False)
        
        old_state = config.get("enabled", False)
        config["enabled"] = enabled
        self.save_config()

        # Create response embed
        if enabled:
            embed = discord.Embed(
                title="✅ Giveaway System Enabled",
                description="The giveaway system is now active. Admins can create and manage giveaways.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Giveaway System Disabled",
                description="The giveaway system is now disabled. Existing giveaways will continue but no new ones can be created.",
                color=discord.Color.orange()
            )

        embed.add_field(
            name="Status Change",
            value=f"{'Enabled' if old_state else 'Disabled'} → {'Enabled' if enabled else 'Disabled'}",
            inline=True
        )

        # Show active giveaways if any
        active_count = sum(1 for g in self.giveaways.values() 
                            if g.get('guild_id') == ctx.guild.id and g.get('status') == 'active')
        if active_count > 0:
            embed.add_field(
                name="Active Giveaways",
                value=f"{active_count} giveaways will continue running",
                inline=True
            )

        await ctx.send(embed=embed)

        # Log the change
        details = f"enabled: {enabled}"
        if old_state != enabled:
            details += f" (was: {old_state})"
        
        await self.log_giveaway_action("toggled system state", ctx.guild, ctx.author, details)

    @giveaway.command(name="status")
    async def giveaway_status(self, ctx):
        """Show detailed giveaway system status"""
        config = self.get_guild_config(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        if is_enabled:
            embed = discord.Embed(
                title="✅ Giveaway System Status",
                description="The giveaway system is currently **enabled**.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Giveaway System Status", 
                description="The giveaway system is currently **disabled**.",
                color=discord.Color.orange()
            )

        # Count giveaways by status
        guild_giveaways = {gid: gdata for gid, gdata in self.giveaways.items() 
                            if gdata.get('guild_id') == ctx.guild.id}
        
        active_count = sum(1 for g in guild_giveaways.values() if g.get('status') == 'active')
        ended_count = sum(1 for g in guild_giveaways.values() if g.get('status') == 'ended')
        cancelled_count = sum(1 for g in guild_giveaways.values() if g.get('status') == 'cancelled')
        
        embed.add_field(
            name="📊 Statistics",
            value=f"Active: **{active_count}**\nEnded: **{ended_count}**\nCancelled: **{cancelled_count}**",
            inline=True
        )

        # Configuration
        log_channel_text = "Not set"
        if config.get("log_channel"):
            log_channel = ctx.guild.get_channel(config["log_channel"])
            log_channel_text = log_channel.mention if log_channel else "Channel not found"
        
        embed.add_field(
            name="⚙️ Configuration",
            value=f"Default emoji: {config.get('default_emoji', '🎉')}\n"
                  f"Max winners: **{config.get('max_winners', 10)}**\n"
                    f"Log channel: {log_channel_text}",
            inline=True
        )

        # Duration limits
        min_duration = config.get('min_duration', 60)
        max_duration = config.get('max_duration', 2592000)
        
        embed.add_field(
            name="⏱️ Duration Limits",
            value=f"Minimum: **{min_duration}** seconds\nMaximum: **{max_duration}** seconds",
            inline=True
        )

        # Recent activity
        if guild_giveaways:
            recent_giveaways = sorted(guild_giveaways.values(), 
                                    key=lambda x: x.get('start_time', ''), reverse=True)[:3]
            if recent_giveaways:
                recent_text = []
                for g in recent_giveaways:
                    prize = g['prize'][:30] + "..." if len(g['prize']) > 30 else g['prize']
                    status = g.get('status', 'unknown')
                    recent_text.append(f"• {prize} ({status})")
                
                embed.add_field(
                    name="📈 Recent Activity",
                    value="\n".join(recent_text),
                    inline=False
                )

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="While disabled, no new giveaways can be created, but existing ones will continue.",
                inline=False
            )

        await ctx.send(embed=embed)

    @giveaway.command(name="config")
    async def giveaway_config(self, ctx):
        """Show current giveaway configuration (Admin only)"""
        if not self.has_giveaway_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to view configuration.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        embed = discord.Embed(
            title="🎉 Giveaway Configuration",
            color=0x00ff00 if is_enabled else 0x808080
        )

        # System status
        status_emoji = "✅" if is_enabled else "⏸️"
        embed.add_field(
            name=f"{status_emoji} System Status",
            value=f"**{'Enabled' if is_enabled else 'Disabled'}**",
            inline=True
        )

        # Basic settings
        embed.add_field(
            name="😀 Default Emoji",
            value=config.get('default_emoji', '🎉'),
            inline=True
        )

        embed.add_field(
            name="🏆 Max Winners",
            value=str(config.get('max_winners', 10)),
            inline=True
        )

        # Duration settings
        min_duration = config.get('min_duration', 60)
        max_duration = config.get('max_duration', 2592000)
        
        embed.add_field(
            name="⏱️ Duration Settings",
            value=f"Min: **{min_duration}**s ({min_duration//60}m)\nMax: **{max_duration}**s ({max_duration//86400}d)",
            inline=True
        )

        # Log channel
        log_channel_text = "Not set"
        if config.get("log_channel"):
            log_channel = ctx.guild.get_channel(config["log_channel"])
            log_channel_text = log_channel.mention if log_channel else "Channel not found"
        
        embed.add_field(
            name="📋 Log Channel",
            value=log_channel_text,
            inline=True
        )

        # Timezone
        embed.add_field(
            name="🌍 Default Timezone",
            value=config.get('default_timezone', 'UTC'),
            inline=True
        )

        # Statistics
        guild_giveaways = {gid: gdata for gid, gdata in self.giveaways.items() 
                            if gdata.get('guild_id') == ctx.guild.id}
        
        total_giveaways = len(guild_giveaways)
        active_count = sum(1 for g in guild_giveaways.values() if g.get('status') == 'active')
        
        embed.add_field(
            name="📊 Server Statistics",
            value=f"Total giveaways: **{total_giveaways}**\nCurrently active: **{active_count}**",
            inline=False
        )

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="System is disabled. Use `/giveaway toggle` to enable.",
                inline=False
            )

        await ctx.send(embed=embed)

    @giveaway.command(name="create")
    @discord.app_commands.describe(
        prize="The prize for the giveaway",
        duration="Duration (e.g., 1h, 30m, 2d)",
        winners="Number of winners (default: 1)",
        channel="Channel to post in (default: current channel)"
    )
    async def create_giveaway(self, ctx, prize: str, duration: str, winners: int = 1, channel: discord.TextChannel = None):
        """Create a new giveaway (Admin only)"""
        if not self.has_giveaway_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to create giveaways!", ephemeral=True)
            return
        
        config = self.get_guild_config(ctx.guild.id)
        if not config.get("enabled", False):
            await ctx.send("❌ The giveaway system is disabled in this server. Enable it first with `/giveaway toggle`.", ephemeral=True)
            return
        
        try:
            # Validate inputs
            if winners < 1 or winners > config.get('max_winners', 10):
                await ctx.send(f"❌ Winners must be between 1 and {config.get('max_winners', 10)}", ephemeral=True)
                return
            
            duration_seconds = self.parse_time(duration)
            if duration_seconds < config.get('min_duration', 60):
                await ctx.send(f"❌ Duration must be at least {config.get('min_duration', 60)} seconds", ephemeral=True)
                return
            if duration_seconds > config.get('max_duration', 2592000):
                await ctx.send(f"❌ Duration cannot exceed {config.get('max_duration', 2592000)} seconds", ephemeral=True)
                return
            
            target_channel = channel or ctx.channel
            
            # Create giveaway
            end_time = datetime.utcnow() + timedelta(seconds=duration_seconds)
            giveaway_id = f"{ctx.guild.id}_{int(datetime.utcnow().timestamp())}"
            
            giveaway_data = {
                'id': giveaway_id,
                'guild_id': ctx.guild.id,
                'channel_id': target_channel.id,
                'host_id': ctx.author.id,
                'prize': prize,
                'winners_count': winners,
                'start_time': datetime.utcnow().isoformat(),
                'end_time': end_time.isoformat(),
                'status': 'active',
                'created_via': 'command'
            }
            
            # Create embed and send message
            embed = await self.create_giveaway_embed(giveaway_data, "active")
            message = await target_channel.send(embed=embed)
            
            # Add reaction
            emoji = config.get('default_emoji', '🎉')
            await message.add_reaction(emoji)
            
            # Save giveaway data
            giveaway_data['message_id'] = message.id
            self.giveaways[giveaway_id] = giveaway_data
            self.save_giveaways()
            
            # Log creation
            await self.log_giveaway_action(
                "created", ctx.guild, ctx.author,
                f"giveaway: {giveaway_id}, prize: {prize}, duration: {duration}, winners: {winners}"
            )
            
            embed = discord.Embed(
                title="✅ Giveaway Created",
                description=f"Giveaway created successfully in {target_channel.mention}!",
                color=discord.Color.green()
            )
            embed.add_field(name="Prize", value=prize, inline=True)
            embed.add_field(name="Duration", value=duration, inline=True)
            embed.add_field(name="Winners", value=str(winners), inline=True)
            embed.add_field(name="Giveaway ID", value=giveaway_id, inline=False)
            
            await ctx.send(embed=embed, ephemeral=True)
            
        except ValueError as e:
            await ctx.send(f"❌ Error: {e}", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {e}", ephemeral=True)

    @giveaway.command(name="list")
    @discord.app_commands.describe(
        status="Filter by status (active, ended, cancelled, all)",
        limit="Number of giveaways to show (max 10)"
    )
    @discord.app_commands.choices(status=[
        discord.app_commands.Choice(name="Active", value="active"),
        discord.app_commands.Choice(name="Ended", value="ended"),
        discord.app_commands.Choice(name="Cancelled", value="cancelled"),
        discord.app_commands.Choice(name="All", value="all")
    ])
    async def list_giveaways(self, ctx, status: discord.app_commands.Choice[str] = None, limit: int = 5):
        """List giveaways in this server"""
        if limit > 10:
            limit = 10
        elif limit < 1:
            limit = 5

        # Filter giveaways for this guild
        guild_giveaways = {}
        for gid, gdata in self.giveaways.items():
            if gdata.get('guild_id') != ctx.guild.id:
                continue
            
            # Check status filter
            if status and status.value != "all" and gdata.get('status') != status.value:
                continue
            
            guild_giveaways[gid] = gdata

        if not guild_giveaways:
            embed = discord.Embed(
                title="🎉 Giveaway List",
                description="No giveaways found matching the criteria.",
                color=0xff9900
            )
            embed.add_field(
                name="Create Giveaway",
                value="Use `/giveaway create` to create your first giveaway!",
                inline=False
            )
            await ctx.send(embed=embed)
            return

        # Sort by start time (newest first)
        sorted_giveaways = sorted(
            guild_giveaways.items(),
            key=lambda x: x[1].get('start_time', ''),
            reverse=True
        )[:limit]

        embed = discord.Embed(title="🎉 Giveaway List", color=0x00ff00)
        
        for gid, gdata in sorted_giveaways:
            prize = gdata['prize']
            if len(prize) > 50:
                prize = prize[:47] + "..."
            
            status_emoji = {
                'active': '🟢',
                'ended': '🔴',
                'cancelled': '⚫'
            }.get(gdata.get('status'), '❓')
            
            host = self.bot.get_user(gdata['host_id'])
            host_name = host.name if host else f"Unknown ({gdata['host_id']})"
            
            end_time = datetime.fromisoformat(gdata['end_time'])
            time_str = f"<t:{int(end_time.timestamp())}:R>"
            
            winners_info = ""
            if gdata.get('status') == 'ended' and gdata.get('winners'):
                winners_count = len(gdata['winners'])
                winners_info = f" | {winners_count} winner(s)"
            
            value = f"Host: {host_name}\nTime: {time_str}{winners_info}\nID: `{gid}`"
            
            embed.add_field(
                name=f"{status_emoji} {prize}",
                value=value,
                inline=False
            )

        if len(sorted_giveaways) == limit and len(guild_giveaways) > limit:
            embed.set_footer(text=f"Showing {limit} of {len(guild_giveaways)} giveaways")

        await ctx.send(embed=embed)

    @giveaway.command(name="end")
    @discord.app_commands.describe(giveaway_id="The ID of the giveaway to end")
    async def end_giveaway_early(self, ctx, giveaway_id: str):
        """End a giveaway early (Admin only)"""
        if not self.has_giveaway_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to end giveaways!", ephemeral=True)
            return
        
        try:
            if giveaway_id not in self.giveaways:
                await ctx.send("❌ Giveaway not found!", ephemeral=True)
                return
            
            giveaway_data = self.giveaways[giveaway_id]
            if giveaway_data.get('guild_id') != ctx.guild.id:
                await ctx.send("❌ That giveaway is not from this server!", ephemeral=True)
                return
            
            if giveaway_data.get('status') != 'active':
                await ctx.send("❌ Can only end active giveaways!", ephemeral=True)
                return
            
            # End the giveaway
            result = await self.end_giveaway(giveaway_id, early=True)
            
            embed = discord.Embed(
                title="✅ Giveaway Ended Early",
                description=f"Giveaway **{giveaway_data['prize']}** has been ended early.",
                color=discord.Color.green()
            )
            
            if result['winners']:
                winner_names = [w.name for w in result['winners']]
                embed.add_field(
                    name="Winners",
                    value=", ".join(winner_names),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Result",
                    value="No winners (no valid entries)",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {e}", ephemeral=True)

    @giveaway.command(name="cancel")
    @discord.app_commands.describe(giveaway_id="The ID of the giveaway to cancel")
    async def cancel_giveaway(self, ctx, giveaway_id: str):
        """Cancel an active giveaway (Admin only)"""
        if not self.has_giveaway_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to cancel giveaways!", ephemeral=True)
            return
        
        try:
            if giveaway_id not in self.giveaways:
                await ctx.send("❌ Giveaway not found!", ephemeral=True)
                return
            
            giveaway_data = self.giveaways[giveaway_id]
            if giveaway_data.get('guild_id') != ctx.guild.id:
                await ctx.send("❌ That giveaway is not from this server!", ephemeral=True)
                return
            
            if giveaway_data.get('status') != 'active':
                await ctx.send("❌ Can only cancel active giveaways!", ephemeral=True)
                return
            
            # Update giveaway status
            giveaway_data['status'] = 'cancelled'
            giveaway_data['cancelled_at'] = datetime.utcnow().isoformat()
            giveaway_data['cancelled_by'] = ctx.author.id
            self.save_giveaways()
            
            # Update message
            channel = ctx.guild.get_channel(giveaway_data['channel_id'])
            if channel:
                try:
                    message = await channel.fetch_message(giveaway_data['message_id'])
                    embed = await self.create_giveaway_embed(giveaway_data, "cancelled")
                    await message.edit(embed=embed)
                    await channel.send("❌ **Giveaway Cancelled** by moderator.")
                except discord.NotFound:
                    pass
            
            # Log cancellation
            await self.log_giveaway_action(
                "cancelled", ctx.guild, ctx.author, f"giveaway: {giveaway_id}"
            )
            
            embed = discord.Embed(
                title="✅ Giveaway Cancelled",
                description=f"Giveaway **{giveaway_data['prize']}** has been cancelled.",
                color=discord.Color.green()
            )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {e}", ephemeral=True)

    @giveaway.command(name="reroll")
    @discord.app_commands.describe(giveaway_id="The ID of the giveaway to reroll")
    async def reroll_giveaway(self, ctx, giveaway_id: str):
        """Reroll a giveaway to pick new winners (Admin only)"""
        if not self.has_giveaway_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to reroll giveaways!", ephemeral=True)
            return
        
        try:
            if giveaway_id not in self.giveaways:
                await ctx.send("❌ Giveaway not found!", ephemeral=True)
                return
            
            giveaway_data = self.giveaways[giveaway_id]
            if giveaway_data.get('guild_id') != ctx.guild.id:
                await ctx.send("❌ That giveaway is not from this server!", ephemeral=True)
                return
            
            if giveaway_data.get('status') != 'ended':
                await ctx.send("❌ Can only reroll ended giveaways!", ephemeral=True)
                return
            
            # Get the message and reroll
            channel = ctx.guild.get_channel(giveaway_data['channel_id'])
            if not channel:
                await ctx.send("❌ Giveaway channel not found!", ephemeral=True)
                return
            
            message = await channel.fetch_message(giveaway_data['message_id'])
            
            # Get reactions and pick new winners
            config = self.get_guild_config(ctx.guild.id)
            emoji = config.get('default_emoji', '🎉')
            reaction = None
            for r in message.reactions:
                if str(r.emoji) == emoji:
                    reaction = r
                    break
            
            if not reaction or reaction.count <= 1:
                await ctx.send("❌ No participants found!", ephemeral=True)
                return
            
            users = []
            async for user in reaction.users():
                if not user.bot and user.id != giveaway_data['host_id']:
                    users.append(user)
            
            if not users:
                await ctx.send("❌ No valid participants found!", ephemeral=True)
                return
            
            winners_count = min(giveaway_data.get('winners_count', 1), len(users))
            new_winners = random.sample(users, winners_count)
            
            # Update giveaway data
            giveaway_data['winners'] = [{'id': w.id, 'name': str(w)} for w in new_winners]
            giveaway_data['rerolled_at'] = datetime.utcnow().isoformat()
            giveaway_data['rerolled_by'] = ctx.author.id
            self.save_giveaways()
            
            # Update embed
            embed = await self.create_giveaway_embed(giveaway_data, "ended")
            winner_mentions = ", ".join([w.mention for w in new_winners])
            embed.add_field(name="🎊 New Winners (Rerolled)", value=winner_mentions, inline=False)
            
            await message.edit(embed=embed)
            
            # Send announcement
            await channel.send(f"🔄 **Giveaway Rerolled!**\nNew winner(s): {winner_mentions}")
            
            # Log reroll
            winner_info = ", ".join([f"{w.name} ({w.id})" for w in new_winners])
            await self.log_giveaway_action(
                "rerolled", ctx.guild, ctx.author,
                f"giveaway: {giveaway_id}, new winners: {winner_info}"
            )
            
            embed = discord.Embed(
                title="✅ Giveaway Rerolled",
                description=f"New winners selected for **{giveaway_data['prize']}**",
                color=discord.Color.green()
            )
            embed.add_field(
                name="New Winners",
                value=", ".join([w.name for w in new_winners]),
                inline=False
            )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {e}", ephemeral=True)

    @giveaway.command(name="setconfig")
    @discord.app_commands.describe(
        setting="Setting to change",
        value="New value for the setting"
    )
    @discord.app_commands.choices(setting=[
        discord.app_commands.Choice(name="Default Emoji", value="emoji"),
        discord.app_commands.Choice(name="Max Winners", value="max_winners"),
        discord.app_commands.Choice(name="Log Channel", value="log_channel"),
        discord.app_commands.Choice(name="Min Duration", value="min_duration"),
        discord.app_commands.Choice(name="Max Duration", value="max_duration")
    ])
    async def set_giveaway_config(self, ctx, setting: discord.app_commands.Choice[str], value: str):
        """Configure giveaway settings (Admin only)"""
        if not self.has_giveaway_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure giveaway settings!", ephemeral=True)
            return
        
        config = self.get_guild_config(ctx.guild.id)
        
        try:
            if setting.value == "emoji":
                config["default_emoji"] = value
                await ctx.send(f"✅ Default emoji set to {value}")
                
            elif setting.value == "max_winners":
                max_winners = int(value)
                if max_winners < 1 or max_winners > 50:
                    await ctx.send("❌ Max winners must be between 1 and 50!", ephemeral=True)
                    return
                config["max_winners"] = max_winners
                await ctx.send(f"✅ Max winners set to {max_winners}")
                
            elif setting.value == "log_channel":
                if value.lower() in ['none', 'null', 'remove']:
                    config["log_channel"] = None
                    await ctx.send("✅ Log channel removed")
                else:
                    try:
                        channel_id = int(value.replace('<#', '').replace('>', ''))
                        channel = ctx.guild.get_channel(channel_id)
                        if channel:
                            config["log_channel"] = channel_id
                            await ctx.send(f"✅ Log channel set to {channel.mention}")
                        else:
                            await ctx.send("❌ Channel not found!", ephemeral=True)
                            return
                    except ValueError:
                        await ctx.send("❌ Invalid channel format! Use #channel or channel ID", ephemeral=True)
                        return
                        
            elif setting.value == "min_duration":
                min_duration = int(value)
                if min_duration < 10:
                    await ctx.send("❌ Minimum duration must be at least 10 seconds!", ephemeral=True)
                    return
                config["min_duration"] = min_duration
                await ctx.send(f"✅ Minimum duration set to {min_duration} seconds")
                
            elif setting.value == "max_duration":
                max_duration = int(value)
                if max_duration > 31536000:  # 1 year
                    await ctx.send("❌ Maximum duration cannot exceed 1 year!", ephemeral=True)
                    return
                config["max_duration"] = max_duration
                await ctx.send(f"✅ Maximum duration set to {max_duration} seconds")
            
            self.save_config()
            
            await self.log_giveaway_action(
                "config updated", ctx.guild, ctx.author,
                f"{setting.name}: {value}"
            )
            
        except ValueError:
            await ctx.send("❌ Invalid value provided!", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(GiveawayCog(bot))
