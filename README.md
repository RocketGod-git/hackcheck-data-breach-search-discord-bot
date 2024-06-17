# HackCheck - Data Breach Search - Discord Bot

HackCheck is a Discord bot that enables users to search for data breaches by various criteria such as email, password, username, and more. This bot utilizes the HackCheck.io API to fetch breach data and presents it interactively within Discord servers.

![1](https://github.com/RocketGod-git/hackcheck-data-breach-search-discord-bot/assets/57732082/9de8caf5-c247-4250-a751-a6351f1bbdf0)
![2](https://github.com/RocketGod-git/hackcheck-data-breach-search-discord-bot/assets/57732082/e6a5fcf5-a913-46c8-a7c5-afd1d2fc3446)

## Features

- Search for breaches by email, password, username, full name, IP address, phone number, and hash.
- Interactive Discord buttons and modals for seamless user experience.
- Detailed logging of bot activity.
- Output results in both CSV and PDF report formats.

## Download

You can download the latest version of the bot from the GitHub repository:

```bash
git clone https://github.com/RocketGod-git/hackcheck-data-breach-search-discord-bot.git
```

## Installation

Before running the bot, install the necessary Python packages directly using pip:

```bash
cd hackcheck-data-breach-search-discord-bot
pip install discord aiohttp aiolimiter reportlab

## Configuration

1. Update the `config.json` file with your Discord bot token and HackCheck API key:

```json
{
    "discord_bot_token": "YOUR-TOKEN",
    "hackcheck_api_key": "YOUR-KEY",
    "webhook_url": "DISCORD-WEBHOOK-FOR-LOGGING"
}
```
You'll have to figure out Discord Developer Portal. I'm not teaching these things here.

## Usage

Run the bot:

```bash
python hackcheckbot.py
```

The bot will connect to Discord, and you can start using it by invoking the slash command `/hackcheck` in your server.

## Contributing

Contributions are welcome! Please fork the repository and submit pull requests with your suggested changes.

## License

See `LICENSE` for more information.

![RocketGod](https://github.com/RocketGod-git/Flipper_Zero/assets/57732082/f5d67cfd-585d-4b23-905f-37151e3d6a7d)
