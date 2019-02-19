import asyncio

from pymongo import MongoClient

from utils import update_players

client = MongoClient()
database = client.fpl


async def main():
    await update_players()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
        loop.close()
