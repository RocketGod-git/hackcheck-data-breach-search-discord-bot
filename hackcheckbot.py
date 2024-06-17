# __________                  __             __     ________             .___ 
# \______   \  ____    ____  |  | __  ____ _/  |_  /  _____/   ____    __| _/ 
#  |       _/ /  _ \ _/ ___\ |  |/ /_/ __ \\   __\/   \  ___  /  _ \  / __ |  
#  |    |   \(  <_> )\  \___ |    < \  ___/ |  |  \    \_\  \(  <_> )/ /_/ |  
#  |____|_  / \____/  \___  >|__|_ \ \___  >|__|   \______  / \____/ \____ |  
#         \/              \/      \/     \/               \/              \/  
#
# Hackcheck - Data breach searching Discord Bot - by RocketGod
#
# https://github.com/RocketGod-git/hackcheck-data-breach-search-discord-bot


import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import sys
import os
import io
import traceback
import re
from datetime import datetime
from xml.sax.saxutils import escape

import discord
from discord.ui import Modal, TextInput
from discord.ui import Button, View
from discord import ButtonStyle

import aiohttp
from aiohttp import ClientTimeout, ClientError, ClientResponseError, ServerTimeoutError
import requests

from aiolimiter import AsyncLimiter
limiter = AsyncLimiter(8, 1)

from reportlab.lib.pagesizes import elevenSeventeen, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
import csv
import ast 

from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(), 
        RotatingFileHandler('hackcheck.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8', mode='a')  
    ]
)
logging.getLogger('discord').setLevel(logging.WARNING)


timeout = ClientTimeout(total=120)
retry_attempts = 3
backoff_factor = 0.5


def load_config():
    try:
        with open("config.json", "r") as config_file:
            return json.load(config_file)
    except FileNotFoundError:
        logging.critical("The config.json file was not found.")
        raise
    except json.JSONDecodeError:
        logging.critical("config.json is not a valid JSON file.")
        raise
    except Exception as e:
        logging.critical(f"An unexpected error occurred while loading config.json: {e}")
        raise


config = load_config()


def validate_email(email):
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def prepare_data_for_csv(results):
    prepared_data = []
    for result in results:
        row = {key: value for key, value in result.items() if key != 'source'}
        source_info = result.get('source', {})
        source_name = source_info.get('name', 'Unknown source')
        source_date = source_info.get('date', 'No date provided')
        row['source'] = f"Name: {source_name}, Date: {source_date}"
        prepared_data.append(row)
    return prepared_data


def create_csv_file(data, filename_prefix="results"):
    if not data:  
        return None

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{filename_prefix}_{timestamp}.csv"

    keys = data[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, keys)
        dict_writer.writeheader()
        dict_writer.writerows(data)

    return filename


def create_pdf_from_csv(csv_filename, filename_prefix="results"):
    timestamp = csv_filename.split('_')[-1].split('.')[0]
    pdf_filename = f"{filename_prefix}_{timestamp}.pdf"

    with open(csv_filename, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        data = [list(row) for row in reader]

    readable_style = ParagraphStyle(
        name='Readable',
        fontName='Times-Roman',  
        fontSize=10,
        leading=12,  
        alignment=TA_LEFT,
    )

    styles = getSampleStyleSheet()
    styleNormal = styles['Normal']
    styleNormal.wordWrap = 'CJK'  

    for i, row in enumerate(data):
        for j, cell in enumerate(row):
            if j == len(row) - 1:
                try:
                    source_dict = ast.literal_eval(cell)
                    source_str = f"{source_dict.get('name', 'N/A')}: {source_dict.get('date', 'No date')}"
                    data[i][j] = Paragraph(escape(source_str), readable_style)
                except (ValueError, SyntaxError):
                    data[i][j] = Paragraph(escape(cell), readable_style)
            else:
                data[i][j] = Paragraph(escape(cell), readable_style)

    pdf = SimpleDocTemplate(pdf_filename, pagesize=landscape(elevenSeventeen))

    usable_width = landscape(elevenSeventeen)[0] - 2 * 72  # 1 inch margins on each side
    column_widths = [usable_width * 0.19,  # email
                     usable_width * 0.10,  # password
                     usable_width * 0.10,  # full_name
                     usable_width * 0.10,  # username
                     usable_width * 0.08,  # ip_address
                     usable_width * 0.08,  # phone_number
                     usable_width * 0.20,  # hash (remaining space)
                     usable_width * 0.15]  # source

    table = Table(data, colWidths=column_widths, repeatRows=1)

    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
    ])
    table.setStyle(style)

    elems = [table]
    pdf.build(elems)

    return pdf_filename


class PaginatorView(discord.ui.View):
    def __init__(self, data, term, search_type, page_size=4):
        super().__init__()
        self.data = data
        self.term = term
        self.search_type = search_type
        self.page_size = page_size
        self.current_page = 0
        self.max_page = (len(self.data) - 1) // page_size
        self.message = None

        self.back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.primary, disabled=(self.current_page == 0))
        self.next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary, disabled=(self.current_page >= self.max_page))
        
        self.add_item(self.back_button)
        self.add_item(self.next_button)
        self.back_button.callback = self.back_button_callback
        self.next_button.callback = self.next_button_callback

    async def back_button_callback(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_buttons_and_message(interaction)

    async def next_button_callback(self, interaction: discord.Interaction):
        if self.current_page < self.max_page:
            self.current_page += 1
        await self.update_buttons_and_message(interaction)

    async def update_buttons_and_message(self, interaction):
        try:
            self.back_button.disabled = self.current_page == 0
            self.next_button.disabled = self.current_page >= self.max_page
            await self.update_message(interaction)
            await interaction.response.edit_message(view=self)
        except discord.NotFound:
            logging.error("Error: Message not found when trying to edit.")
        except discord.HTTPException as e:
            logging.error(f"HTTP error occurred: {e}")
        except Exception as e:
            logging.error(f"Unhandled exception: {e}")

    async def update_message(self, interaction):
        start = self.current_page * self.page_size
        end = start + self.page_size
        limited_results = {"results": self.data[start:end]}
        content = format_breaches(self.term, self.search_type, limited_results)
        try:
            if self.message:
                await self.message.edit(content=content, view=self)
            else:
                self.message = await interaction.followup.send(content=content, view=self)
        except discord.NotFound:
            logging.error("Error: Message not found when trying to send or edit.")
        except discord.HTTPException as e:
            logging.error(f"HTTP error while sending or editing message: {e}")
        except Exception as e:
            logging.error(f"Unhandled exception during message update: {e}")

    async def on_timeout(self):
        self.back_button.disabled = True
        self.next_button.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            logging.error("Error: Message not found during timeout.")
        except discord.HTTPException as e:
            logging.error(f"HTTP error occurred during on_timeout: {e}")
        except Exception as e:
            logging.error(f"Unhandled exception during on_timeout: {e}")

    def stop_paginator(self):
        self.stop()


async def make_hackcheck_request(search_type, term, max_pages=75):
    api_key = config["hackcheck_api_key"]
    all_results = []
    offset = 0
    limit = 75  # Adjust the limit as needed
    page_count = 0

    async with aiohttp.ClientSession(timeout=timeout) as session:
        has_more_data = True

        while has_more_data and page_count < max_pages:
            async with limiter:
                url = f"https://api.hackcheck.io/search/{api_key}/{search_type.replace(' ', '_')}/{term}?offset={offset}&limit={limit}"
                try:
                    async with session.get(url) as response:
                        data = await response.json()  
                        if response.status != 200:
                            error_message = data.get('error', 'Unknown error')
                            logging.error(f"API Error: {error_message}")
                            logging.error(f"API Response: {data}")  
                            return {"error": f"API Error: {error_message}"}

                        all_results.extend(data["results"])
                        pagination_info = data.get('pagination', {})

                        next_page = pagination_info.get('next')
                        if next_page:
                            offset = next_page['offset']
                            limit = next_page['limit']
                        else:
                            has_more_data = False

                        page_count += 1

                except aiohttp.ClientError as e:
                    logging.error(f"ClientError occurred: {e}")
                except json.JSONDecodeError as e:
                    logging.error(f"JSONDecodeError occurred: {e}")
                except asyncio.TimeoutError as e:
                    logging.error(f"TimeoutError occurred: {e}")
                except Exception as e:
                    logging.error(f"An unexpected error occurred: {type(e).__name__}: {e}")
                    traceback_str = traceback.format_exc() 
                    logging.error(f"Traceback: {traceback_str}")
                    return {"error": "An unexpected error occurred during the API request."}

    return {"results": all_results}


def format_breaches(term, search_type, response):
    header = f"{term}:\n\n"

    if not response or "results" not in response or not response["results"]:
        return f"No breaches found for {search_type} '{term}'."

    breach_list = []
    for breach in response["results"]:
        details = []
        source_info = breach.get("source", {})
        source_name = source_info.get("name", "Unknown source")
        date = source_info.get("date", "No date")  

        details.append(f"- Source: {source_name} ({date})")  

        for key in ["email", "password", "username", "full_name", "ip_address", "phone_number", "hash"]:
            value = breach.get(key)
            if value:
                details.append(f"  {key.replace('_', ' ').capitalize()}: {value}")

        breach_list.append('\n'.join(details))

    return header + '\n\n'.join(breach_list)


async def attempt_delete_with_retries(filename, max_attempts=5):
    attempt = 0
    while attempt < max_attempts:
        try:
            os.remove(filename)
            return True  
        except PermissionError as e:
            logging.warning(f"PermissionError when trying to delete file {filename}. Retrying... Attempt {attempt + 1}/{max_attempts}")
            await asyncio.sleep(1)  
        except FileNotFoundError:
            logging.warning(f"File {filename} not found. It may have already been deleted.")
            return False  
        except Exception as e:
            logging.error(f"Failed to delete file {filename} on attempt {attempt + 1}: {e}")
            break  
        finally:
            attempt += 1

    logging.error(f"Could not delete file {filename} after {max_attempts} attempts.")
    return False  


class SearchModal(Modal):
    def __init__(self, search_type, bot):
        super().__init__(title=f"Search by {search_type.capitalize()}")
        self.search_type = search_type
        self.bot = bot
        self.add_item(TextInput(label=f"Enter {search_type}", custom_id="search_term"))

    async def on_submit(self, interaction: discord.Interaction):
        term = self.children[0].value
        if interaction.guild:
            guild_name = interaction.guild.name
            channel_name = interaction.channel.name
        else:
            guild_name = "Direct Message"
            channel_name = "Direct Message"

        logging.info(f"{interaction.user} searched for '{term}' from '{channel_name}' at '{guild_name}'")

        if self.search_type == "email" and not validate_email(term):
            await interaction.response.send_message("The provided email is invalid. Please enter a valid email address.")
            return

        asyncio.create_task(self.send_webhook_message(interaction.user, term, interaction, interaction.guild))
        await interaction.response.defer(ephemeral=False)

        asyncio.create_task(self.process_search(interaction, term))
        
    async def process_search(self, interaction: discord.Interaction, term: str):
        try:
            await interaction.followup.send("Processing your search. Please wait...")

            full_results = await make_hackcheck_request(self.search_type, term)
            if "error" in full_results:
                logging.error(full_results["error"])
                await interaction.followup.send("An error occurred while processing your request. Please try again later.")
                return

            reversed_results = list(reversed(full_results["results"]))
            paginator_view = PaginatorView(reversed_results, term, self.search_type)
            self.paginator_view = paginator_view  
            content = format_breaches(term, self.search_type, {"results": reversed_results[:paginator_view.page_size]})
            message = await interaction.followup.send(content=content, view=paginator_view)
            paginator_view.message = message

            csv_filename, pdf_filename = await self.generate_reports(reversed_results)
            if csv_filename and pdf_filename:
                await self.send_reports(interaction, csv_filename, pdf_filename, term, interaction.user.display_name)

        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            await interaction.followup.send("An unexpected error occurred. Please try again later.")

    async def send_webhook_message(self, user, term, interaction, guild):
        webhook_url = config["webhook_url"]
        search_info = f"Search performed by {user.display_name}"
        user_avatar_url = user.avatar.url if user.avatar else None
        embed_content = self.construct_embed(user, term, guild, user_avatar_url)
        webhook_data = {
            "content": None,
            "username": "HackCheck Bot",
            "embeds": [embed_content],
        }

        async with aiohttp.ClientSession() as session:
            try:
                response = await session.post(webhook_url, json=webhook_data)
                if response.status != 204:
                    logging.error(f"Webhook failed with status code {response.status}")
            except Exception as e:
                logging.error(f"An error occurred while sending the webhook message: {e}")

    def construct_embed(self, user, term, guild, avatar_url):
        server_info = f"**Name:** {guild.name}\n**Members:** {guild.member_count}" if guild else "Direct Message"
        return {
            "title": "🔍 New Search Performed",
            "description": f"**User:** {user}\n**Term:** `{term}`",
            "color": 3447003,
            "fields": [{"name": "Server or DM", "value": server_info, "inline": False}],
            "thumbnail": {"url": avatar_url},
            "footer": {"text": f"{user} initiated", "icon_url": avatar_url},
            "timestamp": datetime.utcnow().isoformat()
        }

    async def generate_reports(self, results):
        try:
            csv_filename = create_csv_file(results, "full_results")
            pdf_filename = create_pdf_from_csv(csv_filename, "full_results") if csv_filename else None
            return csv_filename, pdf_filename
        except Exception as e:
            logging.error(f"Error generating reports: {e}")
            return None, None

    async def send_reports(self, interaction, csv_filename, pdf_filename, term, username):
        try:
            if csv_filename:
                await interaction.followup.send("Here's the full report in CSV format:", file=discord.File(csv_filename))
            if pdf_filename:
                await interaction.followup.send("Here's the full report in PDF format:", file=discord.File(pdf_filename))
            await interaction.followup.send(f"Finished searching `{term}` for `{username}`")
            await asyncio.gather(
                attempt_delete_with_retries(csv_filename),
                attempt_delete_with_retries(pdf_filename)
            )
        except Exception as e:
            logging.error(f"Error sending reports: {e}")


class SearchButton(Button):
    def __init__(self, label, search_type, bot):
        super().__init__(label=label, style=ButtonStyle.primary)
        self.search_type = search_type
        self.bot = bot

    async def callback(self, interaction):
        await self.view.disable_all_buttons()
        modal = SearchModal(search_type=self.search_type, bot=self.bot)
        await interaction.response.send_modal(modal)

class SpacerButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", disabled=True)

class SearchTypeView(discord.ui.View):
    def __init__(self, bot, timeout=30):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.add_buttons()

    def add_buttons(self):
        types = ["Email", "Password", "Username", "Full Name", "IP Address", "Phone Number", "Hash", "Domain"]
        for i, t in enumerate(types):
            if i > 0:
                self.add_item(SpacerButton())
            self.add_item(SearchButton(label=f"Search by {t}", search_type=t.lower(), bot=self.bot))

    async def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = True
        try:
            await self.message.edit(view=self)  
        except Exception as e:
            print(f"Failed to update view: {str(e)}")

    async def on_timeout(self):
        await self.disable_all_buttons()


class Bot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = discord.app_commands.CommandTree(self)
        self.discord_message_limit = 2000

    async def setup_hook(self):
        self.tree.add_command(check_breach_command)

    async def on_ready(self):
        for guild in self.guilds:
            try:
                owner = await guild.fetch_member(guild.owner_id)
                owner_name = f"{owner.name}#{owner.discriminator}"
            except Exception as e:
                logging.error(f"Could not fetch owner for guild: {guild.name}, error: {e}")
                owner_name = "Could not fetch owner"
            
            logging.info(f" - {guild.name} (Owner: {owner_name})")

        server_count = len(self.guilds)
        activity_text = f"/hackcheck on {server_count} servers"
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=activity_text))
        await self.tree.sync()

        logging.info(f"Bot {self.user} is ready and running in {len(self.guilds)} servers.")


    async def on_guild_join(self, guild):
        await self.send_webhook_message_for_guild(guild)


    async def send_webhook_message_for_guild(self, guild):
        """
        Sends a webhook message with details about the new guild the bot has joined.
        """
        webhook_url = config["webhook_url"]  
        target_guild_id = 'YOUR-GUILD-ID'
        target_channel_id = 'YOUR-CHANNEL-ID'

        try:
            owner = await guild.fetch_member(guild.owner_id)
        except discord.NotFound:
            owner = await self.fetch_user(guild.owner_id)
            owner_info = f"{owner} (Fetched as User)"
        except Exception as e:
            logging.error(f"Failed to fetch guild owner for {guild.name} (ID: {guild.id}): {e}")
            owner_info = "Owner information unavailable"
        else:
            owner_info = str(owner)

        embed = {
            "title": "🤖 Bot Added to Server",
            "description": "The bot has been added to a new server!",
            "color": 3066993,  
            "fields": [
                {
                    "name": "🌐 Server Name",
                    "value": guild.name,
                    "inline": False
                },
                {
                    "name": "🆔 Server ID",
                    "value": str(guild.id),
                    "inline": False
                },
                {
                    "name": "👑 Owner",
                    "value": f"{owner_info} (ID: {guild.owner_id})",
                    "inline": False
                },
                {
                    "name": "👥 Member Count",
                    "value": str(guild.member_count),
                    "inline": False
                },
                {
                    "name": "🎭 Role Count",
                    "value": str(len(guild.roles)),
                    "inline": False
                },
                {
                    "name": "💬 Channel Count",
                    "value": (f"Text: {len([c for c in guild.channels if isinstance(c, discord.TextChannel)])}, "
                            f"Voice: {len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])}, "
                            f"Categories: {len(guild.categories)}"),
                    "inline": False
                },
                {
                    "name": "📅 Server Creation Date",
                    "value": guild.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "inline": False
                },
            ],
            "footer": {
                "text": f"Bot is now in {len(self.guilds)} servers"
            }
        }

        server_avatar_url = guild.icon.url if guild.icon else None
        if server_avatar_url:
            embed["thumbnail"] = {"url": server_avatar_url}

        try:
            server_region = str(guild.region)
        except AttributeError:
            server_region = "Server region information not available."

        embed["fields"].append({
            "name": "🌍 Server Region",
            "value": server_region,
            "inline": False
        })

        emoji_line = " ".join(str(emoji) for emoji in guild.emojis)
        embed["fields"].append({
            "name": "😃 Server Emojis",
            "value": emoji_line if emoji_line else "No custom emojis",
            "inline": False
        })

        current_server_count = len(self.guilds)  
        webhook_data = {
            "username": "Bot Server Count Update",
            "embeds": [embed],
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(webhook_url, json=webhook_data) as response:
                    if response.status == 204:
                        logging.info(f"New server join: {guild.name}, owned by {owner_info}. Total servers: {current_server_count}")
                    else:
                        logging.error(f"Webhook for new server join failed with status code {response.status} for {guild.name}")
            except Exception as e:
                logging.error(f"Error sending webhook for new server join: {e}")

        target_guild = self.get_guild(int(target_guild_id))
        if target_guild:
            target_channel = target_guild.get_channel(int(target_channel_id))
            if target_channel:
                await target_channel.send(embed=discord.Embed.from_dict(embed))
            else:
                logging.warning(f"Target channel not found: {target_channel_id}")
        else:
            logging.warning(f"Target guild not found: {target_guild_id}")

        channel_names = [f"- {channel.name}" for channel in guild.channels]
        channel_names_str = "\n".join(channel_names)
        await self.send_discord_webhook_message(webhook_url, f"📺 **Channel Names:**\n{channel_names_str}")
        if target_guild:
            target_channel = target_guild.get_channel(int(target_channel_id))
            if target_channel:
                await target_channel.send(f"📺 **Channel Names:**\n{channel_names_str}")
            else:
                logging.warning(f"Target channel not found: {target_channel_id}")
        else:
            logging.warning(f"Target guild not found: {target_guild_id}")

        member_names = [f"- {member.display_name}" for member in guild.members]
        member_names_str = "\n".join(member_names)
        max_length = 1900  
        if len(member_names_str) > max_length:
            parts = [member_names_str[i:i+max_length] for i in range(0, len(member_names_str), max_length)]
            for i, part in enumerate(parts):
                header = f"👥 **Member Names (Part {i+1}/{len(parts)}):**\n"
                await self.send_discord_webhook_message(webhook_url, header + part)
                if target_guild:
                    target_channel = target_guild.get_channel(int(target_channel_id))
                    if target_channel:
                        await target_channel.send(header + part)
                    else:
                        logging.warning(f"Target channel not found: {target_channel_id}")
                else:
                    logging.warning(f"Target guild not found: {target_guild_id}")
        else:
            await self.send_discord_webhook_message(webhook_url, f"👥 **Member Names:**\n{member_names_str}")
            if target_guild:
                target_channel = target_guild.get_channel(int(target_channel_id))
                if target_channel:
                    await target_channel.send(f"👥 **Member Names:**\n{member_names_str}")
                else:
                    logging.warning(f"Target channel not found: {target_channel_id}")
            else:
                logging.warning(f"Target guild not found: {target_guild_id}")
                    

    async def send_discord_webhook_message(self, webhook_url, content):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(webhook_url, json={"content": content}) as response:
                    if response.status != 204:
                        logging.error(f"Failed to send Discord webhook message. Status code: {response.status}")
            except Exception as e:
                logging.error(f"Error sending Discord webhook message: {e}")


    async def on_error(self, event_method, *args, **kwargs):
        error_type, error_instance, traceback_info = sys.exc_info()
        logging.error(f"Unhandled exception in {event_method}: {error_type.__name__}: {error_instance}")
        logging.error(traceback.format_exc())

        if isinstance(error_instance, aiohttp.client_exceptions.ClientConnectorError):
            logging.info("Detected a connection issue, attempting to reconnect...")

            await asyncio.sleep(5)  

            try:
                logging.info("Reconnection attempt successful.")
            except Exception as reconnection_error:
                logging.error(f"Failed to reconnect: {reconnection_error}")

        elif isinstance(error_instance, discord.errors.NotFound) and error_instance.code == 10062:
            logging.warning(f"Unknown interaction error occurred in {event_method}. Error: {error_instance}")

        else:
            channel = None
            for arg in args:
                if isinstance(arg, discord.Message):
                    channel = arg.channel
                    break
                elif hasattr(arg, 'channel'):
                    channel = arg.channel
                    break

            if channel:
                try:
                    await channel.send("Oops! It seems like there was an issue. Don't worry, I'm still here! If the problem persists, please contact support.")
                except discord.DiscordException:
                    logging.error("Failed to send an error message to the channel.")


    async def send_split_messages(self, interaction, message: str, require_response=True):
        """Sends a message, and if it's too long for Discord, splits it."""
        # Handle empty messages
        if not message.strip():
            logging.warning("Attempted to send an empty message.")
            return

        query = ""
        for option in interaction.data.get("options", []):
            if option.get("name") == "query":
                query = option.get("value", "")
                break

        prepend_text = ""
        if query:
            prepend_text = f"Query: {query}\n\n"

        lines = message.split("\n")
        chunks = []
        current_chunk = ""

        if prepend_text:
            current_chunk += prepend_text

        for line in lines:
            while len(line) > self.discord_message_limit:
                sub_line = line[:self.discord_message_limit]
                if len(current_chunk) + len(sub_line) + 1 > self.discord_message_limit:
                    chunks.append(current_chunk)
                    current_chunk = ""
                current_chunk += sub_line + "\n"
                line = line[self.discord_message_limit:]

            if len(current_chunk) + len(line) + 1 > self.discord_message_limit:
                chunks.append(current_chunk)
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"

        if current_chunk:
            chunks.append(current_chunk)

        if not chunks:
            logging.warning("No chunks generated from the message.")
            return

        if require_response and not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)

        try:
            await interaction.followup.send(content=chunks[0], ephemeral=False)
            chunks = chunks[1:]  
        except Exception as e:
            logging.error(f"Failed to send the first chunk via followup. Error: {e}")

        for chunk in chunks:
            try:
                await interaction.channel.send(chunk)
            except Exception as e:
                logging.error(f"Failed to send a message chunk to the channel. Error: {e}")


@discord.app_commands.command(name="hackcheck", description="Check for data breaches.")
async def check_breach_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=False)

        view = SearchTypeView(bot=interaction.client)
        message = await interaction.followup.send("Select the type of data you want to search for:", view=view, ephemeral=False)
        view.message = message  

    except Exception as e:
        logging.error(f"An unexpected error occurred in the 'hackcheck' command: {e}")
        try:
            await interaction.followup.send("Sorry, an unexpected error occurred. Please try again later.", ephemeral=True)
        except discord.errors.NotFound:
            logging.error("Failed to send followup message. The interaction may have expired.")
            

async def run():
    intents = discord.Intents.default() 

    bot = Bot(intents=intents)
    
    try:
        async with bot:
            await bot.start(config["discord_bot_token"])
    except Exception as e:
        logging.critical(f"An error occurred while running the bot: {e}")
        logging.critical(traceback.format_exc())
        

if __name__ == "__main__":
    asyncio.run(run())
