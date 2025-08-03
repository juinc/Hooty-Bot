"""
Hooty Bot - Main Entrypoint

OVERVIEW:
This is the main entrypoint for Hooty Bot, a modular, feature-rich Discord bot for modern communities.  
Handles dynamic cog discovery/loading, logging, error handling, and slash command management.  
Supports Docker, per-guild config, and both slash and prefix commands.

FEATURES:
• Dynamic cog discovery and categorized loading (core, essentials, optional)
• Slash command and prefix command support
• Cog management: load, unload, reload, list, info (with autocomplete)
• Global error handling and logging (file, console, and Discord channel)
• Per-guild config and dynamic command prefix
• Activity/status auto-setup from config
• Discord logging for bot startup, errors, and guild joins
• Docker-ready (with .env support)
• Auto-sync slash commands (global or test guild)
• Owner/admin permission checks for cog management

COG MANAGEMENT COMMANDS (Slash):
/cog load <cog>      - Load a cog by name (admin/owner only)
/cog unload <cog>    - Unload a cog (admin/owner only)
/cog reload <cog>    - Reload a cog (admin/owner only)
/cog list            - List all available and loaded cogs
/cog info <cog>      - Show info about a cog
/sync                - Manually sync slash commands

Prefix commands: (if cogs provide them)

EXTRA:
- All logs are written to `src/logs/bot.log`
- Environment variables are loaded from `.env` in the project root
- Cogs are auto-discovered from `src/cogs/` and loaded in order: permissions, config, essentials, optional
- Command prefix and other settings are dynamically updated from config cog

USAGE BY OTHER COGS:
# Log a bot-level action (if LoggingCog is present)
await bot.log.log(LogLevel.INFO, "Bot action", guild, user, LogType.COG, file_override="main")

# Check cog admin permission (if PermissionsCog is present)
permissions_cog = bot.get_cog('PermissionsCog')
if permissions_cog and permissions_cog.has_permission(member, 'permissions.cog.admin'):
    # Do admin stuff

# Access config or loaded cogs for integrations
config = bot.config
loaded_cogs = bot.cogs

DOCKER:
- To run with Docker, use the provided docker-compose.yml
- All logs and data are stored in the `src/` directory.
"""

import discord
from discord.ext import commands
import asyncio
import logging
import sys
import os
import traceback
from datetime import datetime
from typing import List
from pathlib import Path

# Add src directory to Python path if running from parent directory
if Path.cwd().name != 'src':
    src_path = Path(__file__).parent
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

# Set up file logging - create logs in parent directory
log_dir = Path(__file__).parent.parent / "src/logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('discord_bot')

# Reduce discord.py logging verbosity
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.WARNING)

class MyBot(commands.Bot):
    def __init__(self):
        # Set up intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        # Initialize bot with basic settings
        super().__init__(
            command_prefix="!",  # Will be updated by config cog
            description="Cool Hooty Bot",
            intents=intents,
            help_command=commands.DefaultHelpCommand(
                no_category='Commands'
            )
        )
        
        self.start_time = None
        self.available_cogs = {}  # Track available cogs by path
        self.load_order = []  # Track loading order
        self.base_dir = Path(__file__).parent  # src/ directory
        
        # Will be set by ConfigCog
        self.config = None
        
    async def setup_hook(self):
        """This is called when the bot is starting up"""
        logger.info("Bot is starting up...")
        
        # Discover and load cogs in proper order
        await self.discover_cogs()
        await self.load_cogs_in_order()
        
        # Add the cog management commands
        self.tree.add_command(cog_group)
        
        # Sync commands after all cogs are loaded
        await self.sync_commands()
    
    async def discover_cogs(self):
        """Discover all cogs in the cogs directory and subdirectories"""
        cogs_dir = self.base_dir / "cogs"
        if not cogs_dir.exists():
            logger.error(f"Cogs directory not found at: {cogs_dir}")
            return
        
        self.available_cogs = {}
        
        # Walk through all directories
        for root, dirs, files in os.walk(cogs_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            
            for file in files:
                if file.endswith('.py') and not file.startswith('_'):
                    cog_name = file[:-3]
                    root_path = Path(root)
                    
                    # Calculate relative path from src directory
                    try:
                        relative_path = root_path.relative_to(self.base_dir)
                        module_path = str(relative_path / cog_name).replace(os.sep, '.')
                    except ValueError:
                        # If we can't get relative path, skip this cog
                        logger.warning(f"Skipping cog {cog_name} - invalid path")
                        continue
                    
                    # Categorize cogs
                    if cog_name == 'permissions':
                        category = 'core_permissions'
                    elif cog_name == 'config':
                        category = 'core_config'
                    elif 'essentials' in str(relative_path):
                        category = 'essentials'
                    else:
                        category = 'optional'
                    
                    self.available_cogs[cog_name] = {
                        'module_path': module_path,
                        'category': category,
                        'file_path': root_path / file,
                        'relative_path': relative_path
                    }
        
        logger.info(f"Discovered {len(self.available_cogs)} cogs")
    
    async def load_cogs_in_order(self):
        """Load cogs in the specified order"""
        load_order = ['core_permissions', 'core_config', 'essentials', 'optional']
        loaded = []
        failed = []
        
        for category in load_order:
            category_cogs = [name for name, info in self.available_cogs.items() 
                            if info['category'] == category]
            
            # Sort alphabetically within category
            category_cogs.sort()
            
            for cog_name in category_cogs:
                cog_info = self.available_cogs[cog_name]
                try:
                    await self.load_extension(cog_info['module_path'])
                    loaded.append(cog_name)
                    self.load_order.append(cog_name)
                    logger.info(f"Loaded cog: {cog_name} ({category}) from {cog_info['module_path']}")
                    
                    # Special handling for config cog
                    if cog_name == 'config':
                        # Config cog should have attached self.config to the bot
                        if hasattr(self, 'config') and self.config:
                            # Update bot settings from config
                            await self.apply_config_settings()
                        
                except Exception as e:
                    failed.append(cog_name)
                    logger.error(f"Failed to load cog {cog_name}: {e}")
                    if self.config and self.config.get('features.debug_mode', False):
                        traceback.print_exc()
        
        logger.info(f"Loaded {len(loaded)} cogs successfully")
        if failed:
            logger.warning(f"Failed to load {len(failed)} cogs: {', '.join(failed)}")
    
    async def apply_config_settings(self):
        """Apply settings from config cog"""
        if not self.config:
            return
        
        # Update command prefix
        new_prefix = self.config.get('bot.prefix', '!')
        if new_prefix != self.command_prefix:
            self.command_prefix = new_prefix
            logger.info(f"Updated command prefix to: {new_prefix}")
        
        # Update case sensitivity
        case_insensitive = self.config.get('bot.case_insensitive', True)
        if hasattr(self, 'case_insensitive'):
            self.case_insensitive = case_insensitive
        
        # Set owner IDs
        owner_ids = self.config.get('bot.owner_ids', [])
        if owner_ids:
            self.owner_ids = set(owner_ids)
            logger.info(f"Set owner IDs: {owner_ids}")
    
    async def sync_commands(self):
        """Sync slash commands"""
        try:
            # Check if we should sync commands
            if self.config and not self.config.get('features.auto_sync_commands', True):
                logger.info("Auto sync disabled, skipping command sync")
                return
            
            # Check for test guild
            test_guild_id = None
            if self.config:
                test_guild_id = self.config.get('bot.test_guild_id')
                debug_mode = self.config.get('features.debug_mode', False)
            else:
                debug_mode = False
            
            if test_guild_id and debug_mode:
                # Sync to specific guild in debug mode (faster)
                guild = discord.Object(id=test_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info(f"Synced {len(synced)} commands to test guild")
            else:
                # Sync globally
                synced = await self.tree.sync()
                logger.info(f"Synced {len(synced)} commands globally")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    def has_cog_admin_permission(self, user: discord.Member) -> bool:
        """Check if user has permissions.cog.admin permission"""
        # Check if permissions cog is loaded
        permissions_cog = self.get_cog('PermissionsCog')
        if not permissions_cog:
            # Fall back to owner check if permissions cog not available
            return user.id in self.owner_ids if self.owner_ids else False
        
        # Check for permissions.cog.admin permission
        return permissions_cog.has_permission(user, 'permissions.cog.admin')
    
    async def on_ready(self):
        """Called when the bot is fully ready"""
        self.start_time = datetime.utcnow()
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        logger.info(f'Working directory: {Path.cwd()}')
        logger.info(f'Base directory: {self.base_dir}')
        
        # Set activity from config
        if self.config:
            activity_type_str = self.config.get('bot.activity.type', 'playing').lower()
            activity_name = self.config.get('bot.activity.name', 'with Discord.py')
            
            activity_type = {
                'playing': discord.ActivityType.playing,
                'watching': discord.ActivityType.watching,
                'listening': discord.ActivityType.listening,
                'streaming': discord.ActivityType.streaming
            }.get(activity_type_str, discord.ActivityType.playing)
            
            activity = discord.Activity(type=activity_type, name=activity_name)
            await self.change_presence(activity=activity)
        
        # Log to Discord if enabled
        if self.config:
            log_enabled = self.config.get('logging.discord_enabled', False)
            log_channel_id = self.config.get('logging.discord_channel_id')
            
            if log_enabled and log_channel_id:
                channel = self.get_channel(log_channel_id)
                if channel:
                    embed = discord.Embed(
                        title="Bot Started",
                        description=f"**Bot:** {self.user.mention}\n**Guilds:** {len(self.guilds)}\n**Cogs Loaded:** {len(self.cogs)}",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        logger.warning("No permission to send to log channel")
    
    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild"""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        
        if self.config:
            log_enabled = self.config.get('logging.discord_enabled', False)
            log_channel_id = self.config.get('logging.discord_channel_id')
            
            if log_enabled and log_channel_id:
                channel = self.get_channel(log_channel_id)
                if channel:
                    embed = discord.Embed(
                        title="Joined New Guild",
                        description=f"**Name:** {guild.name}\n**ID:** {guild.id}\n**Members:** {guild.member_count}",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    if guild.icon:
                        embed.set_thumbnail(url=guild.icon.url)
                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass
    
    async def on_command_error(self, ctx, error):
        """Global error handler"""
        # Ignore command not found
        if isinstance(error, commands.CommandNotFound):
            return
        
        # Handle specific errors
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing required argument: `{error.param.name}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument: {error}")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"I don't have permission to do that: {', '.join(error.missing_permissions)}")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Command on cooldown. Try again in {error.retry_after:.1f} seconds.")
        else:
            # Log unexpected errors
            logger.error(f"Unhandled error in command {ctx.command}: {error}")
            
            debug_mode = self.config.get('features.debug_mode', False) if self.config else False
            if debug_mode:
                await ctx.send(f"An error occurred: ```py\n{str(error)[:1900]}\n```")
            else:
                await ctx.send("An unexpected error occurred. The developers have been notified.")
            
            # Log to error channel if configured
            if self.config:
                error_channel_id = self.config.get('logging.error_channel_id')
                if error_channel_id:
                    channel = self.get_channel(error_channel_id)
                    if channel:
                        embed = discord.Embed(
                            title="Command Error",
                            description=f"**Command:** {ctx.command}\n**User:** {ctx.author}\n**Guild:** {ctx.guild}",
                            color=discord.Color.red(),
                            timestamp=datetime.utcnow()
                        )
                        error_text = str(error)[:1000]
                        embed.add_field(name="Error", value=f"```py\n{error_text}\n```", inline=False)
                        try:
                            await channel.send(embed=embed)
                        except discord.Forbidden:
                            pass

# Initialize bot
bot = MyBot()

# Load environment variables from parent directory
def load_environment():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent.parent / '.env'
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)
        logger.info(f"Loaded environment from: {env_file}")
    else:
        logger.warning(f".env file not found at: {env_file}")

# ==================== COMMANDS ====================
# Slash command group for cog management
cog_group = discord.app_commands.Group(name='cog', description='Cog management commands')

# Autocomplete function for cog names
async def cog_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[discord.app_commands.Choice[str]]:
    """Autocomplete for cog names"""
    choices = []
    
    # Get all available cogs
    for cog_name in bot.available_cogs.keys():
        if current.lower() in cog_name.lower():
            choices.append(discord.app_commands.Choice(name=cog_name, value=cog_name))
    
    # Also include loaded cogs that might not be in available list
    for cog_name in list(bot.cogs.keys()):
        if (current.lower() in cog_name.lower() and 
            cog_name not in [c.value for c in choices]):
            choices.append(discord.app_commands.Choice(name=f"{cog_name} (loaded)", value=cog_name))
    
    return choices[:25]  # Discord limits to 25 choices

# ==================== SLASH COMMANDS ====================

@cog_group.command(name='load', description='Load a cog')
@discord.app_commands.describe(extension='The cog to load')
@discord.app_commands.autocomplete(extension=cog_autocomplete)
async def load_cog(interaction: discord.Interaction, extension: str):
    """Load a cog"""
    # Check permissions
    if not isinstance(interaction.user, discord.Member) or not bot.has_cog_admin_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        if extension in bot.available_cogs:
            module_path = bot.available_cogs[extension]['module_path']
            await bot.load_extension(module_path)
        else:
            # Try loading as direct module path
            await bot.load_extension(f'cogs.{extension}')
        
        embed = discord.Embed(
            title="Cog Loaded",
            description=f"✅ Successfully loaded `{extension}`",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Manually loaded cog: {extension}")
    except commands.ExtensionAlreadyLoaded:
        await interaction.followup.send(f"❌ Cog `{extension}` is already loaded.", ephemeral=True)
    except commands.ExtensionNotFound:
        await interaction.followup.send(f"❌ Cog `{extension}` not found.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to load `{extension}`: {e}", ephemeral=True)
        logger.error(f"Failed to manually load cog {extension}: {e}")

@cog_group.command(name='unload', description='Unload a cog')
@discord.app_commands.describe(extension='The cog to unload')
@discord.app_commands.autocomplete(extension=cog_autocomplete)
async def unload_cog(interaction: discord.Interaction, extension: str):
    """Unload a cog"""
    # Check permissions
    if not isinstance(interaction.user, discord.Member) or not bot.has_cog_admin_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    # Prevent unloading core cogs
    if extension in ['permissions', 'config']:
        await interaction.response.send_message(f"❌ Cannot unload core cog `{extension}`.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        if extension in bot.available_cogs:
            module_path = bot.available_cogs[extension]['module_path']
            await bot.unload_extension(module_path)
        else:
            await bot.unload_extension(f'cogs.{extension}')
        
        embed = discord.Embed(
            title="Cog Unloaded",
            description=f"✅ Successfully unloaded `{extension}`",
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Manually unloaded cog: {extension}")
    except commands.ExtensionNotLoaded:
        await interaction.followup.send(f"❌ Cog `{extension}` is not loaded.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to unload `{extension}`: {e}", ephemeral=True)
        logger.error(f"Failed to manually unload cog {extension}: {e}")

@cog_group.command(name='reload', description='Reload a cog')
@discord.app_commands.describe(extension='The cog to reload')
@discord.app_commands.autocomplete(extension=cog_autocomplete)
async def reload_cog(interaction: discord.Interaction, extension: str):
    """Reload a cog"""
    # Check permissions
    if not isinstance(interaction.user, discord.Member) or not bot.has_cog_admin_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        if extension in bot.available_cogs:
            module_path = bot.available_cogs[extension]['module_path']
            await bot.reload_extension(module_path)
        else:
            await bot.reload_extension(f'cogs.{extension}')
        
        # If reloading config cog, reapply settings
        if extension == 'config':
            await bot.apply_config_settings()
        
        embed = discord.Embed(
            title="Cog Reloaded",
            description=f"✅ Successfully reloaded `{extension}`",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Manually reloaded cog: {extension}")
    except commands.ExtensionNotLoaded:
        await interaction.followup.send(f"❌ Cog `{extension}` is not loaded.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to reload `{extension}`: {e}", ephemeral=True)
        logger.error(f"Failed to manually reload cog {extension}: {e}")

@cog_group.command(name='list', description='List all cogs')
async def list_cogs(interaction: discord.Interaction):
    """List all available and loaded cogs"""
    # Check permissions
    if not isinstance(interaction.user, discord.Member) or not bot.has_cog_admin_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    loaded_cogs = list(bot.cogs.keys())
    
    embed = discord.Embed(
        title="Cog Status",
        color=discord.Color.blue()
    )
    
    # Group by category
    categories = {}
    for cog_name, cog_info in bot.available_cogs.items():
        category = cog_info['category']
        if category not in categories:
            categories[category] = []
        
        status_icon = "✅" if cog_name in loaded_cogs else "❌"
        status_text = "Loaded" if cog_name in loaded_cogs else "Not loaded"
        categories[category].append(f"{status_icon} **{cog_name}** - {status_text}")
    
    # Add fields for each category
    category_names = {
        'core_permissions': 'Core - Permissions',
        'core_config': 'Core - Config',
        'essentials': 'Essential Cogs',
        'optional': 'Optional Cogs'
    }
    
    for category, cogs in categories.items():
        if cogs:
            embed.add_field(
                name=category_names.get(category, category.title()),
                value="\n".join(cogs),
                inline=False
            )
    
    # Add any loaded cogs not in available list
    orphaned_cogs = [cog for cog in loaded_cogs if cog not in bot.available_cogs]
    if orphaned_cogs:
        orphaned_status = [f"⚠️ **{cog}** - Loaded (file missing)" for cog in orphaned_cogs]
        embed.add_field(
            name="Orphaned Cogs",
            value="\n".join(orphaned_status),
            inline=False
        )
    
    embed.set_footer(text=f"Total: {len(loaded_cogs)}/{len(bot.available_cogs)} cogs loaded")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@cog_group.command(name='info', description='Get information about a specific cog')
@discord.app_commands.describe(extension='The cog to get info about')
@discord.app_commands.autocomplete(extension=cog_autocomplete)
async def cog_info(interaction: discord.Interaction, extension: str):
    """Get detailed information about a cog"""
    # Check permissions
    if not isinstance(interaction.user, discord.Member) or not bot.has_cog_admin_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"Cog Information: {extension}",
        color=discord.Color.blue()
    )
    
    # Check if cog is loaded
    cog_instance = bot.get_cog(extension)
    is_loaded = cog_instance is not None
    
    embed.add_field(name="Status", value="✅ Loaded" if is_loaded else "❌ Not Loaded", inline=True)
    
    # Get cog info from available_cogs
    if extension in bot.available_cogs:
        cog_info = bot.available_cogs[extension]
        embed.add_field(name="Category", value=cog_info['category'].replace('_', ' ').title(), inline=True)
        embed.add_field(name="Module Path", value=cog_info['module_path'], inline=False)
        embed.add_field(name="File Path", value=str(cog_info['file_path']), inline=False)
    
    # If loaded, get additional info
    if is_loaded:
        commands_count = len(cog_instance.get_commands()) if hasattr(cog_instance, 'get_commands') else 0
        embed.add_field(name="Commands", value=str(commands_count), inline=True)
        
        if hasattr(cog_instance, '__doc__') and cog_instance.__doc__:
            embed.add_field(name="Description", value=cog_instance.__doc__, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Standalone sync command
@bot.tree.command(name='sync', description='Sync slash commands')
async def sync_commands(interaction: discord.Interaction):
    """Manually sync slash commands"""
    # Check permissions
    if not isinstance(interaction.user, discord.Member) or not bot.has_cog_admin_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        await bot.sync_commands()
        embed = discord.Embed(
            title="Commands Synced",
            description="✅ Successfully synced all slash commands",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands: {e}", ephemeral=True)
        logger.error(f"Failed to sync commands: {e}")

# Run the bot
async def main():
    """Main bot runner"""
    # Load environment variables
    load_environment()
    
    # Get token from environment
    token = os.getenv('BOT_TOKEN')
    
    if not token:
        logger.critical("BOT_TOKEN not found in environment variables!")
        logger.critical("Make sure you have a .env file in the bot/ directory with BOT_TOKEN=your_token")
        return
    
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
        traceback.print_exc()
