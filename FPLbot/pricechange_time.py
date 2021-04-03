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
client = MongoClient()


async def main(config):
    """Returns a list of players whose price has changed since the last
    time the database was updated.
    """
    database = client.fpl
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        fpl_bot = FPLBot(config, session)
        new_players = await fpl.get_players(include_summary=False)

        for new_player in new_players:
            old_player = database.players.find_one({"id": new_player.id})
            # New player has been added to the game
            if not old_player:
                continue

            if (old_player["now_cost"] > new_player.now_cost or
                    old_player["now_cost"] < new_player.now_cost):
                await fpl_bot.post_price_changes(new_players)

if __name__ == "__main__":
    with open(f"{dirname}/../config.json") as file:
        config = json.loads(file.read())
        try:
            asyncio.run(main(config))
        except AttributeError:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main(config))
            loop.close()