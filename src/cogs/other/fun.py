"""
Discord FunCog - Entertainment, Text, and Meme Commands

OVERVIEW:
A collection of fun, meme, and text transformation commands for Discord.  
Includes games, randomizers, meme/image fetchers, text stylizers, and utility tools.

SETUP:
- No setup required. Just load the cog.
- Requires: aiohttp (for meme/urban dictionary/emoji commands)

COMMANDS (Slash & Prefix):
Text Transformations:
  /text aesthetics <text>      - Fullwidth "aesthetic" text
  /text fraktur <text>         - Fraktur unicode text
  /text boldfraktur <text>     - Bold fraktur unicode text
  /text fancy <text>           - Fancy script unicode text
  /text boldfancy <text>       - Bold fancy script unicode text
  /text double <text>          - Double-struck unicode text
  /text smallcaps <text>       - Small caps text
  /text owofy <text>           - Owo-speak
  /text emojify <text>         - Convert to emoji regional indicators
  /text clap <text>            - Add 👏 between words
  /text space <sep> <text>     - Custom separator between words
  /text reverse <text>         - Reverse the text
  /text mock <text>            - Mocking SpongeBob case

Games & Random:
  /game pick <choices>         - Randomly pick from comma-separated choices
  /game eightball <question>   - Magic 8-ball
  /game coinflip               - Flip a coin
  /game rps <choice>           - Rock Paper Scissors vs bot
  /game meme                   - Get a random meme

Utilities:
  /util urbandictionary <word> - Urban Dictionary lookup
  /util info [member]          - Show info about a member
  /util addemoji <name> <url>  - Add a custom emoji (Manage Emojis required)
  /util ascii <text>           - Convert text to ASCII art

Prefix commands: !fun <subcommand> (same as above, e.g. !fun meme, !fun owofy)

COMMAND EXPLANATIONS:
- aesthetics/fraktur/fancy/double/smallcaps: Unicode text styles
- owofy: Converts text to "owo" speak
- emojify: Turns text into emoji letters
- clap/space: Adds emojis or custom separators between words
- reverse/mock: Reverses or alternates case in text
- pick: Randomly selects from options
- eightball: Magic 8-ball answers
- coinflip/rps: Play games with the bot
- meme: Fetches a random meme
- urbandictionary: Looks up slang/definitions
- info: Shows member info (roles, join date, etc)
- addemoji: Adds a custom emoji to the server
- ascii: Simple ASCII art for short text

FEATURES:
• 10+ text transformation styles
• Meme/image fetching (meme-api)
• Urban Dictionary integration
• Games: 8-ball, coinflip, RPS, random pick
• Custom emoji adder (with permissions)
• User info utility
• Both slash and prefix command support
• All commands are safe for all users (except addemoji, which requires Manage Emojis)

USAGE BY OTHER COGS:
# Use text transformations in your own cogs:
fun_cog = bot.get_cog('FunCog')
if fun_cog:
    owo_text = fun_cog.owofy_text("hello world")
    fancy = fun_cog.transform_text("hello", fun_cog.fancy_map)

# Fetch a meme for another cog:
meme = await fun_cog.get_random_meme()
if meme:
    url = meme['url']

# Use emojify for reactions:
emoji_text = fun_cog.emojify_text("cool")
"""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import random
import re
from typing import Optional

class FunCog(commands.Cog):
    """Fun commands for entertainment and text manipulation"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Character mappings for text transformations
        self.aesthetics_map = str.maketrans(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            'ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ０１２３４５６７８９'
        )
        
        self.fraktur_map = str.maketrans(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
            '𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝔖𝔗𝔘𝔙𝔚𝔛𝔜ℨ'
        )
        
        self.bold_fraktur_map = str.maketrans(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
            '𝖆𝖇𝖈𝖉𝖊𝖋𝖌𝖍𝖎𝖏𝖐𝖑𝖒𝖓𝖔𝖕𝖖𝖗𝖘𝖙𝖚𝖛𝖜𝖝𝖞𝖟𝕬𝕭𝕮𝕯𝕰𝕱𝕲𝕳𝕴𝕵𝕶𝕷𝕸𝕹𝕺𝕻𝕼𝕽𝕾𝕿𝖀𝖁𝖂𝖃𝖄𝖅'
        )
        
        self.fancy_map = str.maketrans(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
            '𝒶𝒷𝒸𝒹𝑒𝒻𝑔𝒽𝒾𝒿𝓀𝓁𝓂𝓃𝑜𝓅𝓆𝓇𝓈𝓉𝓊𝓋𝓌𝓍𝓎𝓏𝒜𝐵𝒞𝒟𝐸𝐹𝒢𝐻𝐼𝒥𝒦𝐿𝑀𝒩𝒪𝒫𝒬𝑅𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵'
        )
        
        self.bold_fancy_map = str.maketrans(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
            '𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝓞𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩'
        )
        
        # Fixed double map - corrected the lowercase letters
        self.double_map = str.maketrans(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            '𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡'
        )
        
        self.small_caps_map = str.maketrans(
            'abcdefghijklmnopqrstuvwxyz',
            'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘqʀꜱᴛᴜᴠᴡxʏᴢ'
        )
        
        # Eight ball responses
        self.eightball_responses = [
            "It is certain", "It is decidedly so", "Without a doubt", "Yes definitely",
            "You may rely on it", "As I see it, yes", "Most likely", "Outlook good",
            "Yes", "Signs point to yes", "Reply hazy, try again", "Ask again later",
            "Better not tell you now", "Cannot predict now", "Concentrate and ask again",
            "Don't count on it", "My reply is no", "My sources say no", "Outlook not so good",
            "Very doubtful"
        ]
        
        # Emoji mappings for emojify
        self.emoji_map = {
            'a': '🇦', 'b': '🇧', 'c': '🇨', 'd': '🇩', 'e': '🇪', 'f': '🇫',
            'g': '🇬', 'h': '🇭', 'i': '🇮', 'j': '🇯', 'k': '🇰', 'l': '🇱',
            'm': '🇲', 'n': '🇳', 'o': '🇴', 'p': '🇵', 'q': '🇶', 'r': '🇷',
            's': '🇸', 't': '🇹', 'u': '🇺', 'v': '🇻', 'w': '🇼', 'x': '🇽',
            'y': '🇾', 'z': '🇿', '0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣',
            '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
        }

    def transform_text(self, text: str, char_map: dict) -> str:
        """Transform text using character mapping"""
        return text.translate(char_map)

    def owofy_text(self, text: str) -> str:
        """Convert text to owo speak"""
        text = re.sub(r'[rl]', 'w', text)
        text = re.sub(r'[RL]', 'W', text)
        text = re.sub(r'n([aeiou])', r'ny\1', text)
        text = re.sub(r'N([aeiou])', r'Ny\1', text)
        text = re.sub(r'N([AEIOU])', r'NY\1', text)
        text = re.sub(r'ove', 'uv', text)
        
        # Add random uwu/owo at the end
        endings = [' uwu', ' owo', ' >w<', ' ^w^', ' :3', ' x3']
        return text + random.choice(endings)

    def emojify_text(self, text: str) -> str:
        """Convert text to emoji regional indicators"""
        result = []
        for char in text.lower():
            if char in self.emoji_map:
                result.append(self.emoji_map[char])
            elif char == ' ':
                result.append('   ')
            else:
                result.append(char)
        return ''.join(result)

    async def get_urban_definition(self, term: str) -> dict:
        """Get definition from Urban Dictionary API"""
        url = f"http://api.urbandictionary.com/v0/define?term={term}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
        except Exception:
            pass
        return None

    async def get_random_meme(self) -> dict:
        """Get random meme from meme API"""
        url = "https://meme-api.com/gimme"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
        except Exception:
            pass
        return None

    def text_to_ascii(self, text: str) -> str:
        """Convert text to ASCII art (simple version)"""
        if len(text) > 10:
            return "Text too long! Please use 10 characters or less."
        
        ascii_art = {
            'A': ['  ▄▄  ', ' ▄▀▀▄ ', '▄▀  ▀▄', '▀▄▄▄▄▀'],
            'B': ['▄▄▄▄▄ ', '▀▄▄▄▄▀', '▀▄▄▄▄▀', '▀▀▀▀▀▀'],
            'C': [' ▄▄▄▄ ', '▄▀   ▀', '▀▄   ▄', ' ▀▀▀▀ '],
            'D': ['▄▄▄▄  ', '▀▄  ▀▄', '▀▄  ▄▀', '▀▀▀▀  '],
            'E': ['▄▄▄▄▄▄', '▀▄▄▄▄ ', '▀▄▄▄▄ ', '▀▀▀▀▀▀'],
            'F': ['▄▄▄▄▄▄', '▀▄▄▄▄ ', '▀▄▄▄▄ ', '▀     '],
            'G': [' ▄▄▄▄ ', '▄▀   ▀', '▀▄ ▄▄▀', ' ▀▀▀▀ '],
            'H': ['▄   ▄ ', '▀▄▄▄▄▀', '▀▄   ▄', '▀▀   ▀'],
            'I': ['▄▄▄▄▄▄', '  ▀▄  ', '  ▀▄  ', '▀▀▀▀▀▀'],
            'J': ['▄▄▄▄▄▄', '    ▀▄', '▀▄  ▄▀', ' ▀▀▀▀ '],
            'K': ['▄   ▄ ', '▀▄▄▀  ', '▀▄ ▀▄ ', '▀▀  ▀▀'],
            'L': ['▄     ', '▀▄    ', '▀▄▄▄▄▄', '▀▀▀▀▀▀'],
            'M': ['▄   ▄ ', '▀▄▄▄▄▀', '▀▄ ▄ ▄', '▀▀ ▀ ▀'],
            'N': ['▄   ▄ ', '▀▄▄ ▄▀', '▀▄ ▄▄▀', '▀▀  ▀▀'],
            'O': [' ▄▄▄▄ ', '▄▀  ▀▄', '▀▄  ▄▀', ' ▀▀▀▀ '],
            'P': ['▄▄▄▄▄ ', '▀▄▄▄▄▀', '▀▄    ', '▀▀    '],
            'Q': [' ▄▄▄▄ ', '▄▀  ▀▄', '▀▄ ▄▄▀', ' ▀▀▀▀▄'],
            'R': ['▄▄▄▄▄ ', '▀▄▄▄▄▀', '▀▄ ▀▄ ', '▀▀  ▀▀'],
            'S': [' ▄▄▄▄▄', '▄▀▄▄▄ ', ' ▄▄▄▄▀', '▀▀▀▀▀ '],
            'T': ['▄▄▄▄▄▄', '  ▀▄  ', '  ▀▄  ', '  ▀▀  '],
            'U': ['▄   ▄ ', '▀▄  ▄▀', '▀▄  ▄▀', ' ▀▀▀▀ '],
            'V': ['▄   ▄ ', '▀▄  ▄▀', ' ▀▄▄▀ ', '  ▀▀  '],
            'W': ['▄ ▄ ▄ ', '▀▄▄▄▄▀', '▀▄ ▄ ▄', ' ▀▀▀▀ '],
            'X': ['▄   ▄ ', ' ▀▄▄▀ ', ' ▄▀▀▄ ', '▀▀  ▀▀'],
            'Y': ['▄   ▄ ', ' ▀▄▄▀ ', '  ▀▄  ', '  ▀▀  '],
            'Z': ['▄▄▄▄▄▄', '  ▄▄▀ ', ' ▄▀▄▄ ', '▀▀▀▀▀▀'],
            ' ': ['      ', '      ', '      ', '      ']
        }
        
        lines = ['', '', '', '']
        for char in text.upper():
            if char in ascii_art:
                for i in range(4):
                    lines[i] += ascii_art[char][i]
            else:
                for i in range(4):
                    lines[i] += '▄▄▄▄▄▄'
        
        return '\n'.join(lines)

    # ==================== SLASH COMMAND GROUPS ====================
    
    # Text transformation group
    text_group = app_commands.Group(name="text", description="Text transformation commands")

    @text_group.command(name="aesthetics", description="Convert text to aesthetic fullwidth characters")
    async def aesthetics_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to aesthetic fullwidth characters"""
        result = self.transform_text(text, self.aesthetics_map).replace(' ', '　')
        await interaction.response.send_message(result)

    @text_group.command(name="fraktur", description="Convert text to fraktur unicode characters")
    async def fraktur_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to fraktur unicode characters"""
        result = self.transform_text(text, self.fraktur_map)
        await interaction.response.send_message(result)

    @text_group.command(name="boldfraktur", description="Convert text to bold fraktur unicode characters")
    async def boldfraktur_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to bold fraktur unicode characters"""
        result = self.transform_text(text, self.bold_fraktur_map)
        await interaction.response.send_message(result)

    @text_group.command(name="fancy", description="Convert text to fancy script unicode characters")
    async def fancy_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to fancy script unicode characters"""
        result = self.transform_text(text, self.fancy_map)
        await interaction.response.send_message(result)

    @text_group.command(name="boldfancy", description="Convert text to bold fancy script unicode characters")
    async def boldfancy_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to bold fancy script unicode characters"""
        result = self.transform_text(text, self.bold_fancy_map)
        await interaction.response.send_message(result)

    @text_group.command(name="double", description="Convert text to double-struck unicode characters")
    async def double_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to double-struck unicode characters"""
        result = self.transform_text(text, self.double_map)
        await interaction.response.send_message(result)

    @text_group.command(name="smallcaps", description="Convert text to small caps")
    async def smallcaps_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to small caps"""
        result = self.transform_text(text, self.small_caps_map)
        await interaction.response.send_message(result)

    @text_group.command(name="owofy", description="Convert text to owo speak")
    async def owofy_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to owo speak"""
        result = self.owofy_text(text)
        await interaction.response.send_message(result)

    @text_group.command(name="emojify", description="Convert text to emoji regional indicators")
    async def emojify_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to emoji regional indicators"""
        result = self.emojify_text(text)
        if len(result) > 2000:
            await interaction.response.send_message("Text too long! Please use shorter text.", ephemeral=True)
            return
        await interaction.response.send_message(result)

    @text_group.command(name="clap", description="Add clap emojis between words")
    async def clap_slash(self, interaction: discord.Interaction, text: str):
        """Add clap emojis between words"""
        result = ' 👏 '.join(text.split()) + ' 👏'
        await interaction.response.send_message(result)

    @text_group.command(name="space", description="Add custom separators between words")
    async def space_slash(self, interaction: discord.Interaction, separator: str, text: str):
        """Add custom separators between words"""
        result = f' {separator} '.join(text.split())
        await interaction.response.send_message(result)

    @text_group.command(name="reverse", description="Reverse the text")
    async def reverse_slash(self, interaction: discord.Interaction, text: str):
        """Reverse the text"""
        result = text[::-1]
        await interaction.response.send_message(result)

    @text_group.command(name="mock", description="Convert text to mocking SpongeBob case")
    async def mock_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to mocking SpongeBob case"""
        result = ''.join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text))
        await interaction.response.send_message(result)

    # Game and random commands group
    game_group = app_commands.Group(name="game", description="Games and random commands")

    @game_group.command(name="pick", description="Randomly pick from comma-separated choices")
    async def pick_slash(self, interaction: discord.Interaction, choices: str):
        """Randomly pick from comma-separated choices"""
        options = [choice.strip() for choice in choices.split(',')]
        if len(options) < 2:
            await interaction.response.send_message("Please provide at least 2 choices separated by commas!", ephemeral=True)
            return
        
        choice = random.choice(options)
        embed = discord.Embed(title="🎲 Random Pick", description=f"I choose: **{choice}**", color=0x00ff00)
        embed.add_field(name="Options", value=", ".join(options), inline=False)
        await interaction.response.send_message(embed=embed)

    @game_group.command(name="eightball", description="Ask the magic 8-ball a yes/no question")
    async def eightball_slash(self, interaction: discord.Interaction, question: str):
        """Ask the magic 8-ball a yes/no question"""
        if not question.endswith('?'):
            question += '?'
        
        response = random.choice(self.eightball_responses)
        embed = discord.Embed(title="🎱 Magic 8-Ball", color=0x8B00FF)
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(name="Answer", value=f"*{response}*", inline=False)
        await interaction.response.send_message(embed=embed)

    @game_group.command(name="coinflip", description="Flip a coin")
    async def coinflip_slash(self, interaction: discord.Interaction):
        """Flip a coin"""
        result = random.choice(["Heads", "Tails"])
        embed = discord.Embed(title="🪙 Coin Flip", description=f"**{result}!**", color=0xFFD700)
        await interaction.response.send_message(embed=embed)

    @game_group.command(name="rps", description="Play Rock Paper Scissors against the bot")
    @app_commands.describe(choice="Your choice: rock, paper, or scissors")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Rock", value="rock"),
        app_commands.Choice(name="Paper", value="paper"),
        app_commands.Choice(name="Scissors", value="scissors")
    ])
    async def rps_slash(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        """Play Rock Paper Scissors against the bot"""
        user_choice = choice.value
        bot_choice = random.choice(["rock", "paper", "scissors"])
        
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        
        embed = discord.Embed(title="🎮 Rock Paper Scissors", color=0x3498db)
        embed.add_field(name="Your Choice", value=f"{emojis[user_choice]} {user_choice.title()}", inline=True)
        embed.add_field(name="Bot's Choice", value=f"{emojis[bot_choice]} {bot_choice.title()}", inline=True)
        
        if user_choice == bot_choice:
            result = "It's a tie!"
            embed.color = 0xf39c12
        elif (user_choice == "rock" and bot_choice == "scissors") or \
                (user_choice == "paper" and bot_choice == "rock") or \
                (user_choice == "scissors" and bot_choice == "paper"):
            result = "You win! 🎉"
            embed.color = 0x2ecc71
        else:
            result = "You lose! 😔"
            embed.color = 0xe74c3c
        
        embed.add_field(name="Result", value=result, inline=False)
        await interaction.response.send_message(embed=embed)

    @game_group.command(name="meme", description="Get a random meme")
    async def meme_slash(self, interaction: discord.Interaction):
        """Get a random meme"""
        await interaction.response.defer()
        
        meme_data = await self.get_random_meme()
        if not meme_data:
            await interaction.followup.send("Failed to fetch a meme. Try again later!")
            return
        
        embed = discord.Embed(title=meme_data.get('title', 'Random Meme'), color=0xff4500)
        embed.set_image(url=meme_data.get('url'))
        embed.add_field(name="Subreddit", value=f"r/{meme_data.get('subreddit', 'unknown')}", inline=True)
        embed.add_field(name="Author", value=f"u/{meme_data.get('author', 'unknown')}", inline=True)
        embed.add_field(name="👍", value=meme_data.get('ups', 0), inline=True)
        
        if meme_data.get('spoiler'):
            embed.add_field(name="⚠️", value="Spoiler content", inline=True)
        
        await interaction.followup.send(embed=embed)

    # Utility commands group
    util_group = app_commands.Group(name="util", description="Utility commands")

    @util_group.command(name="urbandictionary", description="Look up a word on Urban Dictionary")
    async def urbandictionary_slash(self, interaction: discord.Interaction, word: str):
        """Look up a word on Urban Dictionary"""
        await interaction.response.defer()
        
        data = await self.get_urban_definition(word)
        if not data or not data.get('list'):
            await interaction.followup.send(f"No definition found for '{word}' on Urban Dictionary.")
            return
        
        definition = data['list'][0]
        embed = discord.Embed(title=f"📚 Urban Dictionary: {definition['word']}", color=0xFF6600)
        
        def_text = definition['definition'][:1024] if len(definition['definition']) > 1024 else definition['definition']
        example_text = definition.get('example', 'No example provided')[:1024] if len(definition.get('example', '')) > 1024 else definition.get('example', 'No example provided')
        
        embed.add_field(name="Definition", value=def_text, inline=False)
        if example_text != 'No example provided':
            embed.add_field(name="Example", value=example_text, inline=False)
        
        embed.add_field(name="👍", value=str(definition.get('thumbs_up', 0)), inline=True)
        embed.add_field(name="👎", value=str(definition.get('thumbs_down', 0)), inline=True)
        embed.set_footer(text=f"Author: {definition.get('author', 'Unknown')}")
        
        await interaction.followup.send(embed=embed)

    @util_group.command(name="info", description="Show interesting information about a member")
    async def info_slash(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """Show interesting information about a member"""
        if member is None:
            member = interaction.user

        embed = discord.Embed(title=f"📊 Member Info: {member.display_name}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        # Basic info
        embed.add_field(name="Username", value=f"{member.name}#{member.discriminator}", inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
        
        # Dates
        embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        if member.joined_at:
            embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
        
        # Status and activity
        embed.add_field(name="Status", value=str(member.status).title(), inline=True)
        
        # Roles
        if len(member.roles) > 1:
            roles = [role.mention for role in member.roles[1:]]  # Skip @everyone
            roles_text = ', '.join(roles) if len(', '.join(roles)) <= 1024 else f"{len(roles)} roles"
            embed.add_field(name=f"Roles ({len(roles)})", value=roles_text, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @util_group.command(name="addemoji", description="Add a custom emoji to the server")
    @app_commands.describe(name="Name for the emoji", url="URL of the image")
    async def addemoji_slash(self, interaction: discord.Interaction, name: str, url: str):
        """Add a custom emoji to the server"""
        if not interaction.user.guild_permissions.manage_emojis:
            await interaction.response.send_message("You don't have permission to manage emojis!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        await interaction.followup.send("Failed to download image from URL!")
                        return
                    
                    image_data = await response.read()
                    
            emoji = await interaction.guild.create_custom_emoji(name=name, image=image_data)
            embed = discord.Embed(title="✅ Emoji Added", description=f"Successfully added {emoji} as `:{name}:`", color=0x00ff00)
            await interaction.followup.send(embed=embed)
            
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to add emoji: {e}")
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}")

    @util_group.command(name="ascii", description="Convert text to ASCII art")
    async def ascii_slash(self, interaction: discord.Interaction, text: str):
        """Convert text to ASCII art"""
        result = self.text_to_ascii(text)
        await interaction.response.send_message(f"```\n{result}\n```")

    # ==================== PREFIX COMMANDS ====================

    @commands.group(name="fun", invoke_without_command=True)
    async def fun(self, ctx):
        """Fun commands for entertainment and text manipulation"""
        embed = discord.Embed(title="🎉 Fun Commands", description="Use `fun <command>` to access these commands!", color=0x00ff00)
        embed.add_field(name="Text Transformations", 
                        value="aesthetics, fraktur, boldfraktur, fancy, boldfancy, double, smallcaps, owofy, emojify, clap, space, reverse, mock", 
                        inline=False)
        embed.add_field(name="Games & Random", 
                        value="pick, eightball, coinflip, rps, meme", 
                        inline=False)
        embed.add_field(name="Utilities", 
                        value="urbandictionary, info, addemoji, ascii", 
                        inline=False)
        embed.add_field(name="Slash Commands", 
                        value="Use `/text`, `/game`, or `/util` for organized slash commands!", 
                        inline=False)
        await ctx.send(embed=embed)

    @fun.command(name="aesthetics")
    async def aesthetics(self, ctx, *, text: str):
        """Convert text to aesthetic fullwidth characters"""
        result = self.transform_text(text, self.aesthetics_map).replace(' ', '　')
        await ctx.send(result)

    @fun.command(name="pick")
    async def pick(self, ctx, *, choices: str):
        """Randomly pick from comma-separated choices"""
        options = [choice.strip() for choice in choices.split(',')]
        if len(options) < 2:
            await ctx.send("Please provide at least 2 choices separated by commas!")
            return
        
        choice = random.choice(options)
        embed = discord.Embed(title="🎲 Random Pick", description=f"I choose: **{choice}**", color=0x00ff00)
        embed.add_field(name="Options", value=", ".join(options), inline=False)
        await ctx.send(embed=embed)

    @fun.command(name="fraktur")
    async def fraktur(self, ctx, *, text: str):
        """Convert text to fraktur unicode characters"""
        result = self.transform_text(text, self.fraktur_map)
        await ctx.send(result)

    @fun.command(name="boldfraktur")
    async def boldfraktur(self, ctx, *, text: str):
        """Convert text to bold fraktur unicode characters"""
        result = self.transform_text(text, self.bold_fraktur_map)
        await ctx.send(result)

    @fun.command(name="fancy")
    async def fancy(self, ctx, *, text: str):
        """Convert text to fancy script unicode characters"""
        result = self.transform_text(text, self.fancy_map)
        await ctx.send(result)

    @fun.command(name="boldfancy")
    async def boldfancy(self, ctx, *, text: str):
        """Convert text to bold fancy script unicode characters"""
        result = self.transform_text(text, self.bold_fancy_map)
        await ctx.send(result)

    @fun.command(name="double")
    async def double(self, ctx, *, text: str):
        """Convert text to double-struck unicode characters"""
        result = self.transform_text(text, self.double_map)
        await ctx.send(result)

    @fun.command(name="smallcaps")
    async def smallcaps(self, ctx, *, text: str):
        """Convert text to small caps"""
        result = self.transform_text(text, self.small_caps_map)
        await ctx.send(result)

    @fun.command(name="eightball", aliases=['8ball'])
    async def eightball(self, ctx, *, question: str):
        """Ask the magic 8-ball a yes/no question"""
        if not question.endswith('?'):
            question += '?'
        
        response = random.choice(self.eightball_responses)
        embed = discord.Embed(title="🎱 Magic 8-Ball", color=0x8B00FF)
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(name="Answer", value=f"*{response}*", inline=False)
        await ctx.send(embed=embed)

    @fun.command(name="owofy", aliases=['owo'])
    async def owofy(self, ctx, *, text: str):
        """Convert text to owo speak"""
        result = self.owofy_text(text)
        await ctx.send(result)

    @fun.command(name="emojify")
    async def emojify(self, ctx, *, text: str):
        """Convert text to emoji regional indicators"""
        result = self.emojify_text(text)
        if len(result) > 2000:
            await ctx.send("Text too long! Please use shorter text.")
            return
        await ctx.send(result)

    @fun.command(name="urbandictionary", aliases=['urban', 'ud'])
    async def urbandictionary(self, ctx, *, word: str):
        """Look up a word on Urban Dictionary"""
        async with ctx.typing():
            data = await self.get_urban_definition(word)
            if not data or not data.get('list'):
                await ctx.send(f"No definition found for '{word}' on Urban Dictionary.")
                return
            
            definition = data['list'][0]
            embed = discord.Embed(title=f"📚 Urban Dictionary: {definition['word']}", color=0xFF6600)
            
            def_text = definition['definition'][:1024] if len(definition['definition']) > 1024 else definition['definition']
            example_text = definition.get('example', 'No example provided')[:1024] if len(definition.get('example', '')) > 1024 else definition.get('example', 'No example provided')
            
            embed.add_field(name="Definition", value=def_text, inline=False)
            if example_text != 'No example provided':
                embed.add_field(name="Example", value=example_text, inline=False)
            
            embed.add_field(name="👍", value=str(definition.get('thumbs_up', 0)), inline=True)
            embed.add_field(name="👎", value=str(definition.get('thumbs_down', 0)), inline=True)
            embed.set_footer(text=f"Author: {definition.get('author', 'Unknown')}")
            
            await ctx.send(embed=embed)

    @fun.command(name="clap")
    async def clap(self, ctx, *, text: str):
        """Add clap emojis between words"""
        result = ' 👏 '.join(text.split()) + ' 👏'
        await ctx.send(result)

    @fun.command(name="space")
    async def space(self, ctx, separator: str, *, text: str):
        """Add custom separators between words"""
        result = f' {separator} '.join(text.split())
        await ctx.send(result)

    @fun.command(name="info")
    async def info(self, ctx, member: Optional[discord.Member] = None):
        """Show interesting information about a member"""
        if member is None:
            member = ctx.author

        embed = discord.Embed(title=f"📊 Member Info: {member.display_name}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        # Basic info
        embed.add_field(name="Username", value=f"{member.name}#{member.discriminator}", inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
        
        # Dates
        embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        if member.joined_at:
            embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
        
        # Status and activity
        embed.add_field(name="Status", value=str(member.status).title(), inline=True)
        
        # Roles
        if len(member.roles) > 1:
            roles = [role.mention for role in member.roles[1:]]  # Skip @everyone
            roles_text = ', '.join(roles) if len(', '.join(roles)) <= 1024 else f"{len(roles)} roles"
            embed.add_field(name=f"Roles ({len(roles)})", value=roles_text, inline=False)
        
        await ctx.send(embed=embed)

    @fun.command(name="addemoji")
    async def addemoji(self, ctx, name: str, url: str = None):
        """Add a custom emoji to the server"""
        if not ctx.author.guild_permissions.manage_emojis:
            await ctx.send("You don't have permission to manage emojis!")
            return
        
        # Check for attachment if no URL provided
        if url is None and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        elif url is None:
            await ctx.send("Please provide a URL or attach an image!")
            return
        
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            await ctx.send("Failed to download image from URL!")
                            return
                        
                        image_data = await response.read()
                        
                emoji = await ctx.guild.create_custom_emoji(name=name, image=image_data)
                embed = discord.Embed(title="✅ Emoji Added", description=f"Successfully added {emoji} as `:{name}:`", color=0x00ff00)
                await ctx.send(embed=embed)
                
            except discord.HTTPException as e:
                await ctx.send(f"Failed to add emoji: {e}")
            except Exception as e:
                await ctx.send(f"An error occurred: {e}")

    @fun.command(name="coinflip", aliases=['coin', 'flip'])
    async def coinflip(self, ctx):
        """Flip a coin"""
        result = random.choice(["Heads", "Tails"])
        embed = discord.Embed(title="🪙 Coin Flip", description=f"**{result}!**", color=0xFFD700)
        await ctx.send(embed=embed)

    @fun.command(name="ascii")
    async def ascii(self, ctx, *, text: str):
        """Convert text to ASCII art"""
        result = self.text_to_ascii(text)
        await ctx.send(f"```\n{result}\n```")

    @fun.command(name="rps")
    async def rps(self, ctx, choice: str = None):
        """Play Rock Paper Scissors against the bot"""
        if choice is None:
            await ctx.send("Please choose rock, paper, or scissors!")
            return
        
        choice = choice.lower()
        if choice not in ["rock", "paper", "scissors"]:
            await ctx.send("Invalid choice! Please choose rock, paper, or scissors.")
            return
        
        bot_choice = random.choice(["rock", "paper", "scissors"])
        
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        
        embed = discord.Embed(title="🎮 Rock Paper Scissors", color=0x3498db)
        embed.add_field(name="Your Choice", value=f"{emojis[choice]} {choice.title()}", inline=True)
        embed.add_field(name="Bot's Choice", value=f"{emojis[bot_choice]} {bot_choice.title()}", inline=True)
        
        if choice == bot_choice:
            result = "It's a tie!"
            embed.color = 0xf39c12
        elif (choice == "rock" and bot_choice == "scissors") or \
                (choice == "paper" and bot_choice == "rock") or \
                (choice == "scissors" and bot_choice == "paper"):
            result = "You win! 🎉"
            embed.color = 0x2ecc71
        else:
            result = "You lose! 😔"
            embed.color = 0xe74c3c
        
        embed.add_field(name="Result", value=result, inline=False)
        await ctx.send(embed=embed)

    @fun.command(name="meme")
    async def meme(self, ctx):
        """Get a random meme"""
        async with ctx.typing():
            meme_data = await self.get_random_meme()
            if not meme_data:
                await ctx.send("Failed to fetch a meme. Try again later!")
                return
            
            embed = discord.Embed(title=meme_data.get('title', 'Random Meme'), color=0xff4500)
            embed.set_image(url=meme_data.get('url'))
            embed.add_field(name="Subreddit", value=f"r/{meme_data.get('subreddit', 'unknown')}", inline=True)
            embed.add_field(name="Author", value=f"u/{meme_data.get('author', 'unknown')}", inline=True)
            embed.add_field(name="👍", value=meme_data.get('ups', 0), inline=True)
            
            if meme_data.get('spoiler'):
                embed.add_field(name="⚠️", value="Spoiler content", inline=True)
            
            await ctx.send(embed=embed)

    @fun.command(name="reverse")
    async def reverse(self, ctx, *, text: str):
        """Reverse the text"""
        result = text[::-1]
        await ctx.send(result)

    @fun.command(name="mock", aliases=['spongebob'])
    async def mock(self, ctx, *, text: str):
        """CoNvErT tExT tO mOcKiNg SpOnGeBoB cAsE"""
        result = ''.join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text))
        await ctx.send(result)

    # Error handling
    @fun.error
    async def fun_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing required argument: `{error.param.name}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument provided: {error}")
        else:
            await ctx.send(f"An error occurred: {error}")

async def setup(bot):
    await bot.add_cog(FunCog(bot))
