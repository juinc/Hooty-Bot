"""
Discord Autofeed Cog - Automated Message Response System

OVERVIEW:
Automated response system that triggers bot replies when specific words/phrases are detected
in messages. Supports advanced requirement filtering and permission controls.

SETUP:
- No manual setup required - auto-creates files
- Config: src/config/autofeed_config.json
- Requires: PermissionsCog (optional), LoggingCog (optional)
- Auto-responds when trigger words are found in messages

PERMISSIONS:
- Manage autofeeds: 'permissions.autofeed.admin' or Administrator
- Use autofeeds: 'permissions.autofeed.trigger' (default) or custom requirements

COMMANDS:
/autofeed list                           - List all configured autofeeds
/autofeed add <trigger> <reply>          - Add new autofeed response
/autofeed remove <trigger>               - Remove an autofeed
/autofeed edit <trigger> <new_reply>     - Edit existing autofeed reply
/autofeed requirement <trigger> <type> <value> - Add requirement (role/name/useprefix)
/autofeed clearreq <trigger> <type>      - Clear specific requirement type
/autofeed info <trigger>                 - Show detailed trigger information
/autofeed test <trigger>                 - Test if you can trigger autofeed
/autofeed clear                          - Clear all autofeeds (with confirmation)

Prefix commands: !autofeed <subcommand> (same functionality)

USAGE BY OTHER COGS:

# Check if autofeeds are configured
class MyCog(commands.Cog):
    def check_autofeed_exists(self, trigger):
        autofeed_cog = self.bot.get_cog('AutofeedCog')
        if autofeed_cog:
            return trigger in autofeed_cog.autofeeds
        return False
    
    # Programmatically add autofeeds (access autofeed_cog.autofeeds dict)
    def add_custom_autofeed(self, trigger, reply):
        autofeed_cog = self.bot.get_cog('AutofeedCog')
        if autofeed_cog:
            autofeed_cog.autofeeds[trigger] = {'reply': reply, 'requirements': {}}
            autofeed_cog.save_config()

REQUIREMENT TYPES:
• role: User must have specific role (name or ID)
• name: User's name must match pattern (supports regex)
• useprefix: Message must start with specific prefix

FEATURES:
• Automatic message scanning and response triggering
• Advanced requirement system with role, name pattern, and prefix filtering
• Regex support for flexible name pattern matching
• Permission-based access control with default fallbacks
• Comprehensive logging integration for all actions
• Interactive confirmation dialogs for destructive operations
• Full autocomplete support for triggers and requirement types
• Real-time trigger testing without actually triggering responses
• Case-insensitive trigger detection
• Support for multiple requirements per trigger type
• Both slash and prefix command support with consistent functionality
• Detailed trigger information display with formatted requirements
• Bulk operations (clear all with confirmation)
• Edit capabilities for existing autofeeds
"""

import discord
from discord.ext import commands
import json
import re
import os
import asyncio
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

class AutofeedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/autofeed_config.json"
        self.autofeeds = {}
        
        # Load configuration
        self.load_config()

    async def log_autofeed_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log autofeed actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Autofeed {action}"
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
                    file_override="autofeed_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log autofeed action: {e}")

    async def log_autofeed_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log autofeed errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Autofeed Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="autofeed_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log autofeed error: {e}")

    async def log_autofeed_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log autofeed warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Autofeed Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="autofeed_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log autofeed warning: {e}")

    def load_config(self):
        """Load autofeed configuration from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.autofeeds = json.load(f)
            else:
                self.autofeeds = {}
                self.save_config()
        except Exception as e:
            # Use asyncio to schedule the logging since we can't await in __init__
            asyncio.create_task(self.log_autofeed_error(f"Error loading config: {e}"))
            self.autofeeds = {}

    def save_config(self):
        """Save autofeed configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.autofeeds, f, indent=4)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_autofeed_error(f"Error saving config: {e}"))

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has autofeed admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.autofeed.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def has_trigger_permission(self, member: discord.Member) -> bool:
        """Check if member has autofeed trigger permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return True  # Default to allowing triggers if no permissions cog
        
        return (permissions_cog.has_permission(member, 'permissions.autofeed.trigger') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def check_requirements(self, member: discord.Member, message: discord.Message, trigger: str) -> bool:
        """Check if member meets the requirements for a trigger"""
        if trigger not in self.autofeeds:
            return False
            
        requirements = self.autofeeds[trigger].get('requirements', {})
        
        # If no requirements, check default permission
        if not requirements:
            return self.has_trigger_permission(member)
        
        # Check role requirement
        if 'role' in requirements:
            required_roles = requirements['role']
            if isinstance(required_roles, str):
                required_roles = [required_roles]
            
            user_roles = [role.name.lower() for role in member.roles]
            user_role_ids = [str(role.id) for role in member.roles]
            
            has_role = False
            for req_role in required_roles:
                if req_role.lower() in user_roles or req_role in user_role_ids:
                    has_role = True
                    break
            
            if not has_role:
                return False
        
        # Check name requirement (supports regex patterns)
        if 'name' in requirements:
            name_patterns = requirements['name']
            if isinstance(name_patterns, str):
                name_patterns = [name_patterns]
            
            has_name_match = False
            for pattern in name_patterns:
                try:
                    if (re.search(pattern, member.display_name, re.IGNORECASE) or 
                        re.search(pattern, member.name, re.IGNORECASE)):
                        has_name_match = True
                        break
                except re.error:
                    # Fallback to simple string matching if regex fails
                    if (pattern.lower() in member.display_name.lower() or 
                        pattern.lower() in member.name.lower()):
                        has_name_match = True
                        break
            
            if not has_name_match:
                return False
        
        # Check prefix requirement
        if 'useprefix' in requirements:
            required_prefixes = requirements['useprefix']
            if isinstance(required_prefixes, str):
                required_prefixes = [required_prefixes]
            
            has_prefix = False
            for prefix in required_prefixes:
                if message.content.startswith(prefix):
                    has_prefix = True
                    break
            
            if not has_prefix:
                return False
        
        return True

    # ==================== EVENT LISTENERS ====================
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages and trigger autofeeds"""
        if message.author.bot:
            return
        
        if not message.guild:
            return
        
        # Check each trigger
        for trigger, data in self.autofeeds.items():
            if trigger.lower() in message.content.lower():
                # Check if user meets requirements
                if self.check_requirements(message.author, message, trigger):
                    reply = data.get('reply', '')
                    if reply:
                        try:
                            await message.channel.send(reply)
                            # Log the trigger
                            await self.log_autofeed_action(
                                f"triggered by '{trigger}'", 
                                message.guild, 
                                message.author, 
                                f"Channel: {message.channel.name}, Reply: {reply[:100]}{'...' if len(reply) > 100 else ''}"
                            )
                        except discord.HTTPException as e:
                            await self.log_autofeed_error(
                                f"Failed to send autofeed response for trigger '{trigger}': {e}", 
                                message.guild, 
                                message.author
                            )

    # Autocomplete functions
    async def trigger_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for existing triggers"""
        choices = []
        for trigger in self.autofeeds.keys():
            if current.lower() in trigger.lower():
                choices.append(discord.app_commands.Choice(name=trigger, value=trigger))
            if len(choices) >= 25:
                break
        return choices

    async def requirement_type_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """Autocomplete for requirement types"""
        types = ['role', 'name', 'useprefix']
        return [
            discord.app_commands.Choice(name=req_type.title(), value=req_type)
            for req_type in types
            if current.lower() in req_type.lower()
        ]

    # ==================== COMMANDS ====================
    # Hybrid command group
    @commands.hybrid_group(name="autofeed", aliases=["af"], invoke_without_command=True)
    async def autofeed(self, ctx):
        """Autofeed management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🤖 Autofeed Commands",
                description="Manage automatic bot responses to message triggers",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="📋 autofeed list",
                value="List all configured autofeeds",
                inline=False
            )
            embed.add_field(
                name="➕ autofeed add <trigger> <reply>",
                value="Add a new autofeed response",
                inline=False
            )
            embed.add_field(
                name="❌ autofeed remove <trigger>",
                value="Remove an autofeed",
                inline=False
            )
            embed.add_field(
                name="🔒 autofeed requirement <trigger> <type> <value>",
                value="Add requirement for trigger (role/name/useprefix)",
                inline=False
            )
            embed.add_field(
                name="🧹 autofeed clearreq <trigger> <type>",
                value="Clear a specific requirement type",
                inline=False
            )
            embed.add_field(
                name="ℹ️ autofeed info <trigger>",
                value="Show detailed information about a trigger",
                inline=False
            )
            embed.add_field(
                name="🧪 autofeed test <trigger>",
                value="Test if you can trigger a specific autofeed",
                inline=False
            )
            embed.set_footer(text="💡 Autofeeds respond when triggers are found in messages")
            await ctx.send(embed=embed)

    @autofeed.command(name="list")
    async def autofeed_list(self, ctx):
        """List all configured autofeeds"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage autofeeds.", ephemeral=True)
            return

        if not self.autofeeds:
            await ctx.send("📝 No autofeeds configured.")
            return

        # Paginate if there are many autofeeds
        items_per_page = 5
        triggers = list(self.autofeeds.keys())
        pages = [triggers[i:i + items_per_page] for i in range(0, len(triggers), items_per_page)]

        for page_num, page_triggers in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"🤖 Configured Autofeeds (Page {page_num}/{len(pages)})",
                color=discord.Color.blue()
            )

            for trigger in page_triggers:
                data = self.autofeeds[trigger]
                reply = data.get('reply', 'No reply set')
                requirements = data.get('requirements', {})
                
                # Truncate long replies for display
                display_reply = reply[:150] + "..." if len(reply) > 150 else reply
                
                req_text = ""
                if requirements:
                    req_parts = []
                    if 'role' in requirements:
                        roles = requirements['role']
                        if isinstance(roles, list):
                            roles = ', '.join(roles)
                        req_parts.append(f"Role: {roles}")
                    if 'name' in requirements:
                        names = requirements['name']
                        if isinstance(names, list):
                            names = ', '.join(names)
                        req_parts.append(f"Name: {names}")
                    if 'useprefix' in requirements:
                        prefixes = requirements['useprefix']
                        if isinstance(prefixes, list):
                            prefixes = ', '.join(prefixes)
                        req_parts.append(f"Prefix: {prefixes}")
                    req_text = f"\n🔒 **Requirements:** {' | '.join(req_parts)}"
                else:
                    req_text = "\n🔒 **Requirements:** permissions.autofeed.trigger"

                embed.add_field(
                    name=f"🔤 {trigger}",
                    value=f"💬 **Reply:** {display_reply}{req_text}",
                    inline=False
                )

            embed.set_footer(text=f"Total autofeeds: {len(self.autofeeds)}")
            await ctx.send(embed=embed)

    @autofeed.command(name="add")
    @discord.app_commands.describe(
        trigger="The text that will trigger the response",
        reply="The response the bot will send"
    )
    async def autofeed_add(self, ctx, trigger: str, *, reply: str):
        """Add a new autofeed response"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage autofeeds.", ephemeral=True)
            return

        # Check if trigger already exists
        if trigger in self.autofeeds:
            await ctx.send(f"❌ Autofeed for trigger `{trigger}` already exists! Use `autofeed edit` to modify it.", ephemeral=True)
            return

        # Add the autofeed
        self.autofeeds[trigger] = {
            'reply': reply,
            'requirements': {}
        }
        self.save_config()

        # Log the addition
        await self.log_autofeed_action(
            f"added trigger '{trigger}'", 
            ctx.guild, 
            ctx.author, 
            f"Reply: {reply[:100]}{'...' if len(reply) > 100 else ''}"
        )

        # Truncate for display
        display_reply = reply[:100] + "..." if len(reply) > 100 else reply
        embed = discord.Embed(
            title="✅ Autofeed Added",
            color=discord.Color.green()
        )
        embed.add_field(name="🔤 Trigger", value=f"`{trigger}`", inline=False)
        embed.add_field(name="💬 Reply", value=f"`{display_reply}`", inline=False)
        embed.add_field(name="🔒 Requirements", value="permissions.autofeed.trigger (default)", inline=False)
        
        await ctx.send(embed=embed)

    @autofeed.command(name="remove")
    @discord.app_commands.describe(trigger="The trigger to remove")
    @discord.app_commands.autocomplete(trigger=trigger_autocomplete)
    async def autofeed_remove(self, ctx, trigger: str):
        """Remove an autofeed"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage autofeeds.", ephemeral=True)
            return

        if trigger not in self.autofeeds:
            await ctx.send(f"❌ No autofeed found for trigger `{trigger}`!", ephemeral=True)
            return

        # Store removed data for logging
        removed_data = self.autofeeds[trigger]
        
        # Remove the autofeed
        del self.autofeeds[trigger]
        self.save_config()

        # Log the removal
        await self.log_autofeed_action(
            f"removed trigger '{trigger}'", 
            ctx.guild, 
            ctx.author, 
            f"Removed reply: {removed_data.get('reply', 'No reply')[:100]}{'...' if len(removed_data.get('reply', '')) > 100 else ''}"
        )

        embed = discord.Embed(
            title="✅ Autofeed Removed",
            description=f"Removed autofeed for trigger: `{trigger}`",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @autofeed.command(name="requirement", aliases=["req"])
    @discord.app_commands.describe(
        trigger="The trigger to add requirements to",
        req_type="Type of requirement (role/name/useprefix)",
        value="The requirement value"
    )
    @discord.app_commands.autocomplete(
        trigger=trigger_autocomplete,
        req_type=requirement_type_autocomplete
    )
    async def autofeed_requirement(self, ctx, trigger: str, req_type: str, *, value: str):
        """Add a requirement for an autofeed trigger"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage autofeeds.", ephemeral=True)
            return

        if trigger not in self.autofeeds:
            await ctx.send(f"❌ No autofeed found for trigger `{trigger}`!", ephemeral=True)
            return

        if req_type.lower() not in ['role', 'name', 'useprefix']:
            await ctx.send("❌ Invalid requirement type! Use: **role**, **name**, or **useprefix**", ephemeral=True)
            return

        # Initialize requirements if not exists
        if 'requirements' not in self.autofeeds[trigger]:
            self.autofeeds[trigger]['requirements'] = {}

        # Add the requirement
        req_type = req_type.lower()
        requirements = self.autofeeds[trigger]['requirements']
        
        if req_type not in requirements:
            requirements[req_type] = []
        elif not isinstance(requirements[req_type], list):
            requirements[req_type] = [requirements[req_type]]

        # Add value if not already present
        if value not in requirements[req_type]:
            requirements[req_type].append(value)
            self.save_config()
            
            # Log the requirement addition
            await self.log_autofeed_action(
                f"added {req_type} requirement to trigger '{trigger}'", 
                ctx.guild, 
                ctx.author, 
                f"Value: {value}"
            )
            
            embed = discord.Embed(
                title="✅ Requirement Added",
                color=discord.Color.green()
            )
            embed.add_field(name="🔤 Trigger", value=f"`{trigger}`", inline=True)
            embed.add_field(name="🔒 Type", value=req_type.title(), inline=True)
            embed.add_field(name="📝 Value", value=f"`{value}`", inline=True)
            
            if req_type == "role":
                embed.add_field(
                    name="ℹ️ Note", 
                    value="Users need this role name or ID to trigger the autofeed", 
                    inline=False
                )
            elif req_type == "name":
                embed.add_field(
                    name="ℹ️ Note", 
                    value="Users with this name pattern (supports regex) can trigger the autofeed", 
                    inline=False
                )
            elif req_type == "useprefix":
                embed.add_field(
                    name="ℹ️ Note", 
                    value="Messages must start with this prefix to trigger the autofeed", 
                    inline=False
                )
            
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Requirement `{value}` already exists for {req_type} in trigger `{trigger}`!", ephemeral=True)

    @autofeed.command(name="clearreq")
    @discord.app_commands.describe(
        trigger="The trigger to clear requirements from",
        req_type="Type of requirement to clear (role/name/useprefix)"
    )
    @discord.app_commands.autocomplete(
        trigger=trigger_autocomplete,
        req_type=requirement_type_autocomplete
    )
    async def autofeed_clear_requirement(self, ctx, trigger: str, req_type: str):
        """Clear a specific requirement type for a trigger"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage autofeeds.", ephemeral=True)
            return

        if trigger not in self.autofeeds:
            await ctx.send(f"❌ No autofeed found for trigger `{trigger}`!", ephemeral=True)
            return

        if req_type.lower() not in ['role', 'name', 'useprefix']:
            await ctx.send("❌ Invalid requirement type! Use: **role**, **name**, or **useprefix**", ephemeral=True)
            return

        req_type = req_type.lower()
        requirements = self.autofeeds[trigger].get('requirements', {})
        
        if req_type not in requirements:
            await ctx.send(f"❌ No {req_type} requirements found for trigger `{trigger}`!", ephemeral=True)
            return

        # Clear the requirement
        cleared_values = requirements[req_type]
        del requirements[req_type]
        self.save_config()
        
        # Log the requirement clearing
        await self.log_autofeed_action(
            f"cleared {req_type} requirements for trigger '{trigger}'", 
            ctx.guild, 
            ctx.author, 
            f"Cleared values: {', '.join(cleared_values) if isinstance(cleared_values, list) else cleared_values}"
        )
        
        embed = discord.Embed(
            title="✅ Requirements Cleared",
            description=f"Cleared all **{req_type}** requirements for trigger `{trigger}`",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🗑️ Removed Values", 
            value=f"`{', '.join(cleared_values) if isinstance(cleared_values, list) else cleared_values}`", 
            inline=False
        )
        await ctx.send(embed=embed)

    @autofeed.command(name="edit")
    @discord.app_commands.describe(
        trigger="The trigger to edit",
        new_reply="The new reply for the trigger"
    )
    @discord.app_commands.autocomplete(trigger=trigger_autocomplete)
    async def autofeed_edit(self, ctx, trigger: str, *, new_reply: str):
        """Edit the reply for an existing autofeed"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage autofeeds.", ephemeral=True)
            return

        if trigger not in self.autofeeds:
            await ctx.send(f"❌ No autofeed found for trigger `{trigger}`!", ephemeral=True)
            return

        old_reply = self.autofeeds[trigger]['reply']
        self.autofeeds[trigger]['reply'] = new_reply
        self.save_config()

        # Log the edit
        await self.log_autofeed_action(
            f"edited trigger '{trigger}'", 
            ctx.guild, 
            ctx.author, 
            f"Old: {old_reply[:50]}{'...' if len(old_reply) > 50 else ''}, New: {new_reply[:50]}{'...' if len(new_reply) > 50 else ''}"
        )

        embed = discord.Embed(
            title="✅ Autofeed Updated",
            color=discord.Color.green()
        )
        embed.add_field(name="🔤 Trigger", value=f"`{trigger}`", inline=False)
        
        # Truncate for display
        display_old = old_reply[:100] + "..." if len(old_reply) > 100 else old_reply
        display_new = new_reply[:100] + "..." if len(new_reply) > 100 else new_reply
        
        embed.add_field(name="📝 Old Reply", value=f"`{display_old}`", inline=False)
        embed.add_field(name="🆕 New Reply", value=f"`{display_new}`", inline=False)
        
        await ctx.send(embed=embed)

    @autofeed.command(name="info")
    @discord.app_commands.describe(trigger="The trigger to get information about")
    @discord.app_commands.autocomplete(trigger=trigger_autocomplete)
    async def autofeed_info(self, ctx, trigger: str):
        """Show detailed information about a specific autofeed"""
        if trigger not in self.autofeeds:
            await ctx.send(f"❌ No autofeed found for trigger `{trigger}`!", ephemeral=True)
            return

        data = self.autofeeds[trigger]
        reply = data.get('reply', 'No reply set')
        requirements = data.get('requirements', {})

        embed = discord.Embed(
            title=f"ℹ️ Autofeed Information",
            color=discord.Color.blue()
        )
        embed.add_field(name="🔤 Trigger", value=f"`{trigger}`", inline=False)
        embed.add_field(name="💬 Reply", value=f"```{reply}```", inline=False)

        if requirements:
            req_text = []
            if 'role' in requirements:
                roles = requirements['role']
                role_list = ', '.join(f"`{r}`" for r in roles) if isinstance(roles, list) else f"`{roles}`"
                req_text.append(f"**👥 Role(s):** {role_list}")
            
            if 'name' in requirements:
                names = requirements['name']
                name_list = ', '.join(f"`{n}`" for n in names) if isinstance(names, list) else f"`{names}`"
                req_text.append(f"**📛 Name Pattern(s):** {name_list}")
            
            if 'useprefix' in requirements:
                prefixes = requirements['useprefix']
                prefix_list = ', '.join(f"`{p}`" for p in prefixes) if isinstance(prefixes, list) else f"`{prefixes}`"
                req_text.append(f"**🏷️ Required Prefix(es):** {prefix_list}")
            
            embed.add_field(
                name="🔒 Requirements", 
                value='\n'.join(req_text), 
                inline=False
            )
        else:
            embed.add_field(
                name="🔒 Requirements", 
                value="Default: `permissions.autofeed.trigger`", 
                inline=False
            )

        embed.set_footer(text="💡 Use 'autofeed test' to check if you can trigger this autofeed")
        await ctx.send(embed=embed)

    @autofeed.command(name="test")
    @discord.app_commands.describe(trigger="The trigger to test")
    @discord.app_commands.autocomplete(trigger=trigger_autocomplete)
    async def autofeed_test(self, ctx, trigger: str):
        """Test if you can trigger a specific autofeed"""
        if trigger not in self.autofeeds:
            await ctx.send(f"❌ No autofeed found for trigger `{trigger}`!", ephemeral=True)
            return

        # Create a mock message for testing
        mock_message = type('MockMessage', (), {
            'content': trigger,
            'author': ctx.author,
            'channel': ctx.channel
        })()

        can_trigger = self.check_requirements(ctx.author, mock_message, trigger)
        
        # Log the test
        await self.log_autofeed_action(
            f"tested trigger '{trigger}'", 
            ctx.guild, 
            ctx.author, 
            f"Result: {'can trigger' if can_trigger else 'cannot trigger'}"
        )
        
        if can_trigger:
            reply = self.autofeeds[trigger]['reply']
            embed = discord.Embed(
                title="✅ Test Successful",
                description="You can trigger this autofeed!",
                color=discord.Color.green()
            )
            embed.add_field(name="🔤 Trigger", value=f"`{trigger}`", inline=False)
            embed.add_field(name="🤖 Bot Response", value=f"```{reply}```", inline=False)
        else:
            requirements = self.autofeeds[trigger].get('requirements', {})
            embed = discord.Embed(
                title="❌ Test Failed",
                description="You don't meet the requirements to trigger this autofeed.",
                color=discord.Color.red()
            )
            
            if requirements:
                req_text = []
                if 'role' in requirements:
                    req_text.append(f"**👥 Required Role(s):** {', '.join(requirements['role'])}")
                if 'name' in requirements:
                    req_text.append(f"**📛 Required Name Pattern(s):** {', '.join(requirements['name'])}")
                if 'useprefix' in requirements:
                    req_text.append(f"**🏷️ Required Prefix(es):** {', '.join(requirements['useprefix'])}")
                
                embed.add_field(
                    name="🔒 Missing Requirements", 
                    value='\n'.join(req_text), 
                    inline=False
                )
            else:
                embed.add_field(
                    name="🔒 Missing Permission", 
                    value="`permissions.autofeed.trigger`", 
                    inline=False
                )

        await ctx.send(embed=embed, ephemeral=True)

    @autofeed.command(name="clear")
    async def autofeed_clear_all(self, ctx):
        """Clear all autofeeds (requires confirmation)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to manage autofeeds.", ephemeral=True)
            return

        if not self.autofeeds:
            await ctx.send("📝 No autofeeds to clear.")
            return

        # Create confirmation embed
        embed = discord.Embed(
            title="⚠️ Clear All Autofeeds",
            description=f"Are you sure you want to delete **all {len(self.autofeeds)} autofeeds**?\n\n**This action cannot be undone!**",
            color=discord.Color.red()
        )

        view = ConfirmationView(ctx.author)
        message = await ctx.send(embed=embed, view=view)
        
        await view.wait()
        
        if view.confirmed:
            count = len(self.autofeeds)
            trigger_list = list(self.autofeeds.keys())
            self.autofeeds = {}
            self.save_config()
            
            # Log the clearing
            await self.log_autofeed_action(
                f"cleared all autofeeds", 
                ctx.guild, 
                ctx.author, 
                f"Cleared {count} triggers: {', '.join(trigger_list[:10])}{'...' if len(trigger_list) > 10 else ''}"
            )
            
            embed = discord.Embed(
                title="✅ Autofeeds Cleared",
                description=f"Successfully deleted all {count} autofeeds.",
                color=discord.Color.green()
            )
            await message.edit(embed=embed, view=None)
        else:
            embed = discord.Embed(
                title="❌ Action Cancelled",
                description="No autofeeds were deleted.",
                color=discord.Color.grey()
            )
            await message.edit(embed=embed, view=None)

class ConfirmationView(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=30)
        self.author = author
        self.confirmed = False

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("❌ Only the command author can confirm this action.", ephemeral=True)
            return
        
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("❌ Only the command author can cancel this action.", ephemeral=True)
            return
        
        self.confirmed = False
        self.stop()
        await interaction.response.defer()

async def setup(bot):
    await bot.add_cog(AutofeedCog(bot))
