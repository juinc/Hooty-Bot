"""
Discord EconomyCog - Full-Featured Server Economy & Casino System

OVERVIEW:
A comprehensive Discord economy cog with jobs, banking, daily/work rewards, donations, gambling games (blackjack, slots, dice, coinflip), leaderboards, and admin controls.  
Persistent, per-server, and per-user data. Supports both slash and prefix commands.

SETUP:
- No manual setup required – auto-creates config/database files:
- Config: src/config/economy_config.json
- Database: src/database/economy_db.json
- Optional: PermissionsCog (for admin checks), LoggingCog (for logging actions/errors)

PERMISSIONS:
- Admin commands require 'permissions.economy.admin' or Administrator

COMMANDS (Slash & Prefix):
/economy toggle [on/off]           - Enable/disable the economy system (admin)
/economy status                    - Show if the economy is enabled
/economy balance [user]            - Show your or another user's balance
/economy work                      - Work at your job for money (hourly cooldown)
/economy setjob <job>              - Set your job (affects work earnings)
/economy jobs                      - List all available jobs
/economy daily                     - Claim your daily reward (24h cooldown)
/economy deposit <amount/all>      - Deposit money into your bank
/economy withdraw <amount/all>     - Withdraw money from your bank
/economy donate <user> <amount>    - Donate money to another user
/economy steal <user>              - Attempt to steal from another user (2h cooldown)
/economy blackjack <amount>        - Play interactive blackjack vs. the bot
/economy roll <amount>             - Play a dice roll game vs. the bot
/economy coinflip <amount> <side>  - Play a coin flip game
/economy slots <amount>            - Play the slot machine
/economy leaderboard [category]    - View the richest users (net worth, wallet, bank, earned)
/economy resetbal <user> <type>    - Reset a user's balance (admin)
/economy resetbal-all <type>       - Reset all users' balances (admin)

Prefix commands: !economy, !eco, !money (same subcommands as above)

COMMAND EXPLANATIONS:
- balance: Show wallet, bank, net worth, and stats.
- work: Earn money based on your job, with a chance to fail.
- setjob: Change your job (affects work earnings/failure rate).
- daily: Claim a random daily reward.
- deposit/withdraw: Move money between wallet and bank (bank has a max limit).
- donate: Give money to another user.
- steal: Attempt to steal from another user (success/failure, fines).
- blackjack/roll/coinflip/slots: Gamble your money in various games.
- leaderboard: See top users by net worth, wallet, bank, or total earned.
- resetbal/resetbal-all: Admin-only, reset balances for one/all users.

FEATURES:
• Persistent per-server and per-user economy data (JSON)
• Wallet & bank system with interest and storage limits
• Jobs system with salaries and failure rates
• Daily and work rewards with cooldowns
• Gambling games: blackjack (interactive), slots, dice, coinflip
• Donations and stealing (with cooldowns, fines, and success rates)
• Leaderboards and user stats
• Admin controls for enabling/disabling, resetting, and mass resets
• Logging support (if LoggingCog present)
• Permission checks (if PermissionsCog present)
• Both slash and prefix command support
• Confirmation dialogs for destructive actions
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import random
from datetime import datetime
from typing import Union, Dict, Any, List
import os
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

class BlackjackView(discord.ui.View):
    """Interactive view for blackjack game"""
    
    def __init__(self, user_id: int, bet_amount: int, player_hand: List[str], dealer_hand: List[str], economy_cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.bet_amount = bet_amount
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand
        self.economy_cog = economy_cog
        self.game_over = False
        self.doubled_down = False
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the original user can interact"""
        return interaction.user.id == self.user_id
    
    def create_deck(self) -> List[str]:
        """Create a standard deck of cards"""
        return ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'] * 4
    
    def deal_card(self) -> str:
        """Deal a random card"""
        cards = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        return random.choice(cards)
    
    def get_embed(self, interaction: discord.Interaction, show_dealer: bool = False) -> discord.Embed:
        """Create the game embed"""
        player_value = self.economy_cog.calculate_hand_value(self.player_hand)
        dealer_value = self.economy_cog.calculate_hand_value(self.dealer_hand)
        
        embed = discord.Embed(title="🃏 Blackjack", color=0x0099ff)
        
        # Player hand
        embed.add_field(
            name=f"Your Hand ({player_value})",
            value=self.economy_cog.format_hand(self.player_hand),
            inline=True
        )
        
        # Dealer hand
        if show_dealer:
            embed.add_field(
                name=f"Dealer's Hand ({dealer_value})",
                value=self.economy_cog.format_hand(self.dealer_hand),
                inline=True
            )
        else:
            visible_cards = [self.dealer_hand[0], "❓"]
            embed.add_field(
                name="Dealer's Hand",
                value=" ".join(visible_cards),
                inline=True
            )
        
        # Bet amount
        current_bet = self.bet_amount * 2 if self.doubled_down else self.bet_amount
        embed.add_field(
            name="Bet",
            value=self.economy_cog.format_money(current_bet),
            inline=True
        )
        
        return embed
    
    async def end_game(self, interaction: discord.Interaction, result: str, winnings: int):
        """End the game and update user balance"""
        self.game_over = True
        
        # Update user data
        user_data = self.economy_cog.get_user_data(interaction.guild.id, interaction.user.id)
        user_data["wallet"] += winnings
        
        if winnings > 0:
            user_data["total_earned"] += winnings
        elif winnings < 0:
            user_data["total_spent"] += abs(winnings)
        
        self.economy_cog.save_economy_db()
        
        # Log the game
        player_value = self.economy_cog.calculate_hand_value(self.player_hand)
        dealer_value = self.economy_cog.calculate_hand_value(self.dealer_hand)
        
        await self.economy_cog.log_economy_action(
            "blackjack", 
            interaction.guild, 
            interaction.user,
            f"Bet: {self.bet_amount}, Result: {winnings}, P{player_value}/D{dealer_value}"
        )
        
        # Create final embed
        embed = self.get_embed(interaction, show_dealer=True)
        
        # Determine color based on result
        if winnings > 0:
            color = 0x00ff00  # Green
        elif winnings < 0:
            color = 0xff0000  # Red
        else:
            color = 0xffff00  # Yellow
        
        embed.color = color
        embed.add_field(name="Result", value=result, inline=False)
        embed.add_field(
            name="New Balance",
            value=self.economy_cog.format_money(user_data["wallet"]),
            inline=True
        )
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Hit - take another card"""
        if self.game_over:
            return
        
        # Deal a card
        new_card = self.deal_card()
        self.player_hand.append(new_card)
        
        player_value = self.economy_cog.calculate_hand_value(self.player_hand)
        
        if player_value > 21:
            # Player busts
            current_bet = self.bet_amount * 2 if self.doubled_down else self.bet_amount
            await self.end_game(interaction, "Bust! You lose!", -current_bet)
        elif player_value == 21:
            # Player gets 21, auto-stand
            await self.stand_logic(interaction)
        else:
            # Continue game
            if self.doubled_down:
                # If doubled down, must stand after hitting once
                await self.stand_logic(interaction)
            else:
                embed = self.get_embed(interaction)
                await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Stand - keep current hand"""
        if self.game_over:
            return
        
        await self.stand_logic(interaction)
    
    async def stand_logic(self, interaction: discord.Interaction):
        """Logic for standing"""
        # Dealer plays
        while self.economy_cog.calculate_hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deal_card())
        
        player_value = self.economy_cog.calculate_hand_value(self.player_hand)
        dealer_value = self.economy_cog.calculate_hand_value(self.dealer_hand)
        
        current_bet = self.bet_amount * 2 if self.doubled_down else self.bet_amount
        
        # Determine winner
        if dealer_value > 21:
            await self.end_game(interaction, "Dealer bust! You win!", current_bet)
        elif dealer_value > player_value:
            await self.end_game(interaction, "Dealer wins!", -current_bet)
        elif player_value > dealer_value:
            await self.end_game(interaction, "You win!", current_bet)
        else:
            await self.end_game(interaction, "Push! It's a tie!", 0)
    
    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.success, emoji="💰")
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Double down - double bet and take exactly one more card"""
        if self.game_over or self.doubled_down or len(self.player_hand) != 2:
            return
        
        # Check if user has enough money
        user_data = self.economy_cog.get_user_data(interaction.guild.id, interaction.user.id)
        if user_data["wallet"] < self.bet_amount:
            await interaction.response.send_message(
                "You don't have enough money to double down!", ephemeral=True
            )
            return
        
        # Double the bet
        self.doubled_down = True
        user_data["wallet"] -= self.bet_amount  # Take the additional bet now
        self.economy_cog.save_economy_db()
        
        # Deal exactly one card
        new_card = self.deal_card()
        self.player_hand.append(new_card)
        
        player_value = self.economy_cog.calculate_hand_value(self.player_hand)
        
        if player_value > 21:
            # Player busts
            await self.end_game(interaction, "Bust! You lose!", -self.bet_amount)  # Only lose the original bet since we already took the double
        else:
            # Must stand after doubling down
            await self.stand_logic(interaction)
    
    async def on_timeout(self):
        """Handle timeout"""
        self.game_over = True
        for item in self.children:
            item.disabled = True

class EconomyCog(commands.Cog):
    """Comprehensive economy system with jobs, games, and banking"""
    
    def __init__(self, bot):
        self.bot = bot
        self.economy_db_file = "src/database/economy_db.json"
        self.economy_config_file = "src/config/economy_config.json"
        
        # Ensure directories exist
        os.makedirs("src/database", exist_ok=True)
        os.makedirs("src/logs", exist_ok=True)
        
        # Load data
        self.economy_db = self.load_economy_db()
        self.config = self.load_config()
        
        # Cooldown tracking
        self.work_cooldowns = {}
        self.daily_cooldowns = {}
        self.steal_cooldowns = {}
        
        # Start background tasks
        self.save_data_task.start()
        self.apply_interest.start()

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.save_data_task.cancel()
        self.apply_interest.cancel()
        self.save_economy_db()

    def is_economy_enabled(self, guild_id: int) -> bool:
        """Check if economy is enabled for a guild"""
        guild_config = self.config.get("guild_settings", {}).get(str(guild_id), {})
        return guild_config.get("economy_enabled", True)  # Default to enabled

    def set_economy_enabled(self, guild_id: int, enabled: bool):
        """Set economy enabled status for a guild"""
        if "guild_settings" not in self.config:
            self.config["guild_settings"] = {}
        if str(guild_id) not in self.config["guild_settings"]:
            self.config["guild_settings"][str(guild_id)] = {}
        
        self.config["guild_settings"][str(guild_id)]["economy_enabled"] = enabled
        self.save_config()

    async def economy_check(self, interaction: discord.Interaction) -> bool:
        """Check if economy is enabled before running commands"""
        if not self.is_economy_enabled(interaction.guild.id):
            await interaction.response.send_message(
                "❌ The economy system is currently disabled in this server!", 
                ephemeral=True
            )
            return False
        return True

    async def log_economy_action(self, action: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None, details: str = ""):
        """Log economy actions using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                log_message = f"Economy {action}"
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
                    file_override="economy_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log economy action: {e}")

    async def log_economy_error(self, error_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log economy errors using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.ERROR,
                    f"Economy Error: {error_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="economy_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log economy error: {e}")

    async def log_economy_warning(self, warning_msg: str, guild: discord.Guild = None, user: Union[discord.Member, discord.User] = None):
        """Log economy warnings using the logging cog"""
        if hasattr(self.bot, 'log') and hasattr(self.bot.log, 'log'):
            try:
                await self.bot.log.log(
                    LogLevel.WARNING,
                    f"Economy Warning: {warning_msg}",
                    guild,
                    user,
                    LogType.COG,
                    file_override="economy_cog"
                )
            except Exception as e:
                # If logging fails, just print to console - don't break functionality
                print(f"Failed to log economy warning: {e}")

    def load_economy_db(self) -> Dict[str, Any]:
        """Load economy database from JSON file"""
        try:
            if os.path.exists(self.economy_db_file):
                with open(self.economy_db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            # Use asyncio to schedule the logging since we can't await in __init__
            asyncio.create_task(self.log_economy_error(f"Error loading economy database: {e}"))
        return {}

    def save_economy_db(self):
        """Save economy database to JSON file"""
        try:
            with open(self.economy_db_file, 'w', encoding='utf-8') as f:
                json.dump(self.economy_db, f, indent=2, ensure_ascii=False)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_economy_error(f"Error saving economy database: {e}"))

    def load_config(self) -> Dict[str, Any]:
        """Load economy configuration from JSON file"""
        default_config = {
            "work_cooldown": 3600,  # 1 hour
            "daily_cooldown": 86400,  # 24 hours
            "steal_cooldown": 7200,  # 2 hours
            "daily_reward": {"min": 100, "max": 500},
            "interest_rate": 0.01,  # 1% daily
            "max_bank_storage": 100000,
            "steal_success_rate": 0.6,
            "steal_fine": 200,
            "guild_settings": {},  # Per-guild settings
            "jobs": {
                "unemployed": {"name": "Unemployed", "salary_min": 0, "salary_max": 0, "failure_rate": 0},
                "janitor": {"name": "Janitor", "salary_min": 50, "salary_max": 150, "failure_rate": 0.1},
                "cashier": {"name": "Cashier", "salary_min": 100, "salary_max": 250, "failure_rate": 0.15},
                "teacher": {"name": "Teacher", "salary_min": 200, "salary_max": 400, "failure_rate": 0.2},
                "doctor": {"name": "Doctor", "salary_min": 500, "salary_max": 1000, "failure_rate": 0.25},
                "lawyer": {"name": "Lawyer", "salary_min": 800, "salary_max": 1500, "failure_rate": 0.3},
                "ceo": {"name": "CEO", "salary_min": 1000, "salary_max": 2500, "failure_rate": 0.4}
            },
            "shop_items": {
                "coffee": {"name": "☕ Coffee", "price": 50, "description": "Gives you energy"},
                "sandwich": {"name": "🥪 Sandwich", "price": 100, "description": "A tasty meal"},
                "laptop": {"name": "💻 Laptop", "price": 2000, "description": "High-tech equipment"},
                "car": {"name": "🚗 Car", "price": 15000, "description": "Fast transportation"},
                "house": {"name": "🏠 House", "price": 100000, "description": "Your dream home"}
            }
        }
        
        try:
            if os.path.exists(self.economy_config_file):
                with open(self.economy_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Merge with defaults
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_economy_error(f"Error loading economy config: {e}"))
        
        return default_config

    def save_config(self):
        """Save economy configuration to JSON file"""
        try:
            with open(self.economy_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            # Use asyncio to schedule the logging
            asyncio.create_task(self.log_economy_error(f"Error saving economy config: {e}"))

    def get_user_data(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        """Get user economy data"""
        guild_id_str = str(guild_id)
        user_id_str = str(user_id)
        
        if guild_id_str not in self.economy_db:
            self.economy_db[guild_id_str] = {}
        
        if user_id_str not in self.economy_db[guild_id_str]:
            self.economy_db[guild_id_str][user_id_str] = {
                "wallet": 1000,  # Starting money
                "bank": 0,
                "job": "unemployed",
                "last_work": 0,
                "last_daily": 0,
                "last_steal": 0,
                "inventory": {},
                "total_earned": 1000,
                "total_spent": 0
            }
        
        return self.economy_db[guild_id_str][user_id_str]

    def has_economy_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has economy admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.economy.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def format_money(self, amount: int) -> str:
        """Format money with commas and currency symbol"""
        return f"💰 {amount:,}"

    @tasks.loop(minutes=30)
    async def save_data_task(self):
        """Periodically save data"""
        self.save_economy_db()

    @tasks.loop(hours=24)
    async def apply_interest(self):
        """Apply daily interest to bank accounts"""
        interest_rate = self.config["interest_rate"]
        total_interest = 0
        users_affected = 0
        
        for guild_id, guild_data in self.economy_db.items():
            # Skip if economy is disabled for this guild
            if not self.is_economy_enabled(int(guild_id)):
                continue
                
            for user_id, user_data in guild_data.items():
                if user_data["bank"] > 0:
                    interest = int(user_data["bank"] * interest_rate)
                    user_data["bank"] += interest
                    user_data["total_earned"] += interest
                    total_interest += interest
                    users_affected += 1
        
        self.save_economy_db()
        
        # Log interest application
        await self.log_economy_action(
            "daily_interest_applied", 
            details=f"Users affected: {users_affected}, Total interest: {total_interest}"
        )

    @save_data_task.before_loop
    @apply_interest.before_loop
    async def before_loops(self):
        """Wait until bot is ready"""
        await self.bot.wait_until_ready()

    # ==================== GAME LOGIC ====================

    def create_blackjack_hand(self) -> List[str]:
        """Create a new blackjack hand"""
        cards = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        return [random.choice(cards) for _ in range(2)]

    def calculate_hand_value(self, hand: List[str]) -> int:
        """Calculate the value of a blackjack hand"""
        value = 0
        aces = 0
        
        for card in hand:
            if card in ['J', 'Q', 'K']:
                value += 10
            elif card == 'A':
                aces += 1
                value += 11
            else:
                value += int(card)
        
        # Handle aces
        while value > 21 and aces > 0:
            value -= 10
            aces -= 1
        
        return value

    def format_hand(self, hand: List[str]) -> str:
        """Format a hand for display"""
        return ' '.join(hand)

    # ==================== SLASH COMMAND GROUPS ====================

    economy_group = app_commands.Group(name="economy", description="Economy system commands")

    @economy_group.command(name="toggle", description="Toggle the economy system on/off (Admin only)")
    @app_commands.describe(enabled="Whether to enable or disable the economy system")
    async def toggle_economy(self, interaction: discord.Interaction, enabled: bool):
        """Toggle economy system"""
        if not self.has_economy_admin_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to toggle the economy system!", 
                ephemeral=True
            )
            return
        
        current_status = self.is_economy_enabled(interaction.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await interaction.response.send_message(
                f"ℹ️ The economy system is already {status_text} in this server!", 
                ephemeral=True
            )
            return
        
        self.set_economy_enabled(interaction.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_economy_action(
            "economy_toggled", 
            interaction.guild, 
            interaction.user,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Economy System {status_text.title()}",
            description=f"The economy system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="status", description="Check if the economy system is enabled")
    async def economy_status(self, interaction: discord.Interaction):
        """Check economy status"""
        enabled = self.is_economy_enabled(interaction.guild.id)
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        embed = discord.Embed(
            title=f"{status_emoji} Economy System Status",
            description=f"The economy system is currently **{status_text}** in this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="balance", description="Check your or another user's balance")
    @app_commands.describe(user="User to check balance for (optional)")
    async def balance_slash(self, interaction: discord.Interaction, user: discord.Member = None):
        """Check balance"""
        if not await self.economy_check(interaction):
            return
            
        target_user = user or interaction.user
        user_data = self.get_user_data(interaction.guild.id, target_user.id)
        
        embed = discord.Embed(
            title=f"💰 {target_user.display_name}'s Balance",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        embed.add_field(
            name="👛 Wallet",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        embed.add_field(
            name="🏦 Bank",
            value=self.format_money(user_data["bank"]),
            inline=True
        )
        embed.add_field(
            name="💎 Net Worth",
            value=self.format_money(user_data["wallet"] + user_data["bank"]),
            inline=True
        )
        
        # Job info
        job_name = self.config["jobs"][user_data["job"]]["name"]
        embed.add_field(
            name="💼 Job",
            value=job_name,
            inline=True
        )
        
        # Stats
        embed.add_field(
            name="📈 Total Earned",
            value=self.format_money(user_data["total_earned"]),
            inline=True
        )
        embed.add_field(
            name="📉 Total Spent",
            value=self.format_money(user_data["total_spent"]),
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Log balance check
        if target_user != interaction.user:
            await self.log_economy_action(
                "balance_checked", 
                interaction.guild, 
                interaction.user, 
                f"Checked balance of {target_user.name}"
            )

    @economy_group.command(name="work", description="Work at your job to earn money")
    async def work_slash(self, interaction: discord.Interaction):
        """Work at your job"""
        if not await self.economy_check(interaction):
            return
            
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        now = datetime.utcnow().timestamp()
        
        # Check cooldown
        if now - user_data["last_work"] < self.config["work_cooldown"]:
            remaining = self.config["work_cooldown"] - (now - user_data["last_work"])
            hours, remainder = divmod(int(remaining), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            await interaction.response.send_message(
                f"⏰ You need to wait {hours}h {minutes}m {seconds}s before working again!",
                ephemeral=True
            )
            return
        
        job = self.config["jobs"][user_data["job"]]
        
        # Check for work failure
        if random.random() < job["failure_rate"]:
            user_data["last_work"] = now
            self.save_economy_db()
            
            await self.log_economy_action(
                "work_failed", 
                interaction.guild, 
                interaction.user,
                f"Job: {job['name']}"
            )
            
            embed = discord.Embed(
                title="💼 Work Failed!",
                description=f"You failed at your job as a {job['name']} and earned nothing!",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed)
            return
        
        # Calculate earnings
        earnings = random.randint(job["salary_min"], job["salary_max"])
        user_data["wallet"] += earnings
        user_data["total_earned"] += earnings
        user_data["last_work"] = now
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "work_success", 
            interaction.guild, 
            interaction.user,
            f"Job: {job['name']}, Earned: {earnings}"
        )
        
        embed = discord.Embed(
            title="💼 Work Complete!",
            description=f"You worked as a {job['name']} and earned {self.format_money(earnings)}!",
            color=0x00ff00
        )
        embed.add_field(
            name="💛 New Wallet Balance",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="setjob", description="Set your job")
    @app_commands.describe(job="The job you want to apply for")
    @app_commands.choices(job=[
        app_commands.Choice(name="Unemployed", value="unemployed"),
        app_commands.Choice(name="Janitor", value="janitor"),
        app_commands.Choice(name="Cashier", value="cashier"),
        app_commands.Choice(name="Teacher", value="teacher"),
        app_commands.Choice(name="Doctor", value="doctor"),
        app_commands.Choice(name="Lawyer", value="lawyer"),
        app_commands.Choice(name="CEO", value="ceo")
    ])
    async def setjob_slash(self, interaction: discord.Interaction, job: app_commands.Choice[str]):
        """Set your job"""
        if not await self.economy_check(interaction):
            return
            
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        job_id = job.value
        
        if job_id not in self.config["jobs"]:
            await interaction.response.send_message("Invalid job!", ephemeral=True)
            return
        
        old_job = self.config["jobs"][user_data["job"]]["name"]
        new_job = self.config["jobs"][job_id]["name"]
        
        user_data["job"] = job_id
        self.save_economy_db()
        
        await self.log_economy_action(
            "job_changed", 
            interaction.guild, 
            interaction.user,
            f"From: {old_job}, To: {new_job}"
        )
        
        job_info = self.config["jobs"][job_id]
        
        embed = discord.Embed(
            title="💼 Job Set!",
            description=f"You are now working as a **{new_job}**!",
            color=0x00ff00
        )
        embed.add_field(
            name="💰 Salary Range",
            value=f"{self.format_money(job_info['salary_min'])} - {self.format_money(job_info['salary_max'])}",
            inline=True
        )
        embed.add_field(
            name="⚠️ Failure Rate",
            value=f"{job_info['failure_rate']*100:.1f}%",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="jobs", description="List all available jobs")
    async def jobs_slash(self, interaction: discord.Interaction):
        """List available jobs"""
        if not await self.economy_check(interaction):
            return
            
        embed = discord.Embed(title="💼 Available Jobs", color=0x0099ff)
        
        for job_id, job_info in self.config["jobs"].items():
            if job_id == "unemployed":
                continue
                
            salary_range = f"{self.format_money(job_info['salary_min'])} - {self.format_money(job_info['salary_max'])}"
            failure_rate = f"{job_info['failure_rate']*100:.1f}%"
            
            embed.add_field(
                name=job_info["name"],
                value=f"**Salary:** {salary_range}\n**Failure Rate:** {failure_rate}",
                inline=True
            )
        
        embed.set_footer(text="Use /economy setjob to apply for a job!")
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="deposit", description="Deposit money into your bank")
    @app_commands.describe(amount="Amount to deposit (or 'all' for everything)")
    async def deposit_slash(self, interaction: discord.Interaction, amount: str):
        """Deposit money into bank"""
        if not await self.economy_check(interaction):
            return
            
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        if amount.lower() == "all":
            deposit_amount = user_data["wallet"]
        else:
            try:
                deposit_amount = int(amount)
            except ValueError:
                await interaction.response.send_message("Invalid amount!", ephemeral=True)
                return
        
        if deposit_amount <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        if deposit_amount > user_data["wallet"]:
            await interaction.response.send_message("You don't have enough money in your wallet!", ephemeral=True)
            return
        
        max_storage = self.config["max_bank_storage"]
        if user_data["bank"] + deposit_amount > max_storage:
            await interaction.response.send_message(f"Bank storage limit is {self.format_money(max_storage)}!", ephemeral=True)
            return
        
        user_data["wallet"] -= deposit_amount
        user_data["bank"] += deposit_amount
        self.save_economy_db()
        
        await self.log_economy_action(
            "deposit", 
            interaction.guild, 
            interaction.user,
            f"Amount: {deposit_amount}"
        )
        
        embed = discord.Embed(
            title="🏦 Deposit Successful!",
            description=f"Deposited {self.format_money(deposit_amount)} into your bank!",
            color=0x00ff00
        )
        embed.add_field(
            name="👛 Wallet",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        embed.add_field(
            name="🏦 Bank",
            value=self.format_money(user_data["bank"]),
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="withdraw", description="Withdraw money from your bank")
    @app_commands.describe(amount="Amount to withdraw (or 'all' for everything)")
    async def withdraw_slash(self, interaction: discord.Interaction, amount: str):
        """Withdraw money from bank"""
        if not await self.economy_check(interaction):
            return
            
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        if amount.lower() == "all":
            withdraw_amount = user_data["bank"]
        else:
            try:
                withdraw_amount = int(amount)
            except ValueError:
                await interaction.response.send_message("Invalid amount!", ephemeral=True)
                return
        
        if withdraw_amount <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        if withdraw_amount > user_data["bank"]:
            await interaction.response.send_message("You don't have enough money in your bank!", ephemeral=True)
            return
        
        user_data["bank"] -= withdraw_amount
        user_data["wallet"] += withdraw_amount
        self.save_economy_db()
        
        await self.log_economy_action(
            "withdraw", 
            interaction.guild, 
            interaction.user,
            f"Amount: {withdraw_amount}"
        )
        
        embed = discord.Embed(
            title="🏦 Withdrawal Successful!",
            description=f"Withdrew {self.format_money(withdraw_amount)} from your bank!",
            color=0x00ff00
        )
        embed.add_field(
            name="👛 Wallet",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        embed.add_field(
            name="🏦 Bank",
            value=self.format_money(user_data["bank"]),
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="donate", description="Donate money to another user")
    @app_commands.describe(
        user="User to donate to",
        amount="Amount to donate"
    )
    async def donate_slash(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        """Donate money to another user"""
        if not await self.economy_check(interaction):
            return
            
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't donate to yourself!", ephemeral=True)
            return
        
        if user.bot:
            await interaction.response.send_message("You can't donate to bots!", ephemeral=True)
            return
        
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        donor_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        recipient_data = self.get_user_data(interaction.guild.id, user.id)
        
        if donor_data["wallet"] < amount:
            await interaction.response.send_message("You don't have enough money!", ephemeral=True)
            return
        
        donor_data["wallet"] -= amount
        donor_data["total_spent"] += amount
        recipient_data["wallet"] += amount
        recipient_data["total_earned"] += amount
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "donation", 
            interaction.guild, 
            interaction.user,
            f"To: {user.name}, Amount: {amount}"
        )
        
        embed = discord.Embed(
            title="💝 Donation Successful!",
            description=f"{interaction.user.mention} donated {self.format_money(amount)} to {user.mention}!",
            color=0x00ff00
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="steal", description="Attempt to steal money from another user")
    @app_commands.describe(user="User to steal from")
    async def steal_slash(self, interaction: discord.Interaction, user: discord.Member):
        """Steal from another user"""
        if not await self.economy_check(interaction):
            return
            
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't steal from yourself!", ephemeral=True)
            return
        
        if user.bot:
            await interaction.response.send_message("You can't steal from bots!", ephemeral=True)
            return
        
        thief_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        victim_data = self.get_user_data(interaction.guild.id, user.id)
        
        now = datetime.utcnow().timestamp()
        
        # Check cooldown
        if now - thief_data["last_steal"] < self.config["steal_cooldown"]:
            remaining = self.config["steal_cooldown"] - (now - thief_data["last_steal"])
            hours, remainder = divmod(int(remaining), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            await interaction.response.send_message(
                f"⏰ You need to wait {hours}h {minutes}m {seconds}s before stealing again!",
                ephemeral=True
            )
            return
        
        thief_data["last_steal"] = now
        
        # Check if victim has money
        if victim_data["wallet"] <= 0:
            await interaction.response.send_message(f"{user.display_name} has no money to steal!", ephemeral=True)
            return
        
        # Determine success
        success = random.random() < self.config["steal_success_rate"]
        
        if success:
            # Successful steal
            stolen_amount = min(victim_data["wallet"], random.randint(50, 500))
            thief_data["wallet"] += stolen_amount
            thief_data["total_earned"] += stolen_amount
            victim_data["wallet"] -= stolen_amount
            
            await self.log_economy_action(
                "steal_success", 
                interaction.guild, 
                interaction.user,
                f"From: {user.name}, Amount: {stolen_amount}"
            )
            
            embed = discord.Embed(
                title="🔓 Theft Successful!",
                description=f"You successfully stole {self.format_money(stolen_amount)} from {user.display_name}!",
                color=0x00ff00
            )
        else:
            # Failed steal - pay fine
            fine = self.config["steal_fine"]
            if thief_data["wallet"] >= fine:
                thief_data["wallet"] -= fine
                thief_data["total_spent"] += fine
            
            await self.log_economy_action(
                "steal_failed", 
                interaction.guild, 
                interaction.user,
                f"Target: {user.name}, Fine: {fine}"
            )
            
            embed = discord.Embed(
                title="🚨 Theft Failed!",
                description=f"You were caught trying to steal from {user.display_name} and paid a fine of {self.format_money(fine)}!",
                color=0xff0000
            )
        
        self.save_economy_db()
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="blackjack", description="Play interactive blackjack against the bot")
    @app_commands.describe(amount="Amount to bet")
    async def blackjack_slash(self, interaction: discord.Interaction, amount: int):
        """Play interactive blackjack"""
        if not await self.economy_check(interaction):
            return
            
        if amount <= 0:
            await interaction.response.send_message("Bet amount must be positive!", ephemeral=True)
            return
        
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        if user_data["wallet"] < amount:
            await interaction.response.send_message("You don't have enough money!", ephemeral=True)
            return
        
        # Deduct bet from wallet
        user_data["wallet"] -= amount
        self.save_economy_db()
        
        # Create hands
        player_hand = self.create_blackjack_hand()
        dealer_hand = self.create_blackjack_hand()
        
        player_value = self.calculate_hand_value(player_hand)
        dealer_value = self.calculate_hand_value(dealer_hand)
        
        # Check for immediate blackjack
        if player_value == 21:
            if dealer_value == 21:
                # Push - return bet
                user_data["wallet"] += amount
                self.save_economy_db()
                
                embed = discord.Embed(title="🃏 Blackjack", color=0xffff00)
                embed.add_field(
                    name=f"Your Hand ({player_value})",
                    value=self.format_hand(player_hand),
                    inline=True
                )
                embed.add_field(
                    name=f"Dealer's Hand ({dealer_value})",
                    value=self.format_hand(dealer_hand),
                    inline=True
                )
                embed.add_field(name="Result", value="Push! Both have blackjack!", inline=False)
                embed.add_field(
                    name="New Balance",
                    value=self.format_money(user_data["wallet"]),
                    inline=True
                )
                
                await interaction.response.send_message(embed=embed)
                return
            else:
                # Player blackjack wins (1.5x payout)
                winnings = int(amount * 2.5)  # Original bet + 1.5x
                user_data["wallet"] += winnings
                user_data["total_earned"] += int(amount * 1.5)
                self.save_economy_db()
                
                embed = discord.Embed(title="🃏 Blackjack", color=0x00ff00)
                embed.add_field(
                    name=f"Your Hand ({player_value})",
                    value=self.format_hand(player_hand),
                    inline=True
                )
                embed.add_field(
                    name=f"Dealer's Hand ({dealer_value})",
                    value=self.format_hand(dealer_hand),
                    inline=True
                )
                embed.add_field(name="Result", value="Blackjack! You win! 🎉", inline=False)
                embed.add_field(
                    name="New Balance",
                    value=self.format_money(user_data["wallet"]),
                    inline=True
                )
                
                await self.log_economy_action(
                    "blackjack", 
                    interaction.guild, 
                    interaction.user,
                    f"Bet: {amount}, Blackjack win: +{int(amount * 1.5)}"
                )
                
                await interaction.response.send_message(embed=embed)
                return
        
        # Create interactive view
        view = BlackjackView(
            interaction.user.id, 
            amount, 
            player_hand, 
            dealer_hand, 
            self
        )
        
        embed = view.get_embed(interaction)
        embed.set_footer(text="Use the buttons below to play! You have 60 seconds.")
        
        await interaction.response.send_message(embed=embed, view=view)

    @economy_group.command(name="roll", description="Play a dice roll game")
    @app_commands.describe(amount="Amount to bet")
    async def roll_slash(self, interaction: discord.Interaction, amount: int):
        """Play dice roll game"""
        if not await self.economy_check(interaction):
            return
            
        if amount <= 0:
            await interaction.response.send_message("Bet amount must be positive!", ephemeral=True)
            return
        
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        if user_data["wallet"] < amount:
            await interaction.response.send_message("You don't have enough money!", ephemeral=True)
            return
        
        player_roll = random.randint(1, 6)
        bot_roll = random.randint(1, 6)
        
        embed = discord.Embed(title="🎲 Dice Roll", color=0x0099ff)
        embed.add_field(name="Your Roll", value=f"🎲 {player_roll}", inline=True)
        embed.add_field(name="Bot's Roll", value=f"🎲 {bot_roll}", inline=True)
        embed.add_field(name="Bet", value=self.format_money(amount), inline=True)
        
        if player_roll > bot_roll:
            result = "You win!"
            winnings = amount
            color = 0x00ff00
        elif bot_roll > player_roll:
            result = "Bot wins!"
            winnings = -amount
            color = 0xff0000
        else:
            result = "It's a tie!"
            winnings = 0
            color = 0xffff00
        
        # Update user data
        user_data["wallet"] += winnings
        if winnings > 0:
            user_data["total_earned"] += winnings
        elif winnings < 0:
            user_data["total_spent"] += abs(winnings)
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "dice_roll", 
            interaction.guild, 
            interaction.user,
            f"Bet: {amount}, Player: {player_roll}, Bot: {bot_roll}, Result: {winnings}"
        )
        
        embed.add_field(name="Result", value=result, inline=False)
        embed.add_field(
            name="New Balance",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        embed.color = color
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="coinflip", description="Play a coin flip game")
    @app_commands.describe(
        amount="Amount to bet",
        choice="Your choice: heads or tails"
    )
    @app_commands.choices(choice=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails")
    ])
    async def coinflip_slash(self, interaction: discord.Interaction, amount: int, choice: app_commands.Choice[str]):
        """Play coinflip game"""
        if not await self.economy_check(interaction):
            return
            
        if amount <= 0:
            await interaction.response.send_message("Bet amount must be positive!", ephemeral=True)
            return
        
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        if user_data["wallet"] < amount:
            await interaction.response.send_message("You don't have enough money!", ephemeral=True)
            return
        
        result = random.choice(["heads", "tails"])
        user_choice = choice.value
        
        embed = discord.Embed(title="🪙 Coin Flip", color=0x0099ff)
        embed.add_field(name="Your Choice", value=user_choice.title(), inline=True)
        embed.add_field(name="Result", value=result.title(), inline=True)
        embed.add_field(name="Bet", value=self.format_money(amount), inline=True)
        
        if user_choice == result:
            outcome = "You win!"
            winnings = amount
            color = 0x00ff00
        else:
            outcome = "You lose!"
            winnings = -amount
            color = 0xff0000
        
        # Update user data
        user_data["wallet"] += winnings
        if winnings > 0:
            user_data["total_earned"] += winnings
        elif winnings < 0:
            user_data["total_spent"] += abs(winnings)
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "coinflip", 
            interaction.guild, 
            interaction.user,
            f"Bet: {amount}, Choice: {user_choice}, Result: {result}, Winnings: {winnings}"
        )
        
        embed.add_field(name="Outcome", value=outcome, inline=False)
        embed.add_field(
            name="New Balance",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        embed.color = color
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="slots", description="Play the slot machine")
    @app_commands.describe(amount="Amount to bet")
    async def slots_slash(self, interaction: discord.Interaction, amount: int):
        """Play slots"""
        if not await self.economy_check(interaction):
            return
            
        if amount <= 0:
            await interaction.response.send_message("Bet amount must be positive!", ephemeral=True)
            return
        
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        if user_data["wallet"] < amount:
            await interaction.response.send_message("You don't have enough money!", ephemeral=True)
            return
        
        slots = ['🍒', '🍋', '🍊', '🍇', '🔔', '💎', '7️⃣']
        result = [random.choice(slots) for _ in range(3)]
        
        # Calculate winnings
        if result[0] == result[1] == result[2]:
            if result[0] == '💎':
                multiplier = 10
            elif result[0] == '7️⃣':
                multiplier = 5
            else:
                multiplier = 3
        elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
            multiplier = 1.5
        else:
            multiplier = 0
        
        winnings = int(amount * multiplier) - amount
        
        embed = discord.Embed(title="🎰 Slot Machine", color=0x0099ff)
        embed.add_field(
            name="Result",
            value=f"[ {' | '.join(result)} ]",
            inline=False
        )
        embed.add_field(name="Bet", value=self.format_money(amount), inline=True)
        
        if winnings > 0:
            embed.add_field(name="You Win!", value=self.format_money(winnings), inline=True)
            embed.color = 0x00ff00
        elif winnings == 0:
            embed.add_field(name="No Win", value="Better luck next time!", inline=True)
            embed.color = 0xffff00
        else:
            embed.add_field(name="You Lose!", value=self.format_money(abs(winnings)), inline=True)
            embed.color = 0xff0000
        
        # Update user data
        user_data["wallet"] += winnings
        if winnings > 0:
            user_data["total_earned"] += winnings
        elif winnings < 0:
            user_data["total_spent"] += abs(winnings)
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "slots", 
            interaction.guild, 
            interaction.user,
            f"Bet: {amount}, Result: {' '.join(result)}, Winnings: {winnings}"
        )
        
        embed.add_field(
            name="New Balance",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="daily", description="Claim your daily reward")
    async def daily_slash(self, interaction: discord.Interaction):
        """Claim daily reward"""
        if not await self.economy_check(interaction):
            return
            
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        now = datetime.utcnow().timestamp()
        
        # Check cooldown
        if now - user_data["last_daily"] < self.config["daily_cooldown"]:
            remaining = self.config["daily_cooldown"] - (now - user_data["last_daily"])
            hours, remainder = divmod(int(remaining), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            await interaction.response.send_message(
                f"⏰ You need to wait {hours}h {minutes}m {seconds}s before claiming your daily reward!",
                ephemeral=True
            )
            return
        
        # Calculate reward
        daily_min = self.config["daily_reward"]["min"]
        daily_max = self.config["daily_reward"]["max"]
        reward = random.randint(daily_min, daily_max)
        
        user_data["wallet"] += reward
        user_data["total_earned"] += reward
        user_data["last_daily"] = now
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "daily_claimed", 
            interaction.guild, 
            interaction.user,
            f"Amount: {reward}"
        )
        
        embed = discord.Embed(
            title="🎁 Daily Reward Claimed!",
            description=f"You received {self.format_money(reward)}!",
            color=0x00ff00
        )
        embed.add_field(
            name="💛 New Wallet Balance",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="leaderboard", description="View the server's richest users")
    @app_commands.describe(
        category="What to rank by"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="Net Worth", value="net_worth"),
        app_commands.Choice(name="Wallet", value="wallet"),
        app_commands.Choice(name="Bank", value="bank"),
        app_commands.Choice(name="Total Earned", value="total_earned")
    ])
    async def leaderboard_slash(self, interaction: discord.Interaction, 
                                category: app_commands.Choice[str] = None):
        """Show economy leaderboard"""
        if not await self.economy_check(interaction):
            return
            
        await interaction.response.defer()
        
        category_value = category.value if category else "net_worth"
        guild_data = self.economy_db.get(str(interaction.guild.id), {})
        
        if not guild_data:
            await interaction.followup.send("No economy data found for this server!")
            return
        
        # Calculate values and sort
        user_values = []
        for user_id, data in guild_data.items():
            if category_value == "net_worth":
                value = data["wallet"] + data["bank"]
            else:
                value = data[category_value]
            
            user_values.append((int(user_id), value))
        
        # Sort by value
        user_values.sort(key=lambda x: x[1], reverse=True)
        
        # Create embed
        category_names = {
            "net_worth": "💎 Net Worth",
            "wallet": "👛 Wallet",
            "bank": "🏦 Bank",
            "total_earned": "📈 Total Earned"
        }
        
        embed = discord.Embed(
            title=f"{category_names[category_value]} Leaderboard",
            color=0xffd700
        )
        
        for i, (user_id, value) in enumerate(user_values[:10]):
            user = self.bot.get_user(user_id)
            user_name = user.display_name if user else f"Unknown User ({user_id})"
            
            rank_emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
            embed.add_field(
                name=f"{rank_emoji} {user_name}",
                value=self.format_money(value),
                inline=False
            )
        
        embed.set_footer(text=f"Showing top 10 users • Total users: {len(user_values)}")
        await interaction.followup.send(embed=embed)

    @economy_group.command(name="resetbal", description="Reset a user's balance (Admin only)")
    @app_commands.describe(
        user="User to reset balance for",
        balance_type="What to reset"
    )
    @app_commands.choices(balance_type=[
        app_commands.Choice(name="Wallet", value="wallet"),
        app_commands.Choice(name="Bank", value="bank"),
        app_commands.Choice(name="Both", value="both")
    ])
    async def resetbal_slash(self, interaction: discord.Interaction, 
                            user: discord.Member, 
                            balance_type: app_commands.Choice[str]):
        """Reset user balance (admin only)"""
        if not await self.economy_check(interaction):
            return
            
        if not self.has_economy_admin_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to reset balances!", ephemeral=True)
            return
        
        user_data = self.get_user_data(interaction.guild.id, user.id)
        reset_type = balance_type.value
        
        old_wallet = user_data["wallet"]
        old_bank = user_data["bank"]
        
        if reset_type in ["wallet", "both"]:
            user_data["wallet"] = 1000  # Starting amount
        if reset_type in ["bank", "both"]:
            user_data["bank"] = 0
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "balance_reset", 
            interaction.guild, 
            interaction.user,
            f"Target: {user.name}, Type: {reset_type}, Old: W{old_wallet}/B{old_bank}, New: W{user_data['wallet']}/B{user_data['bank']}"
        )
        
        embed = discord.Embed(
            title="💰 Balance Reset",
            description=f"Reset {user.mention}'s {reset_type} balance!",
            color=0xff9900
        )
        embed.add_field(
            name="New Balance",
            value=f"👛 Wallet: {self.format_money(user_data['wallet'])}\n🏦 Bank: {self.format_money(user_data['bank'])}",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="resetbal-all", description="Reset all users' balances (Admin only)")
    @app_commands.describe(balance_type="What to reset for all users")
    @app_commands.choices(balance_type=[
        app_commands.Choice(name="Wallet", value="wallet"),
        app_commands.Choice(name="Bank", value="bank"),
        app_commands.Choice(name="Both", value="both")
    ])
    async def resetbal_all_slash(self, interaction: discord.Interaction, 
                                balance_type: app_commands.Choice[str]):
        """Reset all users' balances (admin only)"""
        if not await self.economy_check(interaction):
            return
            
        if not self.has_economy_admin_permission(interaction.user):
            await interaction.response.send_message("You don't have permission to reset balances!", ephemeral=True)
            return
        
        # Confirmation
        embed = discord.Embed(
            title="⚠️ Confirm Mass Reset",
            description=f"Are you sure you want to reset **{balance_type.name.lower()}** for **ALL USERS** in this server?\n\nThis action cannot be undone!",
            color=0xff0000
        )
        
        view = ConfirmationView()
        await interaction.response.send_message(embed=embed, view=view)
        
        # Wait for confirmation
        await view.wait()
        
        if view.confirmed:
            guild_data = self.economy_db.get(str(interaction.guild.id), {})
            reset_type = balance_type.value
            user_count = len(guild_data)
            
            for user_data in guild_data.values():
                if reset_type in ["wallet", "both"]:
                    user_data["wallet"] = 1000  # Starting amount
                if reset_type in ["bank", "both"]:
                    user_data["bank"] = 0
            
            self.save_economy_db()
            
            await self.log_economy_action(
                "mass_balance_reset", 
                interaction.guild, 
                interaction.user,
                f"Type: {reset_type}, Users affected: {user_count}"
            )
            
            embed = discord.Embed(
                title="✅ Mass Reset Complete",
                description=f"Reset {balance_type.name.lower()} for **{user_count}** users in this server!",
                color=0xff9900
            )
            await interaction.edit_original_response(embed=embed, view=None)
        else:
            embed = discord.Embed(
                title="❌ Reset Cancelled",
                description="No balances were reset.",
                color=0x808080
            )
            await interaction.edit_original_response(embed=embed, view=None)

    # ==================== PREFIX COMMANDS ====================

    @commands.group(name="economy", aliases=['eco', 'money'], invoke_without_command=True)
    async def economy(self, ctx):
        """Economy system commands"""
        if not self.is_economy_enabled(ctx.guild.id):
            await ctx.send("❌ The economy system is currently disabled in this server!")
            return
            
        embed = discord.Embed(title="💰 Economy System", color=0x00ff00)
        embed.add_field(
            name="Basic Commands",
            value="balance, work, setjob, jobs, daily",
            inline=False
        )
        embed.add_field(
            name="Banking",
            value="deposit, withdraw, donate",
            inline=False
        )
        embed.add_field(
            name="Games",
            value="blackjack, roll, coinflip, slots",
            inline=False
        )
        embed.add_field(
            name="Other",
            value="steal, leaderboard",
            inline=False
        )
        embed.add_field(
            name="Admin Commands",
            value="toggle, resetbal, resetbal-all",
            inline=False
        )
        embed.add_field(
            name="Slash Commands",
            value="Use `/economy` for organized slash commands!",
            inline=False
        )
        await ctx.send(embed=embed)

    @economy.command(name="balance", aliases=['bal'])
    async def balance(self, ctx, user: discord.Member = None):
        """Check balance"""
        if not self.is_economy_enabled(ctx.guild.id):
            await ctx.send("❌ The economy system is currently disabled in this server!")
            return
            
        target_user = user or ctx.author
        user_data = self.get_user_data(ctx.guild.id, target_user.id)
        
        embed = discord.Embed(
            title=f"💰 {target_user.display_name}'s Balance",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        embed.add_field(
            name="👛 Wallet",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        embed.add_field(
            name="🏦 Bank",
            value=self.format_money(user_data["bank"]),
            inline=True
        )
        embed.add_field(
            name="💎 Net Worth",
            value=self.format_money(user_data["wallet"] + user_data["bank"]),
            inline=True
        )
        
        await ctx.send(embed=embed)
        
        # Log balance check
        if target_user != ctx.author:
            await self.log_economy_action(
                "balance_checked", 
                ctx.guild, 
                ctx.author, 
                f"Checked balance of {target_user.name}"
            )

    @economy.command(name="work")
    async def work(self, ctx):
        """Work at your job"""
        if not self.is_economy_enabled(ctx.guild.id):
            await ctx.send("❌ The economy system is currently disabled in this server!")
            return
            
        user_data = self.get_user_data(ctx.guild.id, ctx.author.id)
        now = datetime.utcnow().timestamp()
        
        # Check cooldown
        if now - user_data["last_work"] < self.config["work_cooldown"]:
            remaining = self.config["work_cooldown"] - (now - user_data["last_work"])
            hours, remainder = divmod(int(remaining), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            await ctx.send(f"⏰ You need to wait {hours}h {minutes}m {seconds}s before working again!")
            return
        
        job = self.config["jobs"][user_data["job"]]
        
        # Check for work failure
        if random.random() < job["failure_rate"]:
            user_data["last_work"] = now
            self.save_economy_db()
            
            await self.log_economy_action(
                "work_failed", 
                ctx.guild, 
                ctx.author,
                f"Job: {job['name']}"
            )
            
            embed = discord.Embed(
                title="💼 Work Failed!",
                description=f"You failed at your job as a {job['name']} and earned nothing!",
                color=0xff0000
            )
            await ctx.send(embed=embed)
            return
        
        # Calculate earnings
        earnings = random.randint(job["salary_min"], job["salary_max"])
        user_data["wallet"] += earnings
        user_data["total_earned"] += earnings
        user_data["last_work"] = now
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "work_success", 
            ctx.guild, 
            ctx.author,
            f"Job: {job['name']}, Earned: {earnings}"
        )
        
        embed = discord.Embed(
            title="💼 Work Complete!",
            description=f"You worked as a {job['name']} and earned {self.format_money(earnings)}!",
            color=0x00ff00
        )
        embed.add_field(
            name="💛 New Wallet Balance",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        
        await ctx.send(embed=embed)

    @economy.command(name="daily")
    async def daily(self, ctx):
        """Claim daily reward"""
        if not self.is_economy_enabled(ctx.guild.id):
            await ctx.send("❌ The economy system is currently disabled in this server!")
            return
            
        user_data = self.get_user_data(ctx.guild.id, ctx.author.id)
        now = datetime.utcnow().timestamp()
        
        # Check cooldown
        if now - user_data["last_daily"] < self.config["daily_cooldown"]:
            remaining = self.config["daily_cooldown"] - (now - user_data["last_daily"])
            hours, remainder = divmod(int(remaining), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            await ctx.send(f"⏰ You need to wait {hours}h {minutes}m {seconds}s before claiming your daily reward!")
            return
        
        # Calculate reward
        daily_min = self.config["daily_reward"]["min"]
        daily_max = self.config["daily_reward"]["max"]
        reward = random.randint(daily_min, daily_max)
        
        user_data["wallet"] += reward
        user_data["total_earned"] += reward
        user_data["last_daily"] = now
        
        self.save_economy_db()
        
        await self.log_economy_action(
            "daily_claimed", 
            ctx.guild, 
            ctx.author,
            f"Amount: {reward}"
        )
        
        embed = discord.Embed(
            title="🎁 Daily Reward Claimed!",
            description=f"You received {self.format_money(reward)}!",
            color=0x00ff00
        )
        embed.add_field(
            name="💛 New Wallet Balance",
            value=self.format_money(user_data["wallet"]),
            inline=True
        )
        
        await ctx.send(embed=embed)

    @economy.command(name="toggle")
    async def toggle_economy_prefix(self, ctx, enabled: bool = None):
        """Toggle economy system (Admin only)"""
        if not self.has_economy_admin_permission(ctx.author):
            await ctx.send("❌ You don't have permission to toggle the economy system!")
            return
        
        if enabled is None:
            current_status = self.is_economy_enabled(ctx.guild.id)
            status_text = "enabled" if current_status else "disabled"
            status_emoji = "✅" if current_status else "❌"
            
            embed = discord.Embed(
                title=f"{status_emoji} Economy System Status",
                description=f"The economy system is currently **{status_text}** in this server.",
                color=0x00ff00 if current_status else 0xff0000
            )
            await ctx.send(embed=embed)
            return
        
        current_status = self.is_economy_enabled(ctx.guild.id)
        
        if current_status == enabled:
            status_text = "enabled" if enabled else "disabled"
            await ctx.send(f"ℹ️ The economy system is already {status_text} in this server!")
            return
        
        self.set_economy_enabled(ctx.guild.id, enabled)
        
        status_text = "enabled" if enabled else "disabled"
        status_emoji = "✅" if enabled else "❌"
        
        await self.log_economy_action(
            "economy_toggled", 
            ctx.guild, 
            ctx.author,
            f"Status: {status_text}"
        )
        
        embed = discord.Embed(
            title=f"{status_emoji} Economy System {status_text.title()}",
            description=f"The economy system has been **{status_text}** for this server.",
            color=0x00ff00 if enabled else 0xff0000
        )
        
        await ctx.send(embed=embed)

    # Error handling
    @economy.error
    async def economy_error(self, ctx, error):
        await self.log_economy_error(f"Economy command error: {error}", ctx.guild, ctx.author)
        
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing required argument: `{error.param.name}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument provided: {error}")
        else:
            await ctx.send(f"An error occurred: {error}")

class ConfirmationView(discord.ui.View):
    """View for confirmation dialogs"""
    
    def __init__(self):
        super().__init__(timeout=30)
        self.confirmed = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()

    async def on_timeout(self):
        self.confirmed = False

async def setup(bot):
    await bot.add_cog(EconomyCog(bot))
