import asyncio
import json
import logging
import os
import re
from datetime import datetime

import aiohttp
import praw
from fpl import FPL
from fpl.utils import position_converter, team_converter
from pymongo import MongoClient

from constants import fpl_team_names, versus_pattern
from utils import create_logger, get_player_table, to_fpl_team, update_players

dirname = os.path.dirname(os.path.realpath(__file__))
logger = create_logger()
client = MongoClient()


class FPLBot:
    def __init__(self, config, session):
        self.database = client.fpl
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
        old_players = [player for player in self.database.players.find()]

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

    def player_vs_team_table(self, fixtures):
        """Returns a Markdown table showing the player's performance in the
        given fixtures.
        """
        table = ("|Fixture|Date|MP|G|xG|A|xA|NPG|NPxG|KP|\n"
                 "|:-|:-:|-:|-:|-:|-:|-:|-:|-:|-:|\n")

        for fixture in fixtures:
            home_team = f"{fixture['h_team']} {fixture['h_goals']}"
            away_team = f"{fixture['a_goals']} {fixture['a_team']}"

            # Highlight the winning team
            if int(fixture["h_goals"]) > int(fixture["a_goals"]):
                home_team = f"**{home_team}**"
            elif int(fixture["h_goals"]) < int(fixture["a_goals"]):
                away_team = f"**{away_team}**"

            # Highlight whether the player was a starter or not
            if fixture["position"].lower() != "sub":
                fixture["time"] = f"**{fixture['time']}**"

            table += (
                f"|{home_team}-{away_team}"
                f"|{fixture['date']}"
                f"|{fixture['time']}"
                f"|{fixture['goals']}"
                f"|{float(fixture['xG']):.2f}"
                f"|{fixture['assists']}"
                f"|{float(fixture['xA']):.2f}"
                f"|{fixture['npg']}"
                f"|{float(fixture['npxG']):.2f}"
                f"|{fixture['key_passes']}|\n"
            )

        return table

    def versus_team_handler(self, player_name, team_name, number_of_fixtures):
        """Function for handling player vs. team comment."""
        # Find most relevant player using text search
        players = self.database.players.find(
            {"$text": {"$search": player_name}},
            {"score": {"$meta": "textScore"}}
        ).sort([("score", {"$meta": "textScore"})])
        player = list(players.limit(1))[0]

        if not number_of_fixtures:
            number_of_fixtures = len(player["understat_history"])

        fixture_count = 0
        relevant_fixtures = []
        for fixture in player["understat_history"]:
            if fixture_count >= int(number_of_fixtures):
                break

            if (team_name != fixture["h_team"].lower() and
                    team_name != fixture["a_team"].lower()):
                continue

            fixture_count += 1
            relevant_fixtures.append(fixture)

        table = self.player_vs_team_table(relevant_fixtures)
        print(table)

    def comment_handler(self, comment):
        """Generic comment handler."""
        match = re.search(versus_pattern, comment)

        if not match:
            return

        player_name = match.group(1).lower().strip()
        opponent_name = match.group(2).lower().replace(".", "").strip()
        number = match.group(3)

        if to_fpl_team(opponent_name) in fpl_team_names:
            self.versus_team_handler(player_name, opponent_name, number)


async def main(config):
    async with aiohttp.ClientSession() as session:
        fpl_bot = FPLBot(config, session)

        fpl_bot.comment_handler("!fplbot mohamed salah vs. bournemouth")


if __name__ == "__main__":
    config = json.loads(open(f"{dirname}/../config.json").read())
    try:
        asyncio.run(main(config))
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main(config))
        loop.close()
