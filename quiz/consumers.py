import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async



class LobbyConsumer(AsyncWebsocketConsumer):
    


    async def connect(self):
        await self.accept()


    async def disconnect(self, code):
        pass


    async def receive(self, message):
        pass
