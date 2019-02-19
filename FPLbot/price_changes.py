import asyncio
import json
import os

import aiohttp

from bot import FPLBot

dirname = os.path.dirname(os.path.realpath(__file__))

async def main(config):
    async with aiohttp.ClientSession() as session:
        fpl_bot = FPLBot(config, session)

        await fpl_bot.post_price_changes()


if __name__ == "__main__":
    config = json.loads(open(f"{dirname}/../config.json").read())
    try:
        asyncio.run(main(config))
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main(config))
        loop.close()
