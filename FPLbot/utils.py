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

from constants import (desired_attributes, player_dict, team_dict,
                       to_fpl_team_dict)

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

    # If no match could be found, retry (probably rate limited?)
    try:
        byte_data = codecs.escape_decode(match.group(1))
        matches_data = json.loads(byte_data[0].decode("utf-8"))

        for fixture in matches_data:
            fixture["h_team"] = understat_team_converter(fixture["h_team"])
            fixture["a_team"] = understat_team_converter(fixture["a_team"])

        player["understat_history"] = matches_data
    except UnboundLocalError:
        await understat_matches_data(session, player)

    return player


async def get_understat_players():
    """Returns a list of dicts containing all information available on
    https://understat.com/ for Premier League players.
    """
    logger.info("Retrieving player information from https://understat.com/.")

    async with aiohttp.ClientSession() as session:
        players_data = await understat_players_data(session)
        tasks = [asyncio.ensure_future(understat_matches_data(session, player))
                 for player in players_data]
        players = await asyncio.gather(*tasks)

    return players


async def update_players():
    """Updates all players in the database."""
    logger.info("Updating FPL players in database.")
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        players = await fpl.get_players(include_summary=True, return_json=True)
        for player in players:
            player["team"] = team_converter(player["team"])

    requests = [ReplaceOne({"id": player["id"]}, player, upsert=True)
                for player in players]
    database.players.bulk_write(requests)

    logger.info("Adding Understat data to players in database.")
    understat_players = await get_understat_players()

    for player in understat_players:
        # Only update FPL player with desired attributes
        understat_attributes = {
            attribute: value for attribute, value in player.items()
            if attribute in desired_attributes
        }

        # Use player's full name and team to try and find the correct player
        search_string = f"{player['player_name']} {player['team_title']}"
        players = database.players.find(
            {"$text": {"$search": search_string}},
            {"score": {"$meta": "textScore"}}
        ).sort([("score", {"$meta": "textScore"})])
        relevant_player = list(players)[0]

        database.players.update_one(
            {"id": relevant_player["id"]},
            {"$set": understat_attributes}
        )


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


def player_vs_team_table(fixtures):
    """Returns a Markdown table showing the player's performance in the
    given fixtures.
    """
    table = ("|Fixture|Date|MP|G|xG|A|xA|NPG|NPxG|KP|\n"
             "|:-|:-:|-:|-:|-:|-:|-:|-:|-:|-:|\n")

    for fixture in fixtures:
        home_team = f"{fixture['h_team']}"
        away_team = f"{fixture['a_goals']}"

        # Highlight the winning team
        if int(fixture["h_goals"]) > int(fixture["a_goals"]):
            home_team = f"**{home_team}** {fixture['h_goals']}"
        elif int(fixture["h_goals"]) < int(fixture["a_goals"]):
            away_team = f"**{away_team}** {fixture['a_team']}"

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


def find_player(player_name):
    # Find most relevant player using text search
    players = database.players.find(
        {"$text": {"$search": player_name}},
        {"score": {"$meta": "textScore"}}
    ).sort([("score", {"$meta": "textScore"})])

    try:
        player = list(players.limit(1))[0]
    except IndexError:
        logger.error(f"Player {player_name} could not be found!")
        return None
    return player


def to_fpl_team(team_name):
    try:
        return to_fpl_team_dict[team_name]
    except KeyError:
        return team_name


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
