"""
Discord Activities Cog - Automated Daily Activities & Discussion Threads

OVERVIEW:
Automated system for daily community activities (Question of the Day, Quote the Meme)
with scheduled posting, discussion thread creation, and content management.

SETUP:
- No manual setup required - auto-creates files
- Config: src/config/activities_config.json  
- Database: src/database/activities_db.json
- Requires: PermissionsCog (optional), LoggingCog (optional)
- Supports both text channels and forum channels

PERMISSIONS:
- Host activities: 'permissions.activities.host' or admin
- Configure activities: 'permissions.activities.admin' or admin

COMMANDS:
/activity host <type>                    - Manually host activity (creates thread)
/activity channel <type> <channel>       - Set channel for activity type
/activity setchannel <type> <channel_id> - Set channel with autocomplete
/activity role <type> <role>            - Set role to ping for activities
/activity time <type> <time>            - Set daily posting time (HH:MM format)
/activity add <type> <content>          - Add question/image URL to pool
/activity remove <type> <content>       - Remove question/image URL from pool
/activity list <type>                   - List all questions/images for type
/activity status                        - Show complete configuration
/activity toggle <type>                 - Enable/disable activity type

Activity Types: qotd (Question of the Day), quote (Quote the Meme)
Prefix commands: !activity <subcommand> (same functionality)

USAGE BY OTHER COGS:
# This cog is standalone - no direct integration methods
# Other cogs can check if activities are configured:
class MyCog(commands.Cog):
    def check_activities_configured(self, guild):
        activities_cog = self.bot.get_cog('ActivitiesCog')
        if activities_cog:
            return bool(activities_cog.config.get('qotd', {}).get('channel_id'))
        return False

ACTIVITY TYPES:
• QOTD: Random question from pool, creates discussion thread
• Quote: Random meme image, creates quote/caption thread

FEATURES:
• Automated daily posting at configured times (HH:MM format)
• Background scheduler checks every minute for due activities
• Missed activity detection and posting on bot startup
• Support for both text channels (creates threads) and forum channels (creates posts)
• Automatic discussion thread creation with welcome messages
• Role pinging for activity notifications
• Content pool management (questions for QOTD, image URLs for quotes)
• Forum tag support for organized posts
• Comprehensive logging integration for all actions
• Autocomplete for activity types, channels, and content
• Activity status tracking (last posted times)
• Enable/disable toggle for each activity type
• Both slash and prefix command support
• Automatic thread naming with timestamps
• Content deduplication (prevents duplicate questions/images)
"""

import discord
from discord.ext import commands, tasks
import json
import asyncio
from datetime import datetime, time
import random
import os
from typing import List, Union
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

class ActivitiesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/activities_config.json"
        self.db_file = "src/database/activities_db.json"
        self.config = {}
        self.db = {}
        
        # Activity types
        self.activity_types = ["qotd", "quote"]
        
        # Load configuration and database
        self.load_config()
        self.load_db()
        
        # Start background task
        self.activity_scheduler.start()

    def cog_unload(self):
        self.activity_scheduler.cancel()

    async def cog_load(self):
        # Check for missed activities on startup
        await self.check_missed_activities()

    async def log_activity_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log activity actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Activities {action}"
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
                    file_override="activities_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log activity action: {e}")

    async def log_activity_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log activity errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Activities Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="activities_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log activity error: {e}")

    async def log_activity_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log activity warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Activities Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="activities_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log activity warning: {e}")

    def load_config(self):
        """Load configuration from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            else:
                # Default configuration
                self.config = {
                    "qotd": {
                        "channel_id": None,
                        "role_id": None,
                        "time": "09:00",
                        "enabled": True,
                        "questions": [
                            "What's your favorite hobby and why?",
                            "If you could travel anywhere, where would you go?",
                            "What's the best advice you've ever received?",
                            "What's your go-to comfort food?",
                            "If you could have any superpower, what would it be?",
                            "What's a skill you'd love to learn?",
                            "What's your favorite season and why?",
                            "If you could meet any historical figure, who would it be?",
                            "What's your biggest fear and how do you cope with it?",
                            "What's the most interesting place you've ever visited?"
                        ],
                        "forum_tag": "Question of the Day",
                        "thread_name": "💬 Discuss: {title}"
                    },
                    "quote": {
                        "channel_id": None,
                        "role_id": None,
                        "time": "15:00",
                        "enabled": True,
                        "images": [
                            "https://i.imgflip.com/1bij.jpg",
                            "https://i.imgflip.com/5c7lwq.jpg",
                            "https://i.imgflip.com/1ur9b0.jpg",
                            "https://i.imgflip.com/30b1gx.jpg",
                            "https://i.imgflip.com/23ls.jpg",
                            "https://i.imgflip.com/1otk96.jpg",
                            "https://i.imgflip.com/9ehk.jpg",
                            "https://i.imgflip.com/17wip.jpg",
                            "https://i.imgflip.com/26am.jpg",
                            "https://i.imgflip.com/2d3al6.jpg"
                        ],
                        "forum_tag": "Quote the Meme",
                        "thread_name": "🗨️ Quote: {title}"
                    }
                }
                self.save_config()
        except Exception as e:
            # Use asyncio to schedule the logging since we can't await in __init__
            asyncio.create_task(self.log_activity_error(f"Error loading config: {e}"))
            self.config = {}

    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_activity_error(f"Error saving config: {e}"))

    def load_db(self):
        """Load database from file"""
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r') as f:
                    self.db = json.load(f)
            else:
                self.db = {
                    "last_posted": {
                        "qotd": None,
                        "quote": None
                    }
                }
                self.save_db()
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_activity_error(f"Error loading database: {e}"))
            self.db = {"last_posted": {"qotd": None, "quote": None}}

    def save_db(self):
        """Save database to file"""
        try:
            with open(self.db_file, 'w') as f:
                json.dump(self.db, f, indent=4)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_activity_error(f"Error saving database: {e}"))

    def has_host_permission(self, member: discord.Member) -> bool:
        """Check if member has activity host permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.activities.host') or
                permissions_cog.has_permission(member, 'permissions.activities.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has activity admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.activities.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def get_qotd_content(self) -> str:
        """Get question of the day content"""
        config = self.config.get("qotd", {})
        questions = config.get("questions", [])
        
        if questions:
            question = random.choice(questions)
            return f"**Question of the Day:**\n{question}"
        
        return "**Question of the Day:**\nWhat's on your mind today?"

    async def get_quote_content(self) -> str:
        """Get meme image for quote activity"""
        config = self.config.get("quote", {})
        images = config.get("images", [])
        
        if images:
            return random.choice(images)
        
        return "https://i.imgflip.com/1bij.jpg"  # Default meme

    async def post_activity(self, activity_type: str, guild_id: int = None):
        """Post an activity to the configured channel"""
        if activity_type not in self.activity_types:
            return False

        config = self.config.get(activity_type, {})
        if not config.get("enabled", True):
            return False

        channel_id = config.get("channel_id")
        if not channel_id:
            return False

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return False

        # Get content based on activity type
        if activity_type == "qotd":
            content = await self.get_qotd_content()
            title = "Question of the Day"
        elif activity_type == "quote":
            image_url = await self.get_quote_content()
            content = "**Quote this meme!**"
            title = "Quote the Meme"

        # Get role mention
        role_mention = ""
        role_id = config.get("role_id")
        if role_id:
            role = channel.guild.get_role(role_id)
            if role:
                role_mention = f"{role.mention} "

        try:
            # Check if it's a forum channel
            if isinstance(channel, discord.ForumChannel):
                # Create forum post
                embed = discord.Embed(
                    title=title,
                    description=content,
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                if activity_type == "quote":
                    embed.set_image(url=image_url)

                # Find or create tag
                tag = None
                tag_name = config.get("forum_tag", title)
                for available_tag in channel.available_tags:
                    if available_tag.name.lower() == tag_name.lower():
                        tag = available_tag
                        break

                tags = [tag] if tag else []
                
                thread, message = await channel.create_thread(
                    name=f"{title} - {datetime.now().strftime('%Y-%m-%d')}",
                    content=f"{role_mention}",
                    embed=embed,
                    applied_tags=tags
                )
            else:
                # Regular channel - post message and create thread
                embed = discord.Embed(
                    title=title,
                    description=content,
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                
                if activity_type == "quote":
                    embed.set_image(url=image_url)

                # Send the main message
                message = await channel.send(content=role_mention, embed=embed)
                
                # Create a thread for discussion
                thread_name_template = config.get("thread_name", "💬 Discuss: {title}")
                thread_name = thread_name_template.format(title=title)
                
                try:
                    thread = await message.create_thread(
                        name=thread_name,
                        auto_archive_duration=1440  # 24 hours
                    )
                    
                    # Send a welcome message in the thread
                    welcome_msg = "Share your thoughts and discuss with others! 💭"
                    if activity_type == "quote":
                        welcome_msg = "Drop your best quotes for this meme! 😄"
                    
                    await thread.send(welcome_msg)
                    
                except discord.HTTPException as e:
                    await self.log_activity_warning(f"Failed to create thread for {activity_type}: {e}", channel.guild)
                    # Continue without thread if creation fails

            # Update last posted time
            self.db["last_posted"][activity_type] = datetime.now().isoformat()
            self.save_db()
            
            # Log successful activity posting
            await self.log_activity_action(f"posted {activity_type}", channel.guild, details=f"Channel: {channel.name}")
            
            return True

        except Exception as e:
            await self.log_activity_error(f"Error posting {activity_type}: {e}", channel.guild if channel else None)
            return False

    async def check_missed_activities(self):
        """Check for missed activities on startup"""
        now = datetime.now()
        today = now.date()
        
        for activity_type in self.activity_types:
            config = self.config.get(activity_type, {})
            if not config.get("enabled", True):
                continue

            last_posted = self.db["last_posted"].get(activity_type)
            if last_posted:
                last_posted_date = datetime.fromisoformat(last_posted).date()
                if last_posted_date >= today:
                    continue  # Already posted today

            # Check if we should post today
            activity_time = config.get("time", "09:00")
            try:
                hour, minute = map(int, activity_time.split(":"))
                activity_datetime = datetime.combine(today, time(hour, minute))
                
                if now >= activity_datetime:
                    await self.log_activity_action(f"posting missed {activity_type} activity", details="Startup check")
                    await self.post_activity(activity_type)
            except ValueError:
                await self.log_activity_error(f"Invalid time format for {activity_type}: {activity_time}")

    @tasks.loop(minutes=1)
    async def activity_scheduler(self):
        """Background task to schedule activities"""
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        for activity_type in self.activity_types:
            config = self.config.get(activity_type, {})
            if not config.get("enabled", True):
                continue

            activity_time = config.get("time", "09:00")
            if current_time == activity_time:
                # Check if already posted today
                last_posted = self.db["last_posted"].get(activity_type)
                if last_posted:
                    last_posted_date = datetime.fromisoformat(last_posted).date()
                    if last_posted_date >= now.date():
                        continue  # Already posted today

                await self.post_activity(activity_type)

    @activity_scheduler.before_loop
    async def before_activity_scheduler(self):
        await self.bot.wait_until_ready()

    # Autocomplete functions
    async def activity_type_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for activity types"""
        return [
            discord.app_commands.Choice(name=activity_type.upper(), value=activity_type)
            for activity_type in self.activity_types
            if current.lower() in activity_type.lower()
        ]

    async def channel_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for channels (text and forum channels)"""
        if not interaction.guild:
            return []

        choices = []
        
        # Get text channels
        for channel in interaction.guild.text_channels:
            if current.lower() in channel.name.lower():
                choices.append(
                    discord.app_commands.Choice(
                        name=f"#{channel.name} (Text Channel)",
                        value=str(channel.id)
                    )
                )
        
        # Get forum channels
        for channel in interaction.guild.forums:
            if current.lower() in channel.name.lower():
                choices.append(
                    discord.app_commands.Choice(
                        name=f"#{channel.name} (Forum Channel)",
                        value=str(channel.id)
                    )
                )
        
        # Limit to 25 choices and sort by name
        choices = sorted(choices, key=lambda x: x.name)[:25]
        return choices

    async def content_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for content (questions/images) based on activity type"""
        # Get the activity type from the interaction
        activity_type = None
        for option in interaction.data.get("options", []):
            if option["name"] == "activity_type":
                activity_type = option["value"]
                break
        
        if not activity_type or activity_type not in self.activity_types:
            return []

        config = self.config.get(activity_type, {})
        if activity_type == "qotd":
            content_list = config.get("questions", [])
        else:  # quote
            content_list = config.get("images", [])

        # Filter based on current input and limit to 25 choices
        choices = []
        for content in content_list:
            if current.lower() in content.lower():
                # Truncate long content for display
                display_name = content[:97] + "..." if len(content) > 100 else content
                choices.append(discord.app_commands.Choice(name=display_name, value=content))
            
            if len(choices) >= 25:
                break

        return choices

    # ==================== COMMANDS ====================
    # Hybrid command group
    @commands.hybrid_group(name="activity", aliases=["act"], invoke_without_command=True)
    async def activity(self, ctx):
        """Activity management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Activity Commands",
                description="Available activity commands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="activity host <type>",
                value="Host an activity manually",
                inline=False
            )
            embed.add_field(
                name="activity channel <type> <channel>",
                value="Set the channel for an activity type (supports text and forum channels)",
                inline=False
            )
            embed.add_field(
                name="activity role <type> <role>",
                value="Set the role to ping for an activity type",
                inline=False
            )
            embed.add_field(
                name="activity time <type> <time>",
                value="Set the daily time for an activity type (HH:MM format)",
                inline=False
            )
            embed.add_field(
                name="activity add <type> <content>",
                value="Add a question or image URL to an activity type",
                inline=False
            )
            embed.add_field(
                name="activity remove <type> <content>",
                value="Remove a question or image URL from an activity type",
                inline=False
            )
            embed.add_field(
                name="activity list <type>",
                value="List all questions or images for an activity type",
                inline=False
            )
            embed.add_field(
                name="Available Types",
                value="qotd (Question of the Day), quote (Quote the Meme)",
                inline=False
            )
            embed.add_field(
                name="📝 Note",
                value="Activities automatically create discussion threads for engagement!",
                inline=False
            )
            await ctx.send(embed=embed)

    @activity.command(name="host")
    @discord.app_commands.describe(activity_type="The type of activity to host")
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete)
    async def activity_host(self, ctx, activity_type: str):
        """Host an activity manually"""
        if not self.has_host_permission(ctx.author):
            await ctx.send("❌ You don't have permission to host activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        success = await self.post_activity(activity_type.lower())
        if success:
            await ctx.send(f"✅ Successfully hosted {activity_type} activity with discussion thread!")
            # Log manual hosting
            await self.log_activity_action(f"manually hosted {activity_type}", ctx.guild, ctx.author)
        else:
            await ctx.send(f"❌ Failed to host {activity_type} activity. Check configuration.", ephemeral=True)

    @activity.command(name="channel")
    @discord.app_commands.describe(
        activity_type="The type of activity to configure",
        channel="The channel to send activities to (text or forum channel)"
    )
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete)
    async def activity_channel(self, ctx, activity_type: str, channel: Union[discord.TextChannel, discord.ForumChannel]):
        """Set the channel for an activity type"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        if activity_type.lower() not in self.config:
            self.config[activity_type.lower()] = {}

        old_channel_id = self.config[activity_type.lower()].get("channel_id")
        self.config[activity_type.lower()]["channel_id"] = channel.id
        self.save_config()
        
        channel_type = "Forum" if isinstance(channel, discord.ForumChannel) else "Text"
        await ctx.send(f"✅ Set {activity_type} channel to {channel.mention} ({channel_type} Channel)")
        
        # Log configuration change
        await self.log_activity_action(
            f"channel configured for {activity_type}", 
            ctx.guild, 
            ctx.author, 
            f"Channel: {channel.name} ({channel_type}), Previous: {old_channel_id}"
        )

    # For slash commands, we need a separate autocomplete-enabled version
    @activity.command(name="setchannel")
    @discord.app_commands.describe(
        activity_type="The type of activity to configure",
        channel_id="The channel to send activities to"
    )
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete, channel_id=channel_autocomplete)
    async def activity_set_channel_slash(self, ctx, activity_type: str, channel_id: str):
        """Set the channel for an activity type (slash command with autocomplete)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                await ctx.send("❌ Channel not found!", ephemeral=True)
                return

            if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                await ctx.send("❌ Channel must be a text channel or forum channel!", ephemeral=True)
                return

            if activity_type.lower() not in self.config:
                self.config[activity_type.lower()] = {}

            old_channel_id = self.config[activity_type.lower()].get("channel_id")
            self.config[activity_type.lower()]["channel_id"] = channel.id
            self.save_config()
            
            channel_type = "Forum" if isinstance(channel, discord.ForumChannel) else "Text"
            await ctx.send(f"✅ Set {activity_type} channel to {channel.mention} ({channel_type} Channel)")
            
            # Log configuration change
            await self.log_activity_action(
                f"channel configured for {activity_type}", 
                ctx.guild, 
                ctx.author, 
                f"Channel: {channel.name} ({channel_type}), Previous: {old_channel_id}"
            )

        except ValueError:
            await ctx.send("❌ Invalid channel ID!", ephemeral=True)

    @activity.command(name="role")
    @discord.app_commands.describe(
        activity_type="The type of activity to configure",
        role="The role to ping for activities"
    )
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete)
    async def activity_role(self, ctx, activity_type: str, role: discord.Role):
        """Set the role to ping for an activity type"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        if activity_type.lower() not in self.config:
            self.config[activity_type.lower()] = {}

        old_role_id = self.config[activity_type.lower()].get("role_id")
        self.config[activity_type.lower()]["role_id"] = role.id
        self.save_config()
        
        await ctx.send(f"✅ Set {activity_type} role to {role.mention}")
        
        # Log configuration change
        await self.log_activity_action(
            f"role configured for {activity_type}", 
            ctx.guild, 
            ctx.author, 
            f"Role: {role.name}, Previous: {old_role_id}"
        )

    @activity.command(name="time")
    @discord.app_commands.describe(
        activity_type="The type of activity to configure",
        time_str="The time to post activities (HH:MM format, 24-hour)"
    )
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete)
    async def activity_time(self, ctx, activity_type: str, time_str: str):
        """Set the daily time for an activity type (HH:MM format)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        # Validate time format
        try:
            hour, minute = map(int, time_str.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            await ctx.send("❌ Invalid time format. Use HH:MM format (24-hour).", ephemeral=True)
            return

        if activity_type.lower() not in self.config:
            self.config[activity_type.lower()] = {}

        old_time = self.config[activity_type.lower()].get("time")
        self.config[activity_type.lower()]["time"] = time_str
        self.save_config()
        
        await ctx.send(f"✅ Set {activity_type} time to {time_str}")
        
        # Log configuration change
        await self.log_activity_action(
            f"time configured for {activity_type}", 
            ctx.guild, 
            ctx.author, 
            f"Time: {time_str}, Previous: {old_time}"
        )

    @activity.command(name="add")
    @discord.app_commands.describe(
        activity_type="The type of activity to add content to",
        content="The question or image URL to add"
    )
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete)
    async def activity_add(self, ctx, activity_type: str, *, content: str):
        """Add a question or image URL to an activity type"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        if activity_type.lower() not in self.config:
            self.config[activity_type.lower()] = {}

        # Get the appropriate content list
        if activity_type.lower() == "qotd":
            content_key = "questions"
            content_type = "question"
        else:  # quote
            content_key = "images"
            content_type = "image URL"

        if content_key not in self.config[activity_type.lower()]:
            self.config[activity_type.lower()][content_key] = []

        content_list = self.config[activity_type.lower()][content_key]
        
        # Check if content already exists
        if content in content_list:
            await ctx.send(f"❌ This {content_type} already exists in {activity_type}!", ephemeral=True)
            return

        # Add content
        content_list.append(content)
        self.save_config()
        
        # Truncate content for display if too long
        display_content = content[:100] + "..." if len(content) > 100 else content
        await ctx.send(f"✅ Added {content_type} to {activity_type}: `{display_content}`")
        
        # Log content addition
        await self.log_activity_action(
            f"{content_type} added to {activity_type}", 
            ctx.guild, 
            ctx.author, 
            f"Content: {content[:200]}{'...' if len(content) > 200 else ''}"
        )

    @activity.command(name="remove")
    @discord.app_commands.describe(
        activity_type="The type of activity to remove content from",
        content="The question or image URL to remove"
    )
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete, content=content_autocomplete)
    async def activity_remove(self, ctx, activity_type: str, *, content: str):
        """Remove a question or image URL from an activity type"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        if activity_type.lower() not in self.config:
            await ctx.send(f"❌ No configuration found for {activity_type}!", ephemeral=True)
            return

        # Get the appropriate content list
        if activity_type.lower() == "qotd":
            content_key = "questions"
            content_type = "question"
        else:  # quote
            content_key = "images"
            content_type = "image URL"

        if content_key not in self.config[activity_type.lower()]:
            await ctx.send(f"❌ No {content_type}s found for {activity_type}!", ephemeral=True)
            return

        content_list = self.config[activity_type.lower()][content_key]
        
        # Check if content exists
        if content not in content_list:
            await ctx.send(f"❌ This {content_type} doesn't exist in {activity_type}!", ephemeral=True)
            return

        # Remove content
        content_list.remove(content)
        self.save_config()
        
        # Truncate content for display if too long
        display_content = content[:100] + "..." if len(content) > 100 else content
        await ctx.send(f"✅ Removed {content_type} from {activity_type}: `{display_content}`")
        
        # Log content removal
        await self.log_activity_action(
            f"{content_type} removed from {activity_type}", 
            ctx.guild, 
            ctx.author, 
            f"Content: {content[:200]}{'...' if len(content) > 200 else ''}"
        )

    @activity.command(name="list")
    @discord.app_commands.describe(activity_type="The type of activity to list content for")
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete)
    async def activity_list(self, ctx, activity_type: str):
        """List all questions or images for an activity type"""
        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        config = self.config.get(activity_type.lower(), {})
        
        # Get the appropriate content list
        if activity_type.lower() == "qotd":
            content_list = config.get("questions", [])
            content_type = "Questions"
        else:  # quote
            content_list = config.get("images", [])
            content_type = "Image URLs"

        if not content_list:
            await ctx.send(f"❌ No {content_type.lower()} found for {activity_type}!", ephemeral=True)
            return

        # Create paginated embeds if there are many items
        items_per_page = 10
        pages = [content_list[i:i + items_per_page] for i in range(0, len(content_list), items_per_page)]
        
        for page_num, page_items in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{activity_type.upper()} {content_type} (Page {page_num}/{len(pages)})",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for i, item in enumerate(page_items, 1 + (page_num - 1) * items_per_page):
                # Truncate long items for display
                display_item = item[:200] + "..." if len(item) > 200 else item
                embed.add_field(
                    name=f"{i}.",
                    value=f"`{display_item}`",
                    inline=False
                )
            
            embed.set_footer(text=f"Total: {len(content_list)} {content_type.lower()}")
            await ctx.send(embed=embed)

    @activity.command(name="status")
    async def activity_status(self, ctx):
        """Show current activity configuration"""
        embed = discord.Embed(
            title="Activity Configuration",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        for activity_type in self.activity_types:
            config = self.config.get(activity_type, {})
            
            channel_id = config.get("channel_id")
            channel = self.bot.get_channel(channel_id) if channel_id else None
            if channel:
                channel_type = "Forum" if isinstance(channel, discord.ForumChannel) else "Text"
                channel_text = f"{channel.mention} ({channel_type})"
            else:
                channel_text = "Not set"

            role_id = config.get("role_id")
            role = ctx.guild.get_role(role_id) if role_id else None
            role_text = role.mention if role else "Not set"

            time_text = config.get("time", "Not set")
            enabled = config.get("enabled", True)
            
            # Get content count
            if activity_type == "qotd":
                content_count = len(config.get("questions", []))
                content_type = "questions"
            else:
                content_count = len(config.get("images", []))
                content_type = "images"
            
            last_posted = self.db["last_posted"].get(activity_type)
            last_posted_text = "Never"
            if last_posted:
                try:
                    dt = datetime.fromisoformat(last_posted)
                    last_posted_text = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass

            embed.add_field(
                name=f"{activity_type.upper()} {'✅' if enabled else '❌'}",
                value=f"**Channel:** {channel_text}\n"
                        f"**Role:** {role_text}\n"
                        f"**Time:** {time_text}\n"
                        f"**Content:** {content_count} {content_type}\n"
                        f"**Last Posted:** {last_posted_text}",
                inline=True
            )

        embed.set_footer(text="💡 Activities automatically create discussion threads!")
        await ctx.send(embed=embed)

    @activity.command(name="toggle")
    @discord.app_commands.describe(activity_type="The type of activity to toggle")
    @discord.app_commands.autocomplete(activity_type=activity_type_autocomplete)
    async def activity_toggle(self, ctx, activity_type: str):
        """Toggle an activity type on/off"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure activities.", ephemeral=True)
            return

        if activity_type.lower() not in self.activity_types:
            await ctx.send(f"❌ Invalid activity type. Available types: {', '.join(self.activity_types)}", ephemeral=True)
            return

        if activity_type.lower() not in self.config:
            self.config[activity_type.lower()] = {}

        current = self.config[activity_type.lower()].get("enabled", True)
        self.config[activity_type.lower()]["enabled"] = not current
        self.save_config()
        
        status = "enabled" if not current else "disabled"
        await ctx.send(f"✅ {activity_type.upper()} activities {status}")
        
        # Log toggle action
        await self.log_activity_action(
            f"{activity_type} toggled {status}", 
            ctx.guild, 
            ctx.author
        )

async def setup(bot):
    await bot.add_cog(ActivitiesCog(bot))
