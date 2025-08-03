"""
Discord MinecraftCog - Server Management & Monitoring

OVERVIEW:
A full-featured Minecraft server management cog for Discord.  
Supports Docker Compose, Docker, and JAR servers. Start/stop/restart/status/logs, auto-restart, registration, and per-server config.  
Persistent, per-guild, and per-server storage. Both slash and prefix commands.

SETUP:
- No manual setup required – auto-creates config at src/config/minecraft_config.json
- Config: src/config/levels_config.json
- Requires: Bot must have permission to run system commands (docker, java, etc.)
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.minecraft.admin' or Administrator

COMMANDS (Slash & Prefix):
/minecraft register docker-compose <name> <compose_file> <service> [display] - Register a Docker Compose server (admin)
/minecraft register docker <name> <container> [display]                     - Register a Docker container server (admin)
/minecraft register jar <name> <jar_path> [options]                         - Register a JAR server (admin)
/minecraft servers                                                         - List all registered servers
/minecraft remove <server>                                                 - Remove a server (admin)
/minecraft set-default <server>                                            - Set default server (admin)
/minecraft start [server]                                                  - Start a server (admin)
/minecraft stop [server] [force]                                           - Stop a server (admin)
/minecraft restart [server]                                                - Restart a server (admin)
/minecraft status [server]                                                 - Show server status
/minecraft logs [server] [lines]                                           - Show server logs
/minecraft enable/disable                                                  - Enable/disable Minecraft management (admin)
/minecraft set-docker-mode [in_docker]                                     - Override Docker detection (admin)
/minecraft docker-status                                                   - Show Docker environment status

Prefix commands: !minecraft <subcommand> (same as above)

COMMAND EXPLANATIONS:
- register: Add a new Minecraft server (Docker Compose, Docker, or JAR)
- servers: List all registered servers for this guild
- remove: Remove a registered server (confirmation required)
- set-default: Set the default server for commands
- start/stop/restart: Control server state
- status: Show server status and config
- logs: Show recent server logs
- enable/disable: Enable or disable Minecraft management for this server
- set-docker-mode: Manually set Docker mode (for path mapping)
- docker-status: Show Docker detection and override info

FEATURES:
• Register/manage multiple Minecraft servers per guild
• Supports Docker Compose, Docker, and JAR servers
• Start, stop, restart, status, and logs for each server
• Auto-restart support (with alert channel)
• Per-server display names and config
• Default server for quick commands
• Docker environment detection and override
• Confirmation dialogs for destructive actions
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Persistent, per-guild config (JSON)
• Both slash and prefix command support
• Background task for auto-restart/status monitoring

USAGE BY OTHER COGS:
# Access server config or status for integrations
mc_cog = bot.get_cog('MinecraftCog')
if mc_cog:
    servers = mc_cog._get_server_names(guild.id)
    config = mc_cog._get_server_config(guild.id, servers[0])
    status = await mc_cog._get_server_status(config, guild.id)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
import subprocess
import shutil
import zipfile
import datetime
import aiofiles
import aiohttp
import psutil
import signal
from typing import Optional, Dict, List, Union
from enum import Enum
import re

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

class ServerStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"
    NOT_FOUND = "not_found"

class ServerType(Enum):
    DOCKER_COMPOSE = "docker_compose"
    DOCKER_DIRECT = "docker_direct"
    JAR = "jar"

class ConfirmationView(discord.ui.View):
    def __init__(self, timeout=30):
        super().__init__(timeout=timeout)
        self.result = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        self.stop()
        await interaction.response.send_message("✅ Action confirmed.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        self.stop()
        await interaction.response.send_message("❌ Action cancelled.", ephemeral=True)

class MinecraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = "src/config"
        
        # Ensure directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # File path
        self.minecraft_config_path = os.path.join(self.config_dir, "minecraft_config.json")
        
        # Initialize config file
        self._init_config_file()
        
        # Detect if bot is running in docker
        self._bot_in_docker = self._detect_docker_environment()
        
        # Start background tasks
        self.status_monitor.start()

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.status_monitor.cancel()

    def _detect_docker_environment(self) -> bool:
        """Detect if the bot is running inside a Docker container"""
        try:
            # Check for .dockerenv file
            if os.path.exists('/.dockerenv'):
                return True
            
            # Check cgroup for docker
            try:
                with open('/proc/1/cgroup', 'r') as f:
                    content = f.read()
                    if 'docker' in content or 'containerd' in content:
                        return True
            except (FileNotFoundError, PermissionError):
                pass
            
            # Check if we're running as PID 1 (common in containers)
            if os.getpid() == 1:
                return True
                
            return False
        except Exception:
            return False

    def _init_config_file(self):
        """Initialize config file with default settings"""
        default_config = {
            "guilds": {}
        }
        
        if not os.path.exists(self.minecraft_config_path):
            with open(self.minecraft_config_path, 'w') as f:
                json.dump(default_config, f, indent=4)

    def _load_config(self) -> dict:
        """Load Minecraft configuration from file"""
        try:
            with open(self.minecraft_config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_config_file()
            with open(self.minecraft_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save Minecraft configuration to file"""
        with open(self.minecraft_config_path, 'w') as f:
            json.dump(data, f, indent=4)

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create guild Minecraft configuration"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "enabled": True,
                "bot_in_docker": None,  # None = auto-detect, True/False = manual override
                "servers": {},
                "default_server": None,
                "alert_channel_id": None,
                "max_backups": 10
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    def _get_server_names(self, guild_id: int) -> List[str]:
        """Get list of server names for a guild"""
        guild_config = self._get_guild_config(guild_id)
        return list(guild_config.get("servers", {}).keys())

    def _get_server_config(self, guild_id: int, server_name: str) -> Optional[dict]:
        """Get server configuration"""
        guild_config = self._get_guild_config(guild_id)
        return guild_config.get("servers", {}).get(server_name)

    def _is_bot_in_docker(self, guild_id: int) -> bool:
        """Check if bot is running in docker (with guild override)"""
        guild_config = self._get_guild_config(guild_id)
        override = guild_config.get("bot_in_docker")
        if override is not None:
            return override
        return self._bot_in_docker

    async def _server_name_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for server names"""
        server_names = self._get_server_names(interaction.guild.id)
        choices = []
        for name in server_names:
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=name))
        return choices[:25]  # Discord limit

    def has_minecraft_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has Minecraft admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.minecraft.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_minecraft_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log Minecraft actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Minecraft {action}"
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
                    file_override="minecraft_cog"
                )
            except Exception as e:
                print(f"Failed to log Minecraft action: {e}")

    async def _run_command(self, command: List[str], cwd: str = None, shell: bool = False) -> tuple[bool, str]:
        """Run a command and return success status and output"""
        try:
            if shell and isinstance(command, list):
                command = ' '.join(command)
            
            if shell:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd
                )
            
            stdout, stderr = await process.communicate()
            
            success = process.returncode == 0
            output = stdout.decode() if stdout else stderr.decode()
            
            return success, output.strip()
        except Exception as e:
            return False, str(e)

    def _build_command(self, server_config: dict, action: str, guild_id: int, **kwargs) -> tuple[List[str], str, bool]:
        """Build appropriate command based on server type"""
        server_type = ServerType(server_config["type"])
        
        if server_type == ServerType.DOCKER_COMPOSE:
            return self._build_docker_compose_command(server_config, action, guild_id, **kwargs)
        elif server_type == ServerType.DOCKER_DIRECT:
            return self._build_docker_direct_command(server_config, action, guild_id, **kwargs)
        elif server_type == ServerType.JAR:
            return self._build_jar_command(server_config, action, **kwargs)
        
        raise ValueError(f"Unknown server type: {server_type}")

    def _build_docker_compose_command(self, server_config: dict, action: str, guild_id: int, **kwargs) -> tuple[List[str], str, bool]:
        """Build docker-compose command"""
        compose_file = server_config["compose_file_path"]
        service_name = server_config["service_name"]
        
        # Adjust path if bot is in docker
        if self._is_bot_in_docker(guild_id) and not os.path.isabs(compose_file):
            compose_file = f"/host/{compose_file}"
        
        base_cmd = ["docker-compose", "-f", compose_file]
        cwd = os.path.dirname(compose_file) if "/" in compose_file else "."
        
        if action == "start":
            return base_cmd + ["up", "-d", service_name], cwd, False
        elif action == "stop":
            force = kwargs.get("force", False)
            if force:
                return base_cmd + ["kill", service_name], cwd, False
            else:
                return base_cmd + ["stop", service_name], cwd, False
        elif action == "restart":
            return base_cmd + ["restart", service_name], cwd, False
        elif action == "status":
            return base_cmd + ["ps", "-q", service_name], cwd, False
        elif action == "logs":
            lines = kwargs.get("lines", 50)
            return base_cmd + ["logs", "--tail", str(lines), service_name], cwd, False
        elif action == "inspect":
            return base_cmd + ["exec", service_name, "echo", "container_running"], cwd, False
        
        raise ValueError(f"Unknown action: {action}")

    def _build_docker_direct_command(self, server_config: dict, action: str, guild_id: int, **kwargs) -> tuple[List[str], str, bool]:
        """Build direct docker command"""
        container_name = server_config["container_name"]
        
        if action == "start":
            return ["docker", "start", container_name], None, False
        elif action == "stop":
            force = kwargs.get("force", False)
            if force:
                return ["docker", "kill", container_name], None, False
            else:
                return ["docker", "stop", container_name], None, False
        elif action == "restart":
            return ["docker", "restart", container_name], None, False
        elif action == "status":
            return ["docker", "inspect", "--format={{.State.Status}}", container_name], None, False
        elif action == "logs":
            lines = kwargs.get("lines", 50)
            return ["docker", "logs", "--tail", str(lines), container_name], None, False
        elif action == "inspect":
            return ["docker", "inspect", "--format={{.State.Status}}", container_name], None, False
        
        raise ValueError(f"Unknown action: {action}")

    def _build_jar_command(self, server_config: dict, action: str, **kwargs) -> tuple[List[str], str, bool]:
        """Build JAR command"""
        working_dir = server_config.get("working_directory", os.path.dirname(server_config["jar_path"]))
        
        if action == "start":
            start_cmd = server_config.get("start_command", f"java -jar {os.path.basename(server_config['jar_path'])}")
            return start_cmd.split(), working_dir, True
        elif action == "stop":
            # For JAR servers, we need to find and kill the process
            process_name = server_config.get("process_name", "java")
            return ["pkill", "-f", process_name], None, False
        elif action == "restart":
            # Stop then start for JAR
            return None, None, False  # Special handling needed
        elif action == "status":
            process_name = server_config.get("process_name", "java")
            return ["pgrep", "-f", process_name], None, False
        elif action == "logs":
            log_file = server_config.get("log_file", os.path.join(working_dir, "logs/latest.log"))
            lines = kwargs.get("lines", 50)
            return ["tail", "-n", str(lines), log_file], None, False
        
        raise ValueError(f"Unknown action: {action}")

    async def _get_server_status(self, server_config: dict, guild_id: int) -> ServerStatus:
        """Get the status of a server"""
        try:
            server_type = ServerType(server_config["type"])
            
            if server_type in [ServerType.DOCKER_COMPOSE, ServerType.DOCKER_DIRECT]:
                command, cwd, shell = self._build_command(server_config, "status", guild_id)
                success, output = await self._run_command(command, cwd, shell)
                
                if not success:
                    if "No such" in output or "not found" in output:
                        return ServerStatus.NOT_FOUND
                    return ServerStatus.ERROR
                
                if server_type == ServerType.DOCKER_COMPOSE:
                    if output.strip():
                        exec_cmd, exec_cwd, exec_shell = self._build_command(server_config, "inspect", guild_id)
                        exec_success, _ = await self._run_command(exec_cmd, exec_cwd, exec_shell)
                        return ServerStatus.RUNNING if exec_success else ServerStatus.STOPPED
                    else:
                        return ServerStatus.STOPPED
                else:
                    status_map = {
                        "running": ServerStatus.RUNNING,
                        "exited": ServerStatus.STOPPED,
                        "paused": ServerStatus.STOPPED,
                        "restarting": ServerStatus.STARTING,
                        "removing": ServerStatus.STOPPING,
                        "dead": ServerStatus.ERROR
                    }
                    return status_map.get(output.lower(), ServerStatus.ERROR)
                    
            elif server_type == ServerType.JAR:
                command, cwd, shell = self._build_command(server_config, "status", guild_id)
                success, output = await self._run_command(command, cwd, shell)
                
                if success and output.strip():
                    return ServerStatus.RUNNING
                else:
                    return ServerStatus.STOPPED
                    
        except Exception as e:
            print(f"Error getting server status: {e}")
            return ServerStatus.ERROR

    async def _start_server(self, server_config: dict, guild_id: int) -> tuple[bool, str]:
        """Start a server"""
        server_type = ServerType(server_config["type"])
        
        if server_type == ServerType.JAR:
            # For JAR servers, we need to start in background
            try:
                working_dir = server_config.get("working_directory", os.path.dirname(server_config["jar_path"]))
                start_cmd = server_config.get("start_command", f"java -jar {os.path.basename(server_config['jar_path'])}")
                
                # Start process in background
                process = await asyncio.create_subprocess_shell(
                    start_cmd,
                    cwd=working_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    stdin=asyncio.subprocess.DEVNULL
                )
                
                # Give it a moment to start
                await asyncio.sleep(2)
                
                # Check if it's running
                status = await self._get_server_status(server_config, guild_id)
                if status == ServerStatus.RUNNING:
                    return True, f"JAR server started with PID {process.pid}"
                else:
                    return False, "JAR server failed to start properly"
                    
            except Exception as e:
                return False, f"Failed to start JAR server: {str(e)}"
        else:
            command, cwd, shell = self._build_command(server_config, "start", guild_id)
            return await self._run_command(command, cwd, shell)

    async def _stop_server(self, server_config: dict, guild_id: int, force: bool = False) -> tuple[bool, str]:
        """Stop a server"""
        server_type = ServerType(server_config["type"])
        
        if server_type == ServerType.JAR:
            try:
                process_name = server_config.get("process_name", "java")
                
                if force:
                    # Force kill
                    success, output = await self._run_command(["pkill", "-9", "-f", process_name])
                else:
                    # Graceful stop
                    if "stop_command" in server_config:
                        # Custom stop command
                        working_dir = server_config.get("working_directory", os.path.dirname(server_config["jar_path"]))
                        stop_cmd = server_config["stop_command"]
                        success, output = await self._run_command(stop_cmd.split(), working_dir, True)
                    else:
                        # Send SIGTERM
                        success, output = await self._run_command(["pkill", "-TERM", "-f", process_name])
                
                return success, output
                
            except Exception as e:
                return False, f"Failed to stop JAR server: {str(e)}"
        else:
            command, cwd, shell = self._build_command(server_config, "stop", guild_id, force=force)
            return await self._run_command(command, cwd, shell)

    async def _restart_server(self, server_config: dict, guild_id: int) -> tuple[bool, str]:
        """Restart a server"""
        server_type = ServerType(server_config["type"])
        
        if server_type == ServerType.JAR:
            # For JAR, stop then start
            stop_success, stop_output = await self._stop_server(server_config, guild_id)
            if not stop_success:
                return False, f"Failed to stop: {stop_output}"
            
            # Wait a moment
            await asyncio.sleep(3)
            
            start_success, start_output = await self._start_server(server_config, guild_id)
            if not start_success:
                return False, f"Failed to start: {start_output}"
            
            return True, "JAR server restarted successfully"
        else:
            command, cwd, shell = self._build_command(server_config, "restart", guild_id)
            return await self._run_command(command, cwd, shell)

    async def _get_server_logs(self, server_config: dict, guild_id: int, lines: int = 50) -> tuple[bool, str]:
        """Get server logs"""
        try:
            command, cwd, shell = self._build_command(server_config, "logs", guild_id, lines=lines)
            return await self._run_command(command, cwd, shell)
        except Exception as e:
            return False, str(e)

    def _is_enabled(self, guild_id: int) -> bool:
        """Check if Minecraft cog is enabled for a guild"""
        guild_config = self._get_guild_config(guild_id)
        return guild_config.get("enabled", True)

    async def _check_enabled(self, ctx_or_interaction) -> bool:
        """Check if cog is enabled and respond if not"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self._is_enabled(guild.id):
            await respond("❌ Minecraft server management is currently disabled in this server.", ephemeral=True)
            return False
        return True

    @tasks.loop(minutes=5)
    async def status_monitor(self):
        """Monitor server status and send alerts"""
        try:
            config = self._load_config()
            for guild_id_str, guild_config in config["guilds"].items():
                if not guild_config.get("enabled", True):
                    continue
                
                guild_id = int(guild_id_str)
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                
                for server_name, server_config in guild_config.get("servers", {}).items():
                    if not server_config.get("auto_restart", False):
                        continue
                    
                    status = await self._get_server_status(server_config, guild_id)
                    
                    if status == ServerStatus.STOPPED:
                        await self.log_minecraft_action("auto_restart_triggered", guild, None, f"Server: {server_name}")
                        
                        success, output = await self._start_server(server_config, guild_id)
                        if success:
                            await self._send_alert(guild_id, f"🔄 **Auto-restart**: Minecraft server `{server_name}` has been automatically restarted.")
                        else:
                            await self._send_alert(guild_id, f"❌ **Auto-restart failed**: Could not restart `{server_name}`: {output}")
        
        except Exception as e:
            print(f"Status monitor error: {e}")

    @status_monitor.before_loop
    async def before_status_monitor(self):
        await self.bot.wait_until_ready()

    async def _send_alert(self, guild_id: int, message: str, embed: discord.Embed = None):
        """Send alert to configured alert channel"""
        guild_config = self._get_guild_config(guild_id)
        alert_channel_id = guild_config.get("alert_channel_id")
        
        if not alert_channel_id:
            return
        
        channel = self.bot.get_channel(alert_channel_id)
        if not channel:
            return
        
        try:
            if embed:
                await channel.send(message, embed=embed)
            else:
                await channel.send(message)
        except Exception:
            pass

    # ==================== SLASH COMMAND GROUPS ====================
    minecraft_group = app_commands.Group(name="minecraft", description="Minecraft server management commands")
    register_group = app_commands.Group(name="register", description="Register Minecraft servers", parent=minecraft_group)

    @register_group.command(name="docker-compose", description="Register a Docker Compose Minecraft server")
    @app_commands.describe(
        name="Server name (used to identify this server)",
        compose_file="Path to docker-compose.yml file",
        service_name="Service name in the compose file",
        display_name="Display name for the server (optional)"
    )
    async def register_compose_slash(self, interaction: discord.Interaction, name: str, compose_file: str, service_name: str, display_name: str = None):
        """Register a Docker Compose server"""
        await self._register_server(interaction, name, ServerType.DOCKER_COMPOSE, {
            "compose_file_path": compose_file,
            "service_name": service_name,
            "display_name": display_name or name
        })

    @register_group.command(name="docker", description="Register a direct Docker Minecraft server")
    @app_commands.describe(
        name="Server name (used to identify this server)",
        container_name="Docker container name",
        display_name="Display name for the server (optional)"
    )
    async def register_docker_slash(self, interaction: discord.Interaction, name: str, container_name: str, display_name: str = None):
        """Register a direct Docker server"""
        await self._register_server(interaction, name, ServerType.DOCKER_DIRECT, {
            "container_name": container_name,
            "display_name": display_name or name
        })

    @register_group.command(name="jar", description="Register a JAR-based Minecraft server")
    @app_commands.describe(
        name="Server name (used to identify this server)",
        jar_path="Path to the server JAR file",
        start_command="Custom start command (optional, defaults to 'java -jar filename.jar')",
        stop_command="Custom stop command (optional)",
        working_directory="Working directory (optional, defaults to JAR directory)",
        process_name="Process name to search for (optional, defaults to 'java')",
        display_name="Display name for the server (optional)"
    )
    async def register_jar_slash(self, interaction: discord.Interaction, name: str, jar_path: str, 
                                start_command: str = None, stop_command: str = None, 
                                working_directory: str = None, process_name: str = None, 
                                display_name: str = None):
        """Register a JAR server"""
        config_data = {
            "jar_path": jar_path,
            "display_name": display_name or name
        }
        
        if start_command:
            config_data["start_command"] = start_command
        if stop_command:
            config_data["stop_command"] = stop_command
        if working_directory:
            config_data["working_directory"] = working_directory
        if process_name:
            config_data["process_name"] = process_name
            
        await self._register_server(interaction, name, ServerType.JAR, config_data)

    @minecraft_group.command(name="servers", description="List all registered servers")
    async def list_servers_slash(self, interaction: discord.Interaction):
        """List registered servers"""
        await self._list_servers(interaction)

    @minecraft_group.command(name="remove", description="Remove a registered server")
    @app_commands.describe(server="Server to remove")
    @app_commands.autocomplete(server=_server_name_autocomplete)
    async def remove_server_slash(self, interaction: discord.Interaction, server: str):
        """Remove a server"""
        await self._remove_server(interaction, server)

    @minecraft_group.command(name="set-default", description="Set the default server")
    @app_commands.describe(server="Server to set as default")
    @app_commands.autocomplete(server=_server_name_autocomplete)
    async def set_default_slash(self, interaction: discord.Interaction, server: str):
        """Set default server"""
        await self._set_default_server(interaction, server)

    @minecraft_group.command(name="start", description="Start a Minecraft server")
    @app_commands.describe(server="Server to start (optional, uses default if not specified)")
    @app_commands.autocomplete(server=_server_name_autocomplete)
    async def start_slash(self, interaction: discord.Interaction, server: str = None):
        """Start a server"""
        if not await self._check_enabled(interaction):
            return
        await self._start_server_cmd(interaction, server)

    @minecraft_group.command(name="stop", description="Stop a Minecraft server")
    @app_commands.describe(
        server="Server to stop (optional, uses default if not specified)",
        force="Force stop without graceful shutdown"
    )
    @app_commands.autocomplete(server=_server_name_autocomplete)
    async def stop_slash(self, interaction: discord.Interaction, server: str = None, force: bool = False):
        """Stop a server"""
        if not await self._check_enabled(interaction):
            return
        await self._stop_server_cmd(interaction, server, force)

    @minecraft_group.command(name="restart", description="Restart a Minecraft server")
    @app_commands.describe(server="Server to restart (optional, uses default if not specified)")
    @app_commands.autocomplete(server=_server_name_autocomplete)
    async def restart_slash(self, interaction: discord.Interaction, server: str = None):
        """Restart a server"""
        if not await self._check_enabled(interaction):
            return
        await self._restart_server_cmd(interaction, server)

    @minecraft_group.command(name="status", description="Check Minecraft server status")
    @app_commands.describe(server="Server to check (optional, uses default if not specified)")
    @app_commands.autocomplete(server=_server_name_autocomplete)
    async def status_slash(self, interaction: discord.Interaction, server: str = None):
        """Check server status"""
        if not await self._check_enabled(interaction):
            return
        await self._status_cmd(interaction, server)

    @minecraft_group.command(name="logs", description="View Minecraft server logs")
    @app_commands.describe(
        server="Server to view logs for (optional, uses default if not specified)",
        lines="Number of log lines to display (default: 50)"
    )
    @app_commands.autocomplete(server=_server_name_autocomplete)
    async def logs_slash(self, interaction: discord.Interaction, server: str = None, lines: int = 50):
        """View server logs"""
        if not await self._check_enabled(interaction):
            return
        await self._logs_cmd(interaction, server, lines)

    @minecraft_group.command(name="enable", description="Enable Minecraft server management")
    async def enable_slash(self, interaction: discord.Interaction):
        """Enable Minecraft management"""
        await self._toggle_minecraft(interaction, True)

    @minecraft_group.command(name="disable", description="Disable Minecraft server management")
    async def disable_slash(self, interaction: discord.Interaction):
        """Disable Minecraft management"""
        await self._toggle_minecraft(interaction, False)

    @minecraft_group.command(name="set-docker-mode", description="Override Docker environment detection")
    @app_commands.describe(in_docker="Whether the bot is running in Docker (None for auto-detect)")
    async def set_docker_mode_slash(self, interaction: discord.Interaction, in_docker: bool = None):
        """Set Docker mode"""
        await self._set_docker_mode(interaction, in_docker)

    @minecraft_group.command(name="docker-status", description="Check Docker environment status")
    async def docker_status_slash(self, interaction: discord.Interaction):
        """Check Docker status"""
        await self._docker_status(interaction)

    # ==================== IMPLEMENTATION METHODS ====================
    
    async def _register_server(self, ctx_or_interaction, name: str, server_type: ServerType, config_data: dict):
        """Register a new server"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to register Minecraft servers.", ephemeral=True)
            return

        # Validate server name
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            await respond("❌ Server name can only contain letters, numbers, hyphens, and underscores.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if name in guild_config.get("servers", {}):
            await respond(f"❌ A server named `{name}` already exists.", ephemeral=True)
            return

        # Build full server config
        server_config = {
            "type": server_type.value,
            "backup_enabled": True,
            "backup_path": f"/backups/minecraft/{name}",
            "auto_restart": False,
            **config_data
        }

        # Initialize servers dict if it doesn't exist
        if "servers" not in guild_config:
            guild_config["servers"] = {}

        guild_config["servers"][name] = server_config
        
        # Set as default if it's the first server
        if not guild_config.get("default_server"):
            guild_config["default_server"] = name

        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        # Log the action
        await self.log_minecraft_action("server_registered", guild, member, f"Name: {name} - Type: {server_type.value}")

        embed = discord.Embed(
            title="✅ Server Registered",
            description=f"Minecraft server `{name}` has been registered successfully!",
            color=discord.Color.green()
        )
        embed.add_field(name="Type", value=server_type.value.replace('_', ' ').title(), inline=True)
        embed.add_field(name="Display Name", value=config_data.get("display_name", name), inline=True)
        
        if guild_config["default_server"] == name:
            embed.add_field(name="Default Server", value="✅ Set as default", inline=True)

        await respond(embed=embed)

    async def _list_servers(self, ctx_or_interaction):
        """List all registered servers"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        guild_config = self._get_guild_config(guild.id)
        servers = guild_config.get("servers", {})
        default_server = guild_config.get("default_server")

        if not servers:
            embed = discord.Embed(
                title="📋 Registered Servers",
                description="No servers are currently registered.\nUse `/minecraft register` commands to add servers.",
                color=discord.Color.blue()
            )
            await respond(embed=embed)
            return

        embed = discord.Embed(
            title="📋 Registered Servers",
            description=f"Total servers: {len(servers)}",
            color=discord.Color.blue()
        )

        for server_name, server_config in servers.items():
            server_type = ServerType(server_config["type"])
            display_name = server_config.get("display_name", server_name)
            
            # Build type-specific info
            if server_type == ServerType.DOCKER_COMPOSE:
                type_info = f"🐳 Compose: `{server_config['service_name']}`"
            elif server_type == ServerType.DOCKER_DIRECT:
                type_info = f"🐳 Docker: `{server_config['container_name']}`"
            elif server_type == ServerType.JAR:
                type_info = f"☕ JAR: `{os.path.basename(server_config['jar_path'])}`"
            
            # Add default indicator
            if server_name == default_server:
                type_info += " ⭐ (Default)"
            
            embed.add_field(
                name=display_name,
                value=f"**Name:** `{server_name}`\n**Type:** {type_info}",
                inline=True
            )

        await respond(embed=embed)

    async def _remove_server(self, ctx_or_interaction, server_name: str):
        """Remove a server"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to remove Minecraft servers.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if server_name not in guild_config.get("servers", {}):
            await respond(f"❌ Server `{server_name}` not found.", ephemeral=True)
            return

        # Confirmation
        view = ConfirmationView()
        embed = discord.Embed(
            title="⚠️ Remove Server Confirmation",
            description=f"Are you sure you want to remove server `{server_name}`?\nThis action cannot be undone.",
            color=discord.Color.orange()
        )
        await respond(embed=embed, view=view, ephemeral=True)
        
        await view.wait()
        if view.result is None or not view.result:
            return

        # Remove server
        del guild_config["servers"][server_name]
        
        # Update default if needed
        if guild_config.get("default_server") == server_name:
            remaining_servers = list(guild_config["servers"].keys())
            guild_config["default_server"] = remaining_servers[0] if remaining_servers else None

        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        # Log the action
        await self.log_minecraft_action("server_removed", guild, member, f"Name: {server_name}")

        embed = discord.Embed(
            title="✅ Server Removed",
            description=f"Server `{server_name}` has been removed successfully.",
            color=discord.Color.green()
        )
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

    async def _set_default_server(self, ctx_or_interaction, server_name: str):
        """Set default server"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to configure Minecraft settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        if server_name not in guild_config.get("servers", {}):
            await respond(f"❌ Server `{server_name}` not found.", ephemeral=True)
            return

        old_default = guild_config.get("default_server")
        guild_config["default_server"] = server_name
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        # Log the action
        await self.log_minecraft_action("default_server_changed", guild, member, f"From: {old_default} - To: {server_name}")

        embed = discord.Embed(
            title="✅ Default Server Updated",
            description=f"Default server has been set to `{server_name}`",
            color=discord.Color.green()
        )

        await respond(embed=embed)

    def _resolve_server_name(self, guild_id: int, server_name: str = None) -> str:
        """Resolve server name to use (provided or default)"""
        if server_name:
            return server_name
        
        guild_config = self._get_guild_config(guild_id)
        default_server = guild_config.get("default_server")
        
        if not default_server:
            raise ValueError("No server specified and no default server set")
        
        return default_server

    async def _start_server_cmd(self, ctx_or_interaction, server_name: str = None):
        """Start server command implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to control Minecraft servers.", ephemeral=True)
            return

        try:
            server_name = self._resolve_server_name(guild.id, server_name)
        except ValueError as e:
            await respond(f"❌ {str(e)}", ephemeral=True)
            return

        server_config = self._get_server_config(guild.id, server_name)
        if not server_config:
            await respond(f"❌ Server `{server_name}` not found.", ephemeral=True)
            return

        # Check current status
        status = await self._get_server_status(server_config, guild.id)
        
        if status == ServerStatus.RUNNING:
            await respond(f"⚠️ Server `{server_name}` is already running!", ephemeral=True)
            return
        elif status == ServerStatus.NOT_FOUND:
            await respond(f"❌ Server `{server_name}` not found. Please check the configuration.", ephemeral=True)
            return

        # Send initial response
        display_name = server_config.get("display_name", server_name)
        embed = discord.Embed(
            title="🔄 Starting Minecraft Server",
            description=f"Starting `{display_name}`...",
            color=discord.Color.blue()
        )
        await respond(embed=embed)

        # Start the server
        success, output = await self._start_server(server_config, guild.id)

        # Log the action
        await self.log_minecraft_action("server_started" if success else "server_start_failed", guild, member, f"Server: {server_name} - Output: {output}")

        # Update response
        if success:
            embed = discord.Embed(
                title="✅ Minecraft Server Started",
                description=f"`{display_name}` has been started successfully!",
                color=discord.Color.green()
            )
            await self._send_alert(guild.id, f"🟢 **Server Started**: `{display_name}` is now running.")
        else:
            embed = discord.Embed(
                title="❌ Failed to Start Server",
                description=f"Failed to start `{display_name}`:\n```{output}```",
                color=discord.Color.red()
            )

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.edit_original_response(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

    async def _stop_server_cmd(self, ctx_or_interaction, server_name: str = None, force: bool = False):
        """Stop server command implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to control Minecraft servers.", ephemeral=True)
            return

        try:
            server_name = self._resolve_server_name(guild.id, server_name)
        except ValueError as e:
            await respond(f"❌ {str(e)}", ephemeral=True)
            return

        server_config = self._get_server_config(guild.id, server_name)
        if not server_config:
            await respond(f"❌ Server `{server_name}` not found.", ephemeral=True)
            return

        # Check current status
        status = await self._get_server_status(server_config, guild.id)
        
        if status == ServerStatus.STOPPED:
            await respond(f"⚠️ Server `{server_name}` is already stopped!", ephemeral=True)
            return
        elif status == ServerStatus.NOT_FOUND:
            await respond(f"❌ Server `{server_name}` not found. Please check the configuration.", ephemeral=True)
            return

        display_name = server_config.get("display_name", server_name)

        # Confirmation for force stop
        if force:
            view = ConfirmationView()
            embed = discord.Embed(
                title="⚠️ Force Stop Confirmation",
                description=f"Are you sure you want to **force stop** `{display_name}`?\nThis may cause data loss!",
                color=discord.Color.orange()
            )
            await respond(embed=embed, view=view, ephemeral=True)
            
            await view.wait()
            if view.result is None or not view.result:
                return

        # Send initial response
        embed = discord.Embed(
            title="🔄 Stopping Minecraft Server",
            description=f"Stopping `{display_name}`{'(forced)' if force else ''}...",
            color=discord.Color.blue()
        )
        
        if not force:
            await respond(embed=embed)

        # Stop the server
        success, output = await self._stop_server(server_config, guild.id, force)

        # Log the action
        action_type = "server_force_stopped" if force else "server_stopped"
        await self.log_minecraft_action(action_type if success else f"{action_type}_failed", guild, member, f"Server: {server_name} - Output: {output}")

        # Update response
        if success:
            embed = discord.Embed(
                title="✅ Minecraft Server Stopped",
                description=f"`{display_name}` has been stopped successfully!",
                color=discord.Color.green()
            )
            await self._send_alert(guild.id, f"🔴 **Server Stopped**: `{display_name}` has been stopped{'(forced)' if force else ''}.")
        else:
            embed = discord.Embed(
                title="❌ Failed to Stop Server",
                description=f"Failed to stop `{display_name}`:\n```{output}```",
                color=discord.Color.red()
            )

        if force:
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)
        else:
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.edit_original_response(embed=embed)
            else:
                await ctx_or_interaction.send(embed=embed)

    async def _restart_server_cmd(self, ctx_or_interaction, server_name: str = None):
        """Restart server command implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to control Minecraft servers.", ephemeral=True)
            return

        try:
            server_name = self._resolve_server_name(guild.id, server_name)
        except ValueError as e:
            await respond(f"❌ {str(e)}", ephemeral=True)
            return

        server_config = self._get_server_config(guild.id, server_name)
        if not server_config:
            await respond(f"❌ Server `{server_name}` not found.", ephemeral=True)
            return

        # Check current status
        status = await self._get_server_status(server_config, guild.id)
        
        if status == ServerStatus.NOT_FOUND:
            await respond(f"❌ Server `{server_name}` not found. Please check the configuration.", ephemeral=True)
            return

        display_name = server_config.get("display_name", server_name)

        # Send initial response
        embed = discord.Embed(
            title="🔄 Restarting Minecraft Server",
            description=f"Restarting `{display_name}`...",
            color=discord.Color.blue()
        )
        await respond(embed=embed)

        # Restart the server
        success, output = await self._restart_server(server_config, guild.id)

        # Log the action
        await self.log_minecraft_action("server_restarted" if success else "server_restart_failed", guild, member, f"Server: {server_name} - Output: {output}")

        # Update response
        if success:
            embed = discord.Embed(
                title="✅ Minecraft Server Restarted",
                description=f"`{display_name}` has been restarted successfully!",
                color=discord.Color.green()
            )
            await self._send_alert(guild.id, f"🔄 **Server Restarted**: `{display_name}` has been restarted.")
        else:
            embed = discord.Embed(
                title="❌ Failed to Restart Server",
                description=f"Failed to restart `{display_name}`:\n```{output}```",
                color=discord.Color.red()
            )

        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.edit_original_response(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

    async def _status_cmd(self, ctx_or_interaction, server_name: str = None):
        """Status command implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        try:
            server_name = self._resolve_server_name(guild.id, server_name)
        except ValueError as e:
            await respond(f"❌ {str(e)}", ephemeral=True)
            return

        server_config = self._get_server_config(guild.id, server_name)
        if not server_config:
            await respond(f"❌ Server `{server_name}` not found.", ephemeral=True)
            return

        # Get status
        status = await self._get_server_status(server_config, guild.id)
        display_name = server_config.get("display_name", server_name)
        server_type = ServerType(server_config["type"])

        # Create status embed
        embed = discord.Embed(
            title="🟫 Minecraft Server Status",
            color=discord.Color.green() if status == ServerStatus.RUNNING else discord.Color.red()
        )

        # Status info
        status_text = {
            ServerStatus.RUNNING: "🟢 Running",
            ServerStatus.STOPPED: "🔴 Stopped", 
            ServerStatus.STARTING: "🟡 Starting",
            ServerStatus.STOPPING: "🟡 Stopping",
            ServerStatus.ERROR: "❌ Error",
            ServerStatus.NOT_FOUND: "❓ Not Found"
        }

        embed.add_field(
            name="Server Information",
            value=f"**Name:** `{server_name}`\n**Display Name:** {display_name}\n**Status:** {status_text[status]}\n**Type:** {server_type.value.replace('_', ' ').title()}",
            inline=False
        )

        # Type-specific info
        if server_type == ServerType.DOCKER_COMPOSE:
            embed.add_field(
                name="Docker Compose Configuration",
                value=f"**Compose File:** `{server_config['compose_file_path']}`\n**Service:** `{server_config['service_name']}`",
                inline=True
            )
        elif server_type == ServerType.DOCKER_DIRECT:
            embed.add_field(
                name="Docker Configuration",
                value=f"**Container:** `{server_config['container_name']}`",
                inline=True
            )
        elif server_type == ServerType.JAR:
            embed.add_field(
                name="JAR Configuration",
                value=f"**JAR Path:** `{server_config['jar_path']}`\n**Working Dir:** `{server_config.get('working_directory', 'Auto')}`",
                inline=True
            )

        # Settings
        embed.add_field(
            name="Settings",
            value=f"**Backup Enabled:** {'Yes' if server_config.get('backup_enabled', True) else 'No'}\n**Auto-restart:** {'Yes' if server_config.get('auto_restart', False) else 'No'}",
            inline=True
        )

        embed.timestamp = datetime.datetime.now()
        embed.set_footer(text="Status checked at")

        await respond(embed=embed)

    async def _logs_cmd(self, ctx_or_interaction, server_name: str = None, lines: int = 50):
        """Logs command implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        try:
            server_name = self._resolve_server_name(guild.id, server_name)
        except ValueError as e:
            await respond(f"❌ {str(e)}", ephemeral=True)
            return

        server_config = self._get_server_config(guild.id, server_name)
        if not server_config:
            await respond(f"❌ Server `{server_name}` not found.", ephemeral=True)
            return

        display_name = server_config.get("display_name", server_name)

        # Limit lines to reasonable amount
        lines = max(1, min(lines, 100))

        # Get logs
        success, logs = await self._get_server_logs(server_config, guild.id, lines)

        if not success:
            embed = discord.Embed(
                title="❌ Failed to Get Logs",
                description=f"Could not retrieve logs from `{display_name}`:\n```{logs}```",
                color=discord.Color.red()
            )
            await respond(embed=embed, ephemeral=True)
            return

        # Prepare logs for display
        if not logs.strip():
            logs = "No logs available"

        # Truncate if too long
        if len(logs) > 1900:
            logs = logs[-1900:] + "\n... (truncated)"

        embed = discord.Embed(
            title=f"📋 Server Logs (Last {lines} lines)",
            description=f"```{logs}```",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Server: {display_name}")

        await respond(embed=embed, ephemeral=True)

    async def _toggle_minecraft(self, ctx_or_interaction, enabled: bool):
        """Toggle Minecraft management on/off"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to configure Minecraft settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        guild_config["enabled"] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        # Log the toggle action
        action = "enabled" if enabled else "disabled"
        await self.log_minecraft_action(f"cog_{action}", guild, member, f"Minecraft management {action}")
        
        status = "enabled" if enabled else "disabled"
        embed = discord.Embed(
            title=f"✅ Minecraft Management {status.title()}",
            description=f"Minecraft server management has been {status} for this server.",
            color=discord.Color.green() if enabled else discord.Color.red()
        )
        
        await respond(embed=embed)

    async def _set_docker_mode(self, ctx_or_interaction, in_docker: bool = None):
        """Set Docker mode override"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_minecraft_admin_permission(member):
            await respond("❌ You don't have permission to configure Minecraft settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        old_mode = guild_config.get("bot_in_docker")
        guild_config["bot_in_docker"] = in_docker
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        # Log the action
        await self.log_minecraft_action("docker_mode_changed", guild, member, f"From: {old_mode} - To: {in_docker}")

        if in_docker is None:
            mode_text = f"Auto-detect (Currently: {'In Docker' if self._bot_in_docker else 'Host System'})"
        else:
            mode_text = "In Docker" if in_docker else "Host System"

        embed = discord.Embed(
            title="✅ Docker Mode Updated",
            description=f"Docker environment mode set to: **{mode_text}**",
            color=discord.Color.green()
        )

        await respond(embed=embed)

    async def _docker_status(self, ctx_or_interaction):
        """Check Docker environment status"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        guild_config = self._get_guild_config(guild.id)
        override = guild_config.get("bot_in_docker")
        detected = self._bot_in_docker
        effective = self._is_bot_in_docker(guild.id)

        embed = discord.Embed(
            title="🐳 Docker Environment Status",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="Detection Status",
            value=f"**Auto-detected:** {'In Docker' if detected else 'Host System'}\n**Override:** {override if override is not None else 'None (Auto-detect)'}\n**Effective Mode:** {'In Docker' if effective else 'Host System'}",
            inline=False
        )

        # Show detection methods
        detection_info = []
        if os.path.exists('/.dockerenv'):
            detection_info.append("✅ .dockerenv file found")
        else:
            detection_info.append("❌ .dockerenv file not found")

        try:
            with open('/proc/1/cgroup', 'r') as f:
                content = f.read()
                if 'docker' in content or 'containerd' in content:
                    detection_info.append("✅ Docker/containerd in cgroup")
                else:
                    detection_info.append("❌ No container runtime in cgroup")
        except (FileNotFoundError, PermissionError):
            detection_info.append("⚠️ Cannot read /proc/1/cgroup")

        if os.getpid() == 1:
            detection_info.append("✅ Running as PID 1")
        else:
            detection_info.append(f"❌ Running as PID {os.getpid()}")

        embed.add_field(
            name="Detection Methods",
            value="\n".join(detection_info),
            inline=False
        )

        await respond(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(MinecraftCog(bot))