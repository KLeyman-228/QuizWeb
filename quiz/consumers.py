import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async



class QuizConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.group_name = f"lobby_{self.room_code}"
        await self.accept()
        print(f"[connect] подключился к лобби {self.room_code}")


    async def disconnect(self, code):
        pass


    async def receive(self, message):
        data = json.loads(message)
        await self.send(text_data=json.dumps({"echo": data}))
