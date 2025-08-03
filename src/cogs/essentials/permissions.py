"""
Discord Permissions Management Cog - Advanced Role-Based Access Control

OVERVIEW:
Comprehensive permission system with role-based access control, Discord permission
syncing, and granular user/role management. Auto-creates config files and permission structure.

SETUP:
- No manual setup required - auto-creates files and structure
- Config: src/config/perm_config.json
- Default permissions: All users get "default" role automatically
- Initial setup requires Administrator to add authorized roles

PERMISSIONS:
- Authorized roles: Can manage all permissions (set via Administrator)
- Administrator: Can configure authorized roles and Discord sync

COMMANDS:
/permissions grant <permission> <user>      - Grant permission to user
/permissions revoke <permission> <user>     - Revoke permission from user
/permissions role-grant <role> <user>       - Grant permission role to user
/permissions role-revoke <role> <user>      - Revoke permission role from user
/permissions list [user]                    - List user's permissions
/permissions config                         - Show configuration
/permissions add-auth-role <role>          - Add authorized management role
/permissions remove-auth-role <role>       - Remove authorized management role
/permissions setup-toggle-sync             - Toggle Discord permission sync

Permission Role Management:
/permissions discord-role-grant <discord_role> <perm_role> - Grant perm role to Discord role
/permissions role-create <name>            - Create new permission role
/permissions role-delete <name>            - Delete permission role
/permissions role-add-perm <role> <perm>   - Add permission to role

Permission List Management:
/permissions list-show                     - Show all available permissions
/permissions list-add <permission>        - Add permission to list
/permissions suggest [search]             - Find permissions by search

Prefix commands: !permissions <subcommand> (same functionality)

USAGE BY OTHER COGS:

# Check permissions in other cogs
class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.permissions = self.bot.get_cog('PermissionsCog')
    
    @commands.command()
    async def admin_command(self, ctx):
        # Check specific permission
        if not self.permissions.has_permission(ctx.author, 'permissions.admin'):
            await ctx.send("❌ No permission!")
            return
        
        # Get all user permissions
        user_perms = self.permissions.get_user_permissions(ctx.author)
        
        # Check authorized role
        if self.permissions.has_authorized_role(ctx.author):
            # User can manage permissions

PERMISSION SYSTEM:
• Default role: Automatically granted to all users (contains basic permissions)
• Permission roles: Groups of permissions (admin, moderator, helper, etc.)
• Direct permissions: Individual permissions granted to users
• Discord sync: Maps Discord permissions to bot permissions
• Authorized roles: Discord roles that can manage the permission system

FEATURES:
• Role-based permission system with hierarchical structure
• Discord permission synchronization with configurable mappings
• Permission roles (admin, moderator) containing multiple permissions
• Direct user permission granting/revoking
• Discord role integration - assign permission roles to Discord roles
• Comprehensive permission list management with autocomplete
• Default role system (all users get basic permissions automatically)
• Authorized role system for permission management delegation
• Both slash and prefix commands with full autocomplete support
• Detailed permission viewing with source breakdown (direct, roles, discord sync)
• Permission suggestion system for easy discovery
• Protected system roles (cannot delete default, admin roles)
• Automatic permission list updates when new permissions are used
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from typing import Optional, Set, List, Dict, Any, Union

class PermissionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_file = "src/config/perm_config.json"
        self.data = self.load_data()
        
    def load_data(self) -> Dict[str, Any]:
        """Load permissions data from JSON file"""
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r') as f:
                return json.load(f)
        return {"guilds": {}}
    
    def save_data(self):
        """Save permissions data to JSON file"""
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get_guild_data(self, guild_id: int) -> Dict[str, Any]:
        """Get or create guild data"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.data["guilds"]:
            self.data["guilds"][guild_id_str] = {
                "config": {
                    "authorized_roles": [],
                    "sync_discord_permissions": True,
                    "permission_mappings": {
                        "permissions.mod.kick": "kick_members",
                        "permissions.mod.ban": "ban_members",
                        "permissions.mod.msgdel": "manage_messages",
                        "permissions.omni": "administrator",
                        "permissions.mod.timeout": "moderate_members",
                        "permissions.mod.nick": "manage_nicknames",
                        "permissions.mod.mute": "mute_members",
                        "permissions.mod.roles": "manage_roles"
                    },
                    "permission_roles": {
                    "default": [],
                    "all-allowed":[
                        "permissions.omni"
                    ]
                    }
                },
                "user_permissions": {},
                "user_permission_roles": {},
                "role_permission_roles": {},
                "permission_list": [
                    "permissions.omni",
                    "permissions.activities.admin",
                    "permissions.activities.host",
                    "permissions.autofeed.admin",
                    "permissions.autofeed.trigger",
                    "permissions.automod.admin",
                    "permissions.autorole.admin",
                    "permissions.birthday.admin",
                    "permissions.booster.admin",
                    "permissions.bremind.admin",
                    "permissions.cog.admin",
                    "permissions.confess.admin",
                    "permissions.confess.view",
                    "permissions.counting.admin",
                    "permissions.economy.admin",
                    "permissions.giveaway.admin",
                    "permissions.levels.admin",
                    "permissions.logadmin",
                    "permissions.managebotmessages",
                    "permissions.reactionrole.admin",
                    "permissions.sendbotmessage",
                    "permissions.sendembed",
                    "permissions.minecraft.admin",
                    "permissions.star.admin",
                    "permissions.tickets.admin",
                    "permissions.tickets.create",
                    "permissions.tickets.close",
                    "permissions.mod.omni",
                    "permissions.mod.config",
                    "permissions.mod.monitor",
                    "permissions.mod.ban",
                    "permissions.mod.kick",
                    "permissions.mod.timeout",
                    "permissions.mod.mute",
                    "permissions.mod.warn",
                    "permissions.mod.nick",
                    "permissions.mod.purge",
                    "permissions.mod.lock",
                    "permissions.mod.slowmode",
                    "permissions.mod.msgdel",
                    "permissions.mod.mediaonly",
                    "permissions.mod.hardmute",
                    "permissions.mod.softban",
                    "permissions.mod.roles",
                    "permissions.mod.cleanup",
                    "permissions.mod.lookup",
                    "permissions.mod.view",
                    "permissions.tod.admin",
                    "permissions.welcome.admin",
                    "permissions.util.admin"
                ]
            }
            self.save_data()
        return self.data["guilds"][guild_id_str]
    
    def has_authorized_role(self, member: discord.Member) -> bool:
        """Check if member has an authorized role to manage permissions"""
        guild_data = self.get_guild_data(member.guild.id)
        authorized_roles = guild_data["config"]["authorized_roles"]
        return any(role.id in authorized_roles for role in member.roles)
    
    def get_discord_permission_value(self, member: discord.Member, permission_name: str) -> bool:
        """Get the value of a Discord permission for a member"""
        try:
            return getattr(member.guild_permissions, permission_name, False)
        except AttributeError:
            return False
    
    def get_user_permissions(self, member: discord.Member) -> Set[str]:
        """Get all permissions for a user"""
        guild_data = self.get_guild_data(member.guild.id)
        permissions = set()
        
        # Always include default permissions for all users
        default_perms = guild_data["config"]["permission_roles"].get("default", [])
        permissions.update(default_perms)
        
        # Direct user permissions
        user_perms = guild_data["user_permissions"].get(str(member.id), [])
        permissions.update(user_perms)
        
        # User permission roles
        user_roles = guild_data["user_permission_roles"].get(str(member.id), [])
        for role_name in user_roles:
            role_perms = guild_data["config"]["permission_roles"].get(role_name, [])
            permissions.update(role_perms)
        
        # Role permission roles
        for role in member.roles:
            role_roles = guild_data["role_permission_roles"].get(str(role.id), [])
            for role_name in role_roles:
                role_perms = guild_data["config"]["permission_roles"].get(role_name, [])
                permissions.update(role_perms)
        
        # Discord permission sync
        if guild_data["config"]["sync_discord_permissions"]:
            permission_mappings = guild_data["config"]["permission_mappings"]
            for cog_perm, discord_perm in permission_mappings.items():
                if self.get_discord_permission_value(member, discord_perm):
                    permissions.add(cog_perm)
        
        return permissions
    
    def get_permission_list(self, guild_id: int) -> List[str]:
        """Get the permission list for a guild"""
        guild_data = self.get_guild_data(guild_id)
        return guild_data.get("permission_list", [])

    def add_to_permission_list(self, guild_id: int, permission: str) -> bool:
        """Add a permission to the guild's permission list"""
        guild_data = self.get_guild_data(guild_id)
        if "permission_list" not in guild_data:
            guild_data["permission_list"] = []
        
        if permission not in guild_data["permission_list"]:
            guild_data["permission_list"].append(permission)
            guild_data["permission_list"].sort()  # Keep sorted for better UX
            self.save_data()
            return True
        return False

    def remove_from_permission_list(self, guild_id: int, permission: str) -> bool:
        """Remove a permission from the guild's permission list"""
        guild_data = self.get_guild_data(guild_id)
        if "permission_list" not in guild_data:
            guild_data["permission_list"] = []
        
        if permission in guild_data["permission_list"]:
            guild_data["permission_list"].remove(permission)
            self.save_data()
            return True
        return False
    
    def has_permission(self, member: discord.Member, permission: str) -> bool:
        """Check if a member has a specific permission"""
        user_permissions = self.get_user_permissions(member)
        return permission in user_permissions
    
    
    def get_permission_roles(self, guild_id: int) -> Dict[str, List[str]]:
        """Get all permission roles for a guild"""
        guild_data = self.get_guild_data(guild_id)
        return guild_data["config"]["permission_roles"]

    def create_permission_role(self, guild_id: int, role_name: str, permissions: List[str] = None) -> bool:
        """Create a new permission role"""
        guild_data = self.get_guild_data(guild_id)
        
        if role_name in guild_data["config"]["permission_roles"]:
            return False
        
        guild_data["config"]["permission_roles"][role_name] = permissions or []
        self.save_data()
        return True

    def delete_permission_role(self, guild_id: int, role_name: str) -> bool:
        """Delete a permission role"""
        guild_data = self.get_guild_data(guild_id)
        
        if role_name not in guild_data["config"]["permission_roles"]:
            return False
        
        # Prevent deletion of default role
        if role_name == "default":
            return False
        
        # Remove the role from all users and Discord roles
        for user_roles in guild_data["user_permission_roles"].values():
            if role_name in user_roles:
                user_roles.remove(role_name)
        
        for discord_role_roles in guild_data["role_permission_roles"].values():
            if role_name in discord_role_roles:
                discord_role_roles.remove(role_name)
        
        del guild_data["config"]["permission_roles"][role_name]
        self.save_data()
        return True

    def add_permission_to_role(self, guild_id: int, role_name: str, permission: str) -> bool:
        """Add a permission to a permission role"""
        guild_data = self.get_guild_data(guild_id)
        
        if role_name not in guild_data["config"]["permission_roles"]:
            return False
        
        if permission not in guild_data["config"]["permission_roles"][role_name]:
            guild_data["config"]["permission_roles"][role_name].append(permission)
            self.save_data()
            return True
        return False

    def remove_permission_from_role(self, guild_id: int, role_name: str, permission: str) -> bool:
        """Remove a permission from a permission role"""
        guild_data = self.get_guild_data(guild_id)
        
        if role_name not in guild_data["config"]["permission_roles"]:
            return False
        
        if permission in guild_data["config"]["permission_roles"][role_name]:
            guild_data["config"]["permission_roles"][role_name].remove(permission)
            self.save_data()
            return True
        return False

    def grant_permission_role_to_discord_role(self, guild_id: int, discord_role_id: int, permission_role: str) -> bool:
        """Grant a permission role to a Discord role"""
        guild_data = self.get_guild_data(guild_id)
        
        if permission_role not in guild_data["config"]["permission_roles"]:
            return False
        
        role_id_str = str(discord_role_id)
        if role_id_str not in guild_data["role_permission_roles"]:
            guild_data["role_permission_roles"][role_id_str] = []
        
        if permission_role not in guild_data["role_permission_roles"][role_id_str]:
            guild_data["role_permission_roles"][role_id_str].append(permission_role)
            self.save_data()
            return True
        return False

    def revoke_permission_role_from_discord_role(self, guild_id: int, discord_role_id: int, permission_role: str) -> bool:
        """Revoke a permission role from a Discord role"""
        guild_data = self.get_guild_data(guild_id)
        role_id_str = str(discord_role_id)
        
        if (role_id_str in guild_data["role_permission_roles"] and 
            permission_role in guild_data["role_permission_roles"][role_id_str]):
            guild_data["role_permission_roles"][role_id_str].remove(permission_role)
            self.save_data()
            return True
        return False

    # ==================== SHARED IMPLEMENTATION METHODS ====================
    async def _grant_permission_impl(self, guild: discord.Guild, author: discord.Member, permission: str, member: discord.Member, respond_func):
        """Shared implementation for granting permissions"""
        if not self.has_authorized_role(author):
            await respond_func("❌ You don't have permission to manage permissions.", ephemeral=True)
            return
        
        guild_data = self.get_guild_data(guild.id)
        user_id_str = str(member.id)
        
        if user_id_str not in guild_data["user_permissions"]:
            guild_data["user_permissions"][user_id_str] = []
        
        if permission not in guild_data["user_permissions"][user_id_str]:
            guild_data["user_permissions"][user_id_str].append(permission)
            self.save_data()
            
            # Add to permission list if not already there (for convenience)
            permission_list = self.get_permission_list(guild.id)
            if permission not in permission_list:
                self.add_to_permission_list(guild.id, permission)
            
            await respond_func(f"✅ Granted `{permission}` to {member.mention}")
        else:
            await respond_func(f"⚠️ {member.mention} already has `{permission}`")
    async def permission_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for permissions using the permission list"""
        permission_list = self.get_permission_list(interaction.guild.id)
        
        choices = []
        for permission in permission_list:
            if current.lower() in permission.lower():
                choices.append(app_commands.Choice(name=permission, value=permission))
        
        # If no matches in the list, allow custom input
        if not choices and current:
            choices.append(app_commands.Choice(name=f"Custom: {current}", value=current))
        
        return choices[:25]

    async def permission_list_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for permissions in the permission list (for removal)"""
        permission_list = self.get_permission_list(interaction.guild.id)
        
        choices = []
        for permission in permission_list:
            if current.lower() in permission.lower():
                choices.append(app_commands.Choice(name=permission, value=permission))
        
        return choices[:25]
    
    async def permission_role_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for permission roles"""
        permission_roles = self.get_permission_roles(interaction.guild.id)
        
        choices = []
        for role_name in permission_roles.keys():
            if current.lower() in role_name.lower():
                choices.append(app_commands.Choice(name=role_name, value=role_name))
        
        return choices[:25]


    async def _revoke_permission_impl(self, guild: discord.Guild, author: discord.Member, permission: str, member: discord.Member, respond_func):
        """Shared implementation for revoking permissions"""
        if not self.has_authorized_role(author):
            await respond_func("❌ You don't have permission to manage permissions.", ephemeral=True)
            return
        
        guild_data = self.get_guild_data(guild.id)
        user_id_str = str(member.id)
        
        if user_id_str in guild_data["user_permissions"] and permission in guild_data["user_permissions"][user_id_str]:
            guild_data["user_permissions"][user_id_str].remove(permission)
            self.save_data()
            await respond_func(f"✅ Revoked `{permission}` from {member.mention}")
        else:
            await respond_func(f"⚠️ {member.mention} doesn't have `{permission}`")

    async def _grant_role_impl(self, guild: discord.Guild, author: discord.Member, role: str, member: discord.Member, respond_func):
        """Shared implementation for granting permission roles"""
        if not self.has_authorized_role(author):
            await respond_func("❌ You don't have permission to manage permissions.", ephemeral=True)
            return
        
        guild_data = self.get_guild_data(guild.id)
        
        if role not in guild_data["config"]["permission_roles"]:
            await respond_func(f"❌ Permission role `{role}` doesn't exist.")
            return
        
        # Prevent granting default role (users have it automatically)
        if role == "default":
            await respond_func(f"❌ Cannot grant `default` role - all users have it automatically.")
            return
        
        user_id_str = str(member.id)
        
        if user_id_str not in guild_data["user_permission_roles"]:
            guild_data["user_permission_roles"][user_id_str] = []
        
        if role not in guild_data["user_permission_roles"][user_id_str]:
            guild_data["user_permission_roles"][user_id_str].append(role)
            self.save_data()
            await respond_func(f"✅ Granted permission role `{role}` to {member.mention}")
        else:
            await respond_func(f"⚠️ {member.mention} already has permission role `{role}`")

    async def _revoke_role_impl(self, guild: discord.Guild, author: discord.Member, role: str, member: discord.Member, respond_func):
        """Shared implementation for revoking permission roles"""
        if not self.has_authorized_role(author):
            await respond_func("❌ You don't have permission to manage permissions.", ephemeral=True)
            return
        
        # Prevent revoking default role (users have it automatically)
        if role == "default":
            await respond_func(f"❌ Cannot revoke `default` role - all users have it automatically.")
            return
        
        guild_data = self.get_guild_data(guild.id)
        user_id_str = str(member.id)
        
        if user_id_str in guild_data["user_permission_roles"] and role in guild_data["user_permission_roles"][user_id_str]:
            guild_data["user_permission_roles"][user_id_str].remove(role)
            self.save_data()
            await respond_func(f"✅ Revoked permission role `{role}` from {member.mention}")
        else:
            await respond_func(f"⚠️ {member.mention} doesn't have permission role `{role}`")

    def _create_permissions_embed(self, member: discord.Member) -> discord.Embed:
        """Create permissions list embed"""
        permissions = self.get_user_permissions(member)
        guild_data = self.get_guild_data(member.guild.id)
        
        embed = discord.Embed(
            title=f"Permissions for {member.display_name}",
            color=discord.Color.green()
        )
        
        # Default permissions (always present)
        default_perms = guild_data["config"]["permission_roles"].get("default", [])
        if default_perms:
            embed.add_field(
                name="Default Permissions (All Users)",
                value="\n".join(f"• {perm}" for perm in default_perms),
                inline=False
            )
        
        # Direct permissions
        direct_perms = guild_data["user_permissions"].get(str(member.id), [])
        if direct_perms:
            embed.add_field(
                name="Direct Permissions",
                value="\n".join(f"• {perm}" for perm in direct_perms),
                inline=False
            )
        
        # Permission roles
        user_roles = guild_data["user_permission_roles"].get(str(member.id), [])
        role_roles = []
        for role in member.roles:
            role_roles.extend(guild_data["role_permission_roles"].get(str(role.id), []))
        
        all_roles = set(user_roles + role_roles)
        if all_roles:
            embed.add_field(
                name="Permission Roles",
                value="\n".join(f"• {role}" for role in all_roles),
                inline=False
            )
        
        # Discord sync permissions
        if guild_data["config"]["sync_discord_permissions"]:
            discord_perms = []
            for cog_perm, discord_perm in guild_data["config"]["permission_mappings"].items():
                if self.get_discord_permission_value(member, discord_perm):
                    discord_perms.append(cog_perm)
            
            if discord_perms:
                embed.add_field(
                    name="Discord Synced Permissions",
                    value="\n".join(f"• {perm}" for perm in discord_perms),
                    inline=False
                )
        
        embed.add_field(
            name="Total Permissions",
            value=f"{len(permissions)} permissions",
            inline=False
        )
        
        return embed

    def _create_config_embed(self, guild: discord.Guild) -> discord.Embed:
        """Create configuration embed"""
        guild_data = self.get_guild_data(guild.id)
        config = guild_data["config"]
        
        embed = discord.Embed(
            title="Permission Configuration",
            color=discord.Color.blue()
        )
        
        # Authorized roles
        auth_roles = []
        for role_id in config["authorized_roles"]:
            role = guild.get_role(role_id)
            if role:
                auth_roles.append(role.name)
        
        embed.add_field(
            name="Authorized Roles",
            value="\n".join(auth_roles) if auth_roles else "None",
            inline=False
        )
        
        # Permission roles
        perm_roles = []
        for role_name, perms in config["permission_roles"].items():
            if role_name == "default":
                perm_roles.append(f"**{role_name}** (auto-granted): {len(perms)} permissions")
            else:
                perm_roles.append(f"**{role_name}**: {len(perms)} permissions")
        
        embed.add_field(
            name="Permission Roles",
            value="\n".join(perm_roles),
            inline=False
        )
        
        # Default permissions info
        default_perms = config["permission_roles"].get("default", [])
        embed.add_field(
            name="Default User Permissions",
            value=f"{len(default_perms)} permissions automatically granted to all users",
            inline=False
        )
        
        embed.add_field(
            name="Discord Sync",
            value="Enabled" if config["sync_discord_permissions"] else "Disabled",
            inline=True
        )
        
        embed.add_field(
            name="Permission Mappings",
            value=f"{len(config['permission_mappings'])} mappings",
            inline=True
        )
        
        return embed
    
    # ==================== PREFIX COMMANDS ====================
    @commands.group(name="permissions", aliases=["perms"])
    async def permissions_group(self, ctx):
        """Permission management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Permission Commands",
                description="Available permission management commands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Grant Permission",
                value="`permissions grant <permission> <user>`",
                inline=False
            )
            embed.add_field(
                name="Revoke Permission", 
                value="`permissions revoke <permission> <user>`",
                inline=False
            )
            embed.add_field(
                name="Grant Role",
                value="`permissions role-grant <role> <user>`", 
                inline=False
            )
            embed.add_field(
                name="Revoke Role",
                value="`permissions role-revoke <role> <user>`",
                inline=False
            )
            embed.add_field(
                name="List Permissions",
                value="`permissions list [user]`",
                inline=False
            )
            embed.add_field(
                name="Config",
                value="`permissions config`",
                inline=False
            )
            embed.add_field(
                name="Default Permissions",
                value="All users automatically receive the 'default' permission role with basic permissions.",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @permissions_group.command(name="grant")
    async def grant_permission_prefix(self, ctx, permission: str, member: discord.Member):
        """Grant a permission to a user"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._grant_permission_impl(ctx.guild, ctx.author, permission, member, respond)
    
    @permissions_group.command(name="revoke")
    async def revoke_permission_prefix(self, ctx, permission: str, member: discord.Member):
        """Revoke a permission from a user"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._revoke_permission_impl(ctx.guild, ctx.author, permission, member, respond)
    
    @permissions_group.command(name="role-grant")
    async def grant_permission_role_prefix(self, ctx, role: str, member: discord.Member):
        """Grant a permission role to a user"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._grant_role_impl(ctx.guild, ctx.author, role, member, respond)
    
    @permissions_group.command(name="role-revoke")
    async def revoke_permission_role_prefix(self, ctx, role: str, member: discord.Member):
        """Revoke a permission role from a user"""
        async def respond(message, ephemeral=False):
            await ctx.send(message)
        
        await self._revoke_role_impl(ctx.guild, ctx.author, role, member, respond)
    
    @permissions_group.command(name="list")
    async def list_permissions_prefix(self, ctx, member: Optional[discord.Member] = None):
        """List permissions for a user"""
        if member is None:
            member = ctx.author
        
        embed = self._create_permissions_embed(member)
        await ctx.send(embed=embed)
    
    @permissions_group.command(name="config")
    async def config_permissions_prefix(self, ctx):
        """Show permission configuration"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to view configuration.")
            return
        
        embed = self._create_config_embed(ctx.guild)
        await ctx.send(embed=embed)
    
    @permissions_group.group(name="setup")
    async def setup_group(self, ctx):
        """Setup commands for permission system"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Setup Commands",
                description="Configure the permission system:",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="Add Authorized Role",
                value="`permissions setup add-auth-role <role>`",
                inline=False
            )
            embed.add_field(
                name="Remove Authorized Role",
                value="`permissions setup remove-auth-role <role>`",
                inline=False
            )
            embed.add_field(
                name="Toggle Discord Sync",
                value="`permissions setup toggle-sync`",
                inline=False
            )
            await ctx.send(embed=embed)
    
    @setup_group.command(name="add-auth-role")
    @commands.has_permissions(administrator=True)
    async def add_auth_role_prefix(self, ctx, role: discord.Role):
        """Add an authorized role for permission management"""
        guild_data = self.get_guild_data(ctx.guild.id)
        
        if role.id not in guild_data["config"]["authorized_roles"]:
            guild_data["config"]["authorized_roles"].append(role.id)
            self.save_data()
            await ctx.send(f"✅ Added {role.mention} as an authorized role.")
        else:
            await ctx.send(f"⚠️ {role.mention} is already an authorized role.")
    
    @setup_group.command(name="remove-auth-role")
    @commands.has_permissions(administrator=True)
    async def remove_auth_role_prefix(self, ctx, role: discord.Role):
        """Remove an authorized role for permission management"""
        guild_data = self.get_guild_data(ctx.guild.id)
        
        if role.id in guild_data["config"]["authorized_roles"]:
            guild_data["config"]["authorized_roles"].remove(role.id)
            self.save_data()
            await ctx.send(f"✅ Removed {role.mention} from authorized roles.")
        else:
            await ctx.send(f"⚠️ {role.mention} is not an authorized role.")
    
    @setup_group.command(name="toggle-sync")
    @commands.has_permissions(administrator=True)
    async def toggle_discord_sync_prefix(self, ctx):
        """Toggle Discord permission syncing"""
        guild_data = self.get_guild_data(ctx.guild.id)
        
        current = guild_data["config"]["sync_discord_permissions"]
        guild_data["config"]["sync_discord_permissions"] = not current
        self.save_data()
        
        status = "enabled" if not current else "disabled"
        await ctx.send(f"✅ Discord permission syncing {status}.")

    @permissions_group.group(name="permission-list")
    async def permission_list_group(self, ctx):
        """Permission list management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Permission List Commands",
                description="Manage the server's permission list:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="View List",
                value="`permissions list show` - Show all permissions in the list",
                inline=False
            )
            embed.add_field(
                name="Add Permission",
                value="`permissions list add <permission>` - Add permission to list",
                inline=False
            )
            embed.add_field(
                name="Remove Permission",
                value="`permissions list remove <permission>` - Remove permission from list",
                inline=False
            )
            await ctx.send(embed=embed)

    @permission_list_group.command(name="show")
    async def show_permission_list_prefix(self, ctx):
        """Show all permissions in the permission list"""
        permission_list = self.get_permission_list(ctx.guild.id)
        
        if not permission_list:
            await ctx.send("❌ No permissions in the permission list.")
            return
        
        embed = discord.Embed(
            title="Permission List",
            description=f"Server permissions list for {ctx.guild.name}:",
            color=discord.Color.green()
        )
        
        # Split into chunks if too many permissions
        chunk_size = 20
        chunks = [permission_list[i:i + chunk_size] for i in range(0, len(permission_list), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            field_name = f"Permissions ({i*chunk_size + 1}-{i*chunk_size + len(chunk)})" if len(chunks) > 1 else "Permissions"
            embed.add_field(
                name=field_name,
                value="\n".join(f"• {perm}" for perm in chunk),
                inline=False
            )
        
        embed.set_footer(text=f"Total: {len(permission_list)} permissions")
        await ctx.send(embed=embed)

    @permission_list_group.command(name="add")
    async def add_permission_to_list_prefix(self, ctx, *, permission: str):
        """Add a permission to the permission list"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage the permission list.")
            return
        
        if self.add_to_permission_list(ctx.guild.id, permission):
            await ctx.send(f"✅ Added `{permission}` to the permission list.")
        else:
            await ctx.send(f"⚠️ `{permission}` is already in the permission list.")

    @permission_list_group.command(name="remove")
    async def remove_permission_from_list_prefix(self, ctx, *, permission: str):
        """Remove a permission from the permission list"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage the permission list.")
            return
        
        if self.remove_from_permission_list(ctx.guild.id, permission):
            await ctx.send(f"✅ Removed `{permission}` from the permission list.")
        else:
            await ctx.send(f"❌ `{permission}` is not in the permission list.")
            
    @permissions_group.command(name="suggest")
    async def suggest_permissions_prefix(self, ctx, *, search: str = ""):
        """Suggest permissions based on search term"""
        permission_list = self.get_permission_list(ctx.guild.id)
        
        if search:
            matches = [perm for perm in permission_list if search.lower() in perm.lower()]
        else:
            matches = permission_list[:10]  # Show first 10 if no search
        
        if not matches:
            await ctx.send(f"❌ No permissions found matching `{search}`")
            return
        
        embed = discord.Embed(
            title="Permission Suggestions",
            description=f"Permissions matching `{search}`:" if search else "Available permissions:",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Matches",
            value="\n".join(f"• `{perm}`" for perm in matches[:15]),  # Limit to 15
            inline=False
        )
        
        if len(matches) > 15:
            embed.set_footer(text=f"Showing 15 of {len(matches)} matches. Be more specific to see more.")
        
        await ctx.send(embed=embed)
    
    @permissions_group.group(name="role")
    async def permission_role_group(self, ctx):
        """Permission role management commands"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Permission Role Commands",
                description="Manage permission roles and assign them to Discord roles:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Discord Role Management",
                value=(
                    "`permissions role discord-grant <discord_role> <permission_role>` - Grant permission role to Discord role\n"
                    "`permissions role discord-revoke <discord_role> <permission_role>` - Revoke permission role from Discord role\n"
                    "`permissions role discord-list [discord_role]` - List Discord role assignments"
                ),
                inline=False
            )
            embed.add_field(
                name="Permission Role Management",
                value=(
                    "`permissions role create <role_name>` - Create new permission role\n"
                    "`permissions role delete <role_name>` - Delete permission role\n"
                    "`permissions role list` - List all permission roles\n"
                    "`permissions role info <role_name>` - Show permission role details"
                ),
                inline=False
            )
            embed.add_field(
                name="Permission Role Editing",
                value=(
                    "`permissions role add-perm <role_name> <permission>` - Add permission to role\n"
                    "`permissions role remove-perm <role_name> <permission>` - Remove permission from role"
                ),
                inline=False
            )
            embed.add_field(
                name="Default Role",
                value="The 'default' role cannot be deleted, granted, or revoked as all users have it automatically.",
                inline=False
            )
            await ctx.send(embed=embed)

    @permission_role_group.command(name="discord-grant")
    async def grant_discord_role_prefix(self, ctx, discord_role: discord.Role, permission_role: str):
        """Grant a permission role to a Discord role"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage permission roles.")
            return
        
        if self.grant_permission_role_to_discord_role(ctx.guild.id, discord_role.id, permission_role):
            await ctx.send(f"✅ Granted permission role `{permission_role}` to Discord role {discord_role.mention}")
        else:
            await ctx.send(f"❌ Permission role `{permission_role}` doesn't exist or is already assigned to {discord_role.mention}")

    @permission_role_group.command(name="discord-revoke")
    async def revoke_discord_role_prefix(self, ctx, discord_role: discord.Role, permission_role: str):
        """Revoke a permission role from a Discord role"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage permission roles.")
            return
        
        if self.revoke_permission_role_from_discord_role(ctx.guild.id, discord_role.id, permission_role):
            await ctx.send(f"✅ Revoked permission role `{permission_role}` from Discord role {discord_role.mention}")
        else:
            await ctx.send(f"❌ Discord role {discord_role.mention} doesn't have permission role `{permission_role}`")

    @permission_role_group.command(name="discord-list")
    async def list_discord_roles_prefix(self, ctx, discord_role: Optional[discord.Role] = None):
        """List Discord role permission assignments"""
        guild_data = self.get_guild_data(ctx.guild.id)
        role_assignments = guild_data["role_permission_roles"]
        
        if discord_role:
            # Show assignments for specific Discord role
            role_id_str = str(discord_role.id)
            assigned_roles = role_assignments.get(role_id_str, [])
            
            embed = discord.Embed(
                title=f"Permission Roles for {discord_role.name}",
                color=discord_role.color or discord.Color.blue()
            )
            
            if assigned_roles:
                embed.add_field(
                    name="Assigned Permission Roles",
                    value="\n".join(f"• {role}" for role in assigned_roles),
                    inline=False
                )
            else:
                embed.description = "No permission roles assigned to this Discord role."
        else:
            # Show all assignments
            embed = discord.Embed(
                title="Discord Role Permission Assignments",
                description="Permission roles assigned to Discord roles:",
                color=discord.Color.blue()
            )
            
            if role_assignments:
                assignments = []
                for role_id_str, permission_roles in role_assignments.items():
                    if permission_roles:  # Only show roles with assignments
                        discord_role_obj = ctx.guild.get_role(int(role_id_str))
                        role_name = discord_role_obj.name if discord_role_obj else f"Unknown Role ({role_id_str})"
                        assignments.append(f"**{role_name}**: {', '.join(permission_roles)}")
                
                if assignments:
                    embed.add_field(
                        name="Assignments",
                        value="\n".join(assignments),
                        inline=False
                    )
                else:
                    embed.description = "No Discord roles have permission role assignments."
            else:
                embed.description = "No Discord roles have permission role assignments."
        
        await ctx.send(embed=embed)

    @permission_role_group.command(name="create")
    async def create_permission_role_prefix(self, ctx, role_name: str):
        """Create a new permission role"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage permission roles.")
            return
        
        if self.create_permission_role(ctx.guild.id, role_name):
            await ctx.send(f"✅ Created permission role `{role_name}`")
        else:
            await ctx.send(f"❌ Permission role `{role_name}` already exists")

    @permission_role_group.command(name="delete")
    async def delete_permission_role_prefix(self, ctx, role_name: str):
        """Delete a permission role"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage permission roles.")
            return
        
        # Prevent deletion of default and system roles
        if role_name in ["default", "admin", "moderator", "helper"]:
            await ctx.send(f"❌ Cannot delete system permission role `{role_name}`")
            return
        
        if self.delete_permission_role(ctx.guild.id, role_name):
            await ctx.send(f"✅ Deleted permission role `{role_name}` and removed all assignments")
        else:
            await ctx.send(f"❌ Permission role `{role_name}` doesn't exist")

    @permission_role_group.command(name="list")
    async def list_permission_roles_prefix(self, ctx):
        """List all permission roles"""
        permission_roles = self.get_permission_roles(ctx.guild.id)
        
        embed = discord.Embed(
            title="Permission Roles",
            description="Available permission roles:",
            color=discord.Color.green()
        )
        
        for role_name, permissions in permission_roles.items():
            if role_name == "default":
                embed.add_field(
                    name=f"{role_name} (auto-granted) - {len(permissions)} permissions",
                    value=", ".join(permissions[:5]) + ("..." if len(permissions) > 5 else ""),
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"{role_name} ({len(permissions)} permissions)",
                    value=", ".join(permissions[:5]) + ("..." if len(permissions) > 5 else ""),
                    inline=False
                )
        
        embed.set_footer(text=f"Total: {len(permission_roles)} permission roles")
        await ctx.send(embed=embed)

    @permission_role_group.command(name="info")
    async def permission_role_info_prefix(self, ctx, role_name: str):
        """Show detailed information about a permission role"""
        permission_roles = self.get_permission_roles(ctx.guild.id)
        
        if role_name not in permission_roles:
            await ctx.send(f"❌ Permission role `{role_name}` doesn't exist")
            return
        
        permissions = permission_roles[role_name]
        guild_data = self.get_guild_data(ctx.guild.id)
        
        embed = discord.Embed(
            title=f"Permission Role: {role_name}",
            color=discord.Color.blue()
        )
        
        if role_name == "default":
            embed.description = "This role is automatically granted to all users."
        
        # Show permissions
        if permissions:
            # Split into chunks if too many
            chunk_size = 10
            chunks = [permissions[i:i + chunk_size] for i in range(0, len(permissions), chunk_size)]
            
            for i, chunk in enumerate(chunks):
                field_name = f"Permissions ({i*chunk_size + 1}-{i*chunk_size + len(chunk)})" if len(chunks) > 1 else "Permissions"
                embed.add_field(
                    name=field_name,
                    value="\n".join(f"• {perm}" for perm in chunk),
                    inline=False
                )
        else:
            embed.add_field(name="Permissions", value="None", inline=False)
        
        # Show users with this role (excluding default role since all users have it)
        if role_name != "default":
            users_with_role = []
            for user_id, user_roles in guild_data["user_permission_roles"].items():
                if role_name in user_roles:
                    user = ctx.guild.get_member(int(user_id))
                    if user:
                        users_with_role.append(user.display_name)
            
            if users_with_role:
                embed.add_field(
                    name="Users with this role",
                    value=", ".join(users_with_role[:10]) + ("..." if len(users_with_role) > 10 else ""),
                    inline=False
                )
        
        # Show Discord roles with this permission role
        discord_roles_with_role = []
        for discord_role_id, roles in guild_data["role_permission_roles"].items():
            if role_name in roles:
                discord_role = ctx.guild.get_role(int(discord_role_id))
                if discord_role:
                    discord_roles_with_role.append(discord_role.name)
        
        if discord_roles_with_role:
            embed.add_field(
                name="Discord roles with this role",
                value=", ".join(discord_roles_with_role),
                inline=False
            )
        
        await ctx.send(embed=embed)

    @permission_role_group.command(name="add-perm")
    async def add_permission_to_role_prefix(self, ctx, role_name: str, permission: str):
        """Add a permission to a permission role"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage permission roles.")
            return
        
        if self.add_permission_to_role(ctx.guild.id, role_name, permission):
            await ctx.send(f"✅ Added permission `{permission}` to role `{role_name}`")
            
            # Add to permission list if not already there
            permission_list = self.get_permission_list(ctx.guild.id)
            if permission not in permission_list:
                self.add_to_permission_list(ctx.guild.id, permission)
        else:
            await ctx.send(f"❌ Permission role `{role_name}` doesn't exist or already has permission `{permission}`")

    @permission_role_group.command(name="remove-perm")
    async def remove_permission_from_role_prefix(self, ctx, role_name: str, permission: str):
        """Remove a permission from a permission role"""
        if not self.has_authorized_role(ctx.author):
            await ctx.send("❌ You don't have permission to manage permission roles.")
            return
        
        if self.remove_permission_from_role(ctx.guild.id, role_name, permission):
            await ctx.send(f"✅ Removed permission `{permission}` from role `{role_name}`")
        else:
            await ctx.send(f"❌ Permission role `{role_name}` doesn't exist or doesn't have permission `{permission}`")
            
    # ==================== SLASH COMMANDS ====================
        
    permissions_group_slash = app_commands.Group(name="permissions", description="Commands for permissions.")

    @permissions_group_slash.command(name="grant", description="Grant a permission to a user")
    @app_commands.describe(
        permission="The permission to grant (e.g., permissions.kick)",
        user="The user to grant the permission to"
    )
    async def grant_permission_slash(self, interaction: discord.Interaction, permission: str, user: discord.Member):
        """Grant a permission to a user"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._grant_permission_impl(interaction.guild, interaction.user, permission, user, respond)

    @permissions_group_slash.command(name="revoke", description="Revoke a permission from a user")
    @app_commands.describe(
        permission="The permission to revoke",
        user="The user to revoke the permission from"
    )
    async def revoke_permission_slash(self, interaction: discord.Interaction, permission: str, user: discord.Member):
        """Revoke a permission from a user"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._revoke_permission_impl(interaction.guild, interaction.user, permission, user, respond)

    @permissions_group_slash.command(name="role-grant", description="Grant a permission role to a user")
    @app_commands.describe(
        role="The permission role to grant (admin, moderator, helper)",
        user="The user to grant the role to"
    )
    async def grant_role_slash(self, interaction: discord.Interaction, role: str, user: discord.Member):
        """Grant a permission role to a user"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._grant_role_impl(interaction.guild, interaction.user, role, user, respond)

    @permissions_group_slash.command(name="role-revoke", description="Revoke a permission role from a user")
    @app_commands.describe(
        role="The permission role to revoke",
        user="The user to revoke the role from"
    )
    async def revoke_role_slash(self, interaction: discord.Interaction, role: str, user: discord.Member):
        """Revoke a permission role from a user"""
        async def respond(message, ephemeral=False):
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(message, ephemeral=ephemeral)
        
        await self._revoke_role_impl(interaction.guild, interaction.user, role, user, respond)

    @permissions_group_slash.command(name="list", description="List permissions for a user")
    @app_commands.describe(user="The user to list permissions for (defaults to yourself)")
    async def list_permissions_slash(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """List permissions for a user"""
        if user is None:
            user = interaction.user
        
        embed = self._create_permissions_embed(user)
        await interaction.response.send_message(embed=embed)

    @permissions_group_slash.command(name="config", description="Show permission configuration")
    async def config_permissions_slash(self, interaction: discord.Interaction):
        """Show permission configuration"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to view configuration.", ephemeral=True)
            return
        
        embed = self._create_config_embed(interaction.guild)
        await interaction.response.send_message(embed=embed)

    @permissions_group_slash.command(name="add-auth-role", description="Add an authorized role for permission management")
    @app_commands.describe(role="The role to add as authorized for permission management")
    @app_commands.default_permissions(administrator=True)
    async def add_auth_role_slash(self, interaction: discord.Interaction, role: discord.Role):
        """Add an authorized role for permission management"""
        guild_data = self.get_guild_data(interaction.guild.id)
        
        if role.id not in guild_data["config"]["authorized_roles"]:
            guild_data["config"]["authorized_roles"].append(role.id)
            self.save_data()
            await interaction.response.send_message(f"✅ Added {role.mention} as an authorized role.")
        else:
            await interaction.response.send_message(f"⚠️ {role.mention} is already an authorized role.")

    @permissions_group_slash.command(name="remove-auth-role", description="Remove an authorized role for permission management")
    @app_commands.describe(role="The role to remove from authorized permission management")
    @app_commands.default_permissions(administrator=True)
    async def remove_auth_role_slash(self, interaction: discord.Interaction, role: discord.Role):
        """Remove an authorized role for permission management"""
        guild_data = self.get_guild_data(interaction.guild.id)
        
        if role.id in guild_data["config"]["authorized_roles"]:
            guild_data["config"]["authorized_roles"].remove(role.id)
            self.save_data()
            await interaction.response.send_message(f"✅ Removed {role.mention} from authorized roles.")
        else:
            await interaction.response.send_message(f"⚠️ {role.mention} is not an authorized role.")

    @permissions_group_slash.command(name="setup-toggle-sync", description="Toggle Discord permission syncing")
    @app_commands.default_permissions(administrator=True)
    async def toggle_discord_sync_slash(self, interaction: discord.Interaction):
        """Toggle Discord permission syncing"""
        guild_data = self.get_guild_data(interaction.guild.id)
        
        current = guild_data["config"]["sync_discord_permissions"]
        guild_data["config"]["sync_discord_permissions"] = not current
        self.save_data()
        
        status = "enabled" if not current else "disabled"
        await interaction.response.send_message(f"✅ Discord permission syncing {status}.")

    # Autocomplete for permission roles
    async def permission_role_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        guild_data = self.get_guild_data(interaction.guild.id)
        roles = list(guild_data["config"]["permission_roles"].keys())
        
        return [
            app_commands.Choice(name=role, value=role)
            for role in roles
            if current.lower() in role.lower()
        ][:25]
        
    @permissions_group_slash.command(name="list-show", description="Show all permissions in the permission list")
    async def show_permission_list_slash(self, interaction: discord.Interaction):
        """Show all permissions in the permission list"""
        permission_list = self.get_permission_list(interaction.guild.id)
        
        if not permission_list:
            await interaction.response.send_message("❌ No permissions in the permission list.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Permission List",
            description=f"Server permissions list for {interaction.guild.name}:",
            color=discord.Color.green()
        )
        
        # Split into chunks if too many permissions
        chunk_size = 20
        chunks = [permission_list[i:i + chunk_size] for i in range(0, len(permission_list), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            field_name = f"Permissions ({i*chunk_size + 1}-{i*chunk_size + len(chunk)})" if len(chunks) > 1 else "Permissions"
            embed.add_field(
                name=field_name,
                value="\n".join(f"• {perm}" for perm in chunk),
                inline=False
            )
        
        embed.set_footer(text=f"Total: {len(permission_list)} permissions")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @permissions_group_slash.command(name="list-add", description="Add a permission to the permission list")
    @app_commands.describe(permission="Permission to add to the list")
    async def add_permission_to_list_slash(self, interaction: discord.Interaction, permission: str):
        """Add a permission to the permission list"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage the permission list.", ephemeral=True)
            return
        
        if self.add_to_permission_list(interaction.guild.id, permission):
            await interaction.response.send_message(f"✅ Added `{permission}` to the permission list.")
        else:
            await interaction.response.send_message(f"⚠️ `{permission}` is already in the permission list.")

    @permissions_group_slash.command(name="list-remove", description="Remove a permission from the permission list")
    @app_commands.describe(permission="Permission to remove from the list")
    @app_commands.autocomplete(permission=permission_list_autocomplete)
    async def remove_permission_from_list_slash(self, interaction: discord.Interaction, permission: str):
        """Remove a permission from the permission list"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage the permission list.", ephemeral=True)
            return
        
        if self.remove_from_permission_list(interaction.guild.id, permission):
            await interaction.response.send_message(f"✅ Removed `{permission}` from the permission list.")
        else:
            await interaction.response.send_message(f"❌ `{permission}` is not in the permission list.")
            
    @permissions_group_slash.command(name="suggest", description="Suggest permissions based on search term")
    @app_commands.describe(search="Search term to find permissions")
    async def suggest_permissions_slash(self, interaction: discord.Interaction, search: str = ""):
        """Suggest permissions based on search term"""
        permission_list = self.get_permission_list(interaction.guild.id)
        
        if search:
            matches = [perm for perm in permission_list if search.lower() in perm.lower()]
        else:
            matches = permission_list[:10]  # Show first 10 if no search
        
        if not matches:
            await interaction.response.send_message(f"❌ No permissions found matching `{search}`", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Permission Suggestions",
            description=f"Permissions matching `{search}`:" if search else "Available permissions:",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Matches",
            value="\n".join(f"• `{perm}`" for perm in matches[:15]),  # Limit to 15
            inline=False
        )
        
        if len(matches) > 15:
            embed.set_footer(text=f"Showing 15 of {len(matches)} matches. Be more specific to see more.")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    @permissions_group_slash.command(name="discord-role-grant", description="Grant a permission role to a Discord role")
    @app_commands.describe(
        discord_role="The Discord role to grant the permission role to",
        permission_role="The permission role to grant"
    )
    @app_commands.autocomplete(permission_role=permission_role_autocomplete)
    async def grant_discord_role_slash(self, interaction: discord.Interaction, discord_role: discord.Role, permission_role: str):
        """Grant a permission role to a Discord role"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage permission roles.", ephemeral=True)
            return
        
        if self.grant_permission_role_to_discord_role(interaction.guild.id, discord_role.id, permission_role):
            await interaction.response.send_message(f"✅ Granted permission role `{permission_role}` to Discord role {discord_role.mention}")
        else:
            await interaction.response.send_message(f"❌ Permission role `{permission_role}` doesn't exist or is already assigned to {discord_role.mention}")

    @permissions_group_slash.command(name="discord-role-revoke", description="Revoke a permission role from a Discord role")
    @app_commands.describe(
        discord_role="The Discord role to revoke the permission role from",
        permission_role="The permission role to revoke"
    )
    @app_commands.autocomplete(permission_role=permission_role_autocomplete)
    async def revoke_discord_role_slash(self, interaction: discord.Interaction, discord_role: discord.Role, permission_role: str):
        """Revoke a permission role from a Discord role"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage permission roles.", ephemeral=True)
            return
        
        if self.revoke_permission_role_from_discord_role(interaction.guild.id, discord_role.id, permission_role):
            await interaction.response.send_message(f"✅ Revoked permission role `{permission_role}` from Discord role {discord_role.mention}")
        else:
            await interaction.response.send_message(f"❌ Discord role {discord_role.mention} doesn't have permission role `{permission_role}`")

    @permissions_group_slash.command(name="discord-role-list", description="List Discord role permission assignments")
    @app_commands.describe(discord_role="Specific Discord role to check (optional)")
    async def list_discord_roles_slash(self, interaction: discord.Interaction, discord_role: Optional[discord.Role] = None):
        """List Discord role permission assignments"""
        guild_data = self.get_guild_data(interaction.guild.id)
        role_assignments = guild_data["role_permission_roles"]
        
        if discord_role:
            # Show assignments for specific Discord role
            role_id_str = str(discord_role.id)
            assigned_roles = role_assignments.get(role_id_str, [])
            
            embed = discord.Embed(
                title=f"Permission Roles for {discord_role.name}",
                color=discord_role.color or discord.Color.blue()
            )
            
            if assigned_roles:
                embed.add_field(
                    name="Assigned Permission Roles",
                    value="\n".join(f"• {role}" for role in assigned_roles),
                    inline=False
                )
            else:
                embed.description = "No permission roles assigned to this Discord role."
        else:
            # Show all assignments
            embed = discord.Embed(
                title="Discord Role Permission Assignments",
                description="Permission roles assigned to Discord roles:",
                color=discord.Color.blue()
            )
            
            if role_assignments:
                assignments = []
                for role_id_str, permission_roles in role_assignments.items():
                    if permission_roles:  # Only show roles with assignments
                        discord_role_obj = interaction.guild.get_role(int(role_id_str))
                        role_name = discord_role_obj.name if discord_role_obj else f"Unknown Role ({role_id_str})"
                        assignments.append(f"**{role_name}**: {', '.join(permission_roles)}")
                
                if assignments:
                    embed.add_field(
                        name="Assignments",
                        value="\n".join(assignments),
                        inline=False
                    )
                else:
                    embed.description = "No Discord roles have permission role assignments."
            else:
                embed.description = "No Discord roles have permission role assignments."
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @permissions_group_slash.command(name="role-create", description="Create a new permission role")
    @app_commands.describe(role_name="Name of the new permission role")
    async def create_permission_role_slash(self, interaction: discord.Interaction, role_name: str):
        """Create a new permission role"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage permission roles.", ephemeral=True)
            return
        
        if self.create_permission_role(interaction.guild.id, role_name):
            await interaction.response.send_message(f"✅ Created permission role `{role_name}`")
        else:
            await interaction.response.send_message(f"❌ Permission role `{role_name}` already exists")

    @permissions_group_slash.command(name="role-delete", description="Delete a permission role")
    @app_commands.describe(role_name="Permission role to delete")
    @app_commands.autocomplete(role_name=permission_role_autocomplete)
    async def delete_permission_role_slash(self, interaction: discord.Interaction, role_name: str):
        """Delete a permission role"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage permission roles.", ephemeral=True)
            return
        
        # Prevent deletion of default and system roles
        if role_name in ["default", "admin", "moderator", "helper"]:
            await interaction.response.send_message(f"❌ Cannot delete system permission role `{role_name}`", ephemeral=True)
            return
        
        if self.delete_permission_role(interaction.guild.id, role_name):
            await interaction.response.send_message(f"✅ Deleted permission role `{role_name}` and removed all assignments")
        else:
            await interaction.response.send_message(f"❌ Permission role `{role_name}` doesn't exist")

    @permissions_group_slash.command(name="role-list", description="List all permission roles")
    async def list_permission_roles_slash(self, interaction: discord.Interaction):
        """List all permission roles"""
        permission_roles = self.get_permission_roles(interaction.guild.id)
        
        embed = discord.Embed(
            title="Permission Roles",
            description="Available permission roles:",
            color=discord.Color.green()
        )
        
        for role_name, permissions in permission_roles.items():
            if role_name == "default":
                embed.add_field(
                    name=f"{role_name} (auto-granted) - {len(permissions)} permissions",
                    value=", ".join(permissions[:5]) + ("..." if len(permissions) > 5 else ""),
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"{role_name} ({len(permissions)} permissions)",
                    value=", ".join(permissions[:5]) + ("..." if len(permissions) > 5 else ""),
                    inline=False
                )
        
        embed.set_footer(text=f"Total: {len(permission_roles)} permission roles")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @permissions_group_slash.command(name="role-info", description="Show detailed information about a permission role")
    @app_commands.describe(role_name="Permission role to get information about")
    @app_commands.autocomplete(role_name=permission_role_autocomplete)
    async def permission_role_info_slash(self, interaction: discord.Interaction, role_name: str):
        """Show detailed information about a permission role"""
        permission_roles = self.get_permission_roles(interaction.guild.id)
        
        if role_name not in permission_roles:
            await interaction.response.send_message(f"❌ Permission role `{role_name}` doesn't exist", ephemeral=True)
            return
        
        permissions = permission_roles[role_name]
        guild_data = self.get_guild_data(interaction.guild.id)
        
        embed = discord.Embed(
            title=f"Permission Role: {role_name}",
            color=discord.Color.blue()
        )
        
        if role_name == "default":
            embed.description = "This role is automatically granted to all users."
        
        # Show permissions
        if permissions:
            # Split into chunks if too many
            chunk_size = 10
            chunks = [permissions[i:i + chunk_size] for i in range(0, len(permissions), chunk_size)]
            
            for i, chunk in enumerate(chunks):
                field_name = f"Permissions ({i*chunk_size + 1}-{i*chunk_size + len(chunk)})" if len(chunks) > 1 else "Permissions"
                embed.add_field(
                    name=field_name,
                    value="\n".join(f"• {perm}" for perm in chunk),
                    inline=False
                )
        else:
            embed.add_field(name="Permissions", value="None", inline=False)
        
        # Show users with this role (excluding default role since all users have it)
        if role_name != "default":
            users_with_role = []
            for user_id, user_roles in guild_data["user_permission_roles"].items():
                if role_name in user_roles:
                    user = interaction.guild.get_member(int(user_id))
                    if user:
                        users_with_role.append(user.display_name)
            
            if users_with_role:
                embed.add_field(
                    name="Users with this role",
                    value=", ".join(users_with_role[:10]) + ("..." if len(users_with_role) > 10 else ""),
                    inline=False
                )
        
        # Show Discord roles with this permission role
        discord_roles_with_role = []
        for discord_role_id, roles in guild_data["role_permission_roles"].items():
            if role_name in roles:
                discord_role = interaction.guild.get_role(int(discord_role_id))
                if discord_role:
                    discord_roles_with_role.append(discord_role.name)
        
        if discord_roles_with_role:
            embed.add_field(
                name="Discord roles with this role",
                value=", ".join(discord_roles_with_role),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @permissions_group_slash.command(name="role-add-perm", description="Add a permission to a permission role")
    @app_commands.describe(
        role_name="Permission role to modify",
        permission="Permission to add"
    )
    @app_commands.autocomplete(role_name=permission_role_autocomplete)
    @app_commands.autocomplete(permission=permission_autocomplete)
    async def add_permission_to_role_slash(self, interaction: discord.Interaction, role_name: str, permission: str):
        """Add a permission to a permission role"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage permission roles.", ephemeral=True)
            return
        
        if self.add_permission_to_role(interaction.guild.id, role_name, permission):
            await interaction.response.send_message(f"✅ Added permission `{permission}` to role `{role_name}`")
            
            # Add to permission list if not already there
            permission_list = self.get_permission_list(interaction.guild.id)
            if permission not in permission_list:
                self.add_to_permission_list(interaction.guild.id, permission)
        else:
            await interaction.response.send_message(f"❌ Permission role `{role_name}` doesn't exist or already has permission `{permission}`")

    @permissions_group_slash.command(name="role-remove-perm", description="Remove a permission from a permission role")
    @app_commands.describe(
        role_name="Permission role to modify", 
        permission="Permission to remove"
    )
    @app_commands.autocomplete(role_name=permission_role_autocomplete)
    @app_commands.autocomplete(permission=permission_autocomplete)
    async def remove_permission_from_role_slash(self, interaction: discord.Interaction, role_name: str, permission: str):
        """Remove a permission from a permission role"""
        if not self.has_authorized_role(interaction.user):
            await interaction.response.send_message("❌ You don't have permission to manage permission roles.", ephemeral=True)
            return
        
        if self.remove_permission_from_role(interaction.guild.id, role_name, permission):
            await interaction.response.send_message(f"✅ Removed permission `{permission}` from role `{role_name}`")
        else:
            await interaction.response.send_message(f"❌ Permission role `{role_name}` doesn't exist or doesn't have permission `{permission}`")

    # Add autocomplete to role commands
    grant_permission_slash.autocomplete('permission')(permission_autocomplete)
    revoke_permission_slash.autocomplete('permission')(permission_autocomplete)
    grant_role_slash.autocomplete('role')(permission_role_autocomplete)
    revoke_role_slash.autocomplete('role')(permission_role_autocomplete)

async def setup(bot):
    await bot.add_cog(PermissionsCog(bot))
