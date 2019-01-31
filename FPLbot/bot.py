import asyncio

import aiohttp
from fpl import FPL
from pymongo import MongoClient


class FPLBot:
    def __init__(self, config, session):
        self.client = MongoClient()
        self.config = config
        self.fpl = FPL(session)

    async def get_price_changers(self):
        """Returns a list of players whose price has changed since the last
        time the database was updated.
        """
        new_players = await self.fpl.get_players(include_summary=True)
        old_players = self.client.fpl.players.find()

        risers = []
        fallers = []

        for new_player in new_players:
            old_player = next(player for player in old_players
                              if player["id"] == new_player.id)

            if old_player["cost_change_event"] > new_player.cost_change_event:
                if old_player["now_cost"] > new_player.now_cost:
                    fallers.append(new_player)
                else:
                    risers.append(new_player)

        return risers, fallers
