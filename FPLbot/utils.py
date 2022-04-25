import asyncio
import codecs
import json
import logging
import os
import re

from fpl import FPL
from fpl.utils import position_converter, team_converter
from pymongo import MongoClient, ReplaceOne

import aiohttp
from bs4 import BeautifulSoup
from constants import (desired_attributes, fpl_team_names, player_dict,
                       team_dict, to_fpl_team_dict)
from tabulate import tabulate
from understat import Understat

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
    understat = Understat(session)
    player_data = await understat.get_league_players("EPL", "2021")

    # Convert Understat player name to FPL player name
    for player in player_data:
        print(player["player_name"])
        player["team_title"] = understat_team_converter(player["team_title"])
        player["player_name"] = understat_player_converter(player["player_name"])

    return player_data


async def understat_matches_data(session, player):
    """Sets the 'matches' attribute of the given player to the data found on
    https://understat.com/player/<player_id>.
    """

    try:
        understat = Understat(session)
        matches_data = await understat.get_player_matches(player["id"])
        await asyncio.sleep(0.1)
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
    async with aiohttp.ClientSession() as session:
        print("Getting players data...")
        players_data = await understat_players_data(session)
        print("Getting matches data...")
        tasks = [asyncio.ensure_future(understat_matches_data(session, player))
                 for player in players_data]
        players = await asyncio.gather(*tasks)

    return players


def create_text_indexes():
    database.players.create_index([
        ("web_name", "text"),
        ("first_name", "text"),
        ("second_name", "text")
    ])


async def update_players():
    """Updates all players in the database."""
    logger.info(f"Updating players")
    print("Getting FPL players...")
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        players = await fpl.get_players(include_summary=True, return_json=True)
        for player in players:
            player["team"] = team_converter(player["team"])

    requests = [ReplaceOne({"id": player["id"]}, player, upsert=True)
                for player in players]
    database.players.bulk_write(requests)
    create_text_indexes()

    print("Getting Understat players...")
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
        try:
            relevant_player = list(players)[0]
        except IndexError:
            continue

        database.players.update_one(
            {"id": relevant_player["id"]},
            {"$set": understat_attributes}
        )


async def update_results():
    async with aiohttp.ClientSession() as session:
        understat = Understat(session)
        results = await understat.get_league_results("EPL", "2021")
        for result in results:
            result["h"]["title"] = understat_team_converter(result["h"]["title"])
            result["a"]["title"] = understat_team_converter(result["a"]["title"])

    requests = [ReplaceOne({"id": result["id"]}, result, upsert=True)
                for result in results]
    database.results.bulk_write(requests)


def get_xGA(fixture_id, player_team):
    database_fixture = database.results.find_one({"id": fixture_id})
    if database_fixture["h"]["title"] == player_team:
        xGA = float(database_fixture["xG"]["a"])
    else:
        xGA = float(database_fixture["xG"]["h"])
    return xGA


def create_goalkeeper_table(player, history_list, fixtures):
    """Returns a Markdown table for a goalkeeper."""

    table_body = []
    total_result = []

    table_header = ["Fixture", "MP", "GA", "xGA", "Saves", "Points"]
    alignment = ("left", "right", "right", "right", "right", "right")

    total_points = 0
    total_bonus = 0

    for history, fixture in zip(history_list, fixtures[::-1]):
        result = (f"{fixture['h_team']} {fixture['h_goals']}-"
                  f"{fixture['a_goals']} {fixture['a_team']}")
        points = f"{history['total_points']} ({history['bonus']})"
        xGA = get_xGA(fixture["id"], player["team"])

        table_row = [
            result, int(fixture["time"]),  history["goals_conceded"],
            f"{xGA:.2f}", history['saves'], points
        ]

        table_body.append(table_row)
        total_result.append(table_row[1:-1])
        total_points += history["total_points"]
        total_bonus += history["bonus"]

    # List comprehension to sum the values of each of the table's columns
    table_footer = [sum([float(j) if isinstance(j, str) else j for j in i])
                    for i in zip(*total_result)]

    # Bold the values in the table's footer
    for i, value in enumerate(table_footer):
        if isinstance(value, float):
            value = f"{value:.2f}"

        table_footer[i] = f"**{value}**"

    table_body.append([""] + table_footer + [f"**{total_points} ({total_bonus})**"])
    table = tabulate(table_body, headers=table_header, tablefmt="pipe",
                     colalign=alignment)

    return f"# {player['web_name']}\n\n{table}"


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


def get_total(total, fixture):
    for key, value in fixture.items():
        total.setdefault(key, 0)
        try:
            total[key] += float(value)
        except ValueError:
            continue
    return total


def create_player_table(player, history_list, fixtures):
    """Returns a Markdown table for players who aren't goalkeepers."""

    table_body = []
    total_result = []

    table_header = ["Fixture", "MP", "G", "xG", "A", "xA", "Points"]
    alignment = ("left", "right", "right", "right", "right", "right", "right")

    # If the player is a defender, also include GA and xGA
    if player["element_type"] == 2:
        table_header.insert(-1, "GA")
        table_header.insert(-1, "xGA")
        alignment = (*alignment, "right", "right")

    total_points = 0
    total_bonus = 0

    for history, fixture in zip(history_list, fixtures[::-1]):
        result = (f"{fixture['h_team']} {fixture['h_goals']}-"
                  f"{fixture['a_goals']} {fixture['a_team']}")
        points = f"{history['total_points']} ({history['bonus']})"

        table_row = [
            result, int(fixture["time"]), history["goals_scored"],
            f"{float(fixture['xG']):.2f}", history["assists"],
            f"{float(fixture['xA']):.2f}", points
        ]

        # Player is a defender, so add additional data
        if player["element_type"] == 2:
            xGA = get_xGA(fixture["id"], player["team"])
            table_row.insert(-1, history["goals_conceded"])
            table_row.insert(-1, float(f"{xGA:.2f}"))

        table_body.append(table_row)
        total_result.append(table_row[1:-1])
        total_points += history["total_points"]
        total_bonus += history["bonus"]

    # List comprehension to sum the values of each of the table's columns
    table_footer = [sum([float(j) if isinstance(j, str) else j for j in i])
                    for i in zip(*total_result)]

    # Bold the values in the table's footer
    for i, value in enumerate(table_footer):
        if isinstance(value, float):
            value = f"{value:.2f}"

        table_footer[i] = f"**{value}**"

    table_body.append([""] + table_footer + [f"**{total_points} ({total_bonus})**"])
    table = tabulate(table_body, headers=table_header, tablefmt="pipe",
                     colalign=alignment)

    return f"# {player['web_name']}\n\n{table}"


def player_vs_player_table(players, number_of_fixtures):
    """Creates tables from the given players."""
    tables = []

    for player in players:
        fixtures = get_relevant_fixtures(player)[:number_of_fixtures]
        history = get_relevant_history(player["history"])[-number_of_fixtures:]

        # Player is a goalkeeper
        if player["element_type"] == 1:
            table = create_goalkeeper_table(player, history, fixtures)
        else:
            table = create_player_table(player, history, fixtures)

        tables.append(table)

    return tables[0] + "\n\n" + tables[1]


def player_vs_team_table(fixtures):
    """Returns a Markdown table showing the player's performance in the
    given fixtures.
    """
    table = ("|Fixture|Date|MP|G|xG|A|xA|NPG|NPxG|KP|\n"
             "|:-|:-|-:|-:|-:|-:|-:|-:|-:|-:|\n")

    total = {}

    for fixture in fixtures:
        home_team = f"{fixture['h_team']} {fixture['h_goals']}"
        away_team = f"{fixture['a_goals']} {fixture['a_team']}"
        minutes_played = fixture["time"]

        # Highlight the winning team
        if int(fixture["h_goals"]) > int(fixture["a_goals"]):
            home_team = f"**{fixture['h_team']}** {fixture['h_goals']}"
        elif int(fixture["h_goals"]) < int(fixture["a_goals"]):
            away_team = f"**{fixture['a_goals']}** {fixture['a_team']}"

        # Highlight whether the player was a starter or not
        if fixture["position"].lower() != "sub":
            minutes_played = f"**{minutes_played}**"

        table += (
            f"|{home_team}-{away_team}"
            f"|{fixture['date']}"
            f"|{minutes_played}"
            f"|{fixture['goals']}"
            f"|{float(fixture['xG']):.2f}"
            f"|{fixture['assists']}"
            f"|{float(fixture['xA']):.2f}"
            f"|{fixture['npg']}"
            f"|{float(fixture['npxG']):.2f}"
            f"|{fixture['key_passes']}|\n"
        )

        for key, value in fixture.items():
            total.setdefault(key, 0)
            try:
                total[key] += float(value)
            except ValueError:
                continue

    # Add footer with totals
    table_footer = (
        f"|||**{int(total['time'])}**"
        f"|**{int(total['goals'])}**"
        f"|**{total['xG']:.2f}**"
        f"|**{int(total['assists'])}**"
        f"|**{total['xA']:.2f}**"
        f"|**{total['npg']}**"
        f"|**{total['npxG']:.2f}**"
        f"|**{int(total['key_passes'])}**|\n"
    )

    return table + table_footer


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


def get_relevant_history(history):
    return [fixture for fixture in history if fixture["minutes"] > 0]


def get_relevant_fixtures(player, team_name=None):
    """Return all fixtures that the player has played for his current team
    (optionally) against the given team.
    """
    fixtures = [
        fixture for fixture in player["understat_history"]
        if (to_fpl_team(fixture["h_team"].lower()) in fpl_team_names or
            to_fpl_team(fixture["a_team"].lower()) in fpl_team_names) and
        int(fixture["time"]) > 0
    ]

    if team_name:
        team_name = to_fpl_team(team_name.lower()).lower()
        fixtures = [
            fixture for fixture in fixtures
            if team_name == to_fpl_team(fixture["h_team"].lower()) or
            team_name == to_fpl_team(fixture["a_team"].lower())
        ]

        # Player could've played for the given team before, so only include
        # fixtures played vs. them for his current team.
        if len(fixtures) > 10:
            fixtures = [
                fixture for fixture in fixtures
                if player["team"].lower() in [
                        to_fpl_team(fixture["h_team"].lower()),
                        to_fpl_team(fixture["a_team"].lower())
                    ]
                ]
    else:
        # If comparing player vs. player, then only include this season.
        fixture_ids = [result["id"] for result in database.results.find()]
        fixtures = [f for f in fixtures if f["id"] in fixture_ids]

    return fixtures


if __name__ == "__main__":
    try:
        asyncio.run(update_players())
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(update_players())
        loop.close()
