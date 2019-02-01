import asyncio

import aiohttp
from fpl import FPL
from fpl.utils import team_converter, position_converter
from pymongo import MongoClient, ReplaceOne

client = MongoClient()
database = client.fpl
logger = logging.getLogger("FPLbot - utils")
logger.setLevel(logging.DEBUG)
logger.basicConfig()

async def update_players():
    """Updates all players in the database."""
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        players = await fpl.get_players(include_summary=True, return_json=True)

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


if __name__ == "__main__":
    asyncio.run(update_players())
