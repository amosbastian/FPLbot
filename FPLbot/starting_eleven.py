import asyncio
import json
import os
from datetime import datetime, timedelta

import aiohttp
import tweepy
from dateutil.parser import parse
from fpl import FPL, utils
from pymongo import MongoClient
from constants import lineup_markers, twitter_usernames

dirname = os.path.dirname(os.path.realpath(__file__))
client = MongoClient()
database = client.team_news


def short_name_converter(team_id):
    """Converts a team's ID to their short name."""
    short_name_map = {
        1: "ARS",
        2: "AVL",
        3: "BHA",
        4: "BUR",
        5: "CHE",
        6: "CRY",
        7: "EVE",
        8: "FUL",
        9: "LEI",
        10: "LEE",
        11: "LIV",
        12: "MCI",
        13: "MUN",
        14: "NEW",
        15: "SHU",
        16: "SOU",
        17: "TOT",
        18: "WBA",
        19: "WHU",
        20: "WOL",
        None: None
    }
    return short_name_map[team_id]


async def get_current_fixtures():
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        current_gameweek = await utils.get_current_gameweek(session)
        fixtures = await fpl.get_fixtures_by_gameweek(current_gameweek)

    min_range = timedelta(minutes=2)
    return [fixture for fixture in fixtures
            if fixture.team_news_time.replace(tzinfo=None) - min_range <
            datetime.now() <
            fixture.team_news_time.replace(tzinfo=None) + min_range]


def is_new_lineup(fixture_id, team_id):
    if database.lineup.count_documents({"fixture_id": fixture_id,
                                        "team_id": team_id}) < 1:
        return True
    return False


def add_lineup_to_database(fixture_id, team_id, url):
    self.database.lineup.update_one(
        {"fixture_id": fixture_id},
        {"$set": {"fixture_id": fixture_id,
                  "team_id": team_id,
                  "url": url}},
        upsert=True
    )


def lineup_handler(team_id, team_short_name, opponent_id):
    team_name = twitter_usernames[team_short_name]
    for status in api.user_timeline(screen_name=team_name,
                                    tweet_mode="extended",
                                    count=3):

        status_split = status.full_text.lower().replace("-", " ").split()

        for marker in lineup_markers:
            if marker in list(zip(split_status, split_status[1:])):
                if "media" not in status.entities:
                    continue
                media = status.entities["media"][0]
                media_url = media["media_url_https"]
                if is_new_lineup(fixture.id, team_id):
                    add_lineup_to_database(fixture.id, team_id, media_url)
                return


async def main(config):
    auth = tweepy.OAuthHandler(config["CONSUMER_API_KEY"],
                               config["CONSUMER_API_SECRET_KEY"])
    auth.set_access_token(config["ACCESS_TOKEN"],
                          config["ACCESS_TOKEN_SECRET"])
    api = tweepy.API(auth)

    current_fixtures = await get_current_fixtures()
    images_urls = []

    for fixture in current_fixtures:
        team_h_short = short_name_converter(fixture.team_h)
        team_a_short = short_name_converter(fixture.team_a)

        lineup_handler(fixture.team_h, team_h_short, fixture.team_a)
        lineup_handler(fixture.team_a, team_a_short, fixture.team_h)


if __name__ == "__main__":
    with open(f"{dirname}/../twitter_config.json") as file:
        config = json.loads(file.read())
        try:
            asyncio.run(main(config))
        except AttributeError:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main(config))
            loop.close()
