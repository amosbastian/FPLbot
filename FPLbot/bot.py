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

from constants import fpl_team_names, versus_pattern
from utils import (create_logger, find_player, get_player_table,
                   player_vs_player_table, player_vs_team_table, to_fpl_team,
                   update_players, get_relevant_fixtures)

dirname = os.path.dirname(os.path.realpath(__file__))
logger = create_logger()
client = MongoClient()


class FPLBot:
    def __init__(self, config, session):
        self.config = config
        self.database = client.fpl
        self.fpl = FPL(session)
        self.reddit = praw.Reddit(
            client_id=config.get("CLIENT_ID"),
            client_secret=config.get("CLIENT_SECRET"),
            password=config.get("PASSWORD"),
            user_agent=config.get("USER_AGENT"),
            username=config.get("USERNAME"))
        self.subreddit = self.reddit.subreddit(self.config.get("SUBREDDIT"))

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

    def versus_player_handler(self, player_A_name, player_B_name,
                              number_of_fixtures):
        """Function for handling player vs. player comment."""
        player_A = find_player(player_A_name)
        player_B = find_player(player_B_name)

        if not player_A or not player_B:
            return

        player_A_fixtures = get_relevant_fixtures(player_A)
        player_B_fixtures = get_relevant_fixtures(player_B)

        if not number_of_fixtures:
            number_of_fixtures = max(len(player_A_fixtures),
                                     len(player_B_fixtures))

        fixtures = zip(player_A_fixtures[:number_of_fixtures],
                       player_B_fixtures[:number_of_fixtures])

        post_template = open(f"{dirname}/../comment_template.md").read()
        table_header = (
            f"# {player_A['web_name']} (£{player_A['now_cost'] / 10.0:.1f}) "
            f"vs. {player_B['web_name']} (£{player_B['now_cost'] / 10.0:.1f}) "
            f"(last {number_of_fixtures} fixtures)")
        table_body = player_vs_player_table(fixtures)

        return post_template.format(
            comment_header=table_header,
            comment_body=table_body
        )

    def versus_team_handler(self, player_name, team_name, number_of_fixtures):
        """Function for handling player vs. team comment."""
        player = find_player(player_name)
        if not player:
            return

        if not number_of_fixtures:
            number_of_fixtures = len(player["understat_history"])

        fixtures = get_relevant_fixtures(
            player, team_name=to_fpl_team(team_name))[:number_of_fixtures]
        post_template = open(f"{dirname}/../comment_template.md").read()
        table_header = (
            f"# {player_name.title()} vs. {team_name.title()} (last "
            f"{len(fixtures)} fixtures)")
        table_body = player_vs_team_table(fixtures)

        return post_template.format(
            comment_header=table_header,
            comment_body=table_body
        )

    def add_comment_to_database(self, comment):
        logger.info(f"Adding comment with ID {comment.id} to the database.")
        self.database.comments.update_one(
            {"comment_id": comment.id},
            {"$set": {"comment_id": comment.id}},
            upsert=True
        )

    def comment_handler(self, comment):
        """Generic comment handler."""
        logger.info(f"Handling COMMENT with ID {comment.id}.")
        match = re.search(versus_pattern, comment.body.lower())

        if not match:
            logger.info(f"Comment with ID {comment.id} does not match pattern.")
            return

        player_name = match.group(1).lower().strip()
        opponent_name = match.group(2).lower().replace(".", "").strip()
        number = match.group(3)

        if number:
            number = int(number)

        if to_fpl_team(opponent_name) in fpl_team_names:
            reply_text = self.versus_team_handler(
                player_name, opponent_name, number)
        else:
            reply_text = self.versus_player_handler(
                player_name, opponent_name, number)

        if reply_text:
            logger.info(f"Replying ({player_name} vs. {opponent_name}) to "
                        f"comment with ID {comment.id}.")
            comment.reply(reply_text)
            self.add_comment_to_database(comment)

    def is_new_comment(self, comment_id):
        if self.database.comments.count_documents({"comment_id": comment_id}) < 1:
            return True
        return False

    def run(self):
        for comment in self.subreddit.stream.comments():
            body = comment.body.lower()
            if self.config.get("BOT_PREFIX") in body:
                if not self.is_new_comment(comment.id):
                    continue

                try:
                    self.comment_handler(comment)
                except Exception as error:
                    logger.error(f"Something went wrong: {error}")


async def main(config):
    async with aiohttp.ClientSession() as session:
        fpl_bot = FPLBot(config, session)

        fpl_bot.run()


if __name__ == "__main__":
    config = json.loads(open(f"{dirname}/../config.json").read())
    try:
        asyncio.run(main(config))
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main(config))
        loop.close()
