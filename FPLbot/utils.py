import asyncio
import codecs
import json
import logging
import os
import re

import aiohttp
from bs4 import BeautifulSoup
from fpl import FPL
from fpl.utils import position_converter, team_converter
from pymongo import MongoClient, ReplaceOne

from constants import player_dict, team_dict, desired_attributes

client = MongoClient()
database = client.fpl
logger = logging.getLogger("FPLbot")


def create_logger():
    """Creates a logger object for use in logging across all files.

    See: https://docs.python.org/3/howto/logging-cookbook.html
    """
    dirname = os.path.dirname(os.path.realpath(__file__))

    logger = logging.getLogger("FPLbot")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(f"{dirname}/FPLbot.log")
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


async def fetch(session, url):
    async with session.get(url) as response:
        return await response.text()


async def understat_players_data(session):
    """Returns a dict containing general player data retrieved from
    https://understat.com/.
    """
    logger.info("Getting Understat players data.")
    html = await fetch(session, "https://understat.com/league/EPL/")

    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    pattern = re.compile(r"var\s+playersData\s+=\s+JSON.parse\(\'(.*?)\'\);")

    for script in scripts:
        match = re.search(pattern, script.string)
        if match:
            break

    byte_data = codecs.escape_decode(match.group(1))
    player_data = json.loads(byte_data[0].decode("utf-8"))

    # Convert Understat player name to FPL player name
    for player in player_data:
        player["team_title"] = understat_team_converter(player["team_title"])
        player["player_name"] = understat_player_converter(player["player_name"])

    return player_data


async def understat_matches_data(session, player):
    """Sets the 'matches' attribute of the given player to the data found on
    https://understat.com/player/<player_id>.
    """
    logger.info(f"Getting {player['player_name']} Understat matches data.")
    html = await fetch(session, f"https://understat.com/player/{player['id']}")

    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    pattern = re.compile(r"var\s+matchesData\s+=\s+JSON.parse\(\'(.*?)\'\);")

    for script in scripts:
        match = re.search(pattern, script.string)
        if match:
            break

    # If no match could be found, simply return an empty dict
    try:
        byte_data = codecs.escape_decode(match.group(1))
        matches_data = json.loads(byte_data[0].decode("utf-8"))

        player["understat_history"] = matches_data
    except UnboundLocalError:
        player["understat_history"] = {}


async def get_understat_players():
    """Returns a list of dicts containing all information available on
    https://understat.com/ for Premier League players.
    """
    logger.info("Retrieving player information from https://understat.com/.")

    async with aiohttp.ClientSession() as session:
        players_data = await understat_players_data(session)
        tasks = [asyncio.ensure_future(understat_matches_data(session, player))
                 for player in players_data]
        await asyncio.gather(*tasks)

    return players_data


async def update_players():
    """Updates all players in the database."""
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        players = await fpl.get_players(include_summary=True, return_json=True)

    understat_players = await get_understat_players()

    for player in players:
        fpl_name = f"{player['first_name']} {player['second_name']}"
        try:
            understat_player = next(
                understat_player for understat_player in understat_players
                if fpl_name == understat_player["player_name"])
        except StopIteration:
            # FPL player not available on Understat
            continue

        # Only update FPL player with desired attributes
        understat_attributes = {
            attribute: value for attribute, value in understat_player.items()
            if attribute in desired_attributes
        }
        player.update(understat_attributes)

    requests = [ReplaceOne({"id": player["id"]}, player, upsert=True)
                for player in players]

    logger.info("Updating players in database.")
    database.players.bulk_write(requests)


def get_player_table(players, risers=True):
    """Returns the table used in the player price change posts on Reddit."""
    table_header = ("|Name|Team|Position|Ownership|Price|∆|Form|\n"
                    "|:-|:-|:-|:-:|:-:|:-:|:-:|\n")

    table_body = "\n".join([
            f"|{player.web_name}|"
            f"{team_converter(player.team)}|"
            f"{position_converter(player.element_type)}|"
            f"{player.selected_by_percent}%|"
            f"£{player.now_cost / 10.0:.1f}|"
            f"{'+' if risers else '-'}£{abs(player.cost_change_event / 10.0):.1f}|"
            f"{sum([fixture['total_points'] for fixture in player.history[-5:]])}|"
            for player in players])

    return table_header + table_body


def understat_player_converter(player_name):
    try:
        return player_dict[player_name]
    except KeyError:
        return player_name


def understat_team_converter(team_name):
    try:
        return team_dict[team_name]
    except KeyError:
        return team_name


if __name__ == "__main__":
    try:
        asyncio.run(update_players())
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(update_players())
        loop.close()
