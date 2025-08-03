"""
Discord BoosterCog - Automated Server Booster Management

OVERVIEW:
Automates server boost announcements, tracks booster stats, and allows boosters to create/manage their own custom roles.  
Supports admin configuration, persistent storage, and full logging/permissions integration.

SETUP:
- No manual setup required – auto-creates config/database files
- Config: src/config/booster_config.json
- Database: src/database/booster_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.booster.admin' or Administrator

COMMANDS:
/booster replay                      - Replay your boost announcement
/booster role                        - View your booster role info
/booster role-edit <option> [value]  - Edit your booster role (claim, name, color, hoist, icon, info, delete)
/booster info [user]                 - Show booster info (self or another user)
/booster count                       - Show server boost stats

Admin:
/booster role-edit-admin <user> <option> [value] - Edit another user's booster role
/booster setchannel <channel>        - Set boost announcement channel
/booster setbelowrole [role]         - Set/clear role positioning for booster roles
/booster toggle [true/false]         - Enable/disable booster system
/booster status                      - Show system status
/booster config                      - Show current configuration

Prefix commands: !booster <subcommand> (same functionality)

BOOSTER FEATURES:
• Automatic boost detection and announcements
• Booster role creation, editing, and deletion (name, color, hoist, icon)
• Booster role positioning (default or below a specific role)
• Booster stats: total boosts, boost time, top boosters, history
• Booster info and leaderboard
• Admin override for role management
• Customizable announcement messages (content & embed)
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• JSON-based persistent storage
• All commands available as both slash and prefix

ROLE EDIT OPTIONS:
- claim: Create/claim your booster role
- name <text>: Change role name
- color <hex/name>: Change role color
- hoist <true/false>: Toggle role hoisting
- icon <emoji/url>: Change role icon (Level 2+)
- info: Show role info
- delete: Delete your booster role
"""

import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
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

class BoosterCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/booster_config.json"
        self.db_file = "src/database/booster_db.json"
        self.config = {}
        self.boosters = {}
        
        # Load data
        self.load_config()
        self.load_boosters()

    def load_config(self):
        """Load booster configuration from file"""
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
            print(f"Error loading booster config: {e}")
            self.config = {"guilds": {}}

    def save_config(self):
        """Save booster configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving booster config: {e}")

    def load_boosters(self):
        """Load booster data from file"""
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r') as f:
                    self.boosters = json.load(f)
            else:
                self.boosters = {}
                self.save_boosters()
        except Exception as e:
            print(f"Error loading booster db: {e}")
            self.boosters = {}

    def save_boosters(self):
        """Save booster data to file"""
        try:
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
            with open(self.db_file, 'w') as f:
                json.dump(self.boosters, f, indent=4)
        except Exception as e:
            print(f"Error saving booster db: {e}")

    def get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        """Get or create guild configuration"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.config["guilds"]:
            self.config["guilds"][guild_id_str] = {
                "enabled": True,
                "announcement_channel_id": None,
                "boost_message": {
                    "content": "🚀 Thank you {user} for boosting the server! 💎",
                    "has_embed": True,
                    "embed": {
                        "title": "🚀 Server Boost!",
                        "description": "{user} just boosted the server! Thank you for your support! 💎",
                        "color": 0xFF73FA,
                        "footer_text": "You can now create a custom role with /booster role-edit claim",
                        "thumbnail": None
                    }
                },
                "role_permissions": {
                    "position": 1,  # Position from bottom (fallback)
                    "below_role_id": None,  # Role ID to position below
                    "max_name_length": 32,
                    "allowed_colors": True,
                    "allowed_hoist": True,
                    "allowed_icon": True,
                    "allowed_unicode_emoji": True
                }
            }
            self.save_config()
        return self.config["guilds"][guild_id_str]

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has booster admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.booster.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_booster_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log booster actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Booster {action}"
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
                    file_override="booster_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log booster action: {e}")

    def get_booster_data(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        """Get or create booster data for a user"""
        guild_key = str(guild_id)
        user_key = str(user_id)
        
        if guild_key not in self.boosters:
            self.boosters[guild_key] = {}
        
        if user_key not in self.boosters[guild_key]:
            self.boosters[guild_key][user_key] = {
                "first_boost": None,
                "current_boost_start": None,
                "total_boost_time": 0,
                "boost_count": 0,
                "is_currently_boosting": False,
                "role_config": {
                    "name": None,
                    "color": 0xFF73FA,  # Default pink boost color
                    "hoist": False,
                    "icon": None,
                    "unicode_emoji": None
                },
                "current_role_id": None,
                "history": []
            }
        
        return self.boosters[guild_key][user_key]

    def parse_color(self, color_input: str) -> Optional[int]:
        """Parse color input into hex integer"""
        color_input = color_input.strip()
        
        # Remove # if present
        if color_input.startswith('#'):
            color_input = color_input[1:]
        
        # Try hex format
        try:
            if len(color_input) == 6:
                return int(color_input, 16)
        except ValueError:
            pass
        
        # Try common color names
        color_names = {
            'red': 0xFF0000, 'green': 0x00FF00, 'blue': 0x0000FF,
            'yellow': 0xFFFF00, 'purple': 0x800080, 'pink': 0xFF73FA,
            'orange': 0xFFA500, 'cyan': 0x00FFFF, 'magenta': 0xFF00FF,
            'lime': 0x00FF00, 'black': 0x000000, 'white': 0xFFFFFF,
            'gray': 0x808080, 'grey': 0x808080, 'brown': 0xA52A2A,
            'gold': 0xFFD700, 'silver': 0xC0C0C0, 'navy': 0x000080,
            'maroon': 0x800000, 'olive': 0x808000, 'teal': 0x008080
        }
        
        return color_names.get(color_input.lower())

    def get_role_position(self, guild: discord.Guild, guild_config: Dict[str, Any]) -> int:
        """Calculate the position for a new booster role"""
        role_perms = guild_config["role_permissions"]
        below_role_id = role_perms.get("below_role_id")
        
        if below_role_id:
            # Try to position below the specified role
            target_role = guild.get_role(below_role_id)
            if target_role:
                # Position one below the target role (lower position number = lower in hierarchy)
                return max(1, target_role.position - 1)
        
        # Fallback to the configured position from bottom
        return role_perms.get("position", 1)

    async def create_booster_role(self, member: discord.Member, booster_data: Dict[str, Any]) -> Optional[discord.Role]:
        """Create a booster role for a member"""
        try:
            guild_config = self.get_guild_config(member.guild.id)
            role_config = booster_data["role_config"]
            
            # Generate default name if none exists
            if not role_config.get("name"):
                role_config["name"] = f"{member.display_name}'s Role"
            
            # Create role
            role = await member.guild.create_role(
                name=role_config["name"][:guild_config["role_permissions"]["max_name_length"]],
                color=discord.Color(role_config.get("color", 0xFF73FA)),
                hoist=role_config.get("hoist", False),
                reason=f"Booster role for {member}"
            )
            
            # Set position
            target_position = self.get_role_position(member.guild, guild_config)
            try:
                await role.edit(position=target_position)
                await self.log_booster_action("positioned role", member.guild, member, f"position: {target_position}")
            except discord.HTTPException as e:
                # Log the positioning failure but don't fail the entire creation
                await self.log_booster_action("failed to position role", member.guild, member, f"error: {str(e)}, intended position: {target_position}")
            
            # Add role to member
            await member.add_roles(role, reason="Booster role assignment")
            
            # Update data
            booster_data["current_role_id"] = role.id
            self.save_boosters()
            
            await self.log_booster_action("created role", member.guild, member, f"role: {role.name}")
            return role
            
        except Exception as e:
            print(f"Failed to create booster role for {member}: {e}")
            await self.log_booster_action("failed to create role", member.guild, member, f"error: {str(e)}")
            return None

    async def delete_booster_role(self, guild: discord.Guild, booster_data: Dict[str, Any], user_id: int) -> bool:
        """Delete a booster role"""
        try:
            role_id = booster_data.get("current_role_id")
            if not role_id:
                return True
            
            role = guild.get_role(role_id)
            if role:
                role_name = role.name
                await role.delete(reason="User stopped boosting")
                await self.log_booster_action("deleted role", guild, None, f"role: {role_name}, user_id: {user_id}")
            
            booster_data["current_role_id"] = None
            self.save_boosters()
            return True
            
        except Exception as e:
            print(f"Failed to delete booster role: {e}")
            await self.log_booster_action("failed to delete role", guild, None, f"error: {str(e)}, user_id: {user_id}")
            return False

    async def restore_booster_role(self, member: discord.Member, booster_data: Dict[str, Any]) -> Optional[discord.Role]:
        """Restore a booster role from saved configuration"""
        # Check if role still exists
        current_role_id = booster_data.get("current_role_id")
        if current_role_id:
            existing_role = member.guild.get_role(current_role_id)
            if existing_role:
                # Role still exists, just add it back
                if existing_role not in member.roles:
                    await member.add_roles(existing_role, reason="Restored booster role")
                    await self.log_booster_action("restored existing role", member.guild, member, f"role: {existing_role.name}")
                return existing_role
        
        # Create new role with saved configuration
        return await self.create_booster_role(member, booster_data)

    def replace_placeholders(self, text: str, user: discord.Member, guild: discord.Guild) -> str:
        """Replace placeholders in text"""
        if not text:
            return ""
        
        text = text.replace("{user}", user.mention)
        text = text.replace("{username}", user.display_name)
        text = text.replace("{server}", guild.name)
        text = text.replace("{boost_level}", str(guild.premium_tier))
        text = text.replace("{boost_count}", str(guild.premium_subscription_count or 0))
        return text

    async def send_boost_announcement(self, member: discord.Member):
        """Send boost announcement message"""
        try:
            guild_config = self.get_guild_config(member.guild.id)
            
            # Check if booster system is enabled
            if not guild_config.get("enabled", True):
                await self.log_booster_action("boost announcement skipped (system disabled)", member.guild, member)
                return
            
            channel_id = guild_config.get("announcement_channel_id")
            if not channel_id:
                return
            
            channel = member.guild.get_channel(channel_id)
            if not channel:
                return
            
            message_config = guild_config["boost_message"]
            content = self.replace_placeholders(message_config.get("content", ""), member, member.guild)
            
            embed = None
            if message_config.get("has_embed", False):
                embed_config = message_config.get("embed", {})
                embed = discord.Embed(
                    title=self.replace_placeholders(embed_config.get("title", ""), member, member.guild),
                    description=self.replace_placeholders(embed_config.get("description", ""), member, member.guild),
                    color=embed_config.get("color", 0xFF73FA),
                    timestamp=datetime.utcnow()
                )
                
                if embed_config.get("footer_text"):
                    embed.set_footer(text=self.replace_placeholders(embed_config["footer_text"], member, member.guild))
                
                if embed_config.get("thumbnail"):
                    embed.set_thumbnail(url=embed_config["thumbnail"])
                elif member.display_avatar:
                    embed.set_thumbnail(url=member.display_avatar.url)
            
            await channel.send(content=content, embed=embed)
            await self.log_booster_action("sent boost announcement", member.guild, member, f"channel: {channel.name}")
            
        except Exception as e:
            print(f"Failed to send boost announcement: {e}")
            await self.log_booster_action("failed to send boost announcement", member.guild, member, f"error: {str(e)}")

    # ==================== EVENT LISTENERS ====================
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Detect boost changes"""
        # Check if boost status changed
        if before.premium_since != after.premium_since:
            booster_data = self.get_booster_data(after.guild.id, after.id)
            
            if after.premium_since and not before.premium_since:
                # Started boosting
                now = datetime.now()
                booster_data["is_currently_boosting"] = True
                booster_data["current_boost_start"] = now.isoformat()
                booster_data["boost_count"] += 1
                
                if not booster_data["first_boost"]:
                    booster_data["first_boost"] = now.isoformat()
                    details = "first time boosting"
                else:
                    details = f"boost count: {booster_data['boost_count']}"
                
                booster_data["history"].append({
                    "action": "started_boosting",
                    "timestamp": now.isoformat()
                })
                
                self.save_boosters()
                
                await self.log_booster_action("started boosting", after.guild, after, details)
                await self.send_boost_announcement(after)
                
                # Restore or create role if they had one before
                if booster_data["role_config"].get("name"):
                    await self.restore_booster_role(after, booster_data)
                
            elif before.premium_since and not after.premium_since:
                # Stopped boosting
                now = datetime.now()
                booster_data["is_currently_boosting"] = False
                
                # Calculate boost time
                boost_duration_hours = 0
                if booster_data["current_boost_start"]:
                    start_time = datetime.fromisoformat(booster_data["current_boost_start"])
                    boost_duration = (now - start_time).total_seconds()
                    boost_duration_hours = round(boost_duration / 3600, 1)
                    booster_data["total_boost_time"] += boost_duration
                
                booster_data["current_boost_start"] = None
                booster_data["history"].append({
                    "action": "stopped_boosting",
                    "timestamp": now.isoformat()
                })
                
                self.save_boosters()
                
                details = f"boosted for {boost_duration_hours} hours" if boost_duration_hours > 0 else ""
                await self.log_booster_action("stopped boosting", after.guild, after, details)
                
                # Delete role
                await self.delete_booster_role(after.guild, booster_data, after.id)

    # Autocomplete functions
    async def booster_role_option_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for role edit options"""
        options = [
            ("claim", "Claim/create your role"),
            ("name", "Change role name"),
            ("color", "Change role color"),
            ("hoist", "Toggle role hoisting"),
            ("icon", "Change role icon"),
            ("info", "Show role information"),
            ("delete", "Delete the role permanently")
        ]
        
        choices = []
        for option, description in options:
            if current.lower() in option.lower():
                choices.append(discord.app_commands.Choice(name=f"{option} - {description}", value=option))
        
        return choices[:25]

    async def booster_user_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for users with booster data"""
        choices = []
        guild_id = str(interaction.guild.id)
        
        if guild_id in self.boosters:
            for user_id, data in self.boosters[guild_id].items():
                user = interaction.guild.get_member(int(user_id))
                if user and current.lower() in user.display_name.lower():
                    status = "Currently Boosting" if data["is_currently_boosting"] else "Former Booster"
                    choices.append(
                        discord.app_commands.Choice(
                            name=f"{user.display_name} ({status})",
                            value=str(user.id)
                        )
                    )
                
                if len(choices) >= 25:
                    break
        
        return choices

    # ==================== COMMANDS ====================
    # Hybrid command group
    @commands.hybrid_group(name="booster", aliases=["boost"], invoke_without_command=True)
    async def booster(self, ctx):
        """Booster management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🚀 Booster Commands",
                description="Manage your booster perks and server boosting!",
                color=0xFF73FA
            )
            embed.add_field(
                name="👤 Personal Commands",
                value="```replay - Replay boost message\nrole - View your booster role\nrole-edit <option> <value> - Edit your role\ninfo [user] - View booster info```",
                inline=False
            )
            embed.add_field(
                name="👑 Admin Commands",
                value="```role-edit-admin <user> <option> <value> - Edit user's role\ncount - View server boost stats\nsetchannel <channel> - Set announcement channel\nsetbelowrole <role> - Set role positioning\ntoggle [true/false] - Enable/disable system\nstatus - Show system status\nconfig - Show configuration```",
                inline=False
            )
            embed.add_field(
                name="📝 Role Edit Options",
                value="```claim - Create/claim your role\nname <text> - Change role name\ncolor <hex/name> - Change role color\nhoist <true/false> - Toggle role hoisting\nicon <emoji/url> - Change role icon\ninfo - Show role info\ndelete - Delete role```",
                inline=False
            )
            await ctx.send(embed=embed)

    @booster.command(name="replay")
    async def booster_replay(self, ctx):
        """Replay the boost message for yourself"""
        if not ctx.author.premium_since:
            await ctx.send("❌ You must be boosting the server to use this command!", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        if not guild_config.get("enabled", True):
            await ctx.send("❌ The booster system is currently disabled.", ephemeral=True)
            return
        
        await self.send_boost_announcement(ctx.author)
        await ctx.send("✅ Boost message replayed!", ephemeral=True)
        await self.log_booster_action("replayed boost message", ctx.guild, ctx.author)

    @booster.command(name="role")
    async def booster_role(self, ctx):
        """View your booster role information"""
        if not ctx.author.premium_since:
            await ctx.send("❌ You must be boosting the server to use this command!", ephemeral=True)
            return
        
        booster_data = self.get_booster_data(ctx.guild.id, ctx.author.id)
        
        embed = discord.Embed(
            title="🎭 Your Booster Role",
            color=booster_data["role_config"].get("color", 0xFF73FA)
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        
        role_id = booster_data.get("current_role_id")
        current_role = ctx.guild.get_role(role_id) if role_id else None
        
        if current_role:
            embed.add_field(name="📛 Name", value=current_role.name, inline=True)
            embed.add_field(name="🎨 Color", value=f"#{current_role.color.value:06x}", inline=True)
            embed.add_field(name="📍 Hoisted", value="Yes" if current_role.hoist else "No", inline=True)
            embed.add_field(name="🆔 Role ID", value=current_role.id, inline=True)
            embed.add_field(name="👥 Members", value=len(current_role.members), inline=True)
            embed.add_field(name="📊 Position", value=current_role.position, inline=True)
        else:
            embed.description = "You don't have an active booster role. Use `/booster role-edit claim` to create one!"
            role_config = booster_data["role_config"]
            if role_config.get("name"):
                embed.add_field(name="💾 Saved Config", value=f"Name: {role_config['name']}\nColor: #{role_config['color']:06x}", inline=False)
        
        await ctx.send(embed=embed)

    @booster.command(name="role-edit")
    @discord.app_commands.describe(
        option="What to edit about your role",
        value="New value for the option"
    )
    @discord.app_commands.autocomplete(option=booster_role_option_autocomplete)
    async def booster_role_edit(self, ctx, option: str, *, value: Optional[str] = None):
        """Edit your booster role"""
        if not ctx.author.premium_since:
            await ctx.send("❌ You must be boosting the server to use this command!", ephemeral=True)
            return
        
        booster_data = self.get_booster_data(ctx.guild.id, ctx.author.id)
        guild_config = self.get_guild_config(ctx.guild.id)
        
        option = option.lower()
        
        if option == "claim":
            if booster_data.get("current_role_id"):
                current_role = ctx.guild.get_role(booster_data["current_role_id"])
                if current_role:
                    await ctx.send("❌ You already have an active booster role!", ephemeral=True)
                    return
            
            role = await self.create_booster_role(ctx.author, booster_data)
            if role:
                await ctx.send(f"✅ Created your booster role: {role.mention}!")
            else:
                await ctx.send("❌ Failed to create booster role.", ephemeral=True)
            return
        
        elif option == "info":
            await self.booster_role(ctx)
            return
        
        elif option == "delete":
            success = await self.delete_booster_role(ctx.guild, booster_data, ctx.author.id)
            if success:
                await ctx.send("✅ Your booster role has been deleted.")
                await self.log_booster_action("deleted role", ctx.guild, ctx.author)
            else:
                await ctx.send("❌ Failed to delete booster role.", ephemeral=True)
            return
        
        # For other options, we need a value
        if not value:
            await ctx.send(f"❌ Please provide a value for `{option}`.", ephemeral=True)
            return
        
        role_id = booster_data.get("current_role_id")
        current_role = ctx.guild.get_role(role_id) if role_id else None
        
        if not current_role:
            await ctx.send("❌ You don't have an active booster role. Use `claim` first!", ephemeral=True)
            return
        
        try:
            if option == "name":
                max_length = guild_config["role_permissions"]["max_name_length"]
                if len(value) > max_length:
                    await ctx.send(f"❌ Role name cannot be longer than {max_length} characters.", ephemeral=True)
                    return
                
                old_name = current_role.name
                await current_role.edit(name=value, reason=f"Booster role edit by {ctx.author}")
                booster_data["role_config"]["name"] = value
                await ctx.send(f"✅ Changed role name to: **{value}**")
                await self.log_booster_action("edited role name", ctx.guild, ctx.author, f"'{old_name}' → '{value}'")
            
            elif option == "color":
                color_int = self.parse_color(value)
                if color_int is None:
                    await ctx.send("❌ Invalid color format. Use hex (#FF0000) or color name (red).", ephemeral=True)
                    return
                
                await current_role.edit(color=discord.Color(color_int), reason=f"Booster role edit by {ctx.author}")
                booster_data["role_config"]["color"] = color_int
                await ctx.send(f"✅ Changed role color to: #{color_int:06x}")
                await self.log_booster_action("edited role color", ctx.guild, ctx.author, f"color: #{color_int:06x}")
            
            elif option == "hoist":
                hoist_value = value.lower() in ('true', 'yes', '1', 'on')
                await current_role.edit(hoist=hoist_value, reason=f"Booster role edit by {ctx.author}")
                booster_data["role_config"]["hoist"] = hoist_value
                await ctx.send(f"✅ Role hoisting: **{'Enabled' if hoist_value else 'Disabled'}**")
                await self.log_booster_action("edited role hoist", ctx.guild, ctx.author, f"hoist: {hoist_value}")
            
            elif option == "icon":
                if ctx.guild.premium_tier < 2:
                    await ctx.send("❌ Server needs Level 2 boost tier for role icons.", ephemeral=True)
                    return
                
                # Try to handle emoji or URL
                icon = None
                if value.startswith('http'):
                    # URL provided
                    icon = value
                elif len(value) <= 2:  # Likely an emoji
                    icon = value.encode()
                
                await current_role.edit(display_icon=icon, reason=f"Booster role edit by {ctx.author}")
                booster_data["role_config"]["icon"] = value
                await ctx.send(f"✅ Changed role icon!")
                await self.log_booster_action("edited role icon", ctx.guild, ctx.author, f"icon: {value}")
            
            else:
                await ctx.send(f"❌ Unknown option: `{option}`", ephemeral=True)
                return
            
            self.save_boosters()
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to edit roles.", ephemeral=True)
        except discord.HTTPException as e:
            await ctx.send(f"❌ Failed to edit role: {e}", ephemeral=True)

    @booster.command(name="role-edit-admin")
    @discord.app_commands.describe(
        user_id="User to edit role for",
        option="What to edit about their role",
        value="New value for the option"
    )
    @discord.app_commands.autocomplete(user_id=booster_user_autocomplete, option=booster_role_option_autocomplete)
    async def booster_role_edit_admin(self, ctx, user_id: str, option: str, *, value: Optional[str] = None):
        """Edit another user's booster role (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage other users' booster roles.", ephemeral=True)
            return
        
        try:
            user = ctx.guild.get_member(int(user_id))
            if not user:
                await ctx.send("❌ User not found in this server.", ephemeral=True)
                return
        except (ValueError, TypeError):
            await ctx.send("❌ Invalid user ID.", ephemeral=True)
            return
        
        booster_data = self.get_booster_data(ctx.guild.id, user.id)
        
        if not booster_data.get("is_currently_boosting") and option != "delete":
            await ctx.send(f"❌ {user.display_name} is not currently boosting the server.", ephemeral=True)
            return
        
        # Temporarily replace ctx.author with the target user for the role edit logic
        original_author = ctx.author
        ctx.author = user
        
        try:
            await self.booster_role_edit(ctx, option, value)
            await self.log_booster_action("admin edited role", ctx.guild, original_author, f"target: {user.name}, option: {option}, value: {value}")
        finally:
            ctx.author = original_author

    @booster.command(name="info")
    @discord.app_commands.describe(user="User to check booster info for (optional)")
    async def booster_info(self, ctx, user: Optional[discord.Member] = None):
        """Show booster information for a user"""
        target_user = user or ctx.author
        booster_data = self.get_booster_data(ctx.guild.id, target_user.id)
        
        if not booster_data["first_boost"] and not target_user.premium_since:
            name = "You have" if target_user == ctx.author else f"{target_user.display_name} has"
            await ctx.send(f"❌ {name} never boosted this server.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"🚀 {target_user.display_name}'s Booster Info",
            color=0xFF73FA if target_user.premium_since else 0x808080
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        # Current status
        if target_user.premium_since:
            embed.add_field(
                name="📊 Current Status",
                value="🟢 Currently Boosting",
                inline=True
            )
            embed.add_field(
                name="📅 Boosting Since",
                value=f"<t:{int(target_user.premium_since.timestamp())}:R>",
                inline=True
            )
        else:
            embed.add_field(
                name="📊 Current Status",
                value="🔴 Not Boosting",
                inline=True
            )
        
        # Stats
        embed.add_field(name="🔢 Total Boosts", value=booster_data["boost_count"], inline=True)
        
        if booster_data["first_boost"]:
            first_boost = datetime.fromisoformat(booster_data["first_boost"])
            embed.add_field(
                name="🎯 First Boost",
                value=f"<t:{int(first_boost.timestamp())}:D>",
                inline=True
            )
        
        # Total boost time
        total_time = booster_data["total_boost_time"]
        if booster_data["current_boost_start"]:
            start_time = datetime.fromisoformat(booster_data["current_boost_start"])
            current_duration = (datetime.now() - start_time).total_seconds()
            total_time += current_duration
        
        if total_time > 0:
            days = int(total_time // 86400)
            hours = int((total_time % 86400) // 3600)
            embed.add_field(
                name="⏱️ Total Boost Time",
                value=f"{days} days, {hours} hours",
                inline=True
            )
        
        # Role info
        role_id = booster_data.get("current_role_id")
        current_role = ctx.guild.get_role(role_id) if role_id else None
        
        if current_role:
            embed.add_field(
                name="🎭 Booster Role",
                value=f"{current_role.mention}",
                inline=True
            )
        elif booster_data["role_config"].get("name"):
            embed.add_field(
                name="💾 Saved Role",
                value=booster_data["role_config"]["name"],
                inline=True
            )
        
        # Recent activity
        recent_history = booster_data["history"][-3:] if booster_data["history"] else []
        if recent_history:
            history_text = []
            for entry in reversed(recent_history):
                timestamp = datetime.fromisoformat(entry["timestamp"])
                action = "Started boosting" if entry["action"] == "started_boosting" else "Stopped boosting"
                history_text.append(f"• {action} <t:{int(timestamp.timestamp())}:R>")
            
            embed.add_field(
                name="📜 Recent Activity",
                value="\n".join(history_text),
                inline=False
            )
        
        await ctx.send(embed=embed)

    @booster.command(name="count")
    async def booster_count(self, ctx):
        """Show server boosting statistics"""
        embed = discord.Embed(
            title=f"🚀 {ctx.guild.name} Boost Statistics",
            color=0xFF73FA
        )
        
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        
        # Current boost info
        embed.add_field(
            name="📊 Current Boosts",
            value=f"**{ctx.guild.premium_subscription_count or 0}** boosts",
            inline=True
        )
        embed.add_field(
            name="⭐ Boost Level",
            value=f"Level **{ctx.guild.premium_tier}**",
            inline=True
        )
        
        # Progress to next level
        next_level_requirements = {0: 2, 1: 7, 2: 14, 3: float('inf')}
        current_boosts = ctx.guild.premium_subscription_count or 0
        current_level = ctx.guild.premium_tier
        next_requirement = next_level_requirements.get(current_level, float('inf'))
        
        if next_requirement != float('inf'):
            remaining = max(0, next_requirement - current_boosts)
            embed.add_field(
                name="🎯 Next Level",
                value=f"{remaining} boosts needed for Level {current_level + 1}",
                inline=True
            )
        else:
            embed.add_field(
                name="🏆 Max Level",
                value="Server is at maximum boost level!",
                inline=True
            )
        
        # Booster data from our tracking
        guild_boosters = self.boosters.get(str(ctx.guild.id), {})
        
        current_boosters = sum(1 for data in guild_boosters.values() if data["is_currently_boosting"])
        total_boosters = len([data for data in guild_boosters.values() if data["first_boost"]])
        
        embed.add_field(
            name="👥 Current Boosters",
            value=f"{current_boosters} active",
            inline=True
        )
        embed.add_field(
            name="📈 Total Boosters",
            value=f"{total_boosters} all-time",
            inline=True
        )
        
        # Top boosters
        top_boosters = []
        for user_id, data in guild_boosters.items():
            user = ctx.guild.get_member(int(user_id))
            if user and data["boost_count"] > 0:
                top_boosters.append((user, data["boost_count"], data["total_boost_time"]))
        
        top_boosters.sort(key=lambda x: (x[1], x[2]), reverse=True)
        
        if top_boosters:
            top_text = []
            for i, (user, count, time) in enumerate(top_boosters[:5]):
                days = int(time // 86400)
                medal = ["🥇", "🥈", "🥉", "🏅", "🎖️"][i] if i < 5 else "•"
                top_text.append(f"{medal} {user.display_name} - {count} boosts ({days} days)")
            
            embed.add_field(
                name="🏆 Top Boosters",
                value="\n".join(top_text),
                inline=False
            )
        
        # Boost perks
        perks = []
        if ctx.guild.premium_tier >= 1:
            perks.extend([
                "• 128 kbps audio quality",
                "• Custom server emoji (50 slots)",
                "• Custom server invite background"
            ])
        if ctx.guild.premium_tier >= 2:
            perks.extend([
                "• 256 kbps audio quality",
                "• Custom server emoji (100 slots)",
                "• Server banner",
                "• Role icons"
            ])
        if ctx.guild.premium_tier >= 3:
            perks.extend([
                "• 384 kbps audio quality",
                "• Custom server emoji (250 slots)",
                "• Animated server icon",
                "• Custom invite URL"
            ])
        
        if perks:
            embed.add_field(
                name="✨ Active Perks",
                value="\n".join(perks),
                inline=False
            )
        
        await ctx.send(embed=embed)

    @booster.command(name="setchannel")
    @discord.app_commands.describe(channel="Channel for boost announcements")
    async def booster_setchannel(self, ctx, channel: discord.TextChannel):
        """Set the boost announcement channel (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure booster settings.", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        old_channel_id = guild_config.get("announcement_channel_id")
        guild_config["announcement_channel_id"] = channel.id
        self.save_config()
        
        embed = discord.Embed(
            title="✅ Channel Set",
            description=f"Boost announcements will be sent to {channel.mention}",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
        
        old_channel = ctx.guild.get_channel(old_channel_id) if old_channel_id else None
        details = f"channel: {channel.name}"
        if old_channel:
            details += f" (was: {old_channel.name})"
        
        await self.log_booster_action("set announcement channel", ctx.guild, ctx.author, details)

    @booster.command(name="setbelowrole")
    @discord.app_commands.describe(role="Role that booster roles should be positioned below")
    async def booster_setbelowrole(self, ctx, role: Optional[discord.Role] = None):
        """Set the role that booster roles should be positioned below (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure booster settings.", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        old_role_id = guild_config["role_permissions"].get("below_role_id")
        old_role = ctx.guild.get_role(old_role_id) if old_role_id else None
        
        if role is None:
            # Clear the below role setting
            guild_config["role_permissions"]["below_role_id"] = None
            self.save_config()
            
            embed = discord.Embed(
                title="✅ Role Positioning Cleared",
                description="Booster roles will now use the default position setting instead of positioning below a specific role.",
                color=discord.Color.green()
            )
            
            if old_role:
                embed.add_field(
                    name="Previous Setting",
                    value=f"Was positioned below: {old_role.mention}",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            await self.log_booster_action("cleared below role setting", ctx.guild, ctx.author, f"was: {old_role.name if old_role else 'None'}")
        else:
            guild_config["role_permissions"]["below_role_id"] = role.id
            self.save_config()
            
            embed = discord.Embed(
                title="✅ Role Positioning Set",
                description=f"New booster roles will be positioned below {role.mention}",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Target Role",
                value=f"**{role.name}**\nPosition: {role.position}\nColor: {role.color}",
                inline=True
            )
            
            embed.add_field(
                name="New Booster Role Position",
                value=f"Position {max(1, role.position - 1)} (below {role.name})",
                inline=True
            )
            
            if old_role and old_role.id != role.id:
                embed.add_field(
                    name="Previous Setting",
                    value=f"Was positioned below: {old_role.mention}",
                    inline=False
                )
            
            embed.add_field(
                name="ℹ️ Note",
                value="This setting only affects newly created booster roles. Existing roles will not be moved automatically.",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
            details = f"role: {role.name} (position: {role.position})"
            if old_role:
                details += f" (was: {old_role.name})"
            
            await self.log_booster_action("set below role", ctx.guild, ctx.author, details)

    @booster.command(name="toggle")
    @discord.app_commands.describe(enabled="Enable or disable the booster system")
    async def booster_toggle(self, ctx, enabled: Optional[bool] = None):
        """Toggle the booster system on/off (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure booster settings.", ephemeral=True)
            return
        
        guild_config = self.get_guild_config(ctx.guild.id)
        
        # If no argument provided, toggle current state
        if enabled is None:
            enabled = not guild_config.get("enabled", True)
        
        old_state = guild_config.get("enabled", True)
        guild_config["enabled"] = enabled
        self.save_config()
        
        # Create response embed
        if enabled:
            embed = discord.Embed(
                title="✅ Booster System Enabled",
                description="The booster system is now active. Boost announcements and role management are enabled.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Booster System Disabled",
                description="The booster system is now disabled. No boost announcements will be sent, but existing booster roles are preserved.",
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
        
        await self.log_booster_action("toggled system state", ctx.guild, ctx.author, details)

    @booster.command(name="status")
    async def booster_status(self, ctx):
        """Show the current status of the booster system"""
        guild_config = self.get_guild_config(ctx.guild.id)
        is_enabled = guild_config.get("enabled", True)
        
        if is_enabled:
            embed = discord.Embed(
                title="✅ Booster System Status",
                description="The booster system is currently **enabled**.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Booster System Status", 
                description="The booster system is currently **disabled**.",
                color=discord.Color.orange()
            )
        
        # Add current configuration details
        channel_id = guild_config.get("announcement_channel_id")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        
        embed.add_field(
            name="📺 Announcement Channel",
            value=channel.mention if channel else "Not set",
            inline=True
        )
        
        # Role positioning
        below_role_id = guild_config["role_permissions"].get("below_role_id")
        below_role = ctx.guild.get_role(below_role_id) if below_role_id else None
        
        embed.add_field(
            name="📍 Role Positioning",
            value=f"Below {below_role.mention}" if below_role else "Default positioning",
            inline=True
        )
        
        # Add booster statistics
        guild_boosters = self.boosters.get(str(ctx.guild.id), {})
        current_boosters = sum(1 for data in guild_boosters.values() if data["is_currently_boosting"])
        
        embed.add_field(
            name="👥 Active Boosters",
            value=f"{current_boosters} users",
            inline=True
        )
        
        embed.add_field(
            name="🚀 Server Boosts",
            value=f"{ctx.guild.premium_subscription_count or 0} boosts (Level {ctx.guild.premium_tier})",
            inline=True
        )
        
        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="While disabled, boost detection still works and existing roles are preserved, but no announcements will be sent.",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @booster.command(name="config")
    async def booster_config(self, ctx):
        """Show current booster configuration"""
        guild_config = self.get_guild_config(ctx.guild.id)
        
        # Set embed color based on enabled status
        is_enabled = guild_config.get("enabled", True)
        embed_color = 0xFF73FA if is_enabled else 0x808080
        
        embed = discord.Embed(
            title="🚀 Booster Configuration",
            color=embed_color
        )
        
        # Status (make this more prominent)
        status_emoji = "✅" if is_enabled else "⏸️"
        status_text = "Enabled" if is_enabled else "Disabled"
        embed.add_field(
            name=f"{status_emoji} System Status",
            value=f"**{status_text}**",
            inline=True
        )
        
        # Channel
        channel_id = guild_config.get("announcement_channel_id")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        embed.add_field(
            name="📺 Announcement Channel",
            value=channel.mention if channel else "Not set",
            inline=True
        )
        
        # Role positioning
        below_role_id = guild_config["role_permissions"].get("below_role_id")
        below_role = ctx.guild.get_role(below_role_id) if below_role_id else None
        embed.add_field(
            name="📍 Role Positioning",
            value=f"Below {below_role.mention}" if below_role else "Default positioning",
            inline=True
        )
        
        # Role permissions
        role_perms = guild_config["role_permissions"]
        embed.add_field(
            name="🎭 Role Settings",
            value=f"Max name length: {role_perms['max_name_length']}\n"
                    f"Colors allowed: {'Yes' if role_perms['allowed_colors'] else 'No'}\n"
                    f"Hoisting allowed: {'Yes' if role_perms['allowed_hoist'] else 'No'}",
            inline=False
        )
        
        # Booster count
        guild_boosters = self.boosters.get(str(ctx.guild.id), {})
        current_boosters = sum(1 for data in guild_boosters.values() if data["is_currently_boosting"])
        total_boosters = len([data for data in guild_boosters.values() if data["first_boost"]])
        
        embed.add_field(
            name="📊 Statistics",
            value=f"Current boosters: {current_boosters}\nTotal boosters: {total_boosters}\nServer boosts: {ctx.guild.premium_subscription_count or 0}",
            inline=True
        )
        
        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="System is disabled. Use `/booster toggle` to enable.",
                inline=False
            )
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BoosterCog(bot))
