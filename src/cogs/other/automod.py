"""
Discord Automod Cog - Advanced Automatic Moderation System

OVERVIEW:
Comprehensive automatic moderation with multiple detection features, configurable
thresholds, punishment escalation, and detailed logging. Monitors messages in real-time.

SETUP:
- No manual setup required - auto-creates files
- Config: src/config/automod_config.json
- Requires: PermissionsCog (optional), LoggingCog (optional)
- Set log channel: /automod log-channel <channel>

PERMISSIONS:
- Configure automod: 'permissions.automod.admin' or Administrator

COMMANDS:
/automod turnon/turnoff <feature>       - Enable/disable automod features
/automod threshold <feature> <number>   - Set trigger threshold (-1=disabled, 0=instant)
/automod punishment <feature> <enabled> - Enable/disable punishment
/automod punishment-type <feature> <type> - Set punishment type
/automod info                          - Show complete configuration
/automod user-info [user]              - Show user's trigger counts
/automod clear-triggers <user> [feature] - Clear user's violation history
/automod set-ignore-time <feature> <seconds> - Set trigger reset time
/automod channel exclude/include <channel> <feature> - Channel exceptions
/automod channel list <feature/all>    - List channel statuses
/automod log-channel [channel]         - Set/view log channel

Prefix commands: !automod <subcommand> (same functionality)

USAGE BY OTHER COGS:

# Check automod configuration
class MyCog(commands.Cog):
    def check_automod_feature(self, feature):
        automod_cog = self.bot.get_cog('AutomodCog')
        if automod_cog:
            return automod_cog.config.get('features', {}).get(feature, {}).get('enabled', False)
        return False
    
    # Access user trigger data
    def get_user_violations(self, user_id):
        automod_cog = self.bot.get_cog('AutomodCog')
        if automod_cog:
            return dict(automod_cog.user_triggers.get(user_id, {}))
        return {}

AUTOMOD FEATURES:
• attachment_spam: Detects file upload spam with rate limiting
• swear: Scans for configurable inappropriate words
• caps: Detects excessive CAPS usage (configurable percentage)
• invite: Blocks Discord invite links (can allow own server)
• link: Prevents URL spam with rate limiting
• mention_spam: Limits excessive @mentions per message

PUNISHMENT TYPES:
warn, mute (10m timeout), kick, ban, timeout_1h, timeout_10m, delete_only

FEATURES:
• Real-time message monitoring with multiple detection algorithms
• Configurable trigger thresholds with escalation system
• Time-based trigger forgetting (configurable ignore times)
• Rate limiting for spam detection (attachments, links)
• Channel exclusion system for per-channel exceptions
• Comprehensive punishment system with multiple severity levels
• User violation tracking with automatic cleanup
• Detailed logging to both files and Discord channels
• Background tasks for trigger cleanup and maintenance
• Permission-based administration with role integration
• Both slash and prefix commands with full autocomplete
• Regex-based content detection for flexibility
• Guild-specific configuration with persistent storage
"""

import discord
from discord.ext import commands, tasks
import json
import re
import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Optional, Union
from collections import defaultdict, deque
import time
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

class AutomodCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/automod_config.json"
        self.config = {}
        
        # User trigger tracking {user_id: {feature: [(timestamp, channel_id), ...]}}
        self.user_triggers = defaultdict(lambda: defaultdict(list))
        
        # Rate limiting for attachment spam {user_id: deque of timestamps}
        self.attachment_rates = defaultdict(lambda: deque(maxlen=50))
        
        # Automod features
        self.features = [
            "attachment_spam", "swear", "caps", "invite", "link", "mention_spam"
        ]
        
        # Punishment types
        self.punishment_types = [
            "warn", "mute", "kick", "ban", "timeout_1h", "timeout_10m", "delete_only"
        ]
        
        # Load configuration
        self.load_config()
        
        # Start cleanup task
        self.cleanup_triggers.start()

    def cog_unload(self):
        self.cleanup_triggers.cancel()

    async def log_automod_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log automod actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Automod {action}"
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
                    file_override="automod_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log automod action: {e}")

    async def log_automod_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log automod errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Automod Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="automod_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log automod error: {e}")

    async def log_automod_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log automod warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Automod Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="automod_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log automod warning: {e}")

    async def log_violation(self, action: str, user: discord.Member, channel: discord.TextChannel, 
                           feature: str, details: str = "", punishment: str = None):
        """Log automod violations to channel and custom logging system"""
        guild = user.guild
        
        # Log to custom logging system
        violation_details = f"Feature: {feature}, Details: {details}"
        if punishment:
            violation_details += f", Punishment: {punishment}"
        
        await self.log_automod_action(
            f"violation detected - {action}", 
            guild, 
            user, 
            violation_details
        )
        
        # Log to Discord channel
        log_channel_id = self.config.get("log_channel_id")
        if log_channel_id:
            log_channel = self.bot.get_channel(log_channel_id)
            if log_channel:
                try:
                    embed = discord.Embed(
                        title=f"🛡️ Automod: {feature.replace('_', ' ').title()}",
                        color=discord.Color.orange(),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="👤 User", value=f"{user.mention} ({user})", inline=True)
                    embed.add_field(name="📍 Channel", value=channel.mention, inline=True)
                    embed.add_field(name="⚡ Action", value=action, inline=True)
                    
                    if details:
                        embed.add_field(name="📝 Details", value=details[:1024], inline=False)
                    
                    if punishment:
                        embed.add_field(name="⚖️ Punishment", value=punishment, inline=True)
                    
                    await log_channel.send(embed=embed)
                except Exception as e:
                    await self.log_automod_error(f"Failed to send log to channel: {e}", guild)

    def load_config(self):
        """Load automod configuration from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            else:
                # Default configuration
                self.config = {
                    "log_channel_id": None,
                    "features": {
                        "attachment_spam": {
                            "enabled": False,
                            "threshold": 3,
                            "punishment_enabled": True,
                            "punishment_type": "warn",
                            "ignore_time": 300,  # 5 minutes
                            "excluded_channels": [],
                            "rate_limit": 5,  # attachments per minute
                            "rate_window": 60  # seconds
                        },
                        "swear": {
                            "enabled": False,
                            "threshold": 3,
                            "punishment_enabled": True,
                            "punishment_type": "warn",
                            "ignore_time": 600,  # 10 minutes
                            "excluded_channels": [],
                            "words": ["shit", "fuck", "bitch"]  # basic list
                        },
                        "caps": {
                            "enabled": False,
                            "threshold": 3,
                            "punishment_enabled": True,
                            "punishment_type": "warn",
                            "ignore_time": 300,  # 5 minutes
                            "excluded_channels": [],
                            "min_length": 10,  # minimum message length to check
                            "caps_percentage": 70  # percentage of caps required
                        },
                        "invite": {
                            "enabled": False,
                            "threshold": 2,
                            "punishment_enabled": True,
                            "punishment_type": "warn",
                            "ignore_time": 600,  # 10 minutes
                            "excluded_channels": [],
                            "allow_own_server": True
                        },
                        "link": {
                            "enabled": False,
                            "threshold": 4,
                            "punishment_enabled": True,
                            "punishment_type": "warn",
                            "ignore_time": 300,  # 5 minutes
                            "excluded_channels": [],
                            "rate_limit": 3,  # links per minute
                            "rate_window": 60  # seconds
                        },
                        "mention_spam": {
                            "enabled": False,
                            "threshold": 3,
                            "punishment_enabled": True,
                            "punishment_type": "warn",
                            "ignore_time": 300,  # 5 minutes
                            "excluded_channels": [],
                            "max_mentions": 5  # max mentions per message
                        }
                    }
                }
                self.save_config()
        except Exception as e:
            # Use asyncio to schedule the logging since we can't await in __init__
            asyncio.create_task(self.log_automod_error(f"Error loading config: {e}"))
            self.config = {}

    def save_config(self):
        """Save automod configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_automod_error(f"Error saving config: {e}"))

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has automod admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.automod.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def add_trigger(self, user_id: int, feature: str, channel_id: int):
        """Add a trigger for a user and feature"""
        current_time = time.time()
        self.user_triggers[user_id][feature].append((current_time, channel_id))

    def get_trigger_count(self, user_id: int, feature: str) -> int:
        """Get current trigger count for a user and feature"""
        if feature not in self.config.get("features", {}):
            return 0
        
        ignore_time = self.config["features"][feature].get("ignore_time", 300)
        current_time = time.time()
        cutoff_time = current_time - ignore_time
        
        # Filter out old triggers
        self.user_triggers[user_id][feature] = [
            (timestamp, channel_id) for timestamp, channel_id in self.user_triggers[user_id][feature]
            if timestamp > cutoff_time
        ]
        
        return len(self.user_triggers[user_id][feature])

    def clear_user_triggers(self, user_id: int, feature: str = None):
        """Clear triggers for a user (all features or specific feature)"""
        if feature:
            self.user_triggers[user_id][feature] = []
        else:
            self.user_triggers[user_id] = defaultdict(list)

    @tasks.loop(minutes=5)
    async def cleanup_triggers(self):
        """Clean up old triggers periodically"""
        current_time = time.time()
        
        for user_id in list(self.user_triggers.keys()):
            for feature in list(self.user_triggers[user_id].keys()):
                if feature not in self.config.get("features", {}):
                    continue
                
                ignore_time = self.config["features"][feature].get("ignore_time", 300)
                cutoff_time = current_time - ignore_time
                
                # Remove old triggers
                self.user_triggers[user_id][feature] = [
                    (timestamp, channel_id) for timestamp, channel_id in self.user_triggers[user_id][feature]
                    if timestamp > cutoff_time
                ]
                
                # Remove empty feature lists
                if not self.user_triggers[user_id][feature]:
                    del self.user_triggers[user_id][feature]
            
            # Remove empty user entries
            if not self.user_triggers[user_id]:
                del self.user_triggers[user_id]

    @cleanup_triggers.before_loop
    async def before_cleanup_triggers(self):
        await self.bot.wait_until_ready()

    async def apply_punishment(self, user: discord.Member, feature: str, trigger_count: int):
        """Apply punishment to a user"""
        feature_config = self.config["features"][feature]
        punishment_type = feature_config.get("punishment_type", "warn")
        
        try:
            if punishment_type == "warn":
                # Just log the warning
                await self.log_violation(
                    "Warning issued", user, user.guild.system_channel or user.guild.text_channels[0],
                    feature, f"Trigger count: {trigger_count}", "Warning"
                )
            
            elif punishment_type == "mute":
                try:
                    await user.timeout(timedelta(minutes=10), reason=f"Automod: {feature} violation")
                    await self.log_violation(
                        "User timed out", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "10 minute timeout"
                    )
                except discord.Forbidden:
                    await self.log_violation(
                        "Timeout failed (no permission)", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "Failed timeout"
                    )
            
            elif punishment_type == "kick":
                try:
                    await user.kick(reason=f"Automod: {feature} violation")
                    await self.log_violation(
                        "User kicked", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "Kick"
                    )
                except discord.Forbidden:
                    await self.log_violation(
                        "Kick failed (no permission)", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "Failed kick"
                    )
            
            elif punishment_type == "ban":
                try:
                    await user.ban(reason=f"Automod: {feature} violation", delete_message_days=1)
                    await self.log_violation(
                        "User banned", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "Ban"
                    )
                except discord.Forbidden:
                    await self.log_violation(
                        "Ban failed (no permission)", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "Failed ban"
                    )
            
            elif punishment_type == "timeout_1h":
                try:
                    await user.timeout(timedelta(hours=1), reason=f"Automod: {feature} violation")
                    await self.log_violation(
                        "User timed out", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "1 hour timeout"
                    )
                except discord.Forbidden:
                    await self.log_violation(
                        "Timeout failed (no permission)", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "Failed timeout"
                    )
            
            elif punishment_type == "timeout_10m":
                try:
                    await user.timeout(timedelta(minutes=10), reason=f"Automod: {feature} violation")
                    await self.log_violation(
                        "User timed out", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "10 minute timeout"
                    )
                except discord.Forbidden:
                    await self.log_violation(
                        "Timeout failed (no permission)", user, user.guild.system_channel or user.guild.text_channels[0],
                        feature, f"Trigger count: {trigger_count}", "Failed timeout"
                    )
            
        except Exception as e:
            await self.log_automod_error(f"Error applying punishment {punishment_type} to {user}: {e}", user.guild, user)

    async def check_attachment_spam(self, message: discord.Message) -> bool:
        """Check for attachment spam"""
        if not message.attachments:
            return False
        
        feature_config = self.config["features"]["attachment_spam"]
        rate_limit = feature_config.get("rate_limit", 5)
        rate_window = feature_config.get("rate_window", 60)
        
        current_time = time.time()
        user_rates = self.attachment_rates[message.author.id]
        
        # Add current attachment
        user_rates.append(current_time)
        
        # Count attachments in the time window
        cutoff_time = current_time - rate_window
        recent_attachments = sum(1 for timestamp in user_rates if timestamp > cutoff_time)
        
        return recent_attachments > rate_limit

    async def check_swear(self, message: discord.Message) -> bool:
        """Check for swear words"""
        feature_config = self.config["features"]["swear"]
        swear_words = feature_config.get("words", [])
        
        content_lower = message.content.lower()
        for word in swear_words:
            if word.lower() in content_lower:
                return True
        return False

    async def check_caps(self, message: discord.Message) -> bool:
        """Check for excessive caps"""
        feature_config = self.config["features"]["caps"]
        min_length = feature_config.get("min_length", 10)
        caps_percentage = feature_config.get("caps_percentage", 70)
        
        content = message.content
        if len(content) < min_length:
            return False
        
        # Count alphabetic characters
        alpha_chars = [c for c in content if c.isalpha()]
        if not alpha_chars:
            return False
        
        caps_chars = [c for c in alpha_chars if c.isupper()]
        caps_percent = (len(caps_chars) / len(alpha_chars)) * 100
        
        return caps_percent >= caps_percentage

    async def check_invite(self, message: discord.Message) -> bool:
        """Check for invite links"""
        feature_config = self.config["features"]["invite"]
        allow_own_server = feature_config.get("allow_own_server", True)
        
        # Discord invite pattern
        invite_pattern = r'discord\.gg\/\w+|discordapp\.com\/invite\/\w+|discord\.com\/invite\/\w+'
        invites = re.findall(invite_pattern, message.content, re.IGNORECASE)
        
        if not invites:
            return False
        
        if allow_own_server:
            # Check if any invite is from the current server
            try:
                for invite_code in invites:
                    # Extract invite code
                    code = invite_code.split('/')[-1]
                    try:
                        invite = await self.bot.fetch_invite(code)
                        if invite.guild and invite.guild.id == message.guild.id:
                            continue  # Allow own server invites
                        else:
                            return True  # External invite found
                    except:
                        return True  # Treat invalid/expired invites as violations
            except:
                return True
        
        return bool(invites)

    async def check_link_spam(self, message: discord.Message) -> bool:
        """Check for link spam"""
        feature_config = self.config["features"]["link"]
        rate_limit = feature_config.get("rate_limit", 3)
        rate_window = feature_config.get("rate_window", 60)
        
        # URL pattern
        url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        links = re.findall(url_pattern, message.content)
        
        if not links:
            return False
        
        # Track links per user
        if not hasattr(self, 'link_rates'):
            self.link_rates = defaultdict(lambda: deque(maxlen=50))
        
        current_time = time.time()
        user_rates = self.link_rates[message.author.id]
        
        # Add current links
        for _ in links:
            user_rates.append(current_time)
        
        # Count links in the time window
        cutoff_time = current_time - rate_window
        recent_links = sum(1 for timestamp in user_rates if timestamp > cutoff_time)
        
        return recent_links > rate_limit

    async def check_mention_spam(self, message: discord.Message) -> bool:
        """Check for mention spam"""
        feature_config = self.config["features"]["mention_spam"]
        max_mentions = feature_config.get("max_mentions", 5)
        
        total_mentions = len(message.mentions) + len(message.role_mentions)
        return total_mentions > max_mentions

    # ==================== EVENT LISTENER ====================
    @commands.Cog.listener()
    async def on_message(self, message):
        """Check messages for automod violations"""
        if message.author.bot or not message.guild:
            return
        
        # Check each enabled feature
        for feature, feature_config in self.config.get("features", {}).items():
            if not feature_config.get("enabled", False):
                continue
            
            # Check if channel is excluded
            if message.channel.id in feature_config.get("excluded_channels", []):
                continue
            
            # Check for violation
            violation_detected = False
            violation_details = ""
            
            try:
                if feature == "attachment_spam":
                    violation_detected = await self.check_attachment_spam(message)
                    if violation_detected:
                        violation_details = f"{len(message.attachments)} attachments"
                
                elif feature == "swear":
                    violation_detected = await self.check_swear(message)
                    if violation_detected:
                        violation_details = "Inappropriate language detected"
                
                elif feature == "caps":
                    violation_detected = await self.check_caps(message)
                    if violation_detected:
                        violation_details = "Excessive caps usage"
                
                elif feature == "invite":
                    violation_detected = await self.check_invite(message)
                    if violation_detected:
                        violation_details = "Unauthorized invite link"
                
                elif feature == "link":
                    violation_detected = await self.check_link_spam(message)
                    if violation_detected:
                        violation_details = "Link spam detected"
                
                elif feature == "mention_spam":
                    violation_detected = await self.check_mention_spam(message)
                    if violation_detected:
                        total_mentions = len(message.mentions) + len(message.role_mentions)
                        violation_details = f"{total_mentions} mentions"
                
                if violation_detected:
                    # Delete message if not delete_only punishment
                    punishment_type = feature_config.get("punishment_type", "warn")
                    if punishment_type != "delete_only":
                        try:
                            await message.delete()
                        except:
                            pass
                    
                    # Add trigger and check threshold
                    self.add_trigger(message.author.id, feature, message.channel.id)
                    trigger_count = self.get_trigger_count(message.author.id, feature)
                    threshold = feature_config.get("threshold", 3)
                    
                    await self.log_violation(
                        "Violation detected", message.author, message.channel,
                        feature, violation_details
                    )
                    
                    # Apply punishment if threshold reached and punishment is enabled
                    if (trigger_count >= threshold and 
                        feature_config.get("punishment_enabled", True) and 
                        threshold > 0):
                        await self.apply_punishment(message.author, feature, trigger_count)
                        # Clear triggers after punishment
                        self.clear_user_triggers(message.author.id, feature)
            
            except Exception as e:
                await self.log_automod_error(f"Error checking {feature} automod: {e}", message.guild, message.author)

    # Autocomplete functions
    async def feature_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for automod features"""
        return [
            discord.app_commands.Choice(name=feature.replace('_', ' ').title(), value=feature)
            for feature in self.features
            if current.lower() in feature.lower()
        ]

    async def punishment_type_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for punishment types"""
        return [
            discord.app_commands.Choice(name=punishment.replace('_', ' ').title(), value=punishment)
            for punishment in self.punishment_types
            if current.lower() in punishment.lower()
        ]

    async def enabled_feature_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for enabled features only"""
        enabled_features = [
            feature for feature, config in self.config.get("features", {}).items()
            if config.get("enabled", False)
        ]
        return [
            discord.app_commands.Choice(name=feature.replace('_', ' ').title(), value=feature)
            for feature in enabled_features
            if current.lower() in feature.lower()
        ]

    # ==================== COMMANDS ====================
    # Hybrid command group
    @commands.hybrid_group(name="automod", aliases=["am"], invoke_without_command=True)
    async def automod(self, ctx):
        """Automod management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🛡️ Automod Commands",
                description="Manage automatic moderation features",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="🔧 Configuration",
                value="```turnon/turnoff <feature>\nthreshold <feature> <number>\npunishment <feature> <enabled>\npunishment-type <feature> <type>```",
                inline=False
            )
            embed.add_field(
                name="📊 Information",
                value="```info\nuser-info [user]\nchannel list <feature/all>```",
                inline=False
            )
            embed.add_field(
                name="⚙️ Management",
                value="```channel exclude <channel> <feature>\nset-ignore-time <feature> <seconds>\nclear-triggers <user> [feature]```",
                inline=False
            )
            embed.add_field(
                name="🛡️ Features",
                value="attachment_spam, swear, caps, invite, link, mention_spam",
                inline=False
            )
            await ctx.send(embed=embed)

    @automod.command(name="turnon")
    @discord.app_commands.describe(feature="The automod feature to enable")
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_turnon(self, ctx, feature: str):
        """Turn on an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        self.config["features"][feature]["enabled"] = True
        self.save_config()

        embed = discord.Embed(
            title="✅ Automod Feature Enabled",
            description=f"**{feature.replace('_', ' ').title()}** is now active",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🎯 Threshold", 
            value=str(self.config["features"][feature].get("threshold", "Not set")), 
            inline=True
        )
        embed.add_field(
            name="⚖️ Punishment", 
            value=self.config["features"][feature].get("punishment_type", "warn").replace('_', ' ').title(), 
            inline=True
        )
        await ctx.send(embed=embed)
        
        # Log configuration change
        await self.log_automod_action(
            f"feature {feature} enabled", 
            ctx.guild, 
            ctx.author
        )

    @automod.command(name="turnoff")
    @discord.app_commands.describe(feature="The automod feature to disable")
    @discord.app_commands.autocomplete(feature=enabled_feature_autocomplete)
    async def automod_turnoff(self, ctx, feature: str):
        """Turn off an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        self.config["features"][feature]["enabled"] = False
        self.save_config()

        embed = discord.Embed(
            title="🔴 Automod Feature Disabled",
            description=f"**{feature.replace('_', ' ').title()}** is now inactive",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        
        # Log configuration change
        await self.log_automod_action(
            f"feature {feature} disabled", 
            ctx.guild, 
            ctx.author
        )

    @automod.command(name="info")
    async def automod_info(self, ctx):
        """Show automod configuration information"""
        embed = discord.Embed(
            title="🛡️ Automod Configuration",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        log_channel_id = self.config.get("log_channel_id")
        log_channel = self.bot.get_channel(log_channel_id) if log_channel_id else None
        embed.add_field(
            name="📝 Log Channel",
            value=log_channel.mention if log_channel else "Not set",
            inline=False
        )

        enabled_features = []
        disabled_features = []

        for feature, config in self.config.get("features", {}).items():
            feature_name = feature.replace('_', ' ').title()
            if config.get("enabled", False):
                threshold = config.get("threshold", "∞")
                punishment = config.get("punishment_type", "warn").replace('_', ' ').title()
                enabled_features.append(f"**{feature_name}** (T:{threshold}, P:{punishment})")
            else:
                disabled_features.append(feature_name)

        if enabled_features:
            embed.add_field(
                name="✅ Enabled Features",
                value='\n'.join(enabled_features),
                inline=False
            )

        if disabled_features:
            embed.add_field(
                name="❌ Disabled Features",
                value=', '.join(disabled_features),
                inline=False
            )

        await ctx.send(embed=embed)

    @automod.command(name="threshold")
    @discord.app_commands.describe(
        feature="The automod feature to configure",
        value="Threshold value (-1=disabled, 0=instant, >0=trigger count)"
    )
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_threshold(self, ctx, feature: str, value: int):
        """Set the threshold for an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        if value < -1:
            await ctx.send("❌ Invalid threshold. Use -1 (disabled), 0 (instant), or positive number.", ephemeral=True)
            return

        old_threshold = self.config["features"][feature].get("threshold")
        self.config["features"][feature]["threshold"] = value
        self.save_config()

        if value == -1:
            status = "Disabled"
        elif value == 0:
            status = "Instant action"
        else:
            status = f"{value} triggers"

        embed = discord.Embed(
            title="✅ Threshold Updated",
            description=f"**{feature.replace('_', ' ').title()}** threshold set to: **{status}**",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
        # Log configuration change
        await self.log_automod_action(
            f"threshold changed for {feature}", 
            ctx.guild, 
            ctx.author, 
            f"New: {value}, Previous: {old_threshold}"
        )

    @automod.command(name="punishment")
    @discord.app_commands.describe(
        feature="The automod feature to configure",
        enabled="Whether punishment is enabled for this feature"
    )
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_punishment(self, ctx, feature: str, enabled: bool):
        """Enable or disable punishment for an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        old_enabled = self.config["features"][feature].get("punishment_enabled")
        self.config["features"][feature]["punishment_enabled"] = enabled
        self.save_config()

        status = "enabled" if enabled else "disabled"
        embed = discord.Embed(
            title="✅ Punishment Settings Updated",
            description=f"Punishment for **{feature.replace('_', ' ').title()}** is now **{status}**",
            color=discord.Color.green() if enabled else discord.Color.orange()
        )
        await ctx.send(embed=embed)
        
        # Log configuration change
        await self.log_automod_action(
            f"punishment {status} for {feature}", 
            ctx.guild, 
            ctx.author, 
            f"Previous: {old_enabled}"
        )

    @automod.command(name="punishment-type")
    @discord.app_commands.describe(
        feature="The automod feature to configure",
        punishment_type="The type of punishment to apply"
    )
    @discord.app_commands.autocomplete(feature=feature_autocomplete, punishment_type=punishment_type_autocomplete)
    async def automod_punishment_type(self, ctx, feature: str, punishment_type: str):
        """Set the punishment type for an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        if punishment_type not in self.punishment_types:
            await ctx.send(f"❌ Invalid punishment type. Available: {', '.join(self.punishment_types)}", ephemeral=True)
            return

        old_type = self.config["features"][feature].get("punishment_type")
        self.config["features"][feature]["punishment_type"] = punishment_type
        self.save_config()

        embed = discord.Embed(
            title="✅ Punishment Type Updated",
            description=f"**{feature.replace('_', ' ').title()}** punishment set to: **{punishment_type.replace('_', ' ').title()}**",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
        # Log configuration change
        await self.log_automod_action(
            f"punishment type changed for {feature}", 
            ctx.guild, 
            ctx.author, 
            f"New: {punishment_type}, Previous: {old_type}"
        )

    @automod.command(name="user-info")
    @discord.app_commands.describe(user="The user to check (optional)")
    async def automod_user_info(self, ctx, user: Optional[discord.Member] = None):
        """Show automod trigger information for a user"""
        target_user = user or ctx.author

        embed = discord.Embed(
            title=f"🛡️ Automod Info: {target_user.display_name}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)

        has_triggers = False
        for feature in self.features:
            trigger_count = self.get_trigger_count(target_user.id, feature)
            if trigger_count > 0:
                has_triggers = True
                feature_config = self.config["features"][feature]
                threshold = feature_config.get("threshold", 3)
                ignore_time = feature_config.get("ignore_time", 300)
                
                # Calculate time until reset
                if self.user_triggers[target_user.id][feature]:
                    oldest_trigger = min(timestamp for timestamp, _ in self.user_triggers[target_user.id][feature])
                    time_until_reset = max(0, ignore_time - (time.time() - oldest_trigger))
                    reset_text = f"Resets in: {int(time_until_reset)}s"
                else:
                    reset_text = "No triggers"

                embed.add_field(
                    name=f"⚠️ {feature.replace('_', ' ').title()}",
                    value=f"Triggers: {trigger_count}/{threshold}\n{reset_text}",
                    inline=True
                )

        if not has_triggers:
            embed.description = "No recent automod triggers found."

        await ctx.send(embed=embed)

    @automod.command(name="clear-triggers")
    @discord.app_commands.describe(
        user="The user to clear triggers for",
        feature="Specific feature to clear (optional)"
    )
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_clear_triggers(self, ctx, user: discord.Member, feature: Optional[str] = None):
        """Clear automod triggers for a user"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature and feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        self.clear_user_triggers(user.id, feature)

        if feature:
            description = f"Cleared **{feature.replace('_', ' ').title()}** triggers for {user.mention}"
        else:
            description = f"Cleared **all** automod triggers for {user.mention}"

        embed = discord.Embed(
            title="✅ Triggers Cleared",
            description=description,
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
        # Log trigger clearing
        await self.log_automod_action(
            f"triggers cleared for {user}", 
            ctx.guild, 
            ctx.author, 
            f"Feature: {feature if feature else 'all'}"
        )

    @automod.command(name="set-ignore-time")
    @discord.app_commands.describe(
        feature="The automod feature to configure",
        seconds="Time in seconds before triggers are forgotten"
    )
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_set_ignore_time(self, ctx, feature: str, seconds: int):
        """Set the ignore time for an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        if seconds < 0:
            await ctx.send("❌ Ignore time must be positive.", ephemeral=True)
            return

        old_time = self.config["features"][feature].get("ignore_time")
        self.config["features"][feature]["ignore_time"] = seconds
        self.save_config()

        # Convert seconds to human readable format
        if seconds >= 3600:
            time_text = f"{seconds // 3600}h {(seconds % 3600) // 60}m"
        elif seconds >= 60:
            time_text = f"{seconds // 60}m {seconds % 60}s"
        else:
            time_text = f"{seconds}s"

        embed = discord.Embed(
            title="✅ Ignore Time Updated",
            description=f"**{feature.replace('_', ' ').title()}** triggers will be forgotten after: **{time_text}**",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
        # Log configuration change
        await self.log_automod_action(
            f"ignore time changed for {feature}", 
            ctx.guild, 
            ctx.author, 
            f"New: {seconds}s, Previous: {old_time}s"
        )

    # Channel management commands
    @automod.group(name="channel", invoke_without_command=True)
    async def automod_channel(self, ctx):
        """Channel-specific automod commands"""
        await ctx.send_help(ctx.command)

    @automod_channel.command(name="exclude")
    @discord.app_commands.describe(
        channel="The channel to exclude",
        feature="The automod feature to exclude the channel from"
    )
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_channel_exclude(self, ctx, channel: discord.TextChannel, feature: str):
        """Exclude a channel from an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        excluded_channels = self.config["features"][feature].get("excluded_channels", [])
        if channel.id not in excluded_channels:
            excluded_channels.append(channel.id)
            self.config["features"][feature]["excluded_channels"] = excluded_channels
            self.save_config()

            embed = discord.Embed(
                title="✅ Channel Excluded",
                description=f"{channel.mention} is now excluded from **{feature.replace('_', ' ').title()}** automod",
                color=discord.Color.green()
            )
            
            # Log configuration change
            await self.log_automod_action(
                f"channel {channel.name} excluded from {feature}", 
                ctx.guild, 
                ctx.author
            )
        else:
            embed = discord.Embed(
                title="ℹ️ Already Excluded",
                description=f"{channel.mention} is already excluded from **{feature.replace('_', ' ').title()}** automod",
                color=discord.Color.blue()
            )

        await ctx.send(embed=embed)

    @automod_channel.command(name="include")
    @discord.app_commands.describe(
        channel="The channel to include",
        feature="The automod feature to include the channel in"
    )
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_channel_include(self, ctx, channel: discord.TextChannel, feature: str):
        """Include a previously excluded channel in an automod feature"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Available: {', '.join(self.features)}", ephemeral=True)
            return

        excluded_channels = self.config["features"][feature].get("excluded_channels", [])
        if channel.id in excluded_channels:
            excluded_channels.remove(channel.id)
            self.config["features"][feature]["excluded_channels"] = excluded_channels
            self.save_config()

            embed = discord.Embed(
                title="✅ Channel Included",
                description=f"{channel.mention} is now included in **{feature.replace('_', ' ').title()}** automod",
                color=discord.Color.green()
            )
            
            # Log configuration change
            await self.log_automod_action(
                f"channel {channel.name} included in {feature}", 
                ctx.guild, 
                ctx.author
            )
        else:
            embed = discord.Embed(
                title="ℹ️ Already Included",
                description=f"{channel.mention} is already included in **{feature.replace('_', ' ').title()}** automod",
                color=discord.Color.blue()
            )

        await ctx.send(embed=embed)

    @automod_channel.command(name="list")
    @discord.app_commands.describe(feature="The feature to list channels for, or 'all' for everything")
    @discord.app_commands.autocomplete(feature=feature_autocomplete)
    async def automod_channel_list(self, ctx, feature: str):
        """List channels and their automod status"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to view automod configuration.", ephemeral=True)
            return

        if feature != "all" and feature not in self.features:
            await ctx.send(f"❌ Invalid feature. Use 'all' or one of: {', '.join(self.features)}", ephemeral=True)
            return

        if feature == "all":
            # Show comprehensive table
            embed = discord.Embed(
                title="🛡️ Automod Channel Overview",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            # Get all text channels
            channels = ctx.guild.text_channels[:10]  # Limit to prevent embed overflow

            channel_info = []
            for channel in channels:
                excluded_features = []
                for feat, config in self.config.get("features", {}).items():
                    if channel.id in config.get("excluded_channels", []):
                        excluded_features.append(feat.replace('_', ' ').title())

                if excluded_features:
                    status = f"Excluded: {', '.join(excluded_features)}"
                else:
                    status = "All features active"

                channel_info.append(f"**{channel.name}**: {status}")

            if channel_info:
                embed.description = '\n'.join(channel_info)
            else:
                embed.description = "No channels found."

            if len(ctx.guild.text_channels) > 10:
                embed.set_footer(text=f"Showing first 10 of {len(ctx.guild.text_channels)} channels")

        else:
            # Show specific feature
            embed = discord.Embed(
                title=f"🛡️ {feature.replace('_', ' ').title()} Channel Status",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            excluded_channel_ids = self.config["features"][feature].get("excluded_channels", [])
            excluded_channels = [self.bot.get_channel(cid) for cid in excluded_channel_ids]
            excluded_channels = [ch for ch in excluded_channels if ch and ch.guild == ctx.guild]

            all_channels = ctx.guild.text_channels
            included_channels = [ch for ch in all_channels if ch.id not in excluded_channel_ids]

            if included_channels:
                included_names = [ch.mention for ch in included_channels[:10]]
                embed.add_field(
                    name="✅ Monitored Channels",
                    value='\n'.join(included_names) or "None",
                    inline=False
                )

            if excluded_channels:
                excluded_names = [ch.mention for ch in excluded_channels[:10]]
                embed.add_field(
                    name="❌ Excluded Channels",
                    value='\n'.join(excluded_names) or "None",
                    inline=False
                )

            embed.add_field(
                name="📊 Summary",
                value=f"Monitored: {len(included_channels)}\nExcluded: {len(excluded_channels)}",
                inline=True
            )

        await ctx.send(embed=embed)

    # Set log channel command
    @automod.command(name="log-channel")
    @discord.app_commands.describe(channel="The channel to send automod logs to")
    async def automod_log_channel(self, ctx, channel: Optional[discord.TextChannel] = None):
        """Set or view the automod log channel"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage automod.", ephemeral=True)
            return

        if channel is None:
            # Show current log channel
            current_channel_id = self.config.get("log_channel_id")
            current_channel = self.bot.get_channel(current_channel_id) if current_channel_id else None

            embed = discord.Embed(
                title="📝 Automod Log Channel",
                color=discord.Color.blue()
            )
            if current_channel:
                embed.description = f"Current log channel: {current_channel.mention}"
            else:
                embed.description = "No log channel set"

            await ctx.send(embed=embed)
        else:
            # Set new log channel
            old_channel_id = self.config.get("log_channel_id")
            self.config["log_channel_id"] = channel.id
            self.save_config()

            embed = discord.Embed(
                title="✅ Log Channel Set",
                description=f"Automod logs will now be sent to {channel.mention}",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            
            # Log configuration change
            await self.log_automod_action(
                f"log channel set to {channel.name}", 
                ctx.guild, 
                ctx.author, 
                f"Previous: {old_channel_id}"
            )

async def setup(bot):
    await bot.add_cog(AutomodCog(bot))
