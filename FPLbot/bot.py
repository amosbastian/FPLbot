import asyncio
import json
import logging
import os
from datetime import datetime

import aiohttp
import praw
from fpl import FPL
from fpl.utils import position_converter
from pymongo import MongoClient

from utils import get_player_table, update_players

dirname = os.path.dirname(os.path.realpath(__file__))
logger = logging.getLogger("FPLbot")
logger.setLevel(logging.INFO)
logging.basicConfig()


class FPLBot:
    def __init__(self, config, session):
        self.client = MongoClient()
        self.fpl = FPL(session)
        self.reddit = praw.Reddit(
            client_id=config.get("CLIENT_ID"),
            client_secret=config.get("CLIENT_SECRET"),
            password=config.get("PASSWORD"),
            user_agent=config.get("USER_AGENT"),
            username=config.get("USERNAME"))
        self.subreddit = self.reddit.subreddit(config.get("SUBREDDIT"))

    async def get_price_changers(self):
        """Returns a list of players whose price has changed since the last
        time the database was updated.
        """
        logger.info("Retrieving risers and fallers.")
        new_players = await self.fpl.get_players(include_summary=True)
        old_players = [player for player in self.client.fpl.players.find()]

        risers = []
        fallers = []

        for new_player in new_players:
            try:
                old_player = next(player for player in old_players
                                  if player["id"] == new_player.id)
            # New player has been added to the game
            except StopIteration:
                logger.info(f"New player added: {new_player}.")
                continue

            if old_player["now_cost"] > new_player.now_cost:
                fallers.append(new_player)
            elif old_player["now_cost"] < new_player.now_cost:
                risers.append(new_player)

        return risers, fallers

    async def post_price_changes(self):
        """Posts the price changes to Reddit."""
        risers, fallers = await self.get_price_changers()
        risers_table = get_player_table(risers, True)
        fallers_table = get_player_table(fallers, False)

        post_template = open(f"{dirname}/../post_template.md").read()
        post_body = post_template.format(
            risers_number=len(risers),
            risers_table=risers_table,
            fallers_number=len(fallers),
            fallers_table=fallers_table
        )

        today = datetime.now()
        current_date = f"({today:%B} {today.day}, {today.year})"
        post_title = f"Player Price Changes {current_date}"

        logger.info(f"Posting price changes to Reddit.\n\n{post_body}")
        self.subreddit.submit(post_title, selftext=post_body)
        await update_players()


async def main(config):
    async with aiohttp.ClientSession() as session:
        fpl_bot = FPLBot(config, session)

        await fpl_bot.post_price_changes()


if __name__ == "__main__":
    config = json.loads(open(f"{dirname}/../config.json").read())
    asyncio.run(main(config))
