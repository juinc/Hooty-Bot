"""
Discord ConfessionsCog - Anonymous Confession System

OVERVIEW:
Enables anonymous confessions, replies, reporting, and moderation in your Discord server.  
Supports multi-channel posting, admin controls, logging, user bans, and persistent storage.

SETUP:
- No manual setup required – auto-creates config at src/config/confession_config.json
- Config: src/config/confession_config.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.confess.admin' or Administrator

COMMANDS:
/confess <content>                        - Submit an anonymous confession
/confess reply <id/link> <content>        - Reply anonymously to a confession (threaded)
/confess report <id/link> <reason>        - Report a confession to admins
/confess delete <id/link>                 - Delete your own confession (or admin)
/confess status                           - Show system status and stats
/confess config                           - Show current configuration (admin only)
/confess toggle [on/off]                  - Enable/disable confession system (admin only)
/confess ban <user/id/link>               - Ban a user from confessions (admin only)
/confess unban <user/id/link>             - Unban a user (admin only)
/confess banlist                          - View banned users (admin only)
/confess clearban                         - Clear all bans (admin only)
/confess reset                            - Reset all confession data/settings (admin only)
/confess logchannel [channel]             - Set or clear confession log channel (admin only)
/confess channel add <channel>            - Add a confession channel (admin only)
/confess channel remove <channel>         - Remove a confession channel (admin only)
/confess channel list                     - List all confession channels (admin only)
/confess channel clear                    - Remove all confession channels (admin only)

Prefix commands: !confess <subcommand> (same functionality)

FEATURES:
• Anonymous confession submission (multi-channel)
• Anonymous replies (threaded)
• Confession reporting system (with admin notification)
• Confession deletion (by user or admin)
• User ban/unban and banlist management
• Admin-only system reset and configuration
• Logging to both LoggingCog and a configurable log channel
• Per-server persistent config (JSON)
• All commands available as both slash and prefix
• Permission checks (if PermissionsCog present)
• Full statistics and status reporting
• Multi-channel support for confessions and logs
• Confirmation dialog for destructive actions
"""

import discord
from discord.ext import commands
import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Union
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

class ConfirmationView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.value = None

    @discord.ui.button(label='Confirm Reset', style=discord.ButtonStyle.danger, emoji='⚠️')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can confirm this action.", ephemeral=True)
            return
        
        self.value = True
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary, emoji='❌')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can cancel this action.", ephemeral=True)
            return
        
        self.value = False
        self.stop()

class ConfessionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "src/config/confession_config.json"
        self.config = self.load_config()
        self.confession_counter = self.get_next_confession_id()

    def load_config(self):
        """Load configuration from file"""
        try:
            if not os.path.exists("src/config"):
                os.makedirs("src/config")
            
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading confession config: {e}")
            return {}

    def save_config(self):
        """Save configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving confession config: {e}")

    def get_guild_config(self, guild_id: int):
        """Get configuration for a specific guild"""
        guild_id = str(guild_id)
        if guild_id not in self.config:
            self.config[guild_id] = {
                "enabled": False,
                "confession_channels": [],
                "log_channel": None,
                "admin_roles": [],
                "banned_users": [],
                "confessions": {},  # confession_id: {user_id, message_id, channel_id, content, timestamp}
                "reports": {},  # report_id: {confession_id, reporter_id, reason, timestamp}
                "next_confession_id": 1,
                "next_report_id": 1
            }
            self.save_config()
        return self.config[guild_id]

    def get_next_confession_id(self):
        """Get the next available confession ID across all guilds"""
        max_id = 0
        for guild_config in self.config.values():
            if "next_confession_id" in guild_config:
                max_id = max(max_id, guild_config["next_confession_id"])
        return max_id

    def has_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has confession admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.confess.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def has_view_permission(self, member: discord.Member) -> bool:
        """Check if member has confession view permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.confess.view') or
                permissions_cog.has_permission(member, 'permissions.confess.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    async def log_confession_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log confession actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Confessions {action}"
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
                    file_override="confessions_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log confession action: {e}")
        
        # Also log to configured log channel if available
        if guild:
            config = self.get_guild_config(guild.id)
            if config.get("log_channel"):
                log_channel = guild.get_channel(config["log_channel"])
                if log_channel:
                    try:
                        embed = discord.Embed(
                            title="📝 Confession Log",
                            description=f"**Action:** {action}\n**User:** {user.mention if user else 'System'}\n**Details:** {details}",
                            color=0x7289da,
                            timestamp=datetime.now()
                        )
                        await log_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Failed to send to log channel: {e}")

    def is_user_banned(self, guild_id: int, user_id: int) -> bool:
        """Check if user is banned from confessions"""
        config = self.get_guild_config(guild_id)
        return user_id in config.get("banned_users", [])

    def parse_confession_reference(self, reference: str, guild_id: int):
        """Parse confession reference (ID or message link)"""
        config = self.get_guild_config(guild_id)
        
        # Try to parse as confession ID
        try:
            confession_id = int(reference)
            if str(confession_id) in config["confessions"]:
                return confession_id, config["confessions"][str(confession_id)]
        except ValueError:
            pass
        
        # Try to parse as message link
        message_link_pattern = r'https://discord\.com/channels/(\d+)/(\d+)/(\d+)'
        match = re.match(message_link_pattern, reference)
        if match:
            guild_id_from_link, channel_id, message_id = match.groups()
            if int(guild_id_from_link) == guild_id:
                # Find confession by message ID
                for conf_id, confession in config["confessions"].items():
                    if confession["message_id"] == int(message_id):
                        return int(conf_id), confession
        
        return None, None

    def generate_message_link(self, guild_id: int, channel_id: int, message_id: int) -> str:
        """Generate a Discord message link"""
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    async def create_confession_embed(self, content: str, confession_id: int, timestamp: datetime = None) -> discord.Embed:
        """Create a confession embed"""
        if timestamp is None:
            timestamp = datetime.now()
        
        embed = discord.Embed(
            title="📝 Anonymous Confession",
            description=content,
            color=0x7289da,
            timestamp=timestamp
        )
        embed.set_footer(text=f"Confession ID: {confession_id}")
        return embed

    async def submit_confession(self, ctx_or_interaction, content: str):
        """Submit a confession (shared logic for prefix and slash)"""
        # Determine if this is a context or interaction
        if hasattr(ctx_or_interaction, 'response'):  # This is an Interaction
            guild = ctx_or_interaction.guild
            author = ctx_or_interaction.user
            send_method = ctx_or_interaction.response.send_message
        else:  # This is a Context
            guild = ctx_or_interaction.guild
            author = ctx_or_interaction.author
            send_method = ctx_or_interaction.send

        config = self.get_guild_config(guild.id)
        
        if not config["enabled"]:
            await send_method("❌ Confessions are not enabled in this server.", ephemeral=True)
            return

        if self.is_user_banned(guild.id, author.id):
            await send_method("❌ You are banned from submitting confessions.", ephemeral=True)
            return

        if not config["confession_channels"]:
            await send_method("❌ No confession channels are configured.", ephemeral=True)
            return

        if len(content) > 2000:
            await send_method("❌ Confession is too long. Maximum 2000 characters.", ephemeral=True)
            return

        # Get confession ID
        confession_id = config["next_confession_id"]
        config["next_confession_id"] += 1

        # Create embed
        embed = await self.create_confession_embed(content, confession_id)

        # Send to all confession channels
        sent_messages = []
        failed_channels = []
        
        for channel_id in config["confession_channels"]:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    message = await channel.send(embed=embed)
                    sent_messages.append(message)
                except Exception as e:
                    failed_channels.append(f"{channel.name}: {str(e)}")

        if not sent_messages:
            await send_method("❌ Failed to send confession to any channels.", ephemeral=True)
            await self.log_confession_action(
                "confession submission failed",
                guild,
                author,
                f"ID: {confession_id}, no channels available"
            )
            return

        # Store confession data (use first successful message)
        first_message = sent_messages[0]
        config["confessions"][str(confession_id)] = {
            "user_id": author.id,
            "message_id": first_message.id,
            "channel_id": first_message.channel.id,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "all_message_ids": [msg.id for msg in sent_messages]
        }
        
        self.save_config()

        # Log the confession
        details = f"ID: {confession_id}, channels: {len(sent_messages)}"
        if failed_channels:
            details += f", failed: {len(failed_channels)}"
        
        await self.log_confession_action(
            "confession submitted",
            guild,
            author,
            details
        )

        # Generate message link
        message_link = self.generate_message_link(guild.id, first_message.channel.id, first_message.id)
        
        await send_method(
            f"✅ Your confession has been submitted! ID: `{confession_id}`\nLink: {message_link}",
            ephemeral=True
        )

    # ==================== COMMANDS ====================
    # Hybrid Command Group
    @commands.hybrid_group(name="confess", invoke_without_command=True)
    async def confess(self, ctx, *, content: str = None):
        """Submit an anonymous confession or view help"""
        if ctx.invoked_subcommand is not None:
            return
        
        if content is None:
            embed = discord.Embed(
                title="📝 Confessions Help",
                description="Submit anonymous confessions to the server!",
                color=0x7289da
            )
            embed.add_field(
                name="Personal Commands",
                value="`/confess <content>` - Submit a confession\n"
                      "`/confess reply <id/link> <content>` - Reply to a confession\n"
                      "`/confess report <id/link> <reason>` - Report a confession\n"
                      "`/confess delete <id/link>` - Delete your confession",
                inline=False
            )
            embed.add_field(
                name="Admin Commands",
                value="`/confess toggle` - Enable/disable system\n"
                      "`/confess status` - Show system status\n"
                      "`/confess config` - Show configuration\n"
                      "`/confess ban/unban <user>` - Manage user bans",
                inline=False
            )
            await ctx.send(embed=embed)
            return

        await self.submit_confession(ctx, content)

    @confess.command(name="toggle")
    @discord.app_commands.describe(enabled="Enable or disable the confession system")
    async def confess_toggle(self, ctx, enabled: Optional[bool] = None):
        """Toggle confessions on/off (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure confession settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        # If no argument provided, toggle current state
        if enabled is None:
            enabled = not config["enabled"]
        
        old_state = config["enabled"]
        config["enabled"] = enabled
        self.save_config()

        # Create response embed
        if enabled:
            embed = discord.Embed(
                title="✅ Confessions Enabled",
                description="The confession system is now active. Users can submit anonymous confessions.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Confessions Disabled",
                description="The confession system is now disabled. No new confessions can be submitted.",
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
        
        await self.log_confession_action("toggled system state", ctx.guild, ctx.author, details)

    @confess.command(name="status")
    async def confess_status(self, ctx):
        """Show detailed confession system status"""
        config = self.get_guild_config(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        if is_enabled:
            embed = discord.Embed(
                title="✅ Confession System Status",
                description="The confession system is currently **enabled**.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="⏸️ Confession System Status", 
                description="The confession system is currently **disabled**.",
                color=discord.Color.orange()
            )

        # Statistics
        total_confessions = len(config.get("confessions", {}))
        total_reports = len(config.get("reports", {}))
        banned_users = len(config.get("banned_users", []))
        
        embed.add_field(
            name="📊 Statistics",
            value=f"Total confessions: {total_confessions}\nTotal reports: {total_reports}\nBanned users: {banned_users}",
            inline=True
        )

        # Channels
        channel_count = len(config.get("confession_channels", []))
        embed.add_field(
            name="📺 Channels",
            value=f"{channel_count} configured",
            inline=True
        )

        # Log channel
        log_channel_text = "None"
        if config.get("log_channel"):
            log_channel = ctx.guild.get_channel(config["log_channel"])
            log_channel_text = log_channel.mention if log_channel else "Channel not found"
        
        embed.add_field(
            name="📋 Log Channel",
            value=log_channel_text,
            inline=True
        )

        # Recent activity (last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        recent_confessions = 0
        recent_reports = 0
        
        for confession in config.get('confessions', {}).values():
            try:
                confession_time = datetime.fromisoformat(confession['timestamp'])
                if confession_time > week_ago:
                    recent_confessions += 1
            except:
                pass
        
        for report in config.get('reports', {}).values():
            try:
                report_time = datetime.fromisoformat(report['timestamp'])
                if report_time > week_ago:
                    recent_reports += 1
            except:
                pass

        embed.add_field(
            name="📈 Last 7 Days",
            value=f"Confessions: {recent_confessions}\nReports: {recent_reports}",
            inline=True
        )

        # Next IDs
        embed.add_field(
            name="🆔 Next IDs",
            value=f"Confession: {config.get('next_confession_id', 1)}\nReport: {config.get('next_report_id', 1)}",
            inline=True
        )

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="While disabled, no new confessions can be submitted.",
                inline=False
            )

        await ctx.send(embed=embed)

    @confess.command(name="config")
    async def confess_config(self, ctx):
        """Show current confession configuration (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to view configuration.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        is_enabled = config.get("enabled", False)
        
        embed = discord.Embed(
            title="📝 Confession Configuration",
            color=0x7289da if is_enabled else 0x808080
        )
        
        # System status
        status_emoji = "✅" if is_enabled else "⏸️"
        embed.add_field(
            name=f"{status_emoji} System Status",
            value=f"**{'Enabled' if is_enabled else 'Disabled'}**",
            inline=True
        )
        
        # Show all channels with details
        if config["confession_channels"]:
            channel_list = []
            for channel_id in config["confession_channels"]:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    channel_list.append(f"• {channel.mention}")
                else:
                    channel_list.append(f"• Unknown Channel ({channel_id})")
            
            embed.add_field(
                name="📺 Confession Channels",
                value="\n".join(channel_list),
                inline=False
            )
        else:
            embed.add_field(
                name="📺 Confession Channels",
                value="None configured",
                inline=False
            )
        
        # Show log channel
        if config.get("log_channel"):
            log_channel = ctx.guild.get_channel(config["log_channel"])
            embed.add_field(
                name="📋 Log Channel",
                value=log_channel.mention if log_channel else "Channel not found",
                inline=True
            )
        
        # Show admin roles
        if config.get("admin_roles"):
            admin_roles = []
            for role_id in config["admin_roles"]:
                role = ctx.guild.get_role(role_id)
                if role:
                    admin_roles.append(f"• {role.mention}")
                else:
                    admin_roles.append(f"• Unknown Role ({role_id})")
            
            embed.add_field(
                name="👑 Admin Roles",
                value="\n".join(admin_roles),
                inline=False
            )
        
        # Statistics
        embed.add_field(
            name="📊 Statistics",
            value=f"Total Confessions: {len(config.get('confessions', {}))}\n"
                  f"Total Reports: {len(config.get('reports', {}))}\n"
                  f"Banned Users: {len(config.get('banned_users', []))}",
            inline=True
        )

        if not is_enabled:
            embed.add_field(
                name="ℹ️ Note",
                value="System is disabled. Use `/confess toggle` to enable.",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @confess.command(name="delete")
    @discord.app_commands.describe(reference="Confession ID or message link")
    async def delete_confession(self, ctx, reference: str):
        """Delete a confession"""
        config = self.get_guild_config(ctx.guild.id)
        
        confession_id, confession_data = self.parse_confession_reference(reference, ctx.guild.id)
        if not confession_data:
            await ctx.send("❌ Confession not found.", ephemeral=True)
            return

        # Check permissions
        can_delete = (
            confession_data["user_id"] == ctx.author.id or 
            self.has_admin_permission(ctx.author)
        )
        
        if not can_delete:
            await ctx.send("❌ You can only delete your own confessions.", ephemeral=True)
            return

        # Delete messages
        deleted_count = 0
        failed_count = 0
        
        for message_id in confession_data.get("all_message_ids", [confession_data["message_id"]]):
            for channel_id in config["confession_channels"]:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    try:
                        message = await channel.fetch_message(message_id)
                        await message.delete()
                        deleted_count += 1
                    except:
                        failed_count += 1

        # Remove from config
        del config["confessions"][str(confession_id)]
        self.save_config()

        details = f"ID: {confession_id}, deleted: {deleted_count}"
        if failed_count > 0:
            details += f", failed: {failed_count}"

        await self.log_confession_action(
            "confession deleted",
            ctx.guild,
            ctx.author,
            details
        )

        await ctx.send(f"✅ Confession {confession_id} has been deleted.", ephemeral=True)

    @confess.command(name="reply")
    @discord.app_commands.describe(
        reference="Confession ID or message link",
        content="Your anonymous reply"
    )
    async def reply_confession(self, ctx, reference: str, *, content: str):
        """Reply to a confession"""
        config = self.get_guild_config(ctx.guild.id)
        
        if not config["enabled"]:
            await ctx.send("❌ Confessions are not enabled in this server.", ephemeral=True)
            return

        confession_id, confession_data = self.parse_confession_reference(reference, ctx.guild.id)
        if not confession_data:
            await ctx.send("❌ Confession not found.", ephemeral=True)
            return

        # Get the original message
        channel = ctx.guild.get_channel(confession_data["channel_id"])
        if not channel:
            await ctx.send("❌ Original confession channel not found.", ephemeral=True)
            return

        try:
            original_message = await channel.fetch_message(confession_data["message_id"])
        except:
            await ctx.send("❌ Original confession message not found.", ephemeral=True)
            return

        # Create thread for the reply
        try:
            thread = await original_message.create_thread(
                name=f"Reply to Confession {confession_id}",
                auto_archive_duration=1440  # 24 hours
            )
            
            # Send the reply in the thread
            reply_embed = discord.Embed(
                title="💬 Anonymous Reply",
                description=content,
                color=0x00ff00,
                timestamp=datetime.now()
            )
            
            await thread.send(embed=reply_embed)
            await self.log_confession_action(
                "confession reply",
                ctx.guild,
                ctx.author,
                f"confession ID: {confession_id}"
            )
            
            await ctx.send(f"✅ Your reply has been posted to confession {confession_id}!", ephemeral=True)
            
        except Exception as e:
            await ctx.send(f"❌ Failed to create reply thread: {e}", ephemeral=True)
            await self.log_confession_action(
                "confession reply failed",
                ctx.guild,
                ctx.author,
                f"confession ID: {confession_id}, error: {str(e)}"
            )

    @confess.command(name="report")
    @discord.app_commands.describe(
        reference="Confession ID or message link",
        reason="Reason for reporting"
    )
    async def report_confession(self, ctx, reference: str, *, reason: str):
        """Report a confession"""
        config = self.get_guild_config(ctx.guild.id)
        
        confession_id, confession_data = self.parse_confession_reference(reference, ctx.guild.id)
        if not confession_data:
            await ctx.send("❌ Confession not found.", ephemeral=True)
            return

        # Create report
        report_id = config.get("next_report_id", 1)
        config["next_report_id"] = report_id + 1
        
        config["reports"][str(report_id)] = {
            "confession_id": confession_id,
            "reporter_id": ctx.author.id,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        
        self.save_config()

        # Send report to admins
        admin_roles = config.get("admin_roles", [])
        mentions = []
        for role_id in admin_roles:
            role = ctx.guild.get_role(role_id)
            if role:
                mentions.append(role.mention)

        report_embed = discord.Embed(
            title="🚨 Confession Report",
            color=0xff0000,
            timestamp=datetime.now()
        )
        report_embed.add_field(name="Confession ID", value=confession_id, inline=True)
        report_embed.add_field(name="Report ID", value=report_id, inline=True)
        report_embed.add_field(name="Reporter", value=ctx.author.mention, inline=True)
        report_embed.add_field(name="Reason", value=reason, inline=False)
        report_embed.add_field(name="Original Content", value=confession_data["content"][:1000], inline=False)

        message_link = self.generate_message_link(
            ctx.guild.id, 
            confession_data["channel_id"], 
            confession_data["message_id"]
        )
        report_embed.add_field(name="Message Link", value=message_link, inline=False)

        # Send to log channel if configured
        if config.get("log_channel"):
            log_channel = ctx.guild.get_channel(config["log_channel"])
            if log_channel:
                try:
                    mention_text = " ".join(mentions) if mentions else ""
                    await log_channel.send(content=mention_text, embed=report_embed)
                except Exception as e:
                    print(f"Failed to send report to log channel: {e}")

        await self.log_confession_action(
            "confession reported",
            ctx.guild,
            ctx.author,
            f"confession ID: {confession_id}, report ID: {report_id}, reason: {reason[:50]}"
        )

        await ctx.send(f"✅ Confession {confession_id} has been reported (Report ID: {report_id}).", ephemeral=True)

    @confess.command(name="ban")
    @discord.app_commands.describe(reference="User mention, confession ID, or message link")
    async def ban_user(self, ctx, reference: str):
        """Ban a user from confessions (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        # Try to parse as user mention/ID
        user = None
        try:
            user_id = int(reference.replace('<@', '').replace('>', '').replace('!', ''))
            user = ctx.guild.get_member(user_id) or await self.bot.fetch_user(user_id)
        except:
            pass

        # If not a user, try to parse as confession reference
        if not user:
            confession_id, confession_data = self.parse_confession_reference(reference, ctx.guild.id)
            if confession_data:
                user_id = confession_data["user_id"]
                try:
                    user = ctx.guild.get_member(user_id) or await self.bot.fetch_user(user_id)
                except:
                    pass

        if not user:
            await ctx.send("❌ User not found.", ephemeral=True)
            return

        if user.id in config["banned_users"]:
            await ctx.send(f"❌ {user.name} is already banned from confessions.", ephemeral=True)
            return

        config["banned_users"].append(user.id)
        self.save_config()

        embed = discord.Embed(
            title="✅ User Banned",
            description=f"{user.mention} has been banned from confessions.",
            color=discord.Color.red()
        )

        await ctx.send(embed=embed)
        await self.log_confession_action(
            "user banned",
            ctx.guild,
            ctx.author,
            f"banned user: {user.name} ({user.id})"
        )

    @confess.command(name="unban")
    @discord.app_commands.describe(reference="User mention, confession ID, or message link")
    async def unban_user(self, ctx, reference: str):
        """Unban a user from confessions (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        # Try to parse as user mention/ID
        user = None
        try:
            user_id = int(reference.replace('<@', '').replace('>', '').replace('!', ''))
            user = ctx.guild.get_member(user_id) or await self.bot.fetch_user(user_id)
        except:
            pass

        # If not a user, try to parse as confession reference
        if not user:
            confession_id, confession_data = self.parse_confession_reference(reference, ctx.guild.id)
            if confession_data:
                user_id = confession_data["user_id"]
                try:
                    user = ctx.guild.get_member(user_id) or await self.bot.fetch_user(user_id)
                except:
                    pass

        if not user:
            await ctx.send("❌ User not found.", ephemeral=True)
            return

        if user.id not in config["banned_users"]:
            await ctx.send(f"❌ {user.name} is not banned from confessions.", ephemeral=True)
            return

        config["banned_users"].remove(user.id)
        self.save_config()

        embed = discord.Embed(
            title="✅ User Unbanned",
            description=f"{user.mention} has been unbanned from confessions.",
            color=discord.Color.green()
        )

        await ctx.send(embed=embed)
        await self.log_confession_action(
            "user unbanned",
            ctx.guild,
            ctx.author,
            f"unbanned user: {user.name} ({user.id})"
        )

    @confess.group(name="channel", invoke_without_command=True)
    async def confess_channel(self, ctx):
        """Channel management commands (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="📺 Channel Management",
                description="Use the subcommands to manage confession channels:",
                color=0x7289da
            )
            embed.add_field(
                name="Available Commands",
                value="`/confess channel add <channel>` - Add a channel\n"
                      "`/confess channel remove <channel>` - Remove a channel\n"
                      "`/confess channel list` - List all channels\n"
                      "`/confess channel clear` - Remove all channels",
                inline=False
            )
            await ctx.send(embed=embed)

    @confess_channel.command(name="add")
    @discord.app_commands.describe(channel="Channel to add for confessions")
    async def add_confession_channel(self, ctx, channel: discord.TextChannel = None):
        """Add a confession channel (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure confession settings.", ephemeral=True)
            return

        channel = channel or ctx.channel
        config = self.get_guild_config(ctx.guild.id)

        if channel.id not in config["confession_channels"]:
            config["confession_channels"].append(channel.id)
            self.save_config()
            
            embed = discord.Embed(
                title="✅ Channel Added",
                description=f"Added {channel.mention} as a confession channel.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Total Channels",
                value=f"{len(config['confession_channels'])} configured",
                inline=True
            )
            
            await ctx.send(embed=embed)
            await self.log_confession_action("channel added", ctx.guild, ctx.author, f"channel: {channel.name}")
        else:
            await ctx.send(f"❌ {channel.mention} is already a confession channel.", ephemeral=True)

    @confess_channel.command(name="remove")
    @discord.app_commands.describe(channel="Channel to remove from confessions")
    async def remove_confession_channel(self, ctx, channel: discord.TextChannel = None):
        """Remove a confession channel (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure confession settings.", ephemeral=True)
            return

        channel = channel or ctx.channel
        config = self.get_guild_config(ctx.guild.id)

        if channel.id in config["confession_channels"]:
            config["confession_channels"].remove(channel.id)
            self.save_config()
            
            embed = discord.Embed(
                title="✅ Channel Removed",
                description=f"Removed {channel.mention} from confession channels.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Remaining Channels",
                value=f"{len(config['confession_channels'])} configured",
                inline=True
            )
            
            await ctx.send(embed=embed)
            await self.log_confession_action("channel removed", ctx.guild, ctx.author, f"channel: {channel.name}")
        else:
            await ctx.send(f"❌ {channel.mention} is not a confession channel.", ephemeral=True)

    @confess_channel.command(name="list")
    async def list_confession_channels(self, ctx):
        """List all confession channels"""
        config = self.get_guild_config(ctx.guild.id)
        
        if not config["confession_channels"]:
            embed = discord.Embed(
                title="📺 Confession Channels",
                description="No channels are currently configured for confessions.",
                color=0xff9900
            )
            embed.add_field(
                name="Add Channels",
                value="Use `/confess channel add` to add channels.",
                inline=False
            )
            await ctx.send(embed=embed)
            return

        channels = []
        for i, channel_id in enumerate(config["confession_channels"], 1):
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                channels.append(f"{i}. {channel.mention}")
            else:
                channels.append(f"{i}. Unknown Channel ({channel_id})")

        embed = discord.Embed(
            title="📺 Confession Channels",
            description="\n".join(channels),
            color=0x7289da
        )
        
        embed.add_field(
            name="Total Count",
            value=f"{len(config['confession_channels'])} channels configured",
            inline=True
        )

        await ctx.send(embed=embed)

    @confess_channel.command(name="clear")
    async def clear_confession_channels(self, ctx):
        """Remove all confession channels (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure confession settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        
        if not config["confession_channels"]:
            await ctx.send("❌ No channels are currently configured.", ephemeral=True)
            return

        channel_count = len(config["confession_channels"])
        config["confession_channels"] = []
        self.save_config()

        embed = discord.Embed(
            title="✅ All Channels Cleared",
            description=f"Removed all {channel_count} channels from confessions.",
            color=discord.Color.green()
        )

        await ctx.send(embed=embed)
        await self.log_confession_action("all channels cleared", ctx.guild, ctx.author, f"removed {channel_count} channels")

    @confess.command(name="logchannel")
    @discord.app_commands.describe(channel="Channel for confession logs (leave empty to remove)")
    async def set_log_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the log channel for confessions (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to configure confession settings.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        old_channel_id = config.get("log_channel")
        old_channel = ctx.guild.get_channel(old_channel_id) if old_channel_id else None
        
        if channel is None:
            config["log_channel"] = None
            embed = discord.Embed(
                title="✅ Log Channel Removed",
                description="Confession logs will no longer be sent to a channel.",
                color=discord.Color.green()
            )
            details = f"removed log channel (was: {old_channel.name if old_channel else 'none'})"
        else:
            config["log_channel"] = channel.id
            embed = discord.Embed(
                title="✅ Log Channel Set",
                description=f"Confession logs will be sent to {channel.mention}",
                color=discord.Color.green()
            )
            details = f"set to {channel.name} (was: {old_channel.name if old_channel else 'none'})"
        
        if old_channel:
            embed.add_field(
                name="Channel Change",
                value=f"{old_channel.mention if old_channel else 'None'} → {channel.mention if channel else 'None'}",
                inline=True
            )
        
        self.save_config()
        await ctx.send(embed=embed)
        await self.log_confession_action("log channel updated", ctx.guild, ctx.author, details)

    @confess.command(name="banlist")
    async def view_banlist(self, ctx):
        """View the confession ban list (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to view the ban list.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        banned_users = config.get("banned_users", [])
        
        if not banned_users:
            embed = discord.Embed(
                title="📋 Confession Ban List",
                description="No users are currently banned from confessions.",
                color=0x7289da
            )
            await ctx.send(embed=embed)
            return

        user_list = []
        for user_id in banned_users:
            try:
                user = ctx.guild.get_member(user_id) or await self.bot.fetch_user(user_id)
                user_list.append(f"• {user.name} ({user.id})")
            except:
                user_list.append(f"• Unknown User ({user_id})")

        embed = discord.Embed(
            title="📋 Confession Ban List",
            description="\n".join(user_list),
            color=0xff0000
        )
        
        embed.add_field(
            name="Total Banned",
            value=f"{len(banned_users)} users",
            inline=True
        )

        await ctx.send(embed=embed)

    @confess.command(name="clearban")
    async def clear_banlist(self, ctx):
        """Clear the entire confession ban list (Admin only)"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        config = self.get_guild_config(ctx.guild.id)
        banned_count = len(config["banned_users"])
        
        if banned_count == 0:
            await ctx.send("❌ No users are currently banned.", ephemeral=True)
            return

        config["banned_users"] = []
        self.save_config()

        embed = discord.Embed(
            title="✅ Ban List Cleared",
            description=f"Cleared {banned_count} banned users from confessions.",
            color=discord.Color.green()
        )

        await ctx.send(embed=embed)
        await self.log_confession_action(
            "ban list cleared",
            ctx.guild,
            ctx.author,
            f"cleared {banned_count} banned users"
        )

    @confess.command(name="reset")
    async def reset_config(self, ctx):
        """Reset confession configuration (Admin only) - WARNING: Deletes all data!"""
        if not self.has_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        # Confirmation embed
        embed = discord.Embed(
            title="⚠️ Reset Confession Configuration",
            description="This will **permanently delete**:\n"
                    "• All confession records\n"
                    "• All reports\n"
                    "• Ban list\n"
                    "• Channel settings\n"
                    "• Admin roles\n\n"
                    "**This action cannot be undone!**",
            color=0xff0000
        )
        
        view = ConfirmationView(ctx.author.id)
        message = await ctx.send(embed=embed, view=view)
        
        await view.wait()
        
        if view.value:
            # Get counts before reset
            config = self.get_guild_config(ctx.guild.id)
            confession_count = len(config.get("confessions", {}))
            report_count = len(config.get("reports", {}))
            ban_count = len(config.get("banned_users", []))
            
            # Reset the configuration
            guild_id = str(ctx.guild.id)
            self.config[guild_id] = {
                "enabled": False,
                "confession_channels": [],
                "log_channel": None,
                "admin_roles": [],
                "banned_users": [],
                "confessions": {},
                "reports": {},
                "next_confession_id": 1,
                "next_report_id": 1
            }
            self.save_config()
            
            await self.log_confession_action(
                "configuration reset", 
                ctx.guild, 
                ctx.author,
                f"deleted {confession_count} confessions, {report_count} reports, {ban_count} bans"
            )
            
            reset_embed = discord.Embed(
                title="✅ Configuration Reset Complete",
                description=f"Deleted:\n• {confession_count} confessions\n• {report_count} reports\n• {ban_count} banned users\n• All settings reset",
                color=discord.Color.green()
            )
            
            await message.edit(embed=reset_embed, view=None)
        else:
            await message.edit(content="❌ Configuration reset cancelled.", embed=None, view=None)

async def setup(bot):
    await bot.add_cog(ConfessionsCog(bot))
