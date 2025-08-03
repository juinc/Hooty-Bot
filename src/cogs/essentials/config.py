"""
Discord Configuration Management Cog - Dynamic Bot Settings Manager

OVERVIEW:
Provides comprehensive configuration management for Discord bots with JSON/YAML file support,
environment variables, and dynamic setting updates without restarts.

SETUP:
- No manual setup required - auto-creates files
- Config file: src/config/main_config.json (or .yaml)
- Environment file: .env (auto-created with template)
- Access via: self.bot.config.get('key') or self.bot.config.get_env('VAR')

PERMISSIONS:
- Commands require Administrator permission or bot owner status

COMMANDS:
/botconfig get [key]     - View configuration (all or specific key)
/botconfig set <key> <value> - Set configuration value (JSON supported)
/botconfig reload        - Reload configuration from files
/botconfig validate      - Check configuration validity
/botconfig backup        - Create timestamped configuration backup

Prefix commands: !config <subcommand> (same functionality)

USAGE EXAMPLES IN OTHER COGS:

# Basic configuration access
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command()
    async def example(self, ctx):
        # Get config values with defaults
        prefix = self.bot.config.get('bot.prefix', '!')
        log_level = self.bot.config.get('logging.level', 'INFO')
        
        # Check if features are enabled
        if self.bot.config.get('features.command_logging', False):
            print(f"Command {ctx.command} used")
        
        # Get environment variables
        db_password = self.bot.config.get_env('DB_PASSWORD')
        api_key = self.bot.config.get_env('API_KEY')

FEATURES:
• JSON/YAML file support with auto-creation and validation
• Environment variable loading with type conversion  
• Dot notation access with defaults
• Real-time updates without restart
• Permission-based management
• Automatic backup creation
• Both slash and prefix commands
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import yaml
import os
from typing import Any, Dict, List, Optional, Union
from dotenv import load_dotenv
from datetime import datetime
import copy

class BotConfig:
    """Configuration class that provides easy access to bot settings"""
    
    def __init__(self, config_data: Dict[str, Any], env_data: Dict[str, Any]):
        self._config = config_data
        self._env = env_data
        self._last_reload = datetime.now()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation (e.g., 'bot.prefix')"""
        keys = key.split('.')
        current = self._config
        
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        
        return current
    
    def get_env(self, key: str, default: Any = None) -> Any:
        """Get an environment variable"""
        return self._env.get(key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """Set a configuration value using dot notation"""
        keys = key.split('.')
        current = self._config
        
        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Set the final key
        current[keys[-1]] = value
        return True
    
    def exists(self, key: str) -> bool:
        """Check if a configuration key exists"""
        return self.get(key) is not None
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get an entire configuration section"""
        return self.get(section, {})
    
    def to_dict(self) -> Dict[str, Any]:
        """Get the entire configuration as a dictionary"""
        return copy.deepcopy(self._config)
    
    @property
    def last_reload(self) -> datetime:
        """When the config was last reloaded"""
        return self._last_reload

class ConfigManager:
    """Manages loading and saving configuration files"""
    
    def __init__(self, config_file: str = "src/config/main_config.json", env_file: str = ".env"):
        self.config_file = config_file
        self.env_file = env_file
        self.default_config = {
            "bot": {
                "prefix": "!",
                "description": "A Discord Bot",
                "case_insensitive": True,
                "owner_ids": [],
                "activity": {
                    "type": "playing",
                    "name": "with Discord.py"
                }
            },
            "features": {
                "auto_sync_commands": True,
                "error_logging": True,
                "command_logging": True
            },
            "logging": {
                "level": "INFO",
                "file": "bot.log",
                "max_file_size": "10MB",
                "backup_count": 5
            },
        }
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if not os.path.exists(self.config_file):
            self.create_default_config()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                if self.config_file.endswith('.yaml') or self.config_file.endswith('.yml'):
                    return yaml.safe_load(f)
                else:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.default_config.copy()
    
    def load_env(self) -> Dict[str, Any]:
        """Load environment variables"""
        load_dotenv(self.env_file)
        
        env_vars = {}
        for key, value in os.environ.items():
            # Convert common boolean and numeric values
            if value.lower() in ('true', 'false'):
                env_vars[key] = value.lower() == 'true'
            elif value.isdigit():
                env_vars[key] = int(value)
            else:
                try:
                    env_vars[key] = float(value)
                except ValueError:
                    env_vars[key] = value
        
        return env_vars
    
    def save_config(self, config_data: Dict[str, Any]) -> bool:
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                if self.config_file.endswith('.yaml') or self.config_file.endswith('.yml'):
                    yaml.dump(config_data, f, default_flow_style=False, indent=2)
                else:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def create_default_config(self):
        """Create a default configuration file"""
        self.save_config(self.default_config)
        
        # Create default .env file if it doesn't exist
        if not os.path.exists(self.env_file):
            with open(self.env_file, 'w') as f:
                f.write("# Bot Configuration - Keep this file secure!\n")
                f.write("BOT_TOKEN=your_bot_token_here\n")
    
    def validate_config(self, config_data: Dict[str, Any]) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []
        
        # Required sections
        required_sections = ['bot', 'features', 'logging']
        for section in required_sections:
            if section not in config_data:
                errors.append(f"Missing required section: {section}")
        
        # Bot section validation
        if 'bot' in config_data:
            bot_config = config_data['bot']
            if 'prefix' not in bot_config:
                errors.append("Missing bot.prefix")
            elif not isinstance(bot_config['prefix'], str):
                errors.append("bot.prefix must be a string")
        
        # Logging level validation
        if 'logging' in config_data and 'level' in config_data['logging']:
            valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
            if config_data['logging']['level'] not in valid_levels:
                errors.append(f"Invalid logging level. Must be one of: {', '.join(valid_levels)}")
        
        return errors

class ConfigCog(commands.Cog):
    """Configuration management for the bot"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config_manager = ConfigManager()
        self.load_configuration()
    
    def load_configuration(self):
        """Load configuration and attach to bot"""
        config_data = self.config_manager.load_config()
        env_data = self.config_manager.load_env()
        
        # Attach config to bot
        self.bot.config = BotConfig(config_data, env_data)
        
        # Apply bot configuration
        self.apply_bot_settings()
    
    def apply_bot_settings(self):
        """Apply configuration settings to the bot"""
        config = self.bot.config
        
        # Set command prefix if specified
        if hasattr(self.bot, 'command_prefix') and config.exists('bot.prefix'):
            self.bot.command_prefix = config.get('bot.prefix', '!')
        
        # Set case insensitive
        if config.exists('bot.case_insensitive'):
            self.bot.case_insensitive = config.get('bot.case_insensitive', True)
        
        # Set owner IDs
        if config.exists('bot.owner_ids'):
            owner_ids = config.get('bot.owner_ids', [])
            if owner_ids:
                self.bot.owner_ids = set(owner_ids)
    
    async def reload_configuration(self) -> bool:
        """Reload configuration from files"""
        try:
            self.load_configuration()
            return True
        except Exception as e:
            print(f"Error reloading configuration: {e}")
            return False
    
    def has_admin_role(self, member: discord.Member) -> bool:
        """Check if member can manage configuration"""
        return member.guild_permissions.administrator or member.id in self.bot.owner_ids
    
    # Shared implementation methods
    async def _reload_config_impl(self, author: Union[discord.Member, discord.User], respond_func):
        """Shared implementation for config reload"""
        if isinstance(author, discord.Member):
            if not self.has_admin_role(author):
                await respond_func("❌ You don't have permission to reload configuration.", ephemeral=True)
                return
        elif author.id not in self.bot.owner_ids:
            await respond_func("❌ Only bot owners can reload configuration.", ephemeral=True)
            return
        
        success = await self.reload_configuration()
        if success:
            await respond_func("✅ Configuration reloaded successfully!")
        else:
            await respond_func("❌ Failed to reload configuration. Check console for errors.")
    
    async def _get_config_impl(self, key: Optional[str], respond_func):
        """Shared implementation for getting config values"""
        if key:
            value = self.bot.config.get(key)
            if value is None:
                await respond_func(f"❌ Configuration key `{key}` not found.")
            else:
                # Format the value nicely
                if isinstance(value, dict):
                    formatted_value = json.dumps(value, indent=2)
                else:
                    formatted_value = str(value)
                
                embed = discord.Embed(
                    title=f"Configuration: {key}",
                    description=f"```json\n{formatted_value}\n```",
                    color=discord.Color.blue()
                )
                await respond_func(embed=embed)
        else:
            # Show general config info
            config = self.bot.config
            embed = discord.Embed(
                title="Bot Configuration",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Bot Settings",
                value=f"Prefix: `{config.get('bot.prefix', '!')}`\n"
                        f"Description: {config.get('bot.description', 'N/A')}\n"
                        f"Case Insensitive: {config.get('bot.case_insensitive', True)}",
                inline=False
            )
            
            embed.add_field(
                name="Features",
                value=f"Auto Sync: {config.get('features.auto_sync_commands', True)}\n"
                        f"Error Logging: {config.get('features.error_logging', True)}\n"
                        f"Command Logging: {config.get('features.command_logging', True)}",
                inline=False
            )
            
            embed.add_field(
                name="Database",
                value=f"Enabled: {config.get('database.enabled', False)}\n"
                        f"Host: {config.get('database.host', 'localhost')}\n"
                        f"Port: {config.get('database.port', 5432)}",
                inline=False
            )
            
            embed.add_field(
                name="System",
                value=f"Last Reload: {config.last_reload.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"Config File: {self.config_manager.config_file}",
                inline=False
            )
            
            await respond_func(embed=embed)
    
    async def _set_config_impl(self, author: Union[discord.Member, discord.User], key: str, value: str, respond_func):
        """Shared implementation for setting config values"""
        if isinstance(author, discord.Member):
            if not self.has_admin_role(author):
                await respond_func("❌ You don't have permission to modify configuration.", ephemeral=True)
                return
        elif author.id not in self.bot.owner_ids:
            await respond_func("❌ Only bot owners can modify configuration.", ephemeral=True)
            return
        
        # Parse value
        try:
            # Try to parse as JSON first
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            # If that fails, treat as string
            parsed_value = value
        
        # Set the value
        self.bot.config.set(key, parsed_value)
        
        # Save to file
        success = self.config_manager.save_config(self.bot.config.to_dict())
        
        if success:
            await respond_func(f"✅ Set `{key}` to `{parsed_value}`")
            # Apply settings if it's a bot setting
            if key.startswith('bot.'):
                self.apply_bot_settings()
        else:
            await respond_func("❌ Failed to save configuration to file.")
    
    def _create_validation_embed(self, errors: List[str]) -> discord.Embed:
        """Create embed for validation results"""
        if not errors:
            embed = discord.Embed(
                title="✅ Configuration Validation",
                description="Configuration is valid!",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="❌ Configuration Validation",
                description=f"Found {len(errors)} error(s):",
                color=discord.Color.red()
            )
            
            error_text = "\n".join(f"• {error}" for error in errors[:10])
            if len(errors) > 10:
                error_text += f"\n... and {len(errors) - 10} more errors"
            
            embed.add_field(
                name="Errors",
                value=error_text,
                inline=False
            )
        
        return embed

    # PREFIX COMMANDS
    
    @commands.group(name="config", aliases=["cfg"])
    async def config_group(self, ctx):
        """Configuration management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Configuration Commands",
                description="Available configuration management commands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="View Config",
                value="`config get [key]` - View configuration",
                inline=False
            )
            embed.add_field(
                name="Set Config",
                value="`config set <key> <value>` - Set configuration value",
                inline=False
            )
            embed.add_field(
                name="Reload Config",
                value="`config reload` - Reload from files",
                inline=False
            )
            embed.add_field(
                name="Validate Config",
                value="`config validate` - Check configuration validity",
                inline=False
            )
            embed.add_field(
                name="Backup Config",
                value="`config backup` - Create configuration backup",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @config_group.command(name="get", aliases=["show", "view"])
    async def get_config_prefix(self, ctx, *, key: Optional[str] = None):
        """Get configuration value"""
        async def respond(content=None, embed=None, ephemeral=False):
            if embed:
                await ctx.send(embed=embed)
            else:
                await ctx.send(content)
        
        await self._get_config_impl(key, respond)
    
    @config_group.command(name="set")
    async def set_config_prefix(self, ctx, key: str, *, value: str):
        """Set configuration value"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._set_config_impl(ctx.author, key, value, respond)
    
    @config_group.command(name="reload")
    async def reload_config_prefix(self, ctx):
        """Reload configuration from files"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._reload_config_impl(ctx.author, respond)
    
    @config_group.command(name="validate")
    async def validate_config_prefix(self, ctx):
        """Validate current configuration"""
        errors = self.config_manager.validate_config(self.bot.config.to_dict())
        embed = self._create_validation_embed(errors)
        await ctx.send(embed=embed)
    
    @config_group.command(name="backup")
    async def backup_config_prefix(self, ctx):
        """Create a backup of the current configuration"""
        if not self.has_admin_role(ctx.author):
            await ctx.send("❌ You don't have permission to backup configuration.")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"config_backup_{timestamp}.json"
        
        try:
            with open(backup_file, 'w') as f:
                json.dump(self.bot.config.to_dict(), f, indent=2)
            
            await ctx.send(f"✅ Configuration backed up to `{backup_file}`")
        except Exception as e:
            await ctx.send(f"❌ Failed to create backup: {e}")
    
    # @config_group.command(name="env")
    # async def show_env_vars_prefix(self, ctx):
    #     """Show available environment variables (non-sensitive)"""
    #     if not self.has_admin_role(ctx.author):
    #         await ctx.send("❌ You don't have permission to view environment variables.")
    #         return
        
    #     # Only show non-sensitive env vars
    #     safe_vars = {}
    #     sensitive_keywords = ['token', 'password', 'secret', 'key', 'auth']
        
    #     for key, value in self.bot.config._env.items():
    #         if not any(keyword in key.lower() for keyword in sensitive_keywords):
    #             safe_vars[key] = value
        
    #     if safe_vars:
    #         embed = discord.Embed(
    #             title="Environment Variables",
    #             description="Non-sensitive environment variables:",
    #             color=discord.Color.blue()
    #         )
            
    #         for key, value in list(safe_vars.items())[:10]:  # Limit to 10
    #             embed.add_field(name=key, value=str(value)[:100], inline=True)
            
    #         if len(safe_vars) > 10:
    #             embed.add_field(
    #                 name="...",
    #                 value=f"And {len(safe_vars) - 10} more variables",
    #                 inline=False
    #             )
    #     else:
    #         embed = discord.Embed(
    #             title="Environment Variables",
    #             description="No non-sensitive environment variables found.",
    #             color=discord.Color.orange()
    #         )
        
    #     await ctx.send(embed=embed)

    # SLASH COMMANDS
    
    botconfig_group = app_commands.Group(name="botconfig", description="Commands for bot configuration.")
    
    @botconfig_group.command(name="get", description="Get configuration value")
    @app_commands.describe(key="Configuration key to retrieve (optional)")
    async def get_config_slash(self, interaction: discord.Interaction, key: Optional[str] = None):
        """Get configuration value"""
        async def respond(content=None, embed=None, ephemeral=False):
            if interaction.response.is_done():
                if embed:
                    await interaction.followup.send(embed=embed, ephemeral=ephemeral)
                else:
                    await interaction.followup.send(content, ephemeral=ephemeral)
            else:
                if embed:
                    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
                else:
                    await interaction.response.send_message(content, ephemeral=ephemeral)
        
        await self._get_config_impl(key, respond)
    
    @botconfig_group.command(name="set", description="Set configuration value")
    @app_commands.describe(
        key="Configuration key to set",
        value="Value to set (JSON format supported)"
    )
    async def set_config_slash(self, interaction: discord.Interaction, key: str, value: str):
        """Set configuration value"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._set_config_impl(interaction.user, key, value, respond)
    
    @botconfig_group.command(name="reload", description="Reload configuration from files")
    async def reload_config_slash(self, interaction: discord.Interaction):
        """Reload configuration from files"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._reload_config_impl(interaction.user, respond)
    
    @botconfig_group.command(name="validate", description="Validate current configuration")
    async def validate_config_slash(self, interaction: discord.Interaction):
        """Validate current configuration"""
        errors = self.config_manager.validate_config(self.bot.config.to_dict())
        embed = self._create_validation_embed(errors)
        await interaction.response.send_message(embed=embed)
    
    @botconfig_group.command(name="backup", description="Create a backup of the current configuration")
    async def backup_config_slash(self, interaction: discord.Interaction):
        """Create a backup of the current configuration"""
        if isinstance(interaction.user, discord.Member):
            if not self.has_admin_role(interaction.user):
                await interaction.response.send_message("❌ You don't have permission to backup configuration.", ephemeral=True)
                return
        elif interaction.user.id not in self.bot.owner_ids:
            await interaction.response.send_message("❌ Only bot owners can backup configuration.", ephemeral=True)
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"config_backup_{timestamp}.json"
        
        try:
            with open(backup_file, 'w') as f:
                json.dump(self.bot.config.to_dict(), f, indent=2)
            
            await interaction.response.send_message(f"✅ Configuration backed up to `{backup_file}`")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to create backup: {e}")
    
    # @botconfig_group.command(name="env", description="Show available environment variables")
    # async def show_env_vars_slash(self, interaction: discord.Interaction):
    #     """Show available environment variables (non-sensitive)"""
    #     if isinstance(interaction.user, discord.Member):
    #         if not self.has_admin_role(interaction.user):
    #             await interaction.response.send_message("❌ You don't have permission to view environment variables.", ephemeral=True)
    #             return
    #     elif interaction.user.id not in self.bot.owner_ids:
    #         await interaction.response.send_message("❌ Only bot owners can view environment variables.", ephemeral=True)
    #         return
        
    #     # Only show non-sensitive env vars
    #     safe_vars = {}
    #     sensitive_keywords = ['token', 'password', 'secret', 'key', 'auth']
        
    #     for key, value in self.bot.config._env.items():
    #         if not any(keyword in key.lower() for keyword in sensitive_keywords):
    #             safe_vars[key] = value
        
    #     if safe_vars:
    #         embed = discord.Embed(
    #             title="Environment Variables",
    #             description="Non-sensitive environment variables:",
    #             color=discord.Color.blue()
    #         )
            
    #         for key, value in list(safe_vars.items())[:10]:  # Limit to 10
    #             embed.add_field(name=key, value=str(value)[:100], inline=True)
            
    #         if len(safe_vars) > 10:
    #             embed.add_field(
    #                 name="...",
    #                 value=f"And {len(safe_vars) - 10} more variables",
    #                 inline=False
    #             )
    #     else:
    #         embed = discord.Embed(
    #             title="Environment Variables",
    #             description="No non-sensitive environment variables found.",
    #             color=discord.Color.orange()
    #         )
        
    #     await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
