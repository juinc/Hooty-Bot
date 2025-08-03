"""
Discord CountingCog - Server Counting Game System

OVERVIEW:
A full-featured counting game cog for Discord servers. Tracks counts, streaks, milestones, leaderboards, and user stats.  
Supports admin controls, blacklisting, auto-deletion of wrong counts, and persistent storage.

SETUP:
- No manual setup required – auto-creates config/database files:
- Config: src/config/counting_config.json
- Database: src/database/counting_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.counting.admin' or Administrator

COMMANDS:
/count toggle [on/off]                - Enable/disable the counting system (admin)
/count status                         - Show detailed system status and stats
/count config                         - Show current configuration (admin)
/count reset                          - Reset the current count to 0 (admin)
/count setchannel [channel]           - Set the counting channel (admin)
/count leaderboard [limit]            - Show top counters (default 10, max 20)
/count profile [user]                 - Show counting stats for a user
/count stats                          - Show server-wide counting stats
/count blacklist add <user>           - Blacklist a user from counting (admin)
/count blacklist remove <user>        - Remove a user from blacklist (admin)
/count blacklist list                 - List all blacklisted users (admin)
/count blacklist clear                - Clear the entire blacklist (admin)
/count autodelete                     - Toggle auto-deletion of wrong counts (admin)
/count set <number>                   - Set the current count to a specific number (admin)

Prefix commands: !count <subcommand> (same functionality)

COMMAND EXPLANATIONS:
- /count toggle: Enable or disable the counting system.
- /count status: Show current count, highest, streaks, top user, and stats.
- /count config: Show all configuration details (admin only).
- /count reset: Reset the count to 0 and clear streaks (admin only).
- /count setchannel: Set the channel for counting (admin only).
- /count leaderboard: Show the top counters and their stats.
- /count profile: Show a user's counting stats, streaks, milestones, and rank.
- /count stats: Show server-wide stats, milestones, and top contributors.
- /count blacklist: Manage users who are not allowed to count (admin only).
- /count autodelete: Toggle auto-deletion of wrong counts (admin only).
- /count set: Manually set the current count (admin only).

FEATURES:
• Counting game in a dedicated channel
• Tracks current, highest, and reset counts
• User stats: total counts, fails, streaks, milestones, accuracy, rank
• Leaderboard and user profiles
• Milestone celebrations (100, 500, 1000, etc.)
• Blacklist system for cheaters/trolls
• Auto-deletion of wrong counts (toggleable)
• Admin controls for all settings and stats
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Per-server persistent config and stats (JSON)
• Both slash and prefix command support
"""

import discord
from discord.ext import commands
import json
import os
from datetime import datetime
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

class CountingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/counting_config.json"
        self.db_file = "src/database/counting_db.json"
        self.config = self.load_config()
        self.db = self.load_database()

    def load_config(self):
        """Load configuration from file"""
        try:
            if not os.path.exists("src/config"):
                os.makedirs("src/config")
            
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading counting config: {e}")
            return {}

    def save_config(self):
        """Save configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving counting config: {e}")

    def load_database(self):
        """Load database from file"""
        try:
            if not os.path.exists("src/database"):
                os.makedirs("src/database")
            
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading counting database: {e}")
            return {}

    def save_database(self):
        """Save database to file"""
        try:
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
            with open(self.db_file, 'w') as f:
                json.dump(self.db, f, indent=2)
        except Exception as e:
            print(f"Error saving counting database: {e}")

    def get_guild_config(self, guild_id: int):
        """Get configuration for a specific guild"""
        guild_id = str(guild_id)
        if guild_id not in self.config:
            self.config[guild_id] = {
                "enabled": False,
                "counting_channel": None,
                "current_count": 0,
                "highest_count": 0,
                "last_counter": None,
                "blacklisted_users": [],
                "auto_delete_wrong": True,
                "counting_start_date": None,
                "total_resets": 0
            }
            self.save_config()
        return self.config[guild_id]

    def get_guild_database(self, guild_id: int):
        """Get database for a specific guild"""
        guild_id = str(guild_id)
        if guild_id not in self.db:
            self.db[guild_id] = {
                "user_counts": {},  # user_id: total_correct_counts
                "count_history": [],  # {user_id, number, timestamp, was_correct}
                "milestones": {},  # number: {user_id, timestamp}
                "fails": {},  # user_id: total_fails
                "streak_records": {},  # user_id: longest_streak
                "current_streaks": {}  # user_id: current_streak
            }
            self.save_database()
        return self.db[guild_id]

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has counting admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.counting.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_counting_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log counting actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Counting {action}"
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
                    file_override="counting_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log counting action: {e}")

    def is_user_blacklisted(self, guild_id: int, user_id: int) -> bool:
        """Check if user is blacklisted from counting"""
        config = self.get_guild_config(guild_id)
        return user_id in config.get("blacklisted_users", [])

    def update_user_stats(self, guild_id: int, user_id: int, number: int, was_correct: bool):
        """Update user statistics"""
        db = self.get_guild_database(guild_id)
        user_id = str(user_id)
        
        # Update total counts
        if was_correct:
            db["user_counts"][user_id] = db["user_counts"].get(user_id, 0) + 1
            
            # Update current streak
            db["current_streaks"][user_id] = db["current_streaks"].get(user_id, 0) + 1
            
            # Update streak record
            current_streak = db["current_streaks"][user_id]
            if current_streak > db["streak_records"].get(user_id, 0):
                db["streak_records"][user_id] = current_streak
        else:
            # Reset streak on fail
            db["current_streaks"][user_id] = 0
            db["fails"][user_id] = db["fails"].get(user_id, 0) + 1
        
        # Add to history
        db["count_history"].append({
            "user_id": int(user_id),
            "number": number,
            "timestamp": datetime.now().isoformat(),
            "was_correct": was_correct
        })
        
        # Check for milestones (every 100, 500, 1000, etc.)
        if was_correct and (number % 100 == 0 or number % 500 == 0 or number % 1000 == 0):
            db["milestones"][str(number)] = {
                "user_id": int(user_id),
                "timestamp": datetime.now().isoformat()
            }
        
        self.save_database()

    # ==================== EVENT LISTENERS ====================
    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle counting messages"""
        if message.author.bot or not message.guild:
            return

        config = self.get_guild_config(message.guild.id)
        
        # Check if this is the counting channel and system is enabled
        if not config["enabled"] or message.channel.id != config.get("counting_channel"):
            return

        # Check if user is blacklisted
        if self.is_user_blacklisted(message.guild.id, message.author.id):
            if config.get("auto_delete_wrong", True):
                try:
                    await message.delete()
                except:
                    pass
            await self.log_counting_action(
                "blacklisted user attempt",
                message.guild,
                message.author,
                f"content: {message.content[:50]}"
            )
            return

        # Try to parse the number
        try:
            number = int(message.content.strip())
        except ValueError:
            # Not a valid number
            if config.get("auto_delete_wrong", True):
                try:
                    await message.delete()
                    await message.channel.send(f"❌ {message.author.mention}, please only send numbers!", delete_after=5)
                except:
                    pass
            
            self.update_user_stats(message.guild.id, message.author.id, 0, False)
            await self.log_counting_action(
                "invalid number sent",
                message.guild,
                message.author,
                f"content: {message.content[:50]}"
            )
            return

        expected_number = config["current_count"] + 1
        
        # Check if it's the correct number
        if number != expected_number:
            # Wrong number
            await self.handle_wrong_count(message, number, expected_number, config)
            return

        # Check if same person is counting twice in a row
        if config["last_counter"] == message.author.id:
            if config.get("auto_delete_wrong", True):
                try:
                    await message.delete()
                    await message.channel.send(f"❌ {message.author.mention}, you can't count twice in a row!", delete_after=5)
                except:
                    pass
            
            self.update_user_stats(message.guild.id, message.author.id, number, False)
            await self.log_counting_action(
                "consecutive count attempt",
                message.guild,
                message.author,
                f"number: {number}"
            )
            return

        # Correct count!
        await self.handle_correct_count(message, number, config)

    async def handle_correct_count(self, message, number, config):
        """Handle a correct count"""
        # Update config
        config["current_count"] = number
        config["last_counter"] = message.author.id
        
        if number > config["highest_count"]:
            config["highest_count"] = number
        
        if config["counting_start_date"] is None:
            config["counting_start_date"] = datetime.now().isoformat()
        
        self.save_config()
        
        # Update user stats
        self.update_user_stats(message.guild.id, message.author.id, number, True)
        
        # Add reaction to show it's correct
        try:
            await message.add_reaction("✅")
        except:
            pass
        
        # Check for milestones and celebrate
        await self.check_milestone(message, number)
        
        await self.log_counting_action(
            "correct count",
            message.guild,
            message.author,
            f"number: {number}"
        )

    async def handle_wrong_count(self, message, number, expected_number, config):
        """Handle a wrong count"""
        # Update user stats
        self.update_user_stats(message.guild.id, message.author.id, number, False)
        
        # Add reaction to show it's wrong
        try:
            await message.add_reaction("❌")
        except:
            pass
        
        if config.get("auto_delete_wrong", True):
            try:
                await message.delete()
                await message.channel.send(
                    f"❌ {message.author.mention}, wrong number! Expected **{expected_number}** but got **{number}**.\n"
                    f"The count continues from **{config['current_count']}**.",
                    delete_after=10
                )
            except:
                pass
        
        await self.log_counting_action(
            "wrong count",
            message.guild,
            message.author,
            f"expected: {expected_number}, got: {number}"
        )

    async def check_milestone(self, message, number):
        """Check and celebrate milestones"""
        milestone_messages = {
            100: "🎉 **100!** Great job everyone!",
            500: "🎊 **500!** Half way to 1000!",
            1000: "🚀 **1000!** Amazing counting skills!",
            2500: "⭐ **2500!** You're on fire!",
            5000: "💫 **5000!** Incredible dedication!",
            10000: "👑 **10,000!** You are counting legends!"
        }
        
        # Check if this number is a special milestone
        if number in milestone_messages:
            try:
                await message.channel.send(milestone_messages[number])
                await self.log_counting_action(
                    "milestone reached",
                    message.guild,
                    message.author,
                    f"milestone: {number}"
                )
            except:
                pass
        
        # Celebrate every 1000 after 10k
        elif number > 10000 and number % 1000 == 0:
            try:
                await message.channel.send(f"🎯 **{number:,}!** Keep up the amazing work!")
                await self.log_counting_action(
                    "milestone reached",
                    message.guild,
                    message.author,
                    f"milestone: {number}"
                )
            except:
                pass

    # ==================== COMMANDS ====================
    # Hybrid Command Group
    @commands.hybrid_group(name="count", invoke_without_command=True)
    async def count(self, ctx):
        """Counting system commands"""
        if ctx.invoked_subcommand is None:
            config = self.get_guild_config(ctx.guild.id)
            
            embed = discord.Embed(
                title="🔢 Counting System",
                color=0x00ff00 if config["enabled"] else 0xff0000
            )
            
            # System status
            status_emoji = "✅" if config["enabled"] else "⏸️"
            embed.add_field(
                name=f"{status_emoji} System Status",
                value="**Enabled**" if config["enabled"] else "**Disabled**",
                inline=True
            )
            
            if config.get("counting_channel"):
                channel = ctx.guild.get_channel(config["counting_channel"])
                embed.add_field(
                    name="📺 Counting Channel",
                    value=channel.mention if channel else "Channel not found",
                    inline=True
                )
            
            embed.add_field(
                name="🔢 Current Count",
                value=f"**{config['current_count']:,}**",
                inline=True
            )
            
            embed.add_field(
                name="🏆 Highest Count",
                value=f"**{config['highest_count']:,}**",
                inline=True
            )
            
            if config["last_counter"]:
                last_user = ctx.guild.get_member(config["last_counter"])
                embed.add_field(
                    name="👤 Last Counter",
                    value=last_user.mention if last_user else "Unknown User",
                    inline=True
                )
            
            # Auto-delete setting
            embed.add_field(
                name="🗑️ Auto-delete Wrong",
                value="Enabled" if config.get("auto_delete_wrong", True) else "Disabled",
                inline=True
            )
            
            embed.add_field(
                name="📋 Commands",
                value="`/count toggle` - Enable/disable system\n"
                      "`/count status` - Show detailed status\n"
                      "`/count config` - Show configuration\n"
                      "`/count leaderboard` - View leaderboard\n"
                      "`/count profile [user]` - View user profile",
                inline=False
            )
            
            if not config["enabled"]:
                embed.add_field(
                    name="ℹ️ Note",
                    value="System is disabled. Use `/count toggle` to enable.",
                    inline=False
                )
            
            await ctx.send(embed=embed)

    @count.command(name="toggle")
    @discord.app_commands.describe(enabled="Enable or disable the counting system")
    async def count_toggle(self, ctx, enabled: Optional[bool] = None):
        """Toggle counting system on/off (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure counting settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        # If no argument provided, toggle current state
        if enabled is None:
            enabled = not config["enabled"]
        
        old_state = config["enabled"]
        config["enabled"] = enabled
        self.save_config()

        # Create response embed
        if enabled:
            embed = discord.Embed(
                title="✅ Counting System Enabled",
                description="The counting system is now active. Users can count in the configured channel.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Counting System Disabled",
                description="The counting system is now disabled. No counting will be processed.",
                color=discord.Color.orange()
            )

        embed.add_field(
            name="Status Change",
            value=f"{'Enabled' if old_state else 'Disabled'} → {'Enabled' if enabled else 'Disabled'}",
            inline=True
        )

        # Show current configuration if enabled
        if enabled and config.get("counting_channel"):
            channel = ctx.guild.get_channel(config["counting_channel"])
            embed.add_field(
                name="Counting Channel",
                value=channel.mention if channel else "Not set",
                inline=True
            )

        await ctx.send(embed=embed)

        # Log the change
        details = f"enabled: {enabled}"
        if old_state != enabled:
            details += f" (was: {old_state})"
        
        await self.log_counting_action("toggled system state", ctx.guild, ctx.author, details)

    @count.command(name="status")
    async def count_status(self, ctx):
        """Show detailed counting system status"""
        config = self.get_guild_config(ctx.guild.id)
        db = self.get_guild_database(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        if is_enabled:
            embed = discord.Embed(
                title="✅ Counting System Status",
                description="The counting system is currently **enabled**.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Counting System Status", 
                description="The counting system is currently **disabled**.",
                color=discord.Color.orange()
            )

        # Current progress
        embed.add_field(
            name="📊 Current Progress",
            value=f"Current Count: **{config['current_count']:,}**\n"
                  f"Highest Count: **{config['highest_count']:,}**\n"
                  f"Total Resets: **{config['total_resets']}**",
            inline=True
        )

        # Participation stats
        total_counts = sum(db.get("user_counts", {}).values())
        total_fails = sum(db.get("fails", {}).values())
        unique_counters = len(db.get("user_counts", {}))
        
        embed.add_field(
            name="👥 Participation",
            value=f"Total Counts: **{total_counts:,}**\n"
                  f"Failed Attempts: **{total_fails:,}**\n"
                  f"Unique Counters: **{unique_counters}**",
            inline=True
        )

        # Channel and settings
        channel_text = "Not set"
        if config.get("counting_channel"):
            channel = ctx.guild.get_channel(config["counting_channel"])
            channel_text = channel.mention if channel else "Channel not found"
        
        embed.add_field(
            name="⚙️ Settings",
            value=f"Channel: {channel_text}\n"
                  f"Auto-delete: {'Enabled' if config.get('auto_delete_wrong', True) else 'Disabled'}\n"
                  f"Blacklisted: **{len(config.get('blacklisted_users', []))}** users",
            inline=True
        )

        # Success rate
        if total_counts + total_fails > 0:
            success_rate = (total_counts / (total_counts + total_fails)) * 100
            embed.add_field(
                name="📈 Accuracy",
                value=f"Success Rate: **{success_rate:.1f}%**",
                inline=True
            )

        # Top contributor
        if db.get("user_counts"):
            top_user_id = max(db["user_counts"], key=db["user_counts"].get)
            top_user = ctx.guild.get_member(int(top_user_id))
            top_count = db["user_counts"][top_user_id]
            
            embed.add_field(
                name="🏆 Top Contributor",
                value=f"{top_user.mention if top_user else 'Unknown User'}\n**{top_count:,}** counts",
                inline=True
            )

        # Time info
        if config.get("counting_start_date"):
            try:
                start_date = datetime.fromisoformat(config["counting_start_date"])
                days_counting = (datetime.now() - start_date).days
                avg_per_day = config['current_count'] / max(days_counting, 1)
                embed.add_field(
                    name="⏰ Time Statistics",
                    value=f"Counting for: **{days_counting}** days\nAverage per day: **{avg_per_day:.1f}**",
                    inline=True
                )
            except:
                pass

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="While disabled, no counting will be processed.",
                inline=False
            )

        await ctx.send(embed=embed)

    @count.command(name="config")
    async def count_config(self, ctx):
        """Show current counting configuration (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to view configuration.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        embed = discord.Embed(
            title="🔢 Counting Configuration",
            color=0x00ff00 if is_enabled else 0x808080
        )

        # System status
        status_emoji = "✅" if is_enabled else "⏸️"
        embed.add_field(
            name=f"{status_emoji} System Status",
            value=f"**{'Enabled' if is_enabled else 'Disabled'}**",
            inline=True
        )

        # Channel configuration
        if config.get("counting_channel"):
            channel = ctx.guild.get_channel(config["counting_channel"])
            embed.add_field(
                name="📺 Counting Channel",
                value=channel.mention if channel else "Channel not found",
                inline=True
            )
        else:
            embed.add_field(
                name="📺 Counting Channel",
                value="Not configured",
                inline=True
            )

        # Settings
        embed.add_field(
            name="⚙️ Settings",
            value=f"Auto-delete wrong: {'Enabled' if config.get('auto_delete_wrong', True) else 'Disabled'}",
            inline=True
        )

        # Current progress
        embed.add_field(
            name="📊 Progress",
            value=f"Current: **{config['current_count']:,}**\n"
                  f"Highest: **{config['highest_count']:,}**\n"
                  f"Resets: **{config['total_resets']}**",
            inline=True
        )

        # Last counter
        if config["last_counter"]:
            last_user = ctx.guild.get_member(config["last_counter"])
            embed.add_field(
                name="👤 Last Counter",
                value=last_user.mention if last_user else "Unknown User",
                inline=True
            )

        # Blacklisted users
        blacklisted_count = len(config.get("blacklisted_users", []))
        embed.add_field(
            name="🚫 Blacklisted Users",
            value=f"**{blacklisted_count}** users",
            inline=True
        )

        # Start date
        if config.get("counting_start_date"):
            try:
                start_date = datetime.fromisoformat(config["counting_start_date"])
                embed.add_field(
                    name="📅 Started",
                    value=f"<t:{int(start_date.timestamp())}:D>",
                    inline=True
                )
            except:
                pass

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="System is disabled. Use `/count toggle` to enable.",
                inline=False
            )

        await ctx.send(embed=embed)

    @count.command(name="reset")
    async def reset_count(self, ctx):
        """Reset the current count (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        old_count = config["current_count"]
        
        config["current_count"] = 0
        config["last_counter"] = None
        config["total_resets"] += 1
        self.save_config()

        # Reset all current streaks
        db = self.get_guild_database(ctx.guild.id)
        db["current_streaks"] = {}
        self.save_database()

        embed = discord.Embed(
            title="✅ Count Reset",
            description=f"Count has been reset from **{old_count:,}** to **0**.",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Reset Count",
            value=f"This is reset #{config['total_resets']}",
            inline=True
        )

        await ctx.send(embed=embed)
        await self.log_counting_action(
            "count reset",
            ctx.guild,
            ctx.author,
            f"from: {old_count}"
        )

    @count.command(name="setchannel")
    @discord.app_commands.describe(channel="The channel to use for counting")
    async def set_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the counting channel (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure counting settings.", ephemeral=True)
            return

        channel = channel or ctx.channel
        config = self.get_guild_config(ctx.guild.id)
        
        old_channel_id = config.get("counting_channel")
        old_channel = ctx.guild.get_channel(old_channel_id) if old_channel_id else None
        
        config["counting_channel"] = channel.id
        config["enabled"] = True
        self.save_config()

        embed = discord.Embed(
            title="✅ Counting Channel Set",
            description=f"Counting channel set to {channel.mention}!\nThe counting system has been automatically enabled.",
            color=discord.Color.green()
        )
        
        if old_channel:
            embed.add_field(
                name="Channel Change",
                value=f"{old_channel.mention} → {channel.mention}",
                inline=True
            )

        await ctx.send(embed=embed)
        
        details = f"channel: {channel.name}"
        if old_channel:
            details += f" (was: {old_channel.name})"
        
        await self.log_counting_action("counting channel set", ctx.guild, ctx.author, details)

    @count.command(name="leaderboard", aliases=["lb", "top"])
    @discord.app_commands.describe(limit="Number of users to show (max 20)")
    async def leaderboard(self, ctx, limit: int = 10):
        """Show the counting leaderboard"""
        if limit > 20:
            limit = 20
        elif limit < 1:
            limit = 10

        db = self.get_guild_database(ctx.guild.id)
        user_counts = db.get("user_counts", {})
        
        if not user_counts:
            embed = discord.Embed(
                title="🏆 Counting Leaderboard",
                description="No counting data available yet!",
                color=0xff9900
            )
            embed.add_field(
                name="Get Started",
                value="Start counting in the configured channel to appear on the leaderboard!",
                inline=False
            )
            await ctx.send(embed=embed)
            return

        # Sort users by count
        sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        embed = discord.Embed(
            title="🏆 Counting Leaderboard",
            color=0xFFD700
        )
        
        leaderboard_text = ""
        for i, (user_id, count) in enumerate(sorted_users, 1):
            user = ctx.guild.get_member(int(user_id))
            username = user.display_name if user else f"Unknown User ({user_id})"
            
            # Add medal emojis for top 3
            medal = ""
            if i == 1:
                medal = "🥇 "
            elif i == 2:
                medal = "🥈 "
            elif i == 3:
                medal = "🥉 "
            
            # Add streak info
            current_streak = db.get("current_streaks", {}).get(user_id, 0)
            best_streak = db.get("streak_records", {}).get(user_id, 0)
            
            leaderboard_text += f"{medal}**{i}.** {username}\n"
            leaderboard_text += f"   Counts: **{count:,}** | Current Streak: **{current_streak}** | Best: **{best_streak}**\n\n"
        
        embed.description = leaderboard_text
        
        config = self.get_guild_config(ctx.guild.id)
        embed.set_footer(text=f"Current server count: {config['current_count']:,}")
        
        await ctx.send(embed=embed)

    @count.command(name="profile", aliases=["me"])
    @discord.app_commands.describe(user="User to view profile for (defaults to yourself)")
    async def user_profile(self, ctx, user: discord.Member = None):
        """Show counting profile for a user"""
        user = user or ctx.author
        db = self.get_guild_database(ctx.guild.id)
        
        user_id = str(user.id)
        total_counts = db.get("user_counts", {}).get(user_id, 0)
        total_fails = db.get("fails", {}).get(user_id, 0)
        current_streak = db.get("current_streaks", {}).get(user_id, 0)
        best_streak = db.get("streak_records", {}).get(user_id, 0)
        
        embed = discord.Embed(
            title=f"🔢 {user.display_name}'s Counting Profile",
            color=user.color
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        embed.add_field(
            name="📊 Statistics",
            value=f"Correct Counts: **{total_counts:,}**\n"
                  f"Failed Attempts: **{total_fails:,}**\n"
                  f"Current Streak: **{current_streak}**\n"
                  f"Best Streak: **{best_streak}**",
            inline=False
        )
        
        # Calculate accuracy
        if total_counts + total_fails > 0:
            accuracy = (total_counts / (total_counts + total_fails)) * 100
            embed.add_field(
                name="🎯 Accuracy",
                value=f"**{accuracy:.1f}%**",
                inline=True
            )
        
        # Rank in server
        all_users = db.get("user_counts", {})
        if all_users:
            sorted_users = sorted(all_users.items(), key=lambda x: x[1], reverse=True)
            rank = next((i for i, (uid, _) in enumerate(sorted_users, 1) if uid == user_id), None)
            if rank:
                embed.add_field(
                    name="🏆 Server Rank",
                    value=f"**#{rank}** out of {len(all_users)}",
                    inline=True
                )
        
        # Check if blacklisted
        config = self.get_guild_config(ctx.guild.id)
        if user.id in config.get("blacklisted_users", []):
            embed.add_field(
                name="🚫 Status",
                value="**Blacklisted**",
                inline=True
            )

        # Personal milestones
        user_milestones = []
        for milestone_num, milestone_data in db.get("milestones", {}).items():
            if milestone_data["user_id"] == user.id:
                user_milestones.append(int(milestone_num))
        
        if user_milestones:
            user_milestones.sort(reverse=True)
            milestone_text = ", ".join([f"**{m:,}**" for m in user_milestones[:5]])
            if len(user_milestones) > 5:
                milestone_text += f" (and {len(user_milestones) - 5} more)"
            
            embed.add_field(
                name="🎯 Milestones Hit",
                value=milestone_text,
                inline=False
            )

        if total_counts == 0 and total_fails == 0:
            embed.add_field(
                name="💡 Get Started",
                value="Start counting in the configured channel to build your profile!",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @count.command(name="stats")
    async def server_stats(self, ctx):
        """Show server counting statistics"""
        config = self.get_guild_config(ctx.guild.id)
        db = self.get_guild_database(ctx.guild.id)
        
        embed = discord.Embed(
            title="📈 Server Counting Statistics",
            color=0x00ff00
        )
        
        # Basic stats
        total_counts = sum(db.get("user_counts", {}).values())
        total_fails = sum(db.get("fails", {}).values())
        unique_counters = len(db.get("user_counts", {}))
        
        embed.add_field(
            name="📊 Current Progress",
            value=f"Current Count: **{config['current_count']:,}**\n"
                  f"Highest Count: **{config['highest_count']:,}**\n"
                  f"Total Resets: **{config['total_resets']}**",
            inline=False
        )
        
        embed.add_field(
            name="👥 Participation",
            value=f"Total Counts: **{total_counts:,}**\n"
                  f"Failed Attempts: **{total_fails:,}**\n"
                  f"Unique Counters: **{unique_counters}**",
            inline=False
        )
        
        # Success rate
        if total_counts + total_fails > 0:
            success_rate = (total_counts / (total_counts + total_fails)) * 100
            embed.add_field(
                name="🎯 Accuracy",
                value=f"Success Rate: **{success_rate:.1f}%**",
                inline=True
            )
        
        # Top contributor
        if db.get("user_counts"):
            top_user_id = max(db["user_counts"], key=db["user_counts"].get)
            top_user = ctx.guild.get_member(int(top_user_id))
            top_count = db["user_counts"][top_user_id]
            
            embed.add_field(
                name="🏆 Top Contributor",
                value=f"{top_user.mention if top_user else 'Unknown User'}\n**{top_count:,}** counts",
                inline=True
            )
        
        # Recent milestones
        recent_milestones = []
        for number, data in db.get("milestones", {}).items():
            if int(number) >= config["current_count"] - 1000:  # Last 1000 counts
                user = ctx.guild.get_member(data["user_id"])
                recent_milestones.append(f"**{number}** - {user.mention if user else 'Unknown'}")
        
        if recent_milestones:
            recent_milestones.sort(key=lambda x: int(x.split('**')[1]), reverse=True)
            embed.add_field(
                name="🎯 Recent Milestones",
                value="\n".join(recent_milestones[-5:]),  # Last 5 milestones
                inline=False
            )
        
        # Time info
        if config.get("counting_start_date"):
            try:
                start_date = datetime.fromisoformat(config["counting_start_date"])
                days_counting = (datetime.now() - start_date).days
                embed.add_field(
                    name="⏰ Time Statistics",
                    value=f"Counting for: **{days_counting}** days\n"
                          f"Average per day: **{config['current_count'] / max(days_counting, 1):.1f}**",
                    inline=True
                )
            except:
                pass
        
        await ctx.send(embed=embed)

    @count.group(name="blacklist", invoke_without_command=True)
    async def count_blacklist(self, ctx):
        """Blacklist management commands (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🚫 Blacklist Management",
                description="Use the subcommands to manage the counting blacklist:",
                color=0xff0000
            )
            embed.add_field(
                name="Available Commands",
                value="`/count blacklist add <user>` - Add user to blacklist\n"
                      "`/count blacklist remove <user>` - Remove user from blacklist\n"
                      "`/count blacklist list` - Show blacklisted users\n"
                      "`/count blacklist clear` - Clear entire blacklist",
                inline=False
            )
            await ctx.send(embed=embed)

    @count_blacklist.command(name="add")
    @discord.app_commands.describe(user="User to blacklist from counting")
    async def blacklist_add(self, ctx, user: discord.Member):
        """Add a user to the counting blacklist (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        if user.id in config["blacklisted_users"]:
            await ctx.send(f"❌ {user.mention} is already blacklisted.", ephemeral=True)
            return
        
        config["blacklisted_users"].append(user.id)
        self.save_config()
        
        embed = discord.Embed(
            title="✅ User Blacklisted",
            description=f"{user.mention} has been blacklisted from counting.",
            color=discord.Color.red()
        )
        
        embed.add_field(
            name="Total Blacklisted",
            value=f"{len(config['blacklisted_users'])} users",
            inline=True
        )
        
        await ctx.send(embed=embed)
        await self.log_counting_action(
            "user blacklisted",
            ctx.guild,
            ctx.author,
            f"blacklisted: {user.name} ({user.id})"
        )

    @count_blacklist.command(name="remove")
    @discord.app_commands.describe(user="User to remove from blacklist")
    async def blacklist_remove(self, ctx, user: discord.Member):
        """Remove a user from the counting blacklist (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        if user.id not in config["blacklisted_users"]:
            await ctx.send(f"❌ {user.mention} is not blacklisted.", ephemeral=True)
            return
        
        config["blacklisted_users"].remove(user.id)
        self.save_config()
        
        embed = discord.Embed(
            title="✅ User Unblacklisted",
            description=f"{user.mention} has been removed from the blacklist.",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Total Blacklisted",
            value=f"{len(config['blacklisted_users'])} users",
            inline=True
        )
        
        await ctx.send(embed=embed)
        await self.log_counting_action(
            "user unblacklisted",
            ctx.guild,
            ctx.author,
            f"unblacklisted: {user.name} ({user.id})"
        )

    @count_blacklist.command(name="list")
    async def blacklist_list(self, ctx):
        """Show all blacklisted users"""
        config = self.get_guild_config(ctx.guild.id)
        blacklisted = config.get("blacklisted_users", [])
        
        if not blacklisted:
            embed = discord.Embed(
                title="🚫 Counting Blacklist",
                description="No users are currently blacklisted from counting.",
                color=0x7289da
            )
            await ctx.send(embed=embed)
            return
        
        user_list = []
        for i, user_id in enumerate(blacklisted, 1):
            member = ctx.guild.get_member(user_id)
            if member:
                user_list.append(f"{i}. {member.mention}")
            else:
                user_list.append(f"{i}. Unknown User ({user_id})")
        
        embed = discord.Embed(
            title="🚫 Counting Blacklist",
            description="\n".join(user_list),
            color=0xff0000
        )
        
        embed.add_field(
            name="Total Blacklisted",
            value=f"{len(blacklisted)} users",
            inline=True
        )
        
        await ctx.send(embed=embed)

    @count_blacklist.command(name="clear")
    async def blacklist_clear(self, ctx):
        """Clear the entire blacklist (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        blacklisted_count = len(config["blacklisted_users"])
        
        if blacklisted_count == 0:
            await ctx.send("❌ No users are currently blacklisted.", ephemeral=True)
            return

        config["blacklisted_users"] = []
        self.save_config()
        
        embed = discord.Embed(
            title="✅ Blacklist Cleared",
            description=f"Cleared {blacklisted_count} users from the blacklist.",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        await self.log_counting_action(
            "blacklist cleared",
            ctx.guild,
            ctx.author,
            f"cleared {blacklisted_count} users"
        )

    @count.command(name="autodelete")
    async def toggle_autodelete(self, ctx):
        """Toggle auto-deletion of wrong counts (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure counting settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        old_state = config.get("auto_delete_wrong", True)
        config["auto_delete_wrong"] = not old_state
        self.save_config()

        new_state = config["auto_delete_wrong"]
        
        if new_state:
            embed = discord.Embed(
                title="✅ Auto-delete Enabled",
                description="Wrong counts will now be automatically deleted.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Auto-delete Disabled",
                description="Wrong counts will no longer be automatically deleted.",
                color=discord.Color.orange()
            )

        embed.add_field(
            name="Status Change",
            value=f"{'Enabled' if old_state else 'Disabled'} → {'Enabled' if new_state else 'Disabled'}",
            inline=True
        )

        await ctx.send(embed=embed)
        await self.log_counting_action(
            "auto-delete toggled",
            ctx.guild,
            ctx.author,
            f"enabled: {new_state} (was: {old_state})"
        )

    @count.command(name="set")
    @discord.app_commands.describe(number="Number to set the count to")
    async def set_count(self, ctx, number: int):
        """Set the current count to a specific number (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        if number < 0:
            await ctx.send("❌ Count cannot be negative.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        old_count = config["current_count"]
        config["current_count"] = number
        config["last_counter"] = None  # Reset last counter
        
        if number > config["highest_count"]:
            config["highest_count"] = number
        
        self.save_config()

        embed = discord.Embed(
            title="✅ Count Set",
            description=f"Count has been set from **{old_count:,}** to **{number:,}**.",
            color=discord.Color.green()
        )
        
        if number > old_count:
            embed.add_field(
                name="New Record",
                value="This is a new highest count!" if number > config["highest_count"] else "Count increased",
                inline=True
            )

        await ctx.send(embed=embed)
        await self.log_counting_action(
            "count manually set",
            ctx.guild,
            ctx.author,
            f"from: {old_count}, to: {number}"
        )

async def setup(bot):
    await bot.add_cog(CountingCog(bot))
