import sys
import logging
import asyncio
import traceback

import discord
from discord.ext import commands

from helpers.misc import maximize_size
from config_handler import ConfigHandler
from database_handler import DatabaseHandler
from helpers import logger_handlers, embed_handler
from helpers.licence_helper import get_current_time


root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(logger_handlers.get_console_handler())
root_logger.addHandler(logger_handlers.get_file_handler())
logger = logging.getLogger("discord")
logger.setLevel(logging.WARNING)

startup_extensions = [
    "licenses",
    "bot_owner_commands",
    "guild",
    "bot_information",
    "help",
    "cmd_errors",
    # Disabled because dblpy is unmaintained and incompatible with discord.py 2.x.
    # "top_gg_api",
]


class Bot(commands.Bot):
    def __init__(self, **kwargs):
        self.config = ConfigHandler("config")
        self.main_db = None  # Will be initialized in setup_hook
        self.up_time_start_time = get_current_time()
        
        # Updated intents for discord.py 2.x
        intents = discord.Intents.default()
        intents.message_content = True  # Required for message content access in 2.x
        intents.members = True
        
        super(Bot, self).__init__(
            command_prefix=self.prefix_callable,
            help_command=None,
            description=self.config["bot_description"],
            case_insensitive=True,
            intents=intents,
            **kwargs
        )

    async def prefix_callable(self, bot_client, message):
        default_prefix = self.config["default_prefix"]
        if message.guild is None or bot_client.main_db is None:
            return default_prefix
        try:
            # TODO: Store this in list or something so we don't waste calls to db for each message
            return await bot_client.main_db.get_guild_prefix(message.guild.id)
        except Exception as err:
            """
            If fetching prefix from database errors just use the default prefix.
            """
            root_logger.error(f"Can't get guild {message.guild} prefix. Error:{err}. "
                              f"Using '{default_prefix}' as prefix.")
            return default_prefix

    async def on_ready(self):
        root_logger.info(
            f"Logged in as: {self.user.name} - {self.user.id}"
            f"\tDiscordPy version: {discord.__version__}"
        )
        root_logger.info("Successfully logged in and booted...!")

    async def on_connect(self):  # Removed @staticmethod
        root_logger.info("Connection to Discord established")

    async def on_guild_remove(self, guild):  # Removed @staticmethod
        root_logger.info(f"Left guild {guild.name}")

    async def on_disconnect(self):  # Removed @staticmethod
        root_logger.warning("Connection lost")

    async def on_error(self, event: str, *args, **kwargs):
        """
        Called when an EVENT raises an uncaught exception

        This doesn't use the same event system as the rest of events despite being documented as such.
        Can only have one and it's gotta be in main file.
        """
        exc_info = sys.exc_info()
        exc_type = exc_info[0].__name__ if exc_info[0] is not None else "<no exception>"
        exc_what = str(exc_info[1]) if exc_info[1] is not None else ""
        log_message = f"Uncaught {exc_type} in '{event}': {exc_what}\n{traceback.format_exc()}"
        await self.send_to_log_channel(log_message, title="on_error exception!")

    async def send_to_log_channel(self, message: str, *, title: str, ctx=None):
        """
        Logs passed message to logger as critical and sends the said message to bot log channel, if one is found.
        :param message: Message with error/traceback
        :param title: Title for message
        :param ctx: optional, if passed will be used to add additional info to message embed footer
        """
        root_logger.critical(f"{title}\n{message}")
        if self.is_ready():
            log_channel = self.get_channel(self.config["developer_log_channel_id"])
            embed = embed_handler.simple_embed(maximize_size(message), title, discord.Colour.red())
            if ctx is not None:
                guild_id = "DM" if ctx.guild is None else ctx.guild.id
                footer = f"Guild: {guild_id}    Author: {ctx.author}    Channel: {ctx.channel.id}"
                embed.set_footer(text=footer)
            if log_channel is not None:
                await log_channel.send(embed=embed)

    async def setup_hook(self):
        """Setup hook to initialize database and load extensions - new in discord.py 2.x"""
        # Initialize database first
        root_logger.info("Initializing database...")
        self.main_db = await DatabaseHandler.create_instance()
        root_logger.info("Database initialized successfully!")
        
        # Then load extensions
        root_logger.info("Loading extensions:")
        for extension in startup_extensions:
            cog_path = f"cogs.{extension}"
            try:
                await self.load_extension(cog_path)  # Now requires await
                root_logger.info(f"\t{cog_path}")
            except Exception as e:
                exc = f"{type(e).__name__}: {e}"
                root_logger.error(f"{exc} Failed to load extension {cog_path}")
                traceback_msg = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                root_logger.warning(traceback_msg)

    async def close(self):
        if self.main_db is not None and self.main_db.connection is not None:
            try:
                await self.main_db.connection.commit()
                await self.main_db.connection.close()
                root_logger.info("Database closed.")
            finally:
                self.main_db.connection = None
        await super().close()


async def main():
    bot = Bot()
    async with bot:
        await bot.start(bot.config["token"])


if __name__ == "__main__":
    asyncio.run(main())
