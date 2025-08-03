"""
Discord BirthdayCog - Automated Birthday & Server Anniversary System

OVERVIEW:
Automates user birthday and server anniversary announcements, role assignments, and reminders.
Supports custom messages, embeds, and full admin/user management. Persistent, per-guild config.

SETUP:
- No manual setup required – auto-creates config/database files
- Config: src/config/birthday_config.json
- Database: src/database/birthday_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.birthday.admin' or Administrator

COMMANDS:
/birthday add <date>                - Add your birthday (formats: 01/15, Jan 15, January 15)
/birthday edit <date>               - Edit your birthday
/birthday remove                    - Remove your birthday
/birthday info [user]               - Show birthday info (self or another user)
/birthday list                      - List all birthdays in the server
/birthday server                    - Show server anniversary info

Admin:
/birthday adduser <user> <date>     - Add a birthday for another user
/birthday edituser <user> <date>    - Edit another user's birthday
/birthday removeuser <user>         - Remove another user's birthday
/birthday setchannel <channel>      - Set announcement channel
/birthday setrole <role>            - Set birthday role (given for 24h)
/birthday settime <HH:MM>           - Set announcement time (24h, default 09:00)
/birthday config                    - Show current config

Prefix commands: !birthday <subcommand> (same functionality)

BIRTHDAY FEATURES:
• User birthday management (add/edit/remove/info/list)
• Server anniversary info and automatic announcements
• Customizable announcement messages (content & embed)
• Assigns/removes birthday role for 24h
• Optional ping role for announcements
• Admin commands for managing any user's birthday
• Multiple date formats supported (01/15, Jan 15, January 15, etc.)
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• JSON-based persistent storage
• Daily background task for announcements
"""

import discord
from discord.ext import commands, tasks
import json
import asyncio
import os  
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Union
import calendar
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

class BirthdayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/birthday_config.json"
        self.db_file = "src/database/birthday_db.json"
        self.config = {}
        self.birthdays = {}
        
        # Load data
        self.load_config()
        self.load_birthdays()
        
        # Start background task
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()

    async def log_birthday_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log birthday actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Birthday {action}"
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
                    file_override="birthday_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log birthday action: {e}")

    async def log_birthday_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log birthday errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Birthday Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="birthday_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log birthday error: {e}")

    async def log_birthday_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log birthday warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Birthday Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="birthday_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log birthday warning: {e}")

    def load_config(self):
        """Load birthday configuration from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            else:
                # Default configuration
                self.config = {
                    "guilds": {}
                }
                self.save_config()
        except Exception as e:
            # Use asyncio to schedule the logging since we can't await in __init__
            asyncio.create_task(self.log_birthday_error(f"Error loading config: {e}"))
            self.config = {"guilds": {}}

    def save_config(self):
        """Save birthday configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_birthday_error(f"Error saving config: {e}"))

    def load_birthdays(self):
        """Load birthday data from file"""
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r') as f:
                    self.birthdays = json.load(f)
            else:
                self.birthdays = {}
                self.save_birthdays()
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_birthday_error(f"Error loading birthday db: {e}"))
            self.birthdays = {}

    def save_birthdays(self):
        """Save birthday data to file"""
        try:
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
            with open(self.db_file, 'w') as f:
                json.dump(self.birthdays, f, indent=4)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_birthday_error(f"Error saving birthday db: {e}"))

    def get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        """Get or create guild configuration"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.config["guilds"]:
            self.config["guilds"][guild_id_str] = {
                "enabled": True,
                "channel_id": None,
                "ping_role_id": None,
                "birthday_role_id": None,
                "announcement_time": "09:00",
                "server_created": None,  # Will be set automatically
                "birthday_message": {
                    "content": "🎉 Happy Birthday {user}! 🎂",
                    "has_embed": True,
                    "embed": {
                        "title": "🎉 Birthday Celebration! 🎉",
                        "description": "It's {user}'s special day!",
                        "color": 0xFFD700,
                        "footer_text": "Have a wonderful birthday!",
                        "thumbnail": None
                    }
                },
                "server_message": {
                    "content": "🎊 Happy Server Anniversary! 🎊",
                    "has_embed": True,
                    "embed": {
                        "title": "🎊 Server Anniversary! 🎊",
                        "description": "Celebrating another year of our amazing community!",
                        "color": 0x00FF00,
                        "footer_text": "Thank you for being part of our journey!",
                        "thumbnail": None
                    }
                }
            }
            self.save_config()
        return self.config["guilds"][guild_id_str]

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has birthday admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.birthday.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def parse_date(self, date_string: str) -> Optional[tuple]:
        """Parse date string and return (month, day) tuple"""
        # Support formats: MM/DD, DD/MM, Month DD, DD Month
        date_string = date_string.strip()
        
        # Try MM/DD or DD/MM format
        if '/' in date_string:
            parts = date_string.split('/')
            if len(parts) == 2:
                try:
                    month, day = int(parts[0]), int(parts[1])
                    if 1 <= month <= 12 and 1 <= day <= 31:
                        return (month, day)
                    # Try DD/MM if MM/DD failed
                    elif 1 <= day <= 12 and 1 <= month <= 31:
                        return (day, month)
                except ValueError:
                    pass
        
        # Try "Month DD" format
        parts = date_string.split()
        if len(parts) == 2:
            try:
                month_name, day_str = parts[0], parts[1]
                month = datetime.strptime(month_name.title(), '%B').month
                day = int(day_str)
                if 1 <= day <= 31:
                    return (month, day)
            except (ValueError, AttributeError):
                try:
                    # Try abbreviated month
                    month = datetime.strptime(month_name.title(), '%b').month
                    day = int(day_str)
                    if 1 <= day <= 31:
                        return (month, day)
                except (ValueError, AttributeError):
                    pass
        
        return None

    def format_date(self, month: int, day: int) -> str:
        """Format date as readable string"""
        try:
            month_name = calendar.month_name[month]
            return f"{month_name} {day}"
        except (IndexError, ValueError):
            return f"{month}/{day}"

    def get_next_birthday(self, month: int, day: int) -> tuple:
        """Get next birthday date and days until it"""
        today = date.today()
        current_year = today.year
        
        # Try this year first
        try:
            birthday_this_year = date(current_year, month, day)
            if birthday_this_year >= today:
                days_until = (birthday_this_year - today).days
                return birthday_this_year, days_until
        except ValueError:
            # Handle Feb 29 on non-leap years
            pass
        
        # Try next year
        try:
            birthday_next_year = date(current_year + 1, month, day)
            days_until = (birthday_next_year - today).days
            return birthday_next_year, days_until
        except ValueError:
            # Handle Feb 29 on non-leap years by using Feb 28
            birthday_next_year = date(current_year + 1, month, 28)
            days_until = (birthday_next_year - today).days
            return birthday_next_year, days_until

    def get_server_anniversary_info(self, guild: discord.Guild) -> tuple:
        """Get server anniversary information"""
        created_date = guild.created_at.date()
        today = date.today()
        current_year = today.year
        
        # Try this year first
        anniversary_this_year = date(current_year, created_date.month, created_date.day)
        if anniversary_this_year >= today:
            days_until = (anniversary_this_year - today).days
            age = current_year - created_date.year
            return anniversary_this_year, days_until, age
        
        # Next year
        anniversary_next_year = date(current_year + 1, created_date.month, created_date.day)
        days_until = (anniversary_next_year - today).days
        age = current_year + 1 - created_date.year
        return anniversary_next_year, days_until, age

    def replace_placeholders(self, text: str, user: discord.Member, guild: discord.Guild) -> str:
        """Replace placeholders in text"""
        if not text:
            return ""
        
        text = text.replace("{user}", user.mention)
        text = text.replace("{username}", user.display_name)
        text = text.replace("{server}", guild.name)
        return text

    async def create_birthday_embed(self, guild_config: dict, user: discord.Member, guild: discord.Guild, is_server: bool = False) -> Optional[discord.Embed]:
        """Create birthday embed from configuration"""
        message_config = guild_config["server_message" if is_server else "birthday_message"]
        
        if not message_config.get("has_embed", False):
            return None
        
        embed_config = message_config.get("embed", {})
        
        embed = discord.Embed(
            title=self.replace_placeholders(embed_config.get("title", ""), user, guild),
            description=self.replace_placeholders(embed_config.get("description", ""), user, guild),
            color=embed_config.get("color", 0xFFD700),
            timestamp=datetime.utcnow()
        )
        
        if embed_config.get("footer_text"):
            embed.set_footer(text=self.replace_placeholders(embed_config["footer_text"], user, guild))
        
        if embed_config.get("thumbnail"):
            embed.set_thumbnail(url=embed_config["thumbnail"])
        
        return embed

    async def give_birthday_role(self, member: discord.Member, guild_config: dict):
        """Give birthday role to user"""
        role_id = guild_config.get("birthday_role_id")
        if not role_id:
            return
        
        role = member.guild.get_role(role_id)
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Birthday celebration")
                await self.log_birthday_action(f"role given to {member}", member.guild, member, f"Role: {role.name}")
            except discord.Forbidden:
                await self.log_birthday_error(f"No permission to give birthday role to {member}", member.guild, member)
            except discord.HTTPException as e:
                await self.log_birthday_error(f"Failed to give birthday role to {member}: {e}", member.guild, member)

    async def remove_birthday_role(self, member: discord.Member, guild_config: dict):
        """Remove birthday role from user"""
        role_id = guild_config.get("birthday_role_id")
        if not role_id:
            return
        
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Birthday celebration ended")
                await self.log_birthday_action(f"role removed from {member}", member.guild, member, f"Role: {role.name}")
            except discord.Forbidden:
                await self.log_birthday_error(f"No permission to remove birthday role from {member}", member.guild, member)
            except discord.HTTPException as e:
                await self.log_birthday_error(f"Failed to remove birthday role from {member}: {e}", member.guild, member)

    @tasks.loop(hours=1)
    async def check_birthdays(self):
        """Check for birthdays and server anniversaries"""
        now = datetime.now()
        
        for guild in self.bot.guilds:
            guild_config = self.get_guild_config(guild.id)
            
            if not guild_config.get("enabled", True):
                continue
            
            # Check if it's the right time
            announcement_time = guild_config.get("announcement_time", "09:00")
            try:
                hour, minute = map(int, announcement_time.split(":"))
                if now.hour != hour or now.minute != minute:
                    continue
            except (ValueError, AttributeError):
                if now.hour != 9:  # Default to 9 AM
                    continue
            
            channel_id = guild_config.get("channel_id")
            if not channel_id:
                continue
            
            channel = guild.get_channel(channel_id)
            if not channel:
                await self.log_birthday_warning(f"Birthday channel {channel_id} not found", guild)
                continue
            
            today = now.date()
            
            # Check server anniversary
            if guild.created_at.date().month == today.month and guild.created_at.date().day == today.day:
                await self.announce_server_anniversary(guild, channel, guild_config)
            
            # Check user birthdays
            for user_id, birthday_data in self.birthdays.items():
                if birthday_data.get("guild_id") != guild.id:
                    continue
                
                month = birthday_data.get("month")
                day = birthday_data.get("day")
                
                if month == today.month and day == today.day:
                    member = guild.get_member(int(user_id))
                    if member:
                        await self.announce_birthday(member, channel, guild_config)
                    else:
                        await self.log_birthday_warning(f"Birthday user {user_id} not found in guild", guild)

    async def announce_birthday(self, member: discord.Member, channel: discord.TextChannel, guild_config: dict):
        """Announce a user's birthday"""
        try:
            message_config = guild_config["birthday_message"]
            content = self.replace_placeholders(message_config.get("content", ""), member, member.guild)
            
            # Add role ping if configured
            ping_role_id = guild_config.get("ping_role_id")
            if ping_role_id:
                ping_role = member.guild.get_role(ping_role_id)
                if ping_role:
                    content = f"{ping_role.mention} {content}"
            
            embed = await self.create_birthday_embed(guild_config, member, member.guild, False)
            
            await channel.send(content=content, embed=embed)
            await self.give_birthday_role(member, guild_config)
            await self.log_birthday_action(f"birthday announced for {member}", member.guild, member, f"Channel: {channel.name}")
            
            # Schedule role removal for tomorrow
            await asyncio.sleep(86400)  # 24 hours
            await self.remove_birthday_role(member, guild_config)
            
        except Exception as e:
            await self.log_birthday_error(f"Failed to announce birthday for {member}: {e}", member.guild, member)

    async def announce_server_anniversary(self, guild: discord.Guild, channel: discord.TextChannel, guild_config: dict):
        """Announce server anniversary"""
        try:
            # Create a dummy member for placeholder replacement (use bot)
            bot_member = guild.get_member(self.bot.user.id)
            
            message_config = guild_config["server_message"]
            content = self.replace_placeholders(message_config.get("content", ""), bot_member, guild)
            
            # Add role ping if configured
            ping_role_id = guild_config.get("ping_role_id")
            if ping_role_id:
                ping_role = guild.get_role(ping_role_id)
                if ping_role:
                    content = f"{ping_role.mention} {content}"
            
            embed = await self.create_birthday_embed(guild_config, bot_member, guild, True)
            
            await channel.send(content=content, embed=embed)
            
            # Calculate server age
            anniversary_date, days_until, age = self.get_server_anniversary_info(guild)
            await self.log_birthday_action(f"server anniversary announced", guild, details=f"Age: {age} years, Channel: {channel.name}")
            
        except Exception as e:
            await self.log_birthday_error(f"Failed to announce server anniversary for {guild}: {e}", guild)

    @check_birthdays.before_loop
    async def before_check_birthdays(self):
        await self.bot.wait_until_ready()

    # Autocomplete functions
    async def user_with_birthday_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for users with birthdays"""
        choices = []
        guild_id = interaction.guild.id
        
        for user_id, birthday_data in self.birthdays.items():
            if birthday_data.get("guild_id") != guild_id:
                continue
            
            user = interaction.guild.get_member(int(user_id))
            if user and current.lower() in user.display_name.lower():
                month = birthday_data.get("month", 1)
                day = birthday_data.get("day", 1)
                date_str = self.format_date(month, day)
                choices.append(
                    discord.app_commands.Choice(
                        name=f"{user.display_name} ({date_str})",
                        value=str(user.id)
                    )
                )
            
            if len(choices) >= 25:
                break
        
        return choices

    # ==================== COMMANDS ====================
    # Hybrid command group
    @commands.hybrid_group(name="birthday", aliases=["bday"], invoke_without_command=True)
    async def birthday(self, ctx):
        """Birthday management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🎂 Birthday Commands",
                description="Manage birthdays and celebrations!",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="👤 Personal Commands",
                value="```add <date> - Add your birthday\nedit <date> - Edit your birthday\nremove - Remove your birthday\ninfo [user] - View birthday info```",
                inline=False
            )
            embed.add_field(
                name="👑 Admin Commands",
                value="```adduser <user> <date> - Add user birthday\nedituser <user> <date> - Edit user birthday\nremoveuser <user> - Remove user birthday\nlist - List all birthdays```",
                inline=False
            )
            embed.add_field(
                name="⚙️ Configuration",
                value="```setchannel <channel> - Set announcement channel\nsetrole <role> - Set birthday role\nsettime <time> - Set announcement time\nsetmessage-bday - Configure birthday message\nsetmessage-server - Configure server message```",
                inline=False
            )
            embed.add_field(
                name="📅 Date Formats",
                value="MM/DD, Month DD, Jan 15, January 15, 01/15",
                inline=False
            )
            await ctx.send(embed=embed)

    @birthday.command(name="add")
    @discord.app_commands.describe(date="Your birthday (e.g., 01/15, Jan 15, January 15)")
    async def birthday_add(self, ctx, *, date: str):
        """Add your birthday"""
        parsed_date = self.parse_date(date)
        if not parsed_date:
            await ctx.send("❌ Invalid date format! Use MM/DD, Month DD, or DD Month format.", ephemeral=True)
            return
        
        month, day = parsed_date
        
        # Validate date
        try:
            datetime(2024, month, day)  # Use leap year to validate Feb 29
        except ValueError:
            await ctx.send("❌ Invalid date! Please check the month and day.", ephemeral=True)
            return
        
        # Save birthday
        user_id = str(ctx.author.id)
        old_birthday = self.birthdays.get(user_id)
        
        self.birthdays[user_id] = {
            "guild_id": ctx.guild.id,
            "month": month,
            "day": day,
            "set_at": datetime.now().isoformat()
        }
        self.save_birthdays()
        
        # Calculate next birthday
        next_birthday, days_until = self.get_next_birthday(month, day)
        formatted_date = self.format_date(month, day)
        
        embed = discord.Embed(
            title="🎂 Birthday Added!",
            description=f"Your birthday has been set to **{formatted_date}**",
            color=discord.Color.green()
        )
        
        if days_until == 0:
            embed.add_field(name="🎉", value="Happy Birthday! It's your special day!", inline=False)
        elif days_until == 1:
            embed.add_field(name="📅", value="Your birthday is tomorrow!", inline=False)
        else:
            embed.add_field(name="📅", value=f"Your next birthday is in **{days_until} days**", inline=False)
        
        await ctx.send(embed=embed)
        
        # Log the action
        action_type = "updated" if old_birthday else "added"
        await self.log_birthday_action(f"birthday {action_type} by {ctx.author}", ctx.guild, ctx.author, f"Date: {formatted_date}")

    @birthday.command(name="adduser")
    @discord.app_commands.describe(
        user="The user to add a birthday for",
        date="Their birthday (e.g., 01/15, Jan 15, January 15)"
    )
    async def birthday_adduser(self, ctx, user: discord.Member, *, date: str):
        """Add a birthday for another user (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage other users' birthdays.", ephemeral=True)
            return
        
        parsed_date = self.parse_date(date)
        if not parsed_date:
            await ctx.send("❌ Invalid date format! Use MM/DD, Month DD, or DD Month format.", ephemeral=True)
            return
        
        month, day = parsed_date
        
        # Validate date
        try:
            datetime(2024, month, day)
        except ValueError:
            await ctx.send("❌ Invalid date! Please check the month and day.", ephemeral=True)
            return
        
        # Save birthday
        user_id = str(user.id)
        old_birthday = self.birthdays.get(user_id)
        
        self.birthdays[user_id] = {
            "guild_id": ctx.guild.id,
            "month": month,
            "day": day,
            "set_at": datetime.now().isoformat(),
            "set_by": ctx.author.id
        }
        self.save_birthdays()
        
        formatted_date = self.format_date(month, day)
        
        embed = discord.Embed(
            title="🎂 Birthday Added!",
            description=f"Birthday set for {user.mention}: **{formatted_date}**",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        
        # Log the action
        action_type = "updated" if old_birthday else "added"
        await self.log_birthday_action(f"birthday {action_type} for {user} by {ctx.author}", ctx.guild, ctx.author, f"Date: {formatted_date}")

    @birthday.command(name="edit")
    @discord.app_commands.describe(date="Your new birthday (e.g., 01/15, Jan 15, January 15)")
    async def birthday_edit(self, ctx, *, date: str):
        """Edit your birthday"""
        user_id = str(ctx.author.id)
        if user_id not in self.birthdays or self.birthdays[user_id].get("guild_id") != ctx.guild.id:
            await ctx.send("❌ You don't have a birthday set! Use `birthday add` first.", ephemeral=True)
            return
        
        parsed_date = self.parse_date(date)
        if not parsed_date:
            await ctx.send("❌ Invalid date format! Use MM/DD, Month DD, or DD Month format.", ephemeral=True)
            return
        
        month, day = parsed_date
        
        # Validate date
        try:
            datetime(2024, month, day)
        except ValueError:
            await ctx.send("❌ Invalid date! Please check the month and day.", ephemeral=True)
            return
        
        # Update birthday
        old_date = self.format_date(self.birthdays[user_id]["month"], self.birthdays[user_id]["day"])
        self.birthdays[user_id]["month"] = month
        self.birthdays[user_id]["day"] = day
        self.birthdays[user_id]["updated_at"] = datetime.now().isoformat()
        self.save_birthdays()
        
        formatted_date = self.format_date(month, day)
        
        embed = discord.Embed(
            title="🎂 Birthday Updated!",
            description=f"Your birthday has been changed from **{old_date}** to **{formatted_date}**",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        await self.log_birthday_action(f"birthday edited by {ctx.author}", ctx.guild, ctx.author, f"Old: {old_date}, New: {formatted_date}")

    @birthday.command(name="edituser")
    @discord.app_commands.describe(
        user_id="The user to edit the birthday for",
        date="Their new birthday (e.g., 01/15, Jan 15, January 15)"
    )
    @discord.app_commands.autocomplete(user_id=user_with_birthday_autocomplete)
    async def birthday_edituser(self, ctx, user_id: str, *, date: str):
        """Edit a user's birthday (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage other users' birthdays.", ephemeral=True)
            return
        
        # Convert string ID to Member
        try:
            user = ctx.guild.get_member(int(user_id))
            if not user:
                await ctx.send("❌ User not found in this server.", ephemeral=True)
                return
        except (ValueError, TypeError):
            await ctx.send("❌ Invalid user ID.", ephemeral=True)
            return
        
        if user_id not in self.birthdays or self.birthdays[user_id].get("guild_id") != ctx.guild.id:
            await ctx.send(f"❌ {user.display_name} doesn't have a birthday set!", ephemeral=True)
            return
        
        parsed_date = self.parse_date(date)
        if not parsed_date:
            await ctx.send("❌ Invalid date format! Use MM/DD, Month DD, or DD Month format.", ephemeral=True)
            return
        
        month, day = parsed_date
        
        # Validate date
        try:
            datetime(2024, month, day)
        except ValueError:
            await ctx.send("❌ Invalid date! Please check the month and day.", ephemeral=True)
            return
        
        # Update birthday
        old_date = self.format_date(self.birthdays[user_id]["month"], self.birthdays[user_id]["day"])
        self.birthdays[user_id]["month"] = month
        self.birthdays[user_id]["day"] = day
        self.birthdays[user_id]["updated_at"] = datetime.now().isoformat()
        self.birthdays[user_id]["updated_by"] = ctx.author.id
        self.save_birthdays()
        
        formatted_date = self.format_date(month, day)
        
        embed = discord.Embed(
            title="🎂 Birthday Updated!",
            description=f"{user.mention}'s birthday changed from **{old_date}** to **{formatted_date}**",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        await self.log_birthday_action(f"birthday edited for {user} by {ctx.author}", ctx.guild, ctx.author, f"Old: {old_date}, New: {formatted_date}")

    @birthday.command(name="remove")
    async def birthday_remove(self, ctx):
        """Remove your birthday"""
        user_id = str(ctx.author.id)
        if user_id not in self.birthdays or self.birthdays[user_id].get("guild_id") != ctx.guild.id:
            await ctx.send("❌ You don't have a birthday set!", ephemeral=True)
            return
        
        old_date = self.format_date(self.birthdays[user_id]["month"], self.birthdays[user_id]["day"])
        del self.birthdays[user_id]
        self.save_birthdays()
        
        embed = discord.Embed(
            title="🗑️ Birthday Removed",
            description=f"Your birthday ({old_date}) has been removed.",
            color=discord.Color.red()
        )
        
        await ctx.send(embed=embed)
        await self.log_birthday_action(f"birthday removed by {ctx.author}", ctx.guild, ctx.author, f"Date: {old_date}")

    @birthday.command(name="removeuser")
    @discord.app_commands.describe(user_id="The user to remove the birthday for")
    @discord.app_commands.autocomplete(user_id=user_with_birthday_autocomplete)
    async def birthday_removeuser(self, ctx, user_id: str):
        """Remove a user's birthday (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage other users' birthdays.", ephemeral=True)
            return
        
        # Convert string ID to Member
        try:
            user = ctx.guild.get_member(int(user_id))
            if not user:
                await ctx.send("❌ User not found in this server.", ephemeral=True)
                return
        except (ValueError, TypeError):
            await ctx.send("❌ Invalid user ID.", ephemeral=True)
            return
        
        if user_id not in self.birthdays or self.birthdays[user_id].get("guild_id") != ctx.guild.id:
            await ctx.send(f"❌ {user.display_name} doesn't have a birthday set!", ephemeral=True)
            return
        
        old_date = self.format_date(self.birthdays[user_id]["month"], self.birthdays[user_id]["day"])
        del self.birthdays[user_id]
        self.save_birthdays()
        
        embed = discord.Embed(
            title="🗑️ Birthday Removed",
            description=f"{user.mention}'s birthday ({old_date}) has been removed.",
            color=discord.Color.red()
        )
        
        await ctx.send(embed=embed)
        await self.log_birthday_action(f"birthday removed for {user} by {ctx.author}", ctx.guild, ctx.author, f"Date: {old_date}")

    @birthday.command(name="info")
    @discord.app_commands.describe(user="User to check birthday info for (optional)")
    async def birthday_info(self, ctx, user: Optional[discord.Member] = None):
        """Show birthday information for yourself or another user"""
        target_user = user or ctx.author
        user_id = str(target_user.id)
        
        if user_id not in self.birthdays or self.birthdays[user_id].get("guild_id") != ctx.guild.id:
            name = "You don't" if target_user == ctx.author else f"{target_user.display_name} doesn't"
            await ctx.send(f"❌ {name} have a birthday set!", ephemeral=True)
            return
        
        birthday_data = self.birthdays[user_id]
        month = birthday_data["month"]
        day = birthday_data["day"]
        
        next_birthday, days_until = self.get_next_birthday(month, day)
        formatted_date = self.format_date(month, day)
        
        embed = discord.Embed(
            title=f"🎂 {target_user.display_name}'s Birthday Info",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        embed.add_field(name="📅 Birthday", value=formatted_date, inline=True)
        embed.add_field(name="🎯 Next Birthday", value=next_birthday.strftime("%Y-%m-%d"), inline=True)
        
        if days_until == 0:
            embed.add_field(name="🎉", value="Today! Happy Birthday!", inline=False)
        elif days_until == 1:
            embed.add_field(name="⏰", value="Tomorrow!", inline=False)
        else:
            embed.add_field(name="⏰", value=f"{days_until} days to go", inline=False)
        
        embed.set_footer(text=f"Birthday set on {datetime.fromisoformat(birthday_data['set_at']).strftime('%Y-%m-%d')}")
        
        await ctx.send(embed=embed)

    @birthday.command(name="list")
    async def birthday_list(self, ctx):
        """List all birthdays in the server"""
        guild_birthdays = [
            (user_id, data) for user_id, data in self.birthdays.items()
            if data.get("guild_id") == ctx.guild.id
        ]
        
        if not guild_birthdays:
            await ctx.send("❌ No birthdays set in this server yet!")
            return
        
        # Sort by next birthday
        def sort_key(item):
            user_id, data = item
            month, day = data["month"], data["day"]
            next_birthday, days_until = self.get_next_birthday(month, day)
            return days_until
        
        guild_birthdays.sort(key=sort_key)
        
        # Paginate results
        per_page = 10
        total_pages = (len(guild_birthdays) + per_page - 1) // per_page
        
        for page in range(total_pages):
            start_idx = page * per_page
            end_idx = min(start_idx + per_page, len(guild_birthdays))
            page_birthdays = guild_birthdays[start_idx:end_idx]
            
            embed = discord.Embed(
                title=f"🎂 Server Birthdays (Page {page + 1}/{total_pages})",
                description=f"Showing {len(page_birthdays)} of {len(guild_birthdays)} birthdays",
                color=discord.Color.blue()
            )
            
            for user_id, data in page_birthdays:
                user = ctx.guild.get_member(int(user_id))
                if not user:
                    continue
                
                month, day = data["month"], data["day"]
                next_birthday, days_until = self.get_next_birthday(month, day)
                formatted_date = self.format_date(month, day)
                
                if days_until == 0:
                    status = "🎉 TODAY!"
                elif days_until == 1:
                    status = "🔜 Tomorrow"
                else:
                    status = f"⏰ {days_until} days"
                
                embed.add_field(
                    name=f"{user.display_name}",
                    value=f"📅 {formatted_date}\n{status}",
                    inline=True
                )
            
            await ctx.send(embed=embed)

    @birthday.command(name="server")
    async def birthday_server(self, ctx):
        """Show server anniversary information"""
        anniversary_date, days_until, age = self.get_server_anniversary_info(ctx.guild)
        created_date = ctx.guild.created_at.date()
        
        embed = discord.Embed(
            title=f"🎊 {ctx.guild.name} Anniversary Info",
            color=discord.Color.green()
        )
        
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        
        embed.add_field(
            name="📅 Server Created",
            value=created_date.strftime("%B %d, %Y"),
            inline=True
        )
        embed.add_field(
            name="🎯 Next Anniversary",
            value=anniversary_date.strftime("%B %d, %Y"),
            inline=True
        )
        embed.add_field(
            name="🎂 Turning",
            value=f"{age} years old",
            inline=True
        )
        
        if days_until == 0:
            embed.add_field(name="🎉", value="Happy Anniversary! 🎊", inline=False)
        elif days_until == 1:
            embed.add_field(name="⏰", value="Anniversary is tomorrow!", inline=False)
        else:
            embed.add_field(name="⏰", value=f"{days_until} days until anniversary", inline=False)
        
        await ctx.send(embed=embed)

    @birthday.command(name="setchannel")
    @discord.app_commands.describe(channel="Channel for birthday announcements")
    async def birthday_setchannel(self, ctx, channel: discord.TextChannel):
        """Set the birthday announcement channel (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure birthday settings.", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        old_channel_id = guild_config.get("channel_id")
        guild_config["channel_id"] = channel.id
        self.save_config()
        
        embed = discord.Embed(
            title="✅ Channel Set",
            description=f"Birthday announcements will be sent to {channel.mention}",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        await self.log_birthday_action(f"announcement channel set to {channel.name} by {ctx.author}", ctx.guild, ctx.author, f"Previous: {old_channel_id}")

    @birthday.command(name="setrole")
    @discord.app_commands.describe(role="Role to give users on their birthday")
    async def birthday_setrole(self, ctx, role: discord.Role):
        """Set the birthday role (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure birthday settings.", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        old_role_id = guild_config.get("birthday_role_id")
        guild_config["birthday_role_id"] = role.id
        self.save_config()
        
        embed = discord.Embed(
            title="✅ Birthday Role Set",
            description=f"Users will receive {role.mention} on their birthday",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        await self.log_birthday_action(f"birthday role set to {role.name} by {ctx.author}", ctx.guild, ctx.author, f"Previous: {old_role_id}")

    @birthday.command(name="settime")
    @discord.app_commands.describe(time="Time for announcements (HH:MM format, 24-hour)")
    async def birthday_settime(self, ctx, time: str):
        """Set the announcement time (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure birthday settings.", ephemeral=True)
            return
        
        # Validate time format
        try:
            hour, minute = map(int, time.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            await ctx.send("❌ Invalid time format. Use HH:MM format (24-hour).", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        old_time = guild_config.get("announcement_time")
        guild_config["announcement_time"] = time
        self.save_config()
        
        embed = discord.Embed(
            title="✅ Announcement Time Set",
            description=f"Birthday announcements will be sent at **{time}** each day",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        await self.log_birthday_action(f"announcement time set to {time} by {ctx.author}", ctx.guild, ctx.author, f"Previous: {old_time}")

    @birthday.command(name="config")
    async def birthday_config(self, ctx):
        """Show current birthday configuration"""
        guild_config = self.get_guild_config(ctx.guild.id)
        
        embed = discord.Embed(
            title="🎂 Birthday Configuration",
            color=discord.Color.blue()
        )
        
        # Channel
        channel_id = guild_config.get("channel_id")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        embed.add_field(
            name="📺 Announcement Channel",
            value=channel.mention if channel else "Not set",
            inline=True
        )
        
        # Birthday role
        role_id = guild_config.get("birthday_role_id")
        role = ctx.guild.get_role(role_id) if role_id else None
        embed.add_field(
            name="🎭 Birthday Role",
            value=role.mention if role else "Not set",
            inline=True
        )
        
        # Ping role
        ping_role_id = guild_config.get("ping_role_id")
        ping_role = ctx.guild.get_role(ping_role_id) if ping_role_id else None
        embed.add_field(
            name="📢 Ping Role",
            value=ping_role.mention if ping_role else "Not set",
            inline=True
        )
        
        # Time
        embed.add_field(
            name="⏰ Announcement Time",
            value=guild_config.get("announcement_time", "09:00"),
            inline=True
        )
        
        # Status
        embed.add_field(
            name="🔛 Status",
            value="Enabled" if guild_config.get("enabled", True) else "Disabled",
            inline=True
        )
        
        # Birthday count
        birthday_count = sum(1 for data in self.birthdays.values() if data.get("guild_id") == ctx.guild.id)
        embed.add_field(
            name="🎂 Birthdays Set",
            value=str(birthday_count),
            inline=True
        )
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
