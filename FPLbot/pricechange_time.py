
import asyncio
import json
import logging
import os
import re
from datetime import datetime

import aiohttp
import praw
from fpl import FPL
from fpl.utils import position_converter
from pymongo import MongoClient

from bot import FPLBot


dirname = os.path.dirname(os.path.realpath(__file__))


def create_logger():
    """Creates a logger object for use in logging across all files.
    See: https://docs.python.org/3/howto/logging-cookbook.html
    """
    logger = logging.getLogger("FPLbot")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(f"{dirname}/pricechange.log")
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - "
                                  "%(message)s")

    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


logger = create_logger()
client = MongoClient()


async def main(config):
    """Returns a list of players whose price has changed since the last
    time the database was updated.
    """
    database = client.fpl
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        fpl_bot = FPLBot(config, session)
        new_players = await fpl.get_players(include_summary=True)

        for new_player in new_players:
            old_player = database.players.find_one({"id": new_player.id})
            # New player has been added to the game
            if not old_player:
                continue

            if old_player["now_cost"] > new_player.now_cost or old_player["now_cost"] < new_player.now_cost:
                logger.info(f"Price changes occur at roughly: {datetime.now()}")
                await fpl_bot.post_price_changes()

if __name__ == "__main__":
    with open(f"{dirname}/../config.json") as file:
        config = json.loads(file.read())
        try:
            asyncio.run(main(config))
        except AttributeError:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main(config))
            loop.close()

