
<!-- ██╗  ██╗ ██████╗  ██████╗ ████████╗██╗   ██╗    ██████╗  ██████╗ ████████╗ -->
<!-- ██║  ██║██╔═══██╗██╔═══██╗╚══██╔══╝╚██╗ ██╔╝    ██╔══██╗██╔═══██╗╚══██╔══╝ -->
<!-- ███████║██║   ██║██║   ██║   ██║    ╚████╔╝     ██████╔╝██║   ██║   ██║    -->
<!-- ██╔══██║██║   ██║██║   ██║   ██║     ╚██╔╝      ██╔══██╗██║   ██║   ██║    -->
<!-- ██║  ██║╚██████╔╝╚██████╔╝   ██║      ██║       ██████╔╝╚██████╔╝   ██║    -->
<!-- ╚═╝  ╚═╝ ╚═════╝  ╚═════╝    ╚═╝      ╚═╝       ╚═════╝  ╚═════╝    ╚═╝    -->
<p align="center">
  <!-- <img width="800" height="250" alt="Banner" src="https://github.com/user-attachments/assets/b3be5951-4533-4e97-bc58-05dbd6eea284" /> -->
  <img src="https://github.com/user-attachments/assets/b3be5951-4533-4e97-bc58-05dbd6eea284" alt="Hooty Bot Banner" width="600"/>
</p>

<h1 align="center">🦉 Hooty Bot</h1>
<p align="center">
  <b>The all-in-one Discord bot for modern communities.</b><br>
  <i>Welcome, moderate, play, manage, and automate – all in one stylish package.</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-All%20rights%20reserved-red?style=flat-square">
  <img src="https://img.shields.io/badge/Docker-ready-blue?style=flat-square">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?style=flat-square">
</p>

## ‼️ Disclaimer
This bot was created for **my** personal use in my Discord communities. Taking this into account, any use, redistribution, modification or other action done with the code must be done under my approval, the code was only posted and open sourced on Github for easier redistribution to my portfolio.
## 🌟 Features

- **Welcome & Goodbye System**: Customizable messages, embeds, DMs, and logging.
- **Moderation**: Bans, kicks, mutes, timeouts, warnings, purges, role management, and more.
- **Leveling**: Text & voice XP, auto-roles, leaderboards, and rewards.
- **Tickets**: Multi-type ticket system with panels, auto-close, and staff pings.
- **Starboard**: Highlight the best messages with emoji-based starboards.
- **Economy**: Jobs, games, banking, leaderboards, and more.
- **Fun & Games**: Truth or Dare, Would You Rather, memes, and more.
- **Utility**: Role info, avatar viewer, URL shortener, and diagnostics.
- **Autoroles & Reaction Roles**: Auto-assign and reaction-based roles.
- **Minecraft Server Management**: Start/stop/status for Docker/JAR servers (with Docker integration).
- **Giveaways**: Timed, multi-winner, and fully managed.
- **Bump Reminders**: Never miss a Disboard bump again!
- **And much more...**

## 🚀 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/juinc/hooty-bot.git
cd hooty-bot
```
### 2. Configure Environment
Create your `.env` file inside the Hooty Bot directory (not in `src`), and paste in your bot's configuration:
```
BOT_TOKEN=YOUR_TOKEN
```
### 3. Run with Docker (Recommended)
> **Requires Docker & Docker Compose installed.**
#### Build and Start
```bash
docker compose up --build -d
```
- The bot will auto-restart unless stopped.
- All data/config is stored in the `src/` folder (mapped to the container).

#### Stopping the Bot
```bash
docker compose down
```
#### Updating
```bash
git pull
docker compose up --build -d
```

## 🛠️ Configuration
- All configuration and data is stored in the `src/config/` and `src/database/` folders.
- Use the bot's slash commands or prefix commands to configure features in Discord.
- For advanced features (e.g., Minecraft server management), ensure the bot has access to the Docker socket (`/var/run/docker.sock`).

## 💡 Credits & Contact
- **Author:** juinc
- **Discord:** @juinc

## 🦉 Hooty says:  
> _"Why use 10 bots when you can use one? Hooty handles it all, with style."_
---
<p align="center">
  <img src="https://em-content.zobj.net/source/microsoft-teams/363/owl_1f989.png" width="64" alt="Owl"/>
</p>

