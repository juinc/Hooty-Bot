"""
Discord TODCog - Truth or Dare, Would You Rather, Never Have I Ever

OVERVIEW:
A fun, interactive Truth or Dare (TOD) cog for Discord.  
Includes Truth, Dare, Would You Rather, Never Have I Ever, and random question modes.  
Supports custom questions, per-guild enable/disable, and both slash and prefix commands.

SETUP:
- No manual setup required – auto-creates config at src/config/TOD_config.json
- Optional: PermissionsCog (for admin checks)

PERMISSIONS:
- Admin commands require 'permissions.tod.admin' or Administrator

COMMANDS (Slash & Prefix):
/tod enable/disable                  - Enable or disable TOD in this server (admin)
/tod question <category>             - Get a random question (truth, dare, tod, would you rather, never have i ever)
/tod config                          - View current TOD configuration

Custom Questions:
/tod custom-questions list <cat>     - List custom questions for a category (admin)
/tod custom-questions add <cat> <q>  - Add a custom question (admin)
/tod custom-questions remove <cat> <q> - Remove a custom question (admin)
/tod custom-questions clear <cat>    - Remove all custom questions for a category (admin)

Prefix commands: !tod <subcommand> (same as above)

COMMAND EXPLANATIONS:
- enable/disable: Enable or disable the TOD system for your server.
- question: Get a random question from the selected category.
- config: Show system status and question stats.
- custom-questions: Manage custom questions for each category (admin only).

FEATURES:
• Truth, Dare, Would You Rather, Never Have I Ever, and random question modes
• Interactive buttons for more questions (with persistent views)
• Custom questions per category (add, remove, list, clear)
• Per-guild enable/disable
• Both slash and prefix command support
• Permission checks (if PermissionsCog present)
• Persistent, per-guild config and questions (JSON)
• Autocomplete for categories and custom questions
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
from typing import List
from enum import Enum

class QuestionCategory(Enum):
    TRUTH = "truth"
    DARE = "dare"
    TOD = "tod"
    WOULD_YOU_RATHER = "would you rather"
    NEVER_HAVE_I = "never have i ever"

class TODView(discord.ui.View):
    def __init__(self, cog, category: QuestionCategory):
        super().__init__(timeout=300)
        self.cog = cog
        self.category = category
        
        # Add appropriate buttons based on category
        if category == QuestionCategory.TOD:
            self.add_item(TODButton(self.cog, QuestionCategory.TRUTH, "Truth", discord.ButtonStyle.primary))
            self.add_item(TODButton(self.cog, QuestionCategory.DARE, "Dare", discord.ButtonStyle.danger))
            self.add_item(TODButton(self.cog, QuestionCategory.TOD, "Random", discord.ButtonStyle.secondary))
        elif category == QuestionCategory.WOULD_YOU_RATHER:
            self.add_item(TODButton(self.cog, QuestionCategory.WOULD_YOU_RATHER, "Another Would You Rather", discord.ButtonStyle.primary))
        elif category == QuestionCategory.NEVER_HAVE_I:
            self.add_item(TODButton(self.cog, QuestionCategory.NEVER_HAVE_I, "Another Never Have I Ever", discord.ButtonStyle.primary))
        else:  # Truth or Dare
            self.add_item(TODButton(self.cog, QuestionCategory.TRUTH, "Truth", discord.ButtonStyle.primary))
            self.add_item(TODButton(self.cog, QuestionCategory.DARE, "Dare", discord.ButtonStyle.danger))
            self.add_item(TODButton(self.cog, QuestionCategory.TOD, "Random", discord.ButtonStyle.secondary))

class TODButton(discord.ui.Button):
    def __init__(self, cog, category: QuestionCategory, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.cog = cog
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        # Check if TOD is enabled for this guild
        guild_config = self.cog._get_guild_config(interaction.guild.id)
        if not guild_config.get("enabled", True):
            await interaction.response.send_message("❌ Truth or Dare is currently disabled in this server.", ephemeral=True)
            return
        
        # Send a new message instead of editing the existing one
        await self.cog._send_question(interaction, self.category, new_message=True)

class TODCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_dir = "src/config"
        
        # Ensure directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # File path
        self.tod_config_path = os.path.join(self.config_dir, "TOD_config.json")
        
        # Initialize config file
        self._init_config_file()

    def _init_config_file(self):
        """Initialize config file with default questions"""
        default_config = {
            "guilds": {},
            "default_questions": {
                "truth": [
                    "What's the most embarrassing thing that's ever happened to you?",
                    "What's your biggest fear?",
                    "What's the weirdest dream you've ever had?",
                    "What's your most embarrassing childhood memory?",
                    "What's something you've never told anyone?",
                    "What's your biggest regret?",
                    "What's the most childish thing you still do?",
                    "What's your worst habit?",
                    "What's something you're glad your family doesn't know about you?",
                    "What's the most trouble you've ever been in?",
                    "What's your biggest pet peeve?",
                    "What's the strangest thing you believed as a child?",
                    "What's your most irrational fear?",
                    "What's something you do when you're alone that you wouldn't want others to see?",
                    "What's the most embarrassing thing in your search history?"
                ],
                "dare": [
                    "Do your best impression of a celebrity.",
                    "Sing the chorus of your favorite song.",
                    "Do 20 push-ups.",
                    "Call a random contact and sing them 'Happy Birthday'.",
                    "Post an embarrassing photo of yourself.",
                    "Do your best dance for 30 seconds.",
                    "Speak in an accent for the next 3 rounds.",
                    "Do a handstand for 30 seconds.",
                    "Tell a joke in a funny voice.",
                    "Imitate someone in the group until someone guesses who it is.",
                    "Do your best animal impression.",
                    "Recite the alphabet backwards.",
                    "Do 10 jumping jacks while singing a song.",
                    "Balance a book on your head for 2 minutes.",
                    "Do your best robot dance."
                ],
                "would you rather": [
                    "Would you rather have the ability to fly or be invisible?",
                    "Would you rather have unlimited money or unlimited time?",
                    "Would you rather be able to read minds or predict the future?",
                    "Would you rather live without music or without movies?",
                    "Would you rather have super strength or super speed?",
                    "Would you rather be famous or rich?",
                    "Would you rather live in the past or the future?",
                    "Would you rather have the ability to teleport or time travel?",
                    "Would you rather be able to speak any language or play any instrument?",
                    "Would you rather live in space or underwater?",
                    "Would you rather have a rewind button or a pause button for your life?",
                    "Would you rather be able to change the past or see the future?",
                    "Would you rather have unlimited pizza or unlimited tacos?",
                    "Would you rather be a genius or be famous?",
                    "Would you rather live in a world without internet or without air conditioning?"
                ],
                "never have i ever": [
                    "Never have I ever stayed up all night gaming.",
                    "Never have I ever forgotten someone's name right after being introduced.",
                    "Never have I ever pretended to be sick to get out of something.",
                    "Never have I ever laughed so hard I cried.",
                    "Never have I ever had a crush on a fictional character.",
                    "Never have I ever eaten something that fell on the floor.",
                    "Never have I ever talked to myself in the mirror.",
                    "Never have I ever googled myself.",
                    "Never have I ever tried to look cool and failed miserably.",
                    "Never have I ever fallen asleep during a movie.",
                    "Never have I ever stalked someone on social media.",
                    "Never have I ever lied about my age.",
                    "Never have I ever broken something and blamed someone else.",
                    "Never have I ever had an imaginary friend.",
                    "Never have I ever cried during a kids' movie."
                ]
            },
            "custom_questions": {
                "truth": [],
                "dare": [],
                "would you rather": [],
                "never have i ever": []
            }
        }
        
        if not os.path.exists(self.tod_config_path):
            with open(self.tod_config_path, 'w') as f:
                json.dump(default_config, f, indent=4)

    def _load_config(self) -> dict:
        """Load TOD configuration from file"""
        try:
            with open(self.tod_config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._init_config_file()
            with open(self.tod_config_path, 'r') as f:
                return json.load(f)

    def _save_config(self, data: dict):
        """Save TOD configuration to file"""
        with open(self.tod_config_path, 'w') as f:
            json.dump(data, f, indent=4)

    def _get_guild_config(self, guild_id: int) -> dict:
        """Get or create guild TOD configuration"""
        config = self._load_config()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in config["guilds"]:
            config["guilds"][guild_id_str] = {
                "enabled": True  # TOD enabled by default
            }
            self._save_config(config)
        
        return config["guilds"][guild_id_str]

    def has_tod_admin_permission(self, member: discord.Member) -> bool:
        """Check if member has TOD admin permission"""
        permissions_cog = self.bot.get_cog('PermissionsCog')
        if not permissions_cog:
            return member.guild_permissions.administrator
        
        return (permissions_cog.has_permission(member, 'permissions.tod.admin') or 
                permissions_cog.has_permission(member, "permissions.omni"))

    def _get_random_question(self, category: QuestionCategory) -> str:
        """Get a random question from the specified category"""
        config = self._load_config()
        
        if category == QuestionCategory.TOD:
            # For TOD, randomly choose between truth and dare
            actual_category = random.choice([QuestionCategory.TRUTH, QuestionCategory.DARE])
            category_str = actual_category.value
        else:
            category_str = category.value
        
        # Combine default and custom questions
        default_questions = config["default_questions"].get(category_str, [])
        custom_questions = config["custom_questions"].get(category_str, [])
        all_questions = default_questions + custom_questions
        
        if not all_questions:
            return f"No questions available for {category_str}!"
        
        return random.choice(all_questions)

    def _get_category_color(self, category: QuestionCategory) -> discord.Color:
        """Get embed color based on category"""
        color_map = {
            QuestionCategory.TRUTH: discord.Color.blue(),
            QuestionCategory.DARE: discord.Color.red(),
            QuestionCategory.TOD: discord.Color.purple(),
            QuestionCategory.WOULD_YOU_RATHER: discord.Color.green(),
            QuestionCategory.NEVER_HAVE_I: discord.Color.orange()
        }
        return color_map.get(category, discord.Color.blurple())

    def _get_category_emoji(self, category: QuestionCategory) -> str:
        """Get emoji for category"""
        emoji_map = {
            QuestionCategory.TRUTH: "💙",
            QuestionCategory.DARE: "🔥",
            QuestionCategory.TOD: "🎯",
            QuestionCategory.WOULD_YOU_RATHER: "🤔",
            QuestionCategory.NEVER_HAVE_I: "🙋"
        }
        return emoji_map.get(category, "❓")

    async def _send_question(self, ctx_or_interaction, category: QuestionCategory, new_message: bool = False):
        """Send a question embed with buttons"""
        # Check if TOD is enabled for this guild
        if hasattr(ctx_or_interaction, 'guild') and ctx_or_interaction.guild:
            guild_config = self._get_guild_config(ctx_or_interaction.guild.id)
            if not guild_config.get("enabled", True):
                if isinstance(ctx_or_interaction, discord.Interaction):
                    respond = ctx_or_interaction.response.send_message if not new_message else ctx_or_interaction.followup.send
                    await respond("❌ Truth or Dare is currently disabled in this server.", ephemeral=True)
                else:
                    await ctx_or_interaction.send("❌ Truth or Dare is currently disabled in this server.")
                return
        
        question = self._get_random_question(category)
        emoji = self._get_category_emoji(category)
        color = self._get_category_color(category)
        
        # Create embed
        embed = discord.Embed(
            title=f"{emoji} {category.value.title()}",
            description=question,
            color=color
        )
        
        # Add footer with instruction
        if category == QuestionCategory.TOD:
            embed.set_footer(text="Click a button below for another question!")
        elif category in [QuestionCategory.WOULD_YOU_RATHER, QuestionCategory.NEVER_HAVE_I]:
            embed.set_footer(text="Click the button below for another question!")
        else:
            embed.set_footer(text="Click a button below for Truth, Dare, or Random!")
        
        # Create view with buttons
        view = TODView(self, category)
        
        if isinstance(ctx_or_interaction, discord.Interaction):
            if new_message:
                # Send a new message instead of editing
                await ctx_or_interaction.response.send_message(embed=embed, view=view)
            else:
                # Original response (first question)
                await ctx_or_interaction.response.send_message(embed=embed, view=view)
        else:
            await ctx_or_interaction.send(embed=embed, view=view)

    # AUTOCOMPLETE FUNCTIONS
    async def category_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for categories"""
        categories = [category.value for category in QuestionCategory]
        return [
            app_commands.Choice(name=category.title(), value=category)
            for category in categories
            if current.lower() in category.lower()
        ][:25]

    async def question_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Autocomplete for existing questions"""
        # Get category from the current command
        category = None
        for option in interaction.data.get('options', []):
            if option['name'] == 'category':
                category = option['value']
                break
        
        if not category or category == 'tod':
            return []
        
        config = self._load_config()
        custom_questions = config["custom_questions"].get(category, [])
        
        return [
            app_commands.Choice(name=question[:100], value=question)
            for question in custom_questions
            if current.lower() in question.lower()
        ][:25]

    # ==================== SLASH COMMANDS ====================
    tod_group = app_commands.Group(name="tod", description="Truth or Dare commands")

    @tod_group.command(name="enable", description="Enable Truth or Dare for this server")
    async def enable_slash(self, interaction: discord.Interaction):
        """Enable Truth or Dare"""
        await self._toggle_tod(interaction, True)

    @tod_group.command(name="disable", description="Disable Truth or Dare for this server")
    async def disable_slash(self, interaction: discord.Interaction):
        """Disable Truth or Dare"""
        await self._toggle_tod(interaction, False)

    @tod_group.command(name="question", description="Get a random question")
    @app_commands.describe(category="Type of question to get")
    @app_commands.choices(category=[
        app_commands.Choice(name="Truth", value="truth"),
        app_commands.Choice(name="Dare", value="dare"),
        app_commands.Choice(name="Truth or Dare (Random)", value="tod"),
        app_commands.Choice(name="Would You Rather", value="would you rather"),
        app_commands.Choice(name="Never Have I Ever", value="never have i ever")
    ])
    async def question_slash(self, interaction: discord.Interaction, category: str):
        """Get a random question from the specified category"""
        try:
            question_category = QuestionCategory(category)
            await self._send_question(interaction, question_category)
        except ValueError:
            await interaction.response.send_message("❌ Invalid category selected.", ephemeral=True)

    @tod_group.command(name="config", description="View Truth or Dare configuration")
    async def config_slash(self, interaction: discord.Interaction):
        """View current configuration"""
        await self._view_config(interaction)

    # CUSTOM QUESTIONS SUBGROUP
    custom_group = app_commands.Group(name="custom-questions", description="Manage custom questions", parent=tod_group)

    @custom_group.command(name="list", description="List all custom questions for a category")
    @app_commands.describe(category="Category to list questions for")
    @app_commands.autocomplete(category=category_autocomplete)
    async def list_custom_slash(self, interaction: discord.Interaction, category: str):
        """List custom questions for a category"""
        await self._list_custom_questions(interaction, category)

    @custom_group.command(name="add", description="Add a custom question")
    @app_commands.describe(
        category="Category to add question to",
        question="The question to add"
    )
    @app_commands.autocomplete(category=category_autocomplete)
    async def add_custom_slash(self, interaction: discord.Interaction, category: str, question: str):
        """Add a custom question to a category"""
        await self._add_custom_question(interaction, category, question)

    @custom_group.command(name="remove", description="Remove a custom question")
    @app_commands.describe(
        category="Category to remove question from",
        question="The question to remove"
    )
    @app_commands.autocomplete(category=category_autocomplete, question=question_autocomplete)
    async def remove_custom_slash(self, interaction: discord.Interaction, category: str, question: str):
        """Remove a custom question from a category"""
        await self._remove_custom_question(interaction, category, question)

    @custom_group.command(name="clear", description="Clear all custom questions for a category")
    @app_commands.describe(category="Category to clear questions from")
    @app_commands.autocomplete(category=category_autocomplete)
    async def clear_custom_slash(self, interaction: discord.Interaction, category: str):
        """Clear all custom questions for a category"""
        await self._clear_custom_questions(interaction, category)

    # ==================== PREFIX COMMANDS ====================
    @commands.group(name="tod", invoke_without_command=True)
    async def tod_prefix(self, ctx, category: str = None):
        """Truth or Dare commands"""
        if category:
            # If category provided, send a question
            try:
                question_category = QuestionCategory(category.lower().replace("_", " "))
                await self._send_question(ctx, question_category)
            except ValueError:
                await ctx.send("❌ Invalid category. Available categories: truth, dare, tod, would you rather, never have i ever")
        else:
            # Show help
            embed = discord.Embed(
                title="🎯 Truth or Dare Commands",
                description="Available commands and categories",
                color=discord.Color.purple()
            )
            embed.add_field(
                name="System Control",
                value="• `enable` - Enable Truth or Dare\n• `disable` - Disable Truth or Dare",
                inline=False
            )
            embed.add_field(
                name="Categories",
                value="• `truth` - Truth questions\n• `dare` - Dare challenges\n• `tod` - Random truth or dare\n• `would you rather` - Would you rather questions\n• `never have i ever` - Never have I ever statements",
                inline=False
            )
            embed.add_field(
                name="Commands",
                value="• `!tod question <category>` - Get a question\n• `!tod custom-questions` - Manage custom questions (admin only)\n• `!tod config` - View configuration",
                inline=False
            )
            await ctx.send(embed=embed)

    @tod_prefix.command(name="enable")
    async def enable_prefix(self, ctx):
        """Enable Truth or Dare"""
        await self._toggle_tod(ctx, True)

    @tod_prefix.command(name="disable")
    async def disable_prefix(self, ctx):
        """Disable Truth or Dare"""
        await self._toggle_tod(ctx, False)

    @tod_prefix.command(name="question")
    async def question_prefix(self, ctx, *, category: str):
        """Get a random question from the specified category"""
        try:
            question_category = QuestionCategory(category.lower().replace("_", " "))
            await self._send_question(ctx, question_category)
        except ValueError:
            await ctx.send("❌ Invalid category. Available categories: truth, dare, tod, would you rather, never have i ever")

    @tod_prefix.command(name="config")
    async def config_prefix(self, ctx):
        """View current configuration"""
        await self._view_config(ctx)

    @tod_prefix.group(name="custom-questions", aliases=["cq"])
    async def custom_questions_prefix(self, ctx):
        """Manage custom questions"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Custom Questions Management",
                description="Available subcommands:",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Commands",
                value="• `list <category>` - List custom questions\n• `add <category> <question>` - Add custom question\n• `remove <category> <question>` - Remove custom question\n• `clear <category>` - Clear all custom questions",
                inline=False
            )
            await ctx.send(embed=embed)

    @custom_questions_prefix.command(name="list")
    async def list_custom_prefix(self, ctx, *, category: str):
        """List custom questions for a category"""
        await self._list_custom_questions(ctx, category)

    @custom_questions_prefix.command(name="add")
    async def add_custom_prefix(self, ctx, category: str, *, question: str):
        """Add a custom question to a category"""
        await self._add_custom_question(ctx, category, question)

    @custom_questions_prefix.command(name="remove")
    async def remove_custom_prefix(self, ctx, category: str, *, question: str):
        """Remove a custom question from a category"""
        await self._remove_custom_question(ctx, category, question)

    @custom_questions_prefix.command(name="clear")
    async def clear_custom_prefix(self, ctx, *, category: str):
        """Clear all custom questions for a category"""
        await self._clear_custom_questions(ctx, category)

    # ==================== IMPLEMENTATION METHODS ====================
    async def _toggle_tod(self, ctx_or_interaction, enabled: bool):
        """Toggle Truth or Dare on/off"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        if not self.has_tod_admin_permission(member):
            await respond("❌ You don't have permission to configure Truth or Dare settings.", ephemeral=True)
            return

        config = self._load_config()
        guild_config = self._get_guild_config(guild.id)
        
        guild_config["enabled"] = enabled
        config["guilds"][str(guild.id)] = guild_config
        self._save_config(config)
        
        status = "enabled" if enabled else "disabled"
        embed = discord.Embed(
            title=f"✅ Truth or Dare {status.title()}",
            description=f"Truth or Dare has been {status} for this server.",
            color=discord.Color.green() if enabled else discord.Color.red()
        )
        
        await respond(embed=embed)

    async def _view_config(self, ctx_or_interaction):
        """View current configuration"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.response.send_message
        else:
            guild = ctx_or_interaction.guild
            respond = ctx_or_interaction.send

        guild_config = self._get_guild_config(guild.id)
        config = self._load_config()
        
        embed = discord.Embed(
            title="🎯 Truth or Dare Configuration",
            color=discord.Color.purple()
        )
        
        # System status
        system_status = "🟢 Enabled" if guild_config.get("enabled", True) else "🔴 Disabled"
        embed.add_field(
            name="System Status",
            value=system_status,
            inline=False
        )
        
        # Question counts
        total_custom = sum(len(questions) for questions in config["custom_questions"].values())
        total_default = sum(len(questions) for questions in config["default_questions"].values())
        
        embed.add_field(
            name="Question Statistics",
            value=f"Default Questions: {total_default}\nCustom Questions: {total_custom}\nTotal Questions: {total_default + total_custom}",
            inline=False
        )
        
        # Custom questions breakdown
        custom_breakdown = []
        for category, questions in config["custom_questions"].items():
            custom_breakdown.append(f"{category.title()}: {len(questions)}")
        
        embed.add_field(
            name="Custom Questions by Category",
            value="\n".join(custom_breakdown) if custom_breakdown else "No custom questions",
            inline=False
        )
        
        await respond(embed=embed, ephemeral=True)

    async def _list_custom_questions(self, ctx_or_interaction, category: str):
        """List custom questions implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        if not self.has_tod_admin_permission(member):
            await respond("❌ You don't have permission to manage custom questions.", ephemeral=True)
            return

        # Validate category
        category = category.lower().replace("_", " ")
        if category == "tod":
            await respond("❌ Cannot manage custom questions for 'TOD' category. Use 'truth' or 'dare' instead.", ephemeral=True)
            return

        try:
            QuestionCategory(category)
        except ValueError:
            await respond("❌ Invalid category. Available categories: truth, dare, would you rather, never have i ever", ephemeral=True)
            return

        config = self._load_config()
        custom_questions = config["custom_questions"].get(category, [])

        if not custom_questions:
            embed = discord.Embed(
                title=f"📝 Custom {category.title()} Questions",
                description=f"No custom questions added for {category}.",
                color=discord.Color.blue()
            )
            await respond(embed=embed, ephemeral=True)
            return

        # Split questions into multiple embeds if too many
        questions_per_page = 10
        pages = [custom_questions[i:i + questions_per_page] for i in range(0, len(custom_questions), questions_per_page)]
        
        for page_num, questions_page in enumerate(pages):
            embed = discord.Embed(
                title=f"📝 Custom {category.title()} Questions",
                description=f"Page {page_num + 1}/{len(pages)}",
                color=discord.Color.blue()
            )
            
            for i, question in enumerate(questions_page, start=page_num * questions_per_page + 1):
                embed.add_field(
                    name=f"Question #{i}",
                    value=question[:1024],  # Discord field value limit
                    inline=False
                )
            
            embed.set_footer(text=f"Total: {len(custom_questions)} custom questions")
            await respond(embed=embed, ephemeral=True)

    async def _add_custom_question(self, ctx_or_interaction, category: str, question: str):
        """Add custom question implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        if not self.has_tod_admin_permission(member):
            await respond("❌ You don't have permission to manage custom questions.", ephemeral=True)
            return

        # Validate category
        category = category.lower().replace("_", " ")
        if category == "tod":
            await respond("❌ Cannot add custom questions to 'TOD' category. Use 'truth' or 'dare' instead.", ephemeral=True)
            return

        try:
            QuestionCategory(category)
        except ValueError:
            await respond("❌ Invalid category. Available categories: truth, dare, would you rather, never have i ever", ephemeral=True)
            return

        # Validate question length
        if len(question) > 1000:
            await respond("❌ Question is too long. Maximum length is 1000 characters.", ephemeral=True)
            return

        config = self._load_config()
        
        # Initialize category if not exists
        if category not in config["custom_questions"]:
            config["custom_questions"][category] = []

        # Check if question already exists
        if question in config["custom_questions"][category]:
            await respond("❌ This question already exists in the category.", ephemeral=True)
            return

        # Add question
        config["custom_questions"][category].append(question)
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Question Added",
            description=f"Successfully added custom question to {category}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Question", value=question[:1024], inline=False)
        embed.set_footer(text=f"Total custom questions in {category}: {len(config['custom_questions'][category])}")

        await respond(embed=embed)

    async def _remove_custom_question(self, ctx_or_interaction, category: str, question: str):
        """Remove custom question implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        if not self.has_tod_admin_permission(member):
            await respond("❌ You don't have permission to manage custom questions.", ephemeral=True)
            return

        # Validate category
        category = category.lower().replace("_", " ")
        if category == "tod":
            await respond("❌ Cannot remove custom questions from 'TOD' category. Use 'truth' or 'dare' instead.", ephemeral=True)
            return

        try:
            QuestionCategory(category)
        except ValueError:
            await respond("❌ Invalid category. Available categories: truth, dare, would you rather, never have i ever", ephemeral=True)
            return

        config = self._load_config()
        custom_questions = config["custom_questions"].get(category, [])

        if question not in custom_questions:
            await respond("❌ Question not found in the category.", ephemeral=True)
            return

        # Remove question
        config["custom_questions"][category].remove(question)
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Question Removed",
            description=f"Successfully removed custom question from {category}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Removed Question", value=question[:1024], inline=False)
        embed.set_footer(text=f"Remaining custom questions in {category}: {len(config['custom_questions'][category])}")

        await respond(embed=embed)

    async def _clear_custom_questions(self, ctx_or_interaction, category: str):
        """Clear custom questions implementation"""
        if isinstance(ctx_or_interaction, discord.Interaction):
            member = ctx_or_interaction.user
            respond = ctx_or_interaction.response.send_message
        else:
            member = ctx_or_interaction.author
            respond = ctx_or_interaction.send

        if not self.has_tod_admin_permission(member):
            await respond("❌ You don't have permission to manage custom questions.", ephemeral=True)
            return

        # Validate category
        category = category.lower().replace("_", " ")
        if category == "tod":
            await respond("❌ Cannot clear custom questions from 'TOD' category. Use 'truth' or 'dare' instead.", ephemeral=True)
            return

        try:
            QuestionCategory(category)
        except ValueError:
            await respond("❌ Invalid category. Available categories: truth, dare, would you rather, never have i ever", ephemeral=True)
            return

        config = self._load_config()
        custom_questions = config["custom_questions"].get(category, [])
        
        if not custom_questions:
            await respond(f"❌ No custom questions found for {category}.", ephemeral=True)
            return

        question_count = len(custom_questions)
        
        # Clear questions
        config["custom_questions"][category] = []
        self._save_config(config)

        embed = discord.Embed(
            title="✅ Questions Cleared",
            description=f"Successfully cleared all custom questions from {category}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Questions Removed", value=str(question_count), inline=True)

        await respond(embed=embed)

async def setup(bot):
    await bot.add_cog(TODCog(bot))
