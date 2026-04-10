import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Lobby, Question, Player



class QuizConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.group_name = f"lobby_{self.room_code}"
        self.lobby = await self.db_get_or_create_lobby(self.room_code)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()


    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            if self.room.status == "waiting":
                await self.db_delete_player_by_channel(self.channel_name)
                await self.broadcast_lobby()
            await self.channel_layer.group_discard(self.group_name, self.channel_name)


    async def broadcast_lobby(self):
        players = await self.db_get_players_serialized(self.lobby)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "lobby.update", "players": players},
        )


    async def receive(self, message):
        data = json.loads(message)
        data_type = data.get("type")

        if data_type == "join_player":
            await self.handle_join_player(data)
        elif data_type == "join_host":
            await self.handle_join_host(data)
        else:
            await self.send(text_data=json.dumps({"type": "error", "message": "none type"}))
    



    async def handle_join_player(self, data):
        token = data.get("token")
        exist = await self.db_get_player_by_token(token) if token else None

        if exist and exist["lobby_id"] == self.lobby.id:
            self.player_id = exist["id"]
            self.player_name = exist["name"]
            self.avatar = exist["avatar"]
            self.is_host = exist["is_host"]
            await self.db_update_player_channel(self.player_id, self.channel_name)
        else:
            self.player_name = data.get("name", "Случайная лягушка")[:30]
            self.avatar = data.get("avatar", "👀")[:10]
            self.is_host = False
            await self.db_create_player(
                self.lobby, self.player_name, self.avatar, 
                is_host=False, channel_name=self.channel_name
            )
        
        new_token = await self.db_get_player_by_token(self.player_id)
        await self.send(text_data=json.dumps({"type": "your_token", "token": new_token}))
        await self.broadcast_lobby()



    async def handle_join_host(self, data):
        if await self.db_has_host(self.room):
            await self.send(text_data=json.dumps({"type": "error", "message": "host exists"}))
            await self.close()
            return
        self.player_name = "HOST"
        self.avatar = "🦊"
        self.is_host = True
        await self.db_create_player(
            self.room, self.player_name, self.avatar,
            is_host=True, channel_name=self.channel_name,
        )
        await self.broadcast_lobby()





    @database_sync_to_async
    def db_get_or_create_lobby(code):
        lobby, _ = Lobby.objects.get_or_create(code=code)
        return lobby
    
    @database_sync_to_async
    def db_has_host(lobby):
        return lobby.players.filter(is_host=True).exists()
    
    @database_sync_to_async
    def db_create_player(room, name, avatar, is_host, channel_name):
        return Player.objects.create(
            room=room, name=name, avatar=avatar,
            is_host=is_host, channel_name=channel_name,
        )

    @database_sync_to_async
    def db_delete_player_by_channel(channel_name):
        Player.objects.filter(channel_name=channel_name).delete()


    @database_sync_to_async
    def db_get_players_serialized(lobby):
        return [
            {"id": p.id, "name": p.name, "avatar": p.avatar, "exp": p.exp, "is_host": p.is_host}
            for p in lobby.players.all().order_by("-exp", "id")
        ]
    

    @database_sync_to_async
    def db_get_player_by_token(token):
        p = Player.objects.filter(token=token).first()
        if not p:
            return None
        return {"id": p.id, "name": p.name, "avatar": p.avatar, "exp": p.exp, 
                "is_host": p.is_host, "lobby_id": p.lobby_id}

    @database_sync_to_async
    def db_update_player_channel(player_id, channel_name):
        Player.objects.filter(id=player_id).update(channel_name=channel_name)

    @database_sync_to_async
    def db_get_player_token(player_id):
        return Player.objects.get(id=player_id).token

    
