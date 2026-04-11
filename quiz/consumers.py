import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Lobby, Question, Player
import asyncio

import time


QUESTIONS_db = {}
ROOM_TIMERS = {}




class QuizConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.lobby_code = self.scope["url_route"]["kwargs"]["lobby_code"]
        self.group_name = f"lobby_{self.lobby_code}"
        self.lobby = await db_get_or_create_lobby(self.lobby_code)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()


    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            if self.lobby.status == "wait":
                await db_delete_player_by_channel(self.channel_name)
                await self.broadcast_lobby()
            await self.channel_layer.group_discard(self.group_name, self.channel_name)


    async def broadcast_lobby(self):
        players = await db_get_players_serialized(self.lobby)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "lobby.update", "players": players},
        )

    async def lobby_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "lobby_update",
            "players": event["players"],
        }))


    async def receive(self, message):
        data = json.loads(message)
        data_type = data.get("type")

        if data_type == "join_player":
            await self.handle_join_player(data)
        elif data_type == "join_host":
            await self.handle_join_host(data)
        elif data_type == "answer":
            await self.handle_answer(data)
        elif data_type in ("start_game", "next_question", "finish_game"):
            if not getattr(self, "is_host", False):
                return
            if data_type == "start_game":
                await self.handle_start_game()
            elif data_type == "next_question":
                await self.handle_next_question()
            elif data_type == "finish_game":
                await self.handle_finish_game()
        
        else:
            await self.send(text_data=json.dumps({"type": "error", "message": "none type"}))
    






    async def handle_join_player(self, data):
        token = data.get("token")
        exist = await db_get_player_by_token(token) if token else None

        if exist and exist["lobby_id"] == self.lobby.id:
            self.player_id = exist["id"]
            self.player_name = exist["name"]
            self.avatar = exist["avatar"]
            self.is_host = exist["is_host"]
            await db_update_player_channel(self.player_id, self.channel_name)
        else:
            self.player_name = data.get("name", "Случайная лягушка")[:30]
            self.avatar = data.get("avatar", "👀")[:10]
            self.is_host = False
            player = await db_create_player(
                self.lobby, self.player_name, self.avatar,
                is_host=False, channel_name=self.channel_name
            )
            self.player_id = player.id

        new_token = await db_get_player_token(self.player_id)
        await self.send(text_data=json.dumps({"type": "your_token", "token": new_token}))
        await self.broadcast_lobby()


    async def handle_join_host(self, data):
        if await db_has_host(self.lobby):
            await self.send(text_data=json.dumps({"type": "error", "message": "host exists"}))
            await self.close()
            return
        self.player_name = "HOST"
        self.avatar = "🦊"
        self.is_host = True
        await db_create_player(
            self.lobby, self.player_name, self.avatar,
            is_host=True, channel_name=self.channel_name,
        )
        await self.broadcast_lobby()


    async def handle_start_game(self):
        question_ids = await db_load_random_question_ids(5)
        QUESTIONS_db[self.lobby_code] = question_ids
        self.lobby.current_question_index = -1
        await db_set_lobby_status(self.lobby, "play")
        await self.handle_next_question()



    async def handle_next_question(self):
        ids = QUESTIONS_db.get(self.lobby_code, [])
        next_index = self.lobby.current_question_index + 1
        if next_index >= len(ids):
            await self.handle_finish_game()
            return
        await db_set_question_index(self.lobby, next_index)
        self.lobby.current_question_index = next_index
        await db_reset_answers(self.lobby)
        question = await db_get_question(ids[next_index])
        self.current_question = question
        await self.broadcast_question(question)
        await self.broadcast_answer_stats()
        # Timer
        self.current_question = question
        self.question_start_time = time.monotonic()
        self.start_question_timer(15)

    async def handle_answer(self, data):
        if getattr(self, "is_host", False):
            return
        option_index = data.get("option_index")
        if option_index not in (0, 1, 2, 3):
            return
        player_id = await db_get_player_id_by_channel(self.channel_name)
        if player_id is None:
            return
        await db_save_answer(player_id, option_index)
        correct = getattr(self, "current_question", {}).get("correct_index")
        if option_index == correct:
            elapsed = time.monotonic() - getattr(self, "question_start_time", 0)
            speed_bonus = max(0, 100 - int(elapsed * 6))  # 6 очков за секунду
            await db_add_exp(player_id, 50 + speed_bonus)
        await self.broadcast_answer_stats()



    async def handle_finish_game(self):
        t = ROOM_TIMERS.get(self.lobby_code)
        if t and not t.done():
            t.cancel()

        await db_set_lobby_status(self.lobby, "finish")
        leaderboard = await db_get_players_serialized(self.lobby)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "game.finished", "leaderboard": leaderboard},
        )

    async def game_finished(self, event):
        await self.send(text_data=json.dumps({
            "type": "game_finished",
            "leaderboard": [p for p in event["leaderboard"] if not p["is_host"]],
        }))



    async def broadcast_reveal_answer(self):
        correct = getattr(self, "current_question", {}).get("correct_index")
        if correct is None:
            return
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "reveal.answer", "correct_index": correct},
        )

    async def reveal_answer(self, event):
        await self.send(text_data=json.dumps({
            "type": "reveal_answer",
            "correct_index": event["correct_index"],
        }))

    async def broadcast_question(self, question):
        # Игроки НЕ должны видеть правильный ответ!
        safe = {"id": question["id"], "text": question["text"], "options": question["options"]}
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "question.show", "question": safe, "index": self.lobby.current_question_index},
        )

    async def question_show(self, event):
        await self.send(text_data=json.dumps({
            "type": "question_show",
            "question": event["question"],
            "index": event["index"],
        }))

    async def broadcast_answer_stats(self):
        stats = await db_get_answer_stats(self.lobby)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "answer.stats", "stats": stats},
        )

    async def answer_stats(self, event):
        if getattr(self, "is_host", False):
            await self.send(text_data=json.dumps({
                "type": "answer_stats",
                "stats": event["stats"],
            }))
    
    async def _question_timer_coro(self, seconds):
        try:
            for remaining in range(seconds, -1, -1):
                await self.channel_layer.group_send(
                    self.group_name,
                    {"type": "timer.tick", "remaining": remaining},
                )
                if remaining == 0:
                    break
                await asyncio.sleep(1)
            await self.broadcast_reveal_answer()
            await asyncio.sleep(3)
            await self.handle_next_question()
        except asyncio.CancelledError:
            pass

    async def timer_tick(self, event):
        await self.send(text_data=json.dumps({
            "type": "timer_tick",
            "remaining": event["remaining"],
        }))

    def start_question_timer(self, seconds):
        old = ROOM_TIMERS.get(self.lobby_code)
        if old and not old.done():
            old.cancel()
        ROOM_TIMERS[self.lobby_code] = asyncio.create_task(
            self._question_timer_coro(seconds)
        )



# Lobby and players
@database_sync_to_async
def db_get_or_create_lobby(code):
    lobby, _ = Lobby.objects.get_or_create(code=code)
    return lobby

@database_sync_to_async
def db_has_host(lobby):
    return lobby.players.filter(is_host=True).exists()

@database_sync_to_async
def db_create_player(lobby, name, avatar, is_host, channel_name):
    return Player.objects.create(
        lobby=lobby, name=name, avatar=avatar,
        is_host=is_host, channel_name=channel_name,
    )
@database_sync_to_async
def db_delete_player_by_channel(channel_name):
    Player.objects.filter(channel_name=channel_name).delete()
@database_sync_to_async
def db_update_player_channel(player_id, channel_name):
    Player.objects.filter(id=player_id).update(channel_name=channel_name)
@database_sync_to_async
def db_get_player_id_by_channel(channel_name):
    p = Player.objects.filter(channel_name=channel_name).first()
    return p.id if p else None
@database_sync_to_async
def db_get_player_by_token(token):
    p = Player.objects.filter(token=token).first()
    if not p:
        return None
    return {"id": p.id, "name": p.name, "avatar": p.avatar, "exp": p.exp, 
            "is_host": p.is_host, "lobby_id": p.lobby_id}
@database_sync_to_async
def db_get_player_token(player_id):
    return Player.objects.get(id=player_id).token
@database_sync_to_async
def db_get_players_serialized(lobby):
    return [
        {"id": p.id, "name": p.name, "avatar": p.avatar, "exp": p.exp, "is_host": p.is_host}
        for p in lobby.players.all().order_by("-exp", "id")
    ]

# Quiz
@database_sync_to_async
def db_load_random_question_ids(n):
    return list(Question.objects.order_by("?").values_list("id", flat=True)[:n])
@database_sync_to_async
def db_get_question(question_id):
    q = Question.objects.get(id=question_id)
    return {
        "id": q.id, "text": q.text,
        "options": q.options, "correct_index": q.correct_index,
    }

@database_sync_to_async
def db_reset_answers(lobby):
    lobby.players.filter(is_host=False).update(last_answer=None)
@database_sync_to_async
def db_save_answer(player_id, option_index):
    Player.objects.filter(id=player_id).update(last_answer=option_index)
@database_sync_to_async
def db_add_exp(player_id, amount):
    p = Player.objects.get(id=player_id)
    p.exp = p.exp + amount
    p.save()
@database_sync_to_async
def db_get_answer_stats(lobby):
    stats = {0: 0, 1: 0, 2: 0, 3: 0}
    for p in lobby.players.filter(is_host=False):
        if p.last_answer is not None:
            stats[p.last_answer] = stats.get(p.last_answer, 0) + 1
    return stats

@database_sync_to_async
def db_set_lobby_status(lobby, status):
    lobby.status = status
    lobby.save(update_fields=["status"])
@database_sync_to_async
def db_set_question_index(lobby, index):
    lobby.current_question_index = index
    lobby.save(update_fields=["current_question_index"])

