"""
Discord TicketSystemCog - Advanced Ticket & Support System

OVERVIEW:
A full-featured ticket system for Discord servers.  
Supports multiple ticket types, panels, custom categories, ping roles/users, cooldowns, auto-close, logging, and both slash and prefix commands.

SETUP:
- No manual setup required – auto-creates config/database files:
- Config: src/config/ticket_config.json
- Database: src/database/ticket_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.tickets.admin' or Administrator

COMMANDS (Slash & Prefix):
/ticket toggle <on/off>                - Enable/disable the ticket system (admin)
/ticket status                         - Show if ticket system is enabled
/ticket type-create <name>             - Create a new ticket type (admin)
/ticket type-delete <name>             - Delete a ticket type (admin)
/ticket type-set-category <name> <cat> - Set category for a ticket type (admin)
/ticket type-copy-channel <name> <chan>- Copy channel permissions for a ticket type (admin)
/ticket type-add-ping-role <name> <role>   - Add ping role for a ticket type (admin)
/ticket type-add-ping-user <name> <user>   - Add ping user for a ticket type (admin)
/ticket type-remove-ping-role <name> <role> - Remove ping role (admin)
/ticket type-remove-ping-user <name> <user> - Remove ping user (admin)
/ticket panel-send <type> <channel>    - Send a ticket panel (admin)
/ticket create <type> [content]        - Create a ticket manually
/ticket close [id] [reason]            - Close a ticket

Prefix commands: !ticket <subcommand> (same as above)

COMMAND EXPLANATIONS:
- toggle/status: Enable/disable or check ticket system status.
- type-create/delete: Add or remove ticket types.
- type-set-category/copy-channel: Set category or copy permissions for ticket type.
- type-add/remove-ping-role/user: Configure who gets pinged on ticket creation.
- panel-send: Send a panel with a button to create tickets.
- create: Manually create a ticket.
- close: Close a ticket (by ID or in current channel).

FEATURES:
• Multiple ticket types with custom categories, welcome messages, ping roles/users
• Ticket panels with persistent buttons and dropdowns
• Cooldown and max open tickets per user
• Auto-close inactive tickets after configurable hours
• DM notifications for ticket creation/closure (configurable)
• Staff role support for ticket access
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Persistent, per-guild config and ticket data (JSON)
• Both slash and prefix command support
• Activity tracking and message history per ticket

USAGE BY OTHER COGS:
# Access ticket config or ticket data for integrations
tickets_cog = bot.get_cog('TicketSystemCog')
if tickets_cog:
    config = tickets_cog._load_config()
    db = tickets_cog._load_db()
    open_tickets = [t for t in db["tickets"].values() if t["guild_id"] == guild.id and t["status"] == "open"]
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
from typing import Union, Dict, List
from datetime import datetime, timedelta
import uuid
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

class TicketView(discord.ui.View):
    def __init__(self, cog, ticket_types: Dict[str, dict]):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_types = ticket_types
        
        # Add buttons for each ticket type with persistent custom_ids
        for ticket_type, config in ticket_types.items():
            button = discord.ui.Button(
                label=config.get("button_label", ticket_type),
                emoji=config.get("button_emoji"),
                style=discord.ButtonStyle.primary,
                custom_id=f"ticket_create_{ticket_type}_{hash(ticket_type) % 10000}"
            )
            button.callback = self.create_ticket_callback
            self.add_item(button)

    async def create_ticket_callback(self, interaction: discord.Interaction):
        """Handle ticket creation from button click"""
        custom_id = interaction.data["custom_id"]
        # Extract ticket type from custom_id
        parts = custom_id.split("_")
        if len(parts) >= 3:
            ticket_type = "_".join(parts[2:-1])  # Remove "ticket_create_" and the hash
        else:
            ticket_type = parts[2] if len(parts) > 2 else "unknown"
        
        await self.cog._handle_ticket_creation(interaction, ticket_type)

class TicketControlView(discord.ui.View):
    def __init__(self, cog, ticket_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Close ticket button"""
        await interaction.response.send_modal(CloseTicketModal(self.cog, self.ticket_id))

    @discord.ui.button(label="Add User", style=discord.ButtonStyle.secondary, emoji="➕", custom_id="ticket_add_user_btn")
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add user to ticket button"""
        await interaction.response.send_modal(AddUserModal(self.cog, self.ticket_id))

class PersistentTicketView(discord.ui.View):
    """Persistent view for ticket panels that survives bot restarts"""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="persistent_ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle persistent ticket creation"""
        # Check if tickets are enabled
        if not self.cog.is_tickets_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The ticket system is currently disabled in this server!", 
                ephemeral=True
            )
            return
            
        # Get guild config to find available ticket types
        guild_config = self.cog._get_guild_config(interaction.guild.id)
        ticket_types = guild_config["ticket_types"]
        
        if not ticket_types:
            await interaction.response.send_message("❌ No ticket types configured.", ephemeral=True)
            return
        
        # If only one type, create directly
        if len(ticket_types) == 1:
            ticket_type = list(ticket_types.keys())[0]
            await self.cog._handle_ticket_creation(interaction, ticket_type)
        else:
            # Show dropdown for multiple types
            select = TicketTypeSelect(self.cog, ticket_types)
            view = discord.ui.View(timeout=60)
            view.add_item(select)
            await interaction.response.send_message("Please select a ticket type:", view=view, ephemeral=True)

class TicketTypeSelect(discord.ui.Select):
    def __init__(self, cog, ticket_types: Dict[str, dict]):
        self.cog = cog
        
        options = []
        for ticket_type, config in ticket_types.items():
            options.append(discord.SelectOption(
                label=ticket_type,
                description=config.get("description", f"Create a {ticket_type} ticket"),
                emoji=config.get("button_emoji")
            ))
        
        super().__init__(placeholder="Choose a ticket type...", options=options[:25])  # Discord limit

    async def callback(self, interaction: discord.Interaction):
        ticket_type = self.values[0]
        await self.cog._handle_ticket_creation(interaction, ticket_type)

class AddUserModal(discord.ui.Modal, title="Add User to Ticket"):
    def __init__(self, cog, ticket_id: str):
        super().__init__()
        self.cog = cog
        self.ticket_id = ticket_id

    user_input = discord.ui.TextInput(
        label="User ID or Username",
        placeholder="Enter user ID or username to add to ticket",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Try to find user by ID first, then by username
            user = None
            if self.user_input.value.isdigit():
                user = interaction.guild.get_member(int(self.user_input.value))
            
            if not user:
                # Search by username
                user = discord.utils.get(interaction.guild.members, name=self.user_input.value)
            
            if not user:
                await interaction.response.send_message("❌ User not found.", ephemeral=True)
                return

            # Add user to ticket channel
            await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
            
            embed = discord.Embed(
                title="User Added",
                description=f"{user.mention} has been added to this ticket.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            
            await self.cog.log_tickets_action(
                "user_added",
                interaction.guild,
                interaction.user,
                f"Ticket {self.ticket_id}: User {user.name} added"
            )
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error adding user: {e}", ephemeral=True)

class CloseTicketModal(discord.ui.Modal, title="Close Ticket"):
    def __init__(self, cog, ticket_id: str):
        super().__init__()
        self.cog = cog
        self.ticket_id = ticket_id

    reason = discord.ui.TextInput(
        label="Reason for closing (optional)",
        placeholder="Enter a reason for closing this ticket...",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value or "No reason provided"
        await self.cog._close_ticket_by_id(interaction, self.ticket_id, reason_text)

class TicketSystemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = "src/database"
        self.config_dir = "src/config"
        
        # Ensure directories exist
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs("src/logs", exist_ok=True)
        
        # File paths
        self.ticket_config_path = os.path.join(self.config_dir, "ticket_config.json")
        self.ticket_db_path = os.path.join(self.data_dir, "ticket_db.json")
        
        # Initialize data files
        self._init_data_files()
        
        # Start auto-close task
        self.auto_close_task.start()

    def _init_data_files(self):
        """Initialize all data files with default values if they don't exist"""
        default_ticket_config = {
            "guilds": {},
            "guild_settings": {},  # Per-guild settings
            "global_settings": {
                "cooldown_minutes": 5,
                "auto_close_hours": 24,
                "dm_notifications": True,
                "max_open_tickets_per_user": 3
            }
        }
        
        default_ticket_db = {
            "tickets": {},
            "user_cooldowns": {}
        }
        
        files_to_init = [
            (self.ticket_config_path, default_ticket_config),
            (self.ticket_db_path, default_ticket_db)
        ]
        
        for file_path, default_data in files_to_init:
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    json.dump(default_data, f, indent=4)

    def _load_config(self) -> dict:
        """Load ticket configuration from file"""
        try:
            with open(self.ticket_config_path, 'r') as f:
                config = json.load(f)
                # Ensure guild_settings exists
                if "guild_settings" not in config:
                    config["guild_settings"] = {}
                return config
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_data_files()
            with open(self.ticket_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save ticket configuration to file"""
        try:
            with open(self.ticket_config_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving ticket config: {e}")

    def _load_db(self) -> dict:
        """Load ticket database from file"""
        try:
            with open(self.ticket_db_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_data_files()
            with open(self.ticket_db_path, 'r') as f:
                return json.load(f)

    def _save_db(self, data: dict):
        """Save ticket database to file"""
        try:
            with open(self.ticket_db_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving ticket database: {e}")

    # ==================== TOGGLE SYSTEM ====================

    def is_tickets_enabled(self, guild_id: int) -> bool:
        """Check if tickets is enabled for a guild"""
        config = self._load_config()
        guild_config = config.get("guild_settings", {}).get(str(guild_id), {})
        return guild_config.get("tickets_enabled", True)  # Default to enabled

    def set_tickets_enabled(self, guild_id: int, enabled: bool):
        """Set tickets enabled status for a guild"""
        config = self._load_config()
        if "guild_settings" not in config:
            config["guild_settings"] = {}
        if str(guild_id) not in config["guild_settings"]:
            config["guild_settings"][str(guild_id)] = {}
        
        config["guild_settings"][str(guild_id)]["tickets_enabled"] = enabled
        self._save_config(config)

    async def tickets_check(self, interaction: discord.Interaction) -> bool:
        """Check if tickets is enabled before running commands"""
        if not self.is_tickets_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The ticket system is currently disabled in this server!", 
                ephemeral=True
            )
            return False
        return True

    # ==================== LOGGING SYSTEM ====================

    async def log_tickets_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log tickets actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Tickets {action}"
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
                    file_override="tickets_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log tickets action: {e}")

    async def log_tickets_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log tickets errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Tickets Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="tickets_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log tickets error: {e}")

    async def log_tickets_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log tickets warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Tickets Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="tickets_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log tickets warning: {e}")

    # ==================== UTILITY METHODS ====================

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create guild ticket configuration"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "ticket_types": {},
                "panels": {},
                "settings": {
                    "enabled": True,
                    "log_channel_id": None,
                    "staff_role_id": None
                }
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    def has_tickets_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has tickets admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.tickets.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def has_tickets_create_permission(self, member: discord.Member) -> bool:
        """Check if member has tickets create permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return True  # Default allow ticket creation
        
        return (permissions_cog.has_permission(member, 'permissions.tickets.create') or
                permissions_cog.has_permission(member, 'permissions.tickets.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def has_tickets_close_permission(self, member: discord.Member) -> bool:
        """Check if member has tickets close permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.manage_channels
        
        return (permissions_cog.has_permission(member, 'permissions.tickets.close') or
                permissions_cog.has_permission(member, 'permissions.tickets.admin') or
                permissions_cog.has_permission(member, 'permissions.admin'))

    def _generate_ticket_id(self) -> str:
        """Generate a unique ticket ID"""
        return str(uuid.uuid4())[:8].upper()

    async def _check_cooldown(self, user_id: int) -> bool:
        """Check if user is on cooldown"""
        db = self._load_db()
        config = self._load_config()
        cooldown_minutes = config["global_settings"]["cooldown_minutes"]
        
        user_id_str = str(user_id)
        if user_id_str in db["user_cooldowns"]:
            last_ticket = datetime.fromisoformat(db["user_cooldowns"][user_id_str])
            if datetime.now() - last_ticket < timedelta(minutes=cooldown_minutes):
                return False
        
        return True

    async def _set_cooldown(self, user_id: int):
        """Set cooldown for user"""
        db = self._load_db()
        db["user_cooldowns"][str(user_id)] = datetime.now().isoformat()
        self._save_db(db)

    async def _count_user_tickets(self, guild_id: int, user_id: int) -> int:
        """Count open tickets for a user"""
        db = self._load_db()
        count = 0
        
        for ticket_id, ticket_data in db["tickets"].items():
            if (ticket_data["guild_id"] == guild_id and 
                ticket_data["user_id"] == user_id and 
                ticket_data["status"] == "open"):
                count += 1
        
        return count

    async def _handle_ticket_creation(self, interaction: discord.Interaction, ticket_type: str):
        """Handle ticket creation from button or command"""
        # Check if tickets are enabled
        if not self.is_tickets_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The ticket system is currently disabled in this server!", 
                ephemeral=True
            )
            return
            
        # Defer immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        if not self.has_tickets_create_permission(interaction.user):
            await interaction.followup.send("❌ You don't have permission to create tickets.", ephemeral=True)
            return

        # Check cooldown
        if not await self._check_cooldown(interaction.user.id):
            config = self._load_config()
            cooldown = config["global_settings"]["cooldown_minutes"]
            await interaction.followup.send(f"❌ You're on cooldown. Please wait {cooldown} minutes between tickets.", ephemeral=True)
            return

        # Check max open tickets
        config = self._load_config()
        max_tickets = config["global_settings"]["max_open_tickets_per_user"]
        open_count = await self._count_user_tickets(interaction.guild.id, interaction.user.id)
        
        if open_count >= max_tickets:
            await interaction.followup.send(f"❌ You already have {max_tickets} open tickets. Please close one before creating another.", ephemeral=True)
            return

        guild_config = self._get_guild_config(interaction.guild.id)
        
        if ticket_type not in guild_config["ticket_types"]:
            await interaction.followup.send("❌ Invalid ticket type.", ephemeral=True)
            return

        type_config = guild_config["ticket_types"][ticket_type]
        
        if "category_id" not in type_config:
            await interaction.followup.send("❌ No category configured for this ticket type.", ephemeral=True)
            return

        category = interaction.guild.get_channel(type_config["category_id"])
        if not category:
            await interaction.followup.send("❌ Ticket category not found.", ephemeral=True)
            return

        # Generate ticket ID and create channel
        ticket_id = self._generate_ticket_id()
        channel_name = f"ticket-{ticket_id}"
        
        try:
            # Create ticket channel
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add staff role if configured
            if guild_config["settings"]["staff_role_id"]:
                staff_role = interaction.guild.get_role(guild_config["settings"]["staff_role_id"])
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Add ping roles if configured
            ping_roles = type_config.get("ping_roles", [])
            for role_id in ping_roles:
                role = interaction.guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            # Add ping users if configured
            ping_users = type_config.get("ping_users", [])
            for user_id in ping_users:
                user = interaction.guild.get_member(user_id)
                if user:
                    overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Copy permissions from template channel if configured
            if "template_channel_id" in type_config:
                template_channel = interaction.guild.get_channel(type_config["template_channel_id"])
                if template_channel:
                    for target, overwrite in template_channel.overwrites.items():
                        if target != interaction.guild.default_role:
                            overwrites[target] = overwrite
            
            ticket_channel = await category.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                topic=f"Ticket {ticket_id} | Created by {interaction.user.display_name}"
            )
            
            # Create welcome embed
            embed = discord.Embed(
                title=f"🎫 Ticket #{ticket_id}",
                description=type_config.get("welcome_message", f"Welcome to your {ticket_type} ticket!"),
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Created by", value=interaction.user.mention, inline=True)
            embed.add_field(name="Type", value=ticket_type, inline=True)
            embed.add_field(name="Status", value="🟢 Open", inline=True)
            
            # Prepare ping mentions
            ping_mentions = []
            
            # Add role pings
            for role_id in ping_roles:
                role = interaction.guild.get_role(role_id)
                if role:
                    ping_mentions.append(role.mention)
            
            # Add user pings
            for user_id in ping_users:
                user = interaction.guild.get_member(user_id)
                if user:
                    ping_mentions.append(user.mention)
            
            # Send ping message if there are mentions
            ping_content = None
            if ping_mentions:
                ping_content = f"📢 **Staff Alert:** New {ticket_type} ticket created!\n{' '.join(ping_mentions)}"
            
            # Send welcome message with controls
            view = TicketControlView(self, ticket_id)
            
            if ping_content:
                await ticket_channel.send(ping_content)
            
            welcome_msg = await ticket_channel.send(embed=embed, view=view)
            
            # Store ticket in database
            db = self._load_db()
            db["tickets"][ticket_id] = {
                "id": ticket_id,
                "guild_id": interaction.guild.id,
                "channel_id": ticket_channel.id,
                "user_id": interaction.user.id,
                "type": ticket_type,
                "status": "open",
                "created_at": datetime.now().isoformat(),
                "closed_at": None,
                "last_activity": datetime.now().isoformat(),
                "messages": []
            }
            self._save_db(db)
            
            # Set cooldown
            await self._set_cooldown(interaction.user.id)
            
            # Send DM notification if enabled
            if config["global_settings"]["dm_notifications"]:
                try:
                    dm_embed = discord.Embed(
                        title="Ticket Created",
                        description=f"Your {ticket_type} ticket has been created in {interaction.guild.name}.",
                        color=discord.Color.green()
                    )
                    dm_embed.add_field(name="Ticket ID", value=ticket_id, inline=True)
                    dm_embed.add_field(name="Channel", value=ticket_channel.mention, inline=True)
                    await interaction.user.send(embed=dm_embed)
                except discord.Forbidden:
                    pass
            
            # Log action
            await self.log_tickets_action(
                "ticket_created",
                interaction.guild,
                interaction.user,
                f"Ticket {ticket_id} ({ticket_type}) created in {ticket_channel.name}"
            )
            
            # Respond to interaction
            await interaction.followup.send(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to create channels in that category.", ephemeral=True)
            await self.log_tickets_error(
                f"Failed to create ticket: no permissions in category {category.name}",
                interaction.guild, interaction.user
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error creating ticket: {e}", ephemeral=True)
            await self.log_tickets_error(f"Error creating ticket: {e}", interaction.guild, interaction.user)

    async def _close_ticket_by_id(self, interaction: discord.Interaction, ticket_id: str, reason: str = "No reason provided"):
        """Close a ticket by ID"""
        if not self.has_tickets_close_permission(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to close tickets.", ephemeral=True)
            return

        db = self._load_db()
        
        if ticket_id not in db["tickets"]:
            await interaction.response.send_message("❌ Ticket not found.", ephemeral=True)
            return

        ticket_data = db["tickets"][ticket_id]
        
        if ticket_data["status"] == "closed":
            await interaction.response.send_message("❌ Ticket is already closed.", ephemeral=True)
            return

        # Update ticket status
        ticket_data["status"] = "closed"
        ticket_data["closed_at"] = datetime.now().isoformat()
        ticket_data["closed_by"] = interaction.user.id
        ticket_data["close_reason"] = reason
        
        # Get ticket creator for DM
        ticket_creator = interaction.guild.get_member(ticket_data["user_id"])
        
        # Send closing embed
        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description=f"This ticket has been closed by {interaction.user.mention}.",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        
        await interaction.response.send_message(embed=embed)
        
        # Save database
        self._save_db(db)
        
        # Send DM notification to ticket creator
        config = self._load_config()
        if config["global_settings"]["dm_notifications"] and ticket_creator:
            try:
                dm_embed = discord.Embed(
                    title="Ticket Closed",
                    description=f"Your ticket #{ticket_id} in {interaction.guild.name} has been closed.",
                    color=discord.Color.red()
                )
                dm_embed.add_field(name="Closed by", value=interaction.user.display_name, inline=True)
                dm_embed.add_field(name="Reason", value=reason, inline=False)
                await ticket_creator.send(embed=dm_embed)
            except discord.Forbidden:
                pass
        
        # Log action
        await self.log_tickets_action(
            "ticket_closed",
            interaction.guild,
            interaction.user,
            f"Ticket {ticket_id} closed - Reason: {reason}"
        )
        
        # Delete channel after delay
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket {ticket_id} closed")
        except discord.NotFound:
            pass

    # AUTOCOMPLETE FUNCTIONS
    async def ticket_type_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for ticket types"""
        guild_config = self._get_guild_config(interaction.guild.id)
        ticket_types = list(guild_config["ticket_types"].keys())
        
        return [
            app_commands.Choice(name=ticket_type, value=ticket_type)
            for ticket_type in ticket_types
            if current.lower() in ticket_type.lower()
        ][:25]

    @tasks.loop(hours=1)
    async def auto_close_task(self):
        """Auto-close inactive tickets"""
        try:
            config = self._load_config()
            auto_close_hours = config["global_settings"]["auto_close_hours"]
            
            if auto_close_hours <= 0:
                return
            
            db = self._load_db()
            cutoff_time = datetime.now() - timedelta(hours=auto_close_hours)
            
            for ticket_id, ticket_data in db["tickets"].items():
                if ticket_data["status"] != "open":
                    continue
                
                # Check if tickets are enabled for this guild
                if not self.is_tickets_enabled(ticket_data["guild_id"]):
                    continue
                
                last_activity = datetime.fromisoformat(ticket_data["last_activity"])
                if last_activity < cutoff_time:
                    # Auto-close ticket
                    guild = self.bot.get_guild(ticket_data["guild_id"])
                    if guild:
                        channel = guild.get_channel(ticket_data["channel_id"])
                        if channel:
                            embed = discord.Embed(
                                title="🔒 Ticket Auto-Closed",
                                description=f"This ticket has been automatically closed due to inactivity ({auto_close_hours} hours).",
                                color=discord.Color.orange()
                            )
                            await channel.send(embed=embed)
                            
                            # Update database
                            ticket_data["status"] = "closed"
                            ticket_data["closed_at"] = datetime.now().isoformat()
                            ticket_data["closed_by"] = "system"
                            ticket_data["close_reason"] = f"Auto-closed due to inactivity ({auto_close_hours} hours)"
                            
                            # Log action
                            await self.log_tickets_action(
                                "ticket_auto_closed",
                                guild,
                                None,
                                f"Ticket {ticket_id} auto-closed due to inactivity"
                            )
                            
                            # Delete channel after delay
                            await asyncio.sleep(5)
                            try:
                                await channel.delete(reason=f"Ticket {ticket_id} auto-closed")
                            except discord.NotFound:
                                pass
            
            self._save_db(db)
            
        except Exception as e:
            print(f"Error in auto-close task: {e}")

    @auto_close_task.before_loop
    async def before_auto_close_task(self):
        await self.bot.wait_until_ready()

    # ==================== EVENT LISTENERS ====================
    # MESSAGE TRACKING FOR ACTIVITY
    @commands.Cog.listener()
    async def on_message(self, message):
        """Track message activity in ticket channels"""
        if message.author.bot:
            return
        
        # Check if tickets are enabled
        if not self.is_tickets_enabled(message.guild.id):
            return
        
        # Check if message is in a ticket channel
        db = self._load_db()
        
        for ticket_id, ticket_data in db["tickets"].items():
            if (ticket_data["channel_id"] == message.channel.id and 
                ticket_data["status"] == "open"):
                # Update last activity
                ticket_data["last_activity"] = datetime.now().isoformat()
                ticket_data["messages"].append({
                    "author_id": message.author.id,
                    "content": message.content[:500],  # Truncate for storage
                    "timestamp": datetime.now().isoformat()
                })
                
                # Keep only last 50 messages per ticket
                if len(ticket_data["messages"]) > 50:
                    ticket_data["messages"] = ticket_data["messages"][-50:]
                
                self._save_db(db)
                break

    # ==================== TOGGLE COMMANDS ====================

    ticket_group = app_commands.Group(name="ticket", description="Ticket management commands")

    @ticket_group.command(name="toggle", description="Toggle the ticket system on/off (Admin only)")
    @app_commands.describe(enabled="Whether to enable or disable the ticket system")
    async def toggle_tickets(self, interaction: discord.Interaction, enabled: bool):
        """Toggle ticket system"""
        if not self.has_tickets_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to toggle the ticket system!", 
                ephemeral=True
            )
            return
        
        current_status = self.is_tickets_enabled(interaction.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await interaction.response.send_message(
                f"ℹ️ The ticket system is already {status_text} in this server!", 
                ephemeral=True
            )
            return
        
        self.set_tickets_enabled(interaction.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_tickets_action(
            "system_toggled", 
            interaction.guild, 
            interaction.user,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Ticket System {status_text.title()}",
            description=f"The ticket system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    @ticket_group.command(name="status", description="Check if the ticket system is enabled")
    async def tickets_status(self, interaction: discord.Interaction):
        """Check tickets status"""
        enabled = self.is_tickets_enabled(interaction.guild.id)
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        embed = discord.Embed(
            title=f"{status_emoji} Ticket System Status",
            description=f"The ticket system is currently **{status_text}** in this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    # ==================== PREFIX COMMANDS ====================

    @commands.group(name="ticket", invoke_without_command=True)
    async def ticket_prefix(self, ctx):
        """Ticket management commands"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
            
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Ticket Commands",
                description="Available ticket management commands",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Admin Commands",
                value="`ticket type create/delete/set-category/copy-channel/add-ping`\n`ticket panel send/customize`\n`ticket toggle`",
                inline=False
            )
            embed.add_field(
                name="User Commands", 
                value="`ticket create <type> <content>`\n`ticket close [id]`",
                inline=False
            )
            await ctx.send(embed=embed)

    @ticket_prefix.command(name="toggle")
    async def ticket_toggle_prefix(self, ctx, enabled: bool = None):
        """Toggle ticket system (Admin only)"""
        if not self.has_tickets_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to toggle the ticket system!")
            return
        
        if enabled is None:
            current_status = self.is_tickets_enabled(ctx.guild.id)
            status_text = "enabled" if current_status else "disabled"
            status_emoji = "✅" if current_status else "❌"
            
            embed = discord.Embed(
                title=f"{status_emoji} Ticket System Status",
                description=f"The ticket system is currently **{status_text}** in this server.",
                color=0x00ff00 if current_status else 0xff0000
            )
            await ctx.send(embed=embed)
            return
        
        current_status = self.is_tickets_enabled(ctx.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await ctx.send(f"ℹ️ The ticket system is already {status_text} in this server!")
            return
        
        self.set_tickets_enabled(ctx.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_tickets_action(
            "system_toggled", 
            ctx.guild, 
            ctx.author,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Ticket System {status_text.title()}",
            description=f"The ticket system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await ctx.send(embed=embed)

    @ticket_prefix.group(name="type")
    async def ticket_type_prefix(self, ctx):
        """Ticket type management"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
            
        if ctx.invoked_subcommand is None:
            guild_config = self._get_guild_config(ctx.guild.id)
            types = list(guild_config["ticket_types"].keys())
            
            embed = discord.Embed(
                title="Ticket Types",
                description=f"Available types: {', '.join(types) if types else 'None configured'}",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)

    @ticket_type_prefix.command(name="create")
    async def ticket_type_create_prefix(self, ctx, *, name: str):
        """Create a new ticket type"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_create(ctx, name)

    @ticket_type_prefix.command(name="delete")
    async def ticket_type_delete_prefix(self, ctx, *, name: str):
        """Delete a ticket type"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_delete(ctx, name)

    @ticket_type_prefix.command(name="set-category")
    async def ticket_type_set_category_prefix(self, ctx, name: str, category: discord.CategoryChannel):
        """Set category for a ticket type"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_set_category(ctx, name, category)

    @ticket_type_prefix.command(name="copy-channel")
    async def ticket_type_copy_channel_prefix(self, ctx, name: str, channel: discord.TextChannel):
        """Copy channel permissions for ticket type"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_copy_channel(ctx, name, channel)

    @ticket_type_prefix.command(name="add-ping-role")
    async def ticket_type_add_ping_role_prefix(self, ctx, name: str, role: discord.Role):
        """Add a role to be pinged when tickets of this type are created"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_add_ping_role(ctx, name, role)

    @ticket_type_prefix.command(name="add-ping-user")
    async def ticket_type_add_ping_user_prefix(self, ctx, name: str, user: discord.Member):
        """Add a user to be pinged when tickets of this type are created"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_add_ping_user(ctx, name, user)

    @ticket_type_prefix.command(name="remove-ping-role")
    async def ticket_type_remove_ping_role_prefix(self, ctx, name: str, role: discord.Role):
        """Remove a role from being pinged"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_remove_ping_role(ctx, name, role)

    @ticket_type_prefix.command(name="remove-ping-user")
    async def ticket_type_remove_ping_user_prefix(self, ctx, name: str, user: discord.Member):
        """Remove a user from being pinged"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_type_remove_ping_user(ctx, name, user)

    @ticket_prefix.group(name="panel")
    async def ticket_panel_prefix(self, ctx):
        """Ticket panel management"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return

    @ticket_panel_prefix.command(name="send")
    async def ticket_panel_send_prefix(self, ctx, ticket_type: str, channel: discord.TextChannel):
        """Send a ticket panel"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_panel_send(ctx, ticket_type, channel)

    @ticket_prefix.command(name="create")
    async def ticket_create_prefix(self, ctx, ticket_type: str, *, content: str = ""):
        """Create a ticket manually"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_create_manual(ctx, ticket_type, content)

    @ticket_prefix.command(name="close")
    async def ticket_close_prefix(self, ctx, ticket_id: str = None, *, reason: str = "No reason provided"):
        """Close a ticket"""
        if not self.is_tickets_enabled(ctx.guild.id):
            await ctx.send("❌ The ticket system is currently disabled in this server!")
            return
        await self._ticket_close_manual(ctx, ticket_id, reason)

    # ==================== SLASH COMMANDS ====================

    @ticket_group.command(name="type-create", description="Create a new ticket type")
    @app_commands.describe(name="Name of the ticket type")
    async def ticket_type_create_slash(self, interaction: discord.Interaction, name: str):
        """Create a new ticket type"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_type_create(interaction, name)

    @ticket_group.command(name="type-delete", description="Delete a ticket type")
    @app_commands.describe(name="Name of the ticket type")
    @app_commands.autocomplete(name=ticket_type_autocomplete)
    async def ticket_type_delete_slash(self, interaction: discord.Interaction, name: str):
        """Delete a ticket type"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_type_delete(interaction, name)

    @ticket_group.command(name="type-set-category", description="Set category for a ticket type")
    @app_commands.describe(
        name="Name of the ticket type",
        category="Category for tickets of this type"
    )
    @app_commands.autocomplete(name=ticket_type_autocomplete)
    async def ticket_type_set_category_slash(self, interaction: discord.Interaction, name: str, category: discord.CategoryChannel):
        """Set category for a ticket type"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_type_set_category(interaction, name, category)

    @ticket_group.command(name="type-copy-channel", description="Copy channel permissions for ticket type")
    @app_commands.describe(
        name="Name of the ticket type",
        channel="Channel to copy permissions from"
    )
    @app_commands.autocomplete(name=ticket_type_autocomplete)
    async def ticket_type_copy_channel_slash(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel):
        """Copy channel permissions for ticket type"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_type_copy_channel(interaction, name, channel)

    @ticket_group.command(name="type-add-ping-role", description="Add role to ping for ticket type")
    @app_commands.describe(
        name="Name of the ticket type",
        role="Role to ping when tickets are created"
    )
    @app_commands.autocomplete(name=ticket_type_autocomplete)
    async def ticket_type_add_ping_role_slash(self, interaction: discord.Interaction, name: str, role: discord.Role):
        """Add a role to be pinged when tickets of this type are created"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_type_add_ping_role(interaction, name, role)

    @ticket_group.command(name="type-add-ping-user", description="Add user to ping for ticket type")
    @app_commands.describe(
        name="Name of the ticket type",
        user="User to ping when tickets are created"
    )
    @app_commands.autocomplete(name=ticket_type_autocomplete)
    async def ticket_type_add_ping_user_slash(self, interaction: discord.Interaction, name: str, user: discord.Member):
        """Add a user to be pinged when tickets of this type are created"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_type_add_ping_user(interaction, name, user)

    @ticket_group.command(name="panel-send", description="Send a ticket panel")
    @app_commands.describe(
        ticket_type="Type of tickets for this panel",
        channel="Channel to send the panel in"
    )
    @app_commands.autocomplete(ticket_type=ticket_type_autocomplete)
    async def ticket_panel_send_slash(self, interaction: discord.Interaction, ticket_type: str, channel: discord.TextChannel):
        """Send a ticket panel"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_panel_send(interaction, ticket_type, channel)

    @ticket_group.command(name="create", description="Create a ticket manually")
    @app_commands.describe(
        ticket_type="Type of ticket to create",
        content="Initial message content"
    )
    @app_commands.autocomplete(ticket_type=ticket_type_autocomplete)
    async def ticket_create_slash(self, interaction: discord.Interaction, ticket_type: str, content: str = ""):
        """Create a ticket manually"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_create_manual(interaction, ticket_type, content)

    @ticket_group.command(name="close", description="Close a ticket")
    @app_commands.describe(
        ticket_id="ID of ticket to close (leave empty to close current channel)",
        reason="Reason for closing the ticket"
    )
    async def ticket_close_slash(self, interaction: discord.Interaction, ticket_id: str = None, reason: str = "No reason provided"):
        """Close a ticket"""
        if not await self.tickets_check(interaction):
            return
        await self._ticket_close_manual(interaction, ticket_id, reason)

    # ==================== IMPLEMENTATION METHODS ====================

    async def _ticket_type_create(self, ctx_or_interaction, name: str):
        """Create a new ticket type"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' already exists.", ephemeral=True)
            return

        guild_config["ticket_types"][name] = {
            "name": name,
            "button_label": name,
            "button_emoji": None,
            "welcome_message": f"Welcome to your {name} ticket!",
            "ping_roles": [],
            "ping_users": [],
            "created_at": datetime.now().isoformat()
        }

        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Ticket Type Created",
            description=f"Ticket type '{name}' has been created.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_tickets_action(
            "type_created",
            guild,
            member,
            f"Ticket type '{name}' created"
        )

    async def _ticket_type_delete(self, ctx_or_interaction, name: str):
        """Delete a ticket type"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' not found.", ephemeral=True)
            return

        del guild_config["ticket_types"][name]
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Ticket Type Deleted",
            description=f"Ticket type '{name}' has been deleted.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_tickets_action(
            "type_deleted",
            guild,
            member,
            f"Ticket type '{name}' deleted"
        )

    async def _ticket_type_set_category(self, ctx_or_interaction, name: str, category: discord.CategoryChannel):
        """Set category for a ticket type"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' not found.", ephemeral=True)
            return

        guild_config["ticket_types"][name]["category_id"] = category.id
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Category Set",
            description=f"Category for '{name}' tickets set to {category.mention}.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_tickets_action(
            "category_set",
            guild,
            member,
            f"Category for '{name}' set to {category.name}"
        )

    async def _ticket_type_copy_channel(self, ctx_or_interaction, name: str, channel: discord.TextChannel):
        """Copy channel permissions for ticket type"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' not found.", ephemeral=True)
            return

        guild_config["ticket_types"][name]["template_channel_id"] = channel.id
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Template Channel Set",
            description=f"'{name}' tickets will copy permissions from {channel.mention}.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_tickets_action(
            "template_set",
            guild,
            member,
            f"Template channel for '{name}' set to {channel.name}"
        )

    async def _ticket_type_add_ping_role(self, ctx_or_interaction, name: str, role: discord.Role):
        """Add a role to be pinged when tickets of this type are created"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' not found.", ephemeral=True)
            return

        if "ping_roles" not in guild_config["ticket_types"][name]:
            guild_config["ticket_types"][name]["ping_roles"] = []

        if role.id in guild_config["ticket_types"][name]["ping_roles"]:
            await respond(f"❌ {role.mention} is already in the ping list for '{name}'.", ephemeral=True)
            return

        guild_config["ticket_types"][name]["ping_roles"].append(role.id)
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Ping Role Added",
            description=f"{role.mention} will be pinged when '{name}' tickets are created.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_tickets_action(
            "ping_role_added",
            guild,
            member,
            f"Role {role.name} added to ping list for '{name}'"
        )

    async def _ticket_type_add_ping_user(self, ctx_or_interaction, name: str, user: discord.Member):
        """Add a user to be pinged when tickets of this type are created"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' not found.", ephemeral=True)
            return

        if "ping_users" not in guild_config["ticket_types"][name]:
            guild_config["ticket_types"][name]["ping_users"] = []

        if user.id in guild_config["ticket_types"][name]["ping_users"]:
            await respond(f"❌ {user.mention} is already in the ping list for '{name}'.", ephemeral=True)
            return

        guild_config["ticket_types"][name]["ping_users"].append(user.id)
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Ping User Added",
            description=f"{user.mention} will be pinged when '{name}' tickets are created.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

        await self.log_tickets_action(
            "ping_user_added",
            guild,
            member,
            f"User {user.name} added to ping list for '{name}'"
        )

    async def _ticket_type_remove_ping_role(self, ctx_or_interaction, name: str, role: discord.Role):
        """Remove a role from being pinged"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' not found.", ephemeral=True)
            return

        ping_roles = guild_config["ticket_types"][name].get("ping_roles", [])
        if role.id not in ping_roles:
            await respond(f"❌ {role.mention} is not in the ping list for '{name}'.", ephemeral=True)
            return

        guild_config["ticket_types"][name]["ping_roles"].remove(role.id)
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Ping Role Removed",
            description=f"{role.mention} will no longer be pinged for '{name}' tickets.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

    async def _ticket_type_remove_ping_user(self, ctx_or_interaction, name: str, user: discord.Member):
        """Remove a user from being pinged"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket types.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)

        if name not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{name}' not found.", ephemeral=True)
            return

        ping_users = guild_config["ticket_types"][name].get("ping_users", [])
        if user.id not in ping_users:
            await respond(f"❌ {user.mention} is not in the ping list for '{name}'.", ephemeral=True)
            return

        guild_config["ticket_types"][name]["ping_users"].remove(user.id)
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Ping User Removed",
            description=f"{user.mention} will no longer be pinged for '{name}' tickets.",
            color=discord.Color.green()
        )
        await respond(embed=embed)

    async def _ticket_panel_send(self, ctx_or_interaction, ticket_type: str, channel: discord.TextChannel):
        """Send a ticket panel"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tickets_admin_permission(member):
            await respond("❌ You don't have permission to manage ticket panels.", ephemeral=True)
            return

        guild_config = self._get_guild_config(guild.id)

        if ticket_type not in guild_config["ticket_types"]:
            await respond(f"❌ Ticket type '{ticket_type}' not found.", ephemeral=True)
            return

        # Create panel embed
        embed = discord.Embed(
            title="🎫 Support Tickets",
            description=f"Click the button below to create a {ticket_type} ticket.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="How it works",
            value="• Click the button to create a ticket\n• Staff will assist you shortly\n• Close the ticket when resolved",
            inline=False
        )

        # Use persistent view
        view = PersistentTicketView(self)

        try:
            panel_message = await channel.send(embed=embed, view=view)
            await respond(f"✅ Ticket panel sent to {channel.mention}", ephemeral=True)

            await self.log_tickets_action(
                "panel_sent",
                guild,
                member,
                f"Panel for '{ticket_type}' sent to {channel.name}"
            )
        except discord.Forbidden:
            await respond("❌ I don't have permission to send messages in that channel.", ephemeral=True)

    async def _ticket_create_manual(self, ctx_or_interaction, ticket_type: str, content: str):
        """Create a ticket manually"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            await self._handle_ticket_creation(ctx_or_interaction, ticket_type)
        else:
            # For prefix commands, we need to create a mock interaction
            guild_config = self._get_guild_config(ctx_or_interaction.guild.id)
            if ticket_type not in guild_config["ticket_types"]:
                await ctx_or_interaction.send(f"❌ Ticket type '{ticket_type}' not found.")
                return
            
            # This is a simplified version for prefix commands
            await ctx_or_interaction.send("Please use the ticket panel or slash commands for creating tickets.")

    async def _ticket_close_manual(self, ctx_or_interaction, ticket_id: str = None, reason: str = "No reason provided"):
        """Close a ticket manually"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            channel = ctx_or_interaction.channel
            respond = ctx_or_interaction.send

        if not self.has_tickets_close_permission(member):
            await respond("❌ You don't have permission to close tickets.", ephemeral=True)
            return

        db = self._load_db()

        # If no ticket ID provided, try to close current channel
        if not ticket_id:
            for tid, ticket_data in db["tickets"].items():
                if (ticket_data["channel_id"] == channel.id and 
                    ticket_data["status"] == "open"):
                    ticket_id = tid
                    break

        if not ticket_id:
            await respond("❌ No ticket found. Please specify a ticket ID or use this in a ticket channel.", ephemeral=True)
            return

        # Create a mock interaction for the close function
        class MockInteraction:
            def __init__(self, user, guild, channel):
                class MockResponse:
                    async def send_message(self, embed=None, ephemeral=False):
                        if embed:
                            await channel.send(embed=embed)
                
                self.user = user
                self.guild = guild
                self.channel = channel
                self.response = MockResponse()
                
        class MockResponse:
            async def send_message(self, embed=None, ephemeral=False):
                if embed:
                    await channel.send(embed=embed)

        mock_interaction = MockInteraction(member, channel.guild, channel)
        await self._close_ticket_by_id(mock_interaction, ticket_id, reason)

async def setup(bot):
    cog = TicketSystemCog(bot)
    await bot.add_cog(cog)
    
    # Add only the persistent view
    bot.add_view(PersistentTicketView(cog))
