import asyncio

import aiohttp
from fpl import FPL
from pymongo import MongoClient, ReplaceOne

client = MongoClient()
database = client.fpl


async def update_players():
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        players = await fpl.get_players(include_summary=True, return_json=True)

    requests = [ReplaceOne({"id": player["id"]}, player, upsert=True)
                for player in players]
    database.players.bulk_write(requests)

if __name__ == "__main__":
    asyncio.run(update_players())
