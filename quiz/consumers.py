import json
import asyncio
from datetime import datetime, timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import AVATARS_LIST, Lobby, Player, Question, REACTIONS_LIST


QUESTION_DURATION_SECONDS = 20
QUESTION_REVEAL_SECONDS = 10
QUESTIONS_PER_GAME = 118
DEFAULT_PLAYER_NAME = "Игрок"
REACTION_COOLDOWN_SECONDS = 0.35
TIMING_SYNC_GRACE_SECONDS = 0.35


def normalize_player_name(value):
    cleaned = (value or "").strip()
    return cleaned[:30] or DEFAULT_PLAYER_NAME


def normalize_avatar(value):
    return value if value in AVATARS_LIST else AVATARS_LIST[0]


def normalize_reaction(value):
    return value if value in REACTIONS_LIST else None


def serialize_datetime(value):
    return value.isoformat() if value else None


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def serialize_leaderboard(leaderboard):
    return [player for player in (leaderboard or []) if not player["is_host"]]


def serialize_question(question):
    if not question:
        return None

    return {
        "id": question.id,
        "text": question.text,
        "options": question.options,
        "correct_index": question.correct_index,
        "safe": {
            "id": question.id,
            "text": question.text,
            "options": question.options,
        },
    }


def build_question_message(question, index, leaderboard=None):
    message = {
        "type": "question_show",
        "question": question["safe"],
        "index": index,
        "question_id": question["id"],
        "started_at": serialize_datetime(question["started_at"]),
        "revealed_at": serialize_datetime(question["revealed_at"]),
        "duration_seconds": QUESTION_DURATION_SECONDS,
        "reveal_seconds": QUESTION_REVEAL_SECONDS,
    }
    if leaderboard is not None:
        message["leaderboard"] = serialize_leaderboard(leaderboard)
    return message


def build_reveal_message(question):
    return {
        "type": "reveal_answer",
        "question_id": question["id"],
        "correct_index": question["correct_index"],
        "revealed_at": serialize_datetime(question["revealed_at"]),
        "reveal_seconds": QUESTION_REVEAL_SECONDS,
    }


def build_game_finished_message(leaderboard):
    return {
        "type": "game_finished",
        "leaderboard": serialize_leaderboard(leaderboard),
    }


class QuizConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.lobby_code = self.scope["url_route"]["kwargs"]["lobby_code"]
        self.group_name = f"lobby_{self.lobby_code}"
        self.added_to_group = False
        self.timing_sync_task = None
        self.lobby = await db_get_lobby(self.lobby_code)

        if not self.lobby:
            await self.close(code=4404)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        self.added_to_group = True
        await self.accept()

    async def disconnect(self, _code):
        self.cancel_timing_sync()

        if not hasattr(self, "group_name") or not getattr(self, "lobby", None):
            return

        lobby_status = await db_get_lobby_status(self.lobby.id)
        if lobby_status == "wait":
            await db_delete_player_by_channel(self.channel_name)
            await self.broadcast_lobby()

        if getattr(self, "added_to_group", False):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_json({"type": "error", "message": "Некорректный формат сообщения"})
            return

        data_type = data.get("type")

        if data_type == "join_player":
            await self.handle_join_player(data)
            return
        if data_type == "join_host":
            await self.handle_join_host()
            return
        if data_type == "answer":
            await self.handle_answer(data)
            return
        if data_type == "send_message":
            await self.handle_chat_message(data)
            return
        if data_type == "send_reaction":
            await self.handle_reaction(data)
            return
        if data_type == "timer_expired":
            await self.handle_timer_expired(data)
            return
        if data_type == "reveal_expired":
            await self.handle_reveal_expired(data)
            return

        if data_type in {"start_game", "next_question", "finish_game"}:
            if not await self.is_current_host():
                return
            if data_type == "start_game":
                await self.handle_start_game()
            elif data_type == "next_question":
                await self.handle_next_question()
            else:
                await self.handle_finish_game()
            return

        await self.send_json({"type": "error", "message": "Неизвестный тип сообщения"})

    def scope_user_is_superuser(self):
        user = self.scope.get("user")
        return bool(
            getattr(user, "is_authenticated", False)
            and getattr(user, "is_superuser", False)
        )

    def cancel_timing_sync(self):
        task = getattr(self, "timing_sync_task", None)
        if task and not task.done():
            task.cancel()
        self.timing_sync_task = None

    def schedule_timing_sync(self, question_id, target_at):
        if not question_id or not target_at:
            return

        delay = max(0, (target_at - timezone.now()).total_seconds()) + TIMING_SYNC_GRACE_SECONDS
        self.cancel_timing_sync()
        self.timing_sync_task = asyncio.create_task(self.run_timing_sync(question_id, delay))

    def schedule_question_sync(self, question_id, started_at):
        self.schedule_timing_sync(
            question_id,
            started_at + timedelta(seconds=QUESTION_DURATION_SECONDS) if started_at else None,
        )

    def schedule_reveal_sync(self, question_id, revealed_at):
        self.schedule_timing_sync(
            question_id,
            revealed_at + timedelta(seconds=QUESTION_REVEAL_SECONDS) if revealed_at else None,
        )

    def schedule_from_question_message(self, message):
        question_id = message.get("question_id")
        if not question_id:
            return

        revealed_at = parse_datetime(message.get("revealed_at"))
        if revealed_at:
            self.schedule_reveal_sync(question_id, revealed_at)
            return

        self.schedule_question_sync(question_id, parse_datetime(message.get("started_at")))

    def schedule_from_reveal_message(self, message):
        self.schedule_reveal_sync(
            message.get("question_id"),
            parse_datetime(message.get("revealed_at")),
        )

    async def run_timing_sync(self, question_id, delay):
        try:
            await asyncio.sleep(delay)
            await self.sync_lobby_timing(expected_question_id=question_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        finally:
            if asyncio.current_task() is self.timing_sync_task:
                self.timing_sync_task = None

    async def is_current_host(self):
        if not getattr(self, "is_host", False) or not getattr(self, "player_id", None):
            return False
        if not self.scope_user_is_superuser():
            return False
        return await db_is_current_host(self.lobby.id, self.player_id, self.channel_name)

    async def handle_join_player(self, data):
        token = data.get("token") or None
        existing_player = await db_get_player_by_token(token) if token else None
        is_reconnect = False
        should_restore_state = False

        if existing_player and existing_player["lobby_id"] == self.lobby.id:
            self.player_id = existing_player["id"]
            self.player_name = existing_player["name"]
            self.avatar = existing_player["avatar"]
            self.is_host = existing_player["is_host"]
            await db_update_player_channel(self.player_id, self.channel_name)
            is_reconnect = True
            should_restore_state = True
        else:
            lobby_status = await db_get_lobby_status(self.lobby.id)
            if lobby_status == "finish":
                await self.send_json({
                    "type": "join_denied",
                    "message": "Игра уже завершена.",
                })
                await self.close(code=4403)
                return
            should_restore_state = lobby_status == "play"

            self.player_name = normalize_player_name(data.get("name"))
            self.avatar = normalize_avatar(data.get("avatar"))
            self.is_host = False
            self.player_id = await db_create_player(
                lobby_id=self.lobby.id,
                name=self.player_name,
                avatar=self.avatar,
                is_host=False,
                channel_name=self.channel_name,
            )

        new_token = await db_get_player_token(self.player_id)
        await self.send_json({"type": "your_token", "token": new_token})
        await self.broadcast_lobby()

        if should_restore_state or is_reconnect:
            await self.restore_session_state()

    async def handle_join_host(self):
        if not self.scope_user_is_superuser():
            await self.send_json({"type": "error", "message": "Доступ запрещён"})
            await self.close(code=4403)
            return

        if await db_has_host(self.lobby.id):
            await db_delete_host(self.lobby.id)

        self.player_name = "HOST"
        self.avatar = AVATARS_LIST[0]
        self.is_host = True
        self.player_id = await db_create_player(
            lobby_id=self.lobby.id,
            name=self.player_name,
            avatar=self.avatar,
            is_host=True,
            channel_name=self.channel_name,
        )

        await self.broadcast_lobby()
        await self.restore_session_state()

    async def restore_session_state(self):
        sync_result = await self.sync_lobby_timing(broadcast=False)
        if sync_result["event"] == "question_show":
            await self.broadcast_question(sync_result["question"], sync_result["index"])
            await self.broadcast_answer_stats()
            return
        if sync_result["event"] == "game_finished":
            await self.broadcast_game_finished(sync_result["leaderboard"])
            return

        lobby_state = await db_get_lobby_state(self.lobby.id)
        if lobby_state["status"] == "play":
            question = await db_get_current_question(self.lobby.id)
            if not question:
                return

            await self.send_question_message(question, lobby_state["current_question_index"])
            if getattr(self, "is_host", False):
                stats = await db_get_answer_stats(self.lobby.id)
                leaderboard = await db_get_players_serialized(self.lobby.id)
                await self.send_json({
                    "type": "answer_stats",
                    "stats": stats,
                    "leaderboard": serialize_leaderboard(leaderboard),
                })
            elif await db_player_already_answered(self.player_id):
                await self.send_json({"type": "already_answered"})

            if question["revealed_at"]:
                if sync_result["event"] == "reveal_answer":
                    await self.broadcast_reveal_answer(question)
                else:
                    await self.send_reveal_message(question)
            return

        if lobby_state["status"] == "finish":
            leaderboard = await db_get_players_serialized(self.lobby.id)
            await self.send_json(build_game_finished_message(leaderboard))

    async def handle_chat_message(self, data):
        text = (data.get("text") or "").strip()[:200]
        if not text:
            return

        player = await db_get_player_by_channel(self.channel_name)
        if not player:
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "player": player,
                "text": text,
            },
        )

    async def handle_reaction(self, data):
        emoji = normalize_reaction(data.get("emoji"))
        if not emoji:
            return
        reaction_id = data.get("reaction_id")
        if not isinstance(reaction_id, str):
            reaction_id = None
        elif len(reaction_id) > 80:
            reaction_id = reaction_id[:80]

        now = timezone.now()
        last_reaction_at = getattr(self, "last_reaction_at", None)
        if last_reaction_at and (now - last_reaction_at).total_seconds() < REACTION_COOLDOWN_SECONDS:
            return
        self.last_reaction_at = now

        player = await db_get_player_by_channel(self.channel_name)
        if not player:
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "reaction_event",
                "player": player,
                "emoji": emoji,
                "reaction_id": reaction_id,
            },
        )

    async def handle_start_game(self):
        lobby_status = await db_get_lobby_status(self.lobby.id)
        if lobby_status == "play":
            return

        question_ids = await db_load_random_question_ids(QUESTIONS_PER_GAME)
        if not question_ids:
            await self.send_json({
                "type": "error",
                "message": "В базе пока нет вопросов для запуска игры.",
            })
            return

        await db_prepare_game(self.lobby.id, question_ids)
        await self.handle_next_question()

    async def handle_next_question(self):
        lobby_state = await db_get_lobby_state(self.lobby.id)
        question_ids = lobby_state["question_ids"]
        next_index = lobby_state["current_question_index"] + 1

        if next_index >= len(question_ids):
            await self.handle_finish_game()
            return

        question = await db_begin_question(
            lobby_id=self.lobby.id,
            question_id=question_ids[next_index],
            index=next_index,
        )
        if not question:
            await self.handle_finish_game()
            return

        await self.broadcast_question(question, next_index)
        await self.broadcast_answer_stats()

    async def handle_answer(self, data):
        sync_result = await self.sync_lobby_timing()
        if sync_result["event"] is not None:
            return

        if getattr(self, "is_host", False):
            return

        current_question = await db_get_current_question(self.lobby.id)
        if not current_question or current_question["revealed_at"]:
            return

        option_index = data.get("option_index")
        if not isinstance(option_index, int):
            return
        if option_index < 0 or option_index >= len(current_question["options"]):
            return

        player_id = await db_get_player_id_by_channel(self.channel_name)
        if player_id is None:
            return

        was_saved = await db_save_answer(player_id, option_index)
        if not was_saved:
            return

        if option_index == current_question["correct_index"]:
            elapsed = (timezone.now() - current_question["started_at"]).total_seconds()
            speed_bonus = max(0, 100 - int(elapsed * 6))
            await db_add_exp(player_id, 50 + speed_bonus)

        await self.broadcast_answer_stats()

    async def handle_timer_expired(self, data):
        question_id = data.get("question_id")
        if not isinstance(question_id, int):
            return
        await self.sync_lobby_timing(expected_question_id=question_id)

    async def handle_reveal_expired(self, data):
        question_id = data.get("question_id")
        if not isinstance(question_id, int):
            return
        await self.sync_lobby_timing(expected_question_id=question_id)

    async def handle_finish_game(self):
        await db_finish_lobby(self.lobby.id)
        leaderboard = await db_get_players_serialized(self.lobby.id)
        await self.broadcast_game_finished(leaderboard)

    async def sync_lobby_timing(self, broadcast=True, expected_question_id=None):
        result = await db_sync_lobby_timing(self.lobby.id, expected_question_id)
        if not broadcast or result["event"] is None:
            return result

        if result["event"] == "reveal_answer":
            await self.broadcast_reveal_answer(result["question"])
        elif result["event"] == "question_show":
            await self.broadcast_question(result["question"], result["index"])
            await self.broadcast_answer_stats()
        elif result["event"] == "game_finished":
            await self.broadcast_game_finished(result["leaderboard"])

        return result

    async def send_question_message(self, question, index):
        leaderboard = await db_get_players_serialized(self.lobby.id)
        message = build_question_message(question, index, leaderboard)
        self.schedule_from_question_message(message)
        await self.send_json(message)

    async def send_reveal_message(self, question):
        message = build_reveal_message(question)
        self.schedule_from_reveal_message(message)
        await self.send_json(message)

    async def broadcast_lobby(self):
        players = await db_get_players_serialized(self.lobby.id)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "lobby_update", "players": players},
        )

    async def broadcast_question(self, question, index):
        leaderboard = await db_get_players_serialized(self.lobby.id)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "question_show", "message": build_question_message(question, index, leaderboard)},
        )

    async def broadcast_reveal_answer(self, question):
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "reveal_answer", "message": build_reveal_message(question)},
        )

    async def broadcast_answer_stats(self):
        stats = await db_get_answer_stats(self.lobby.id)
        leaderboard = await db_get_players_serialized(self.lobby.id)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "answer_stats",
                "stats": stats,
                "leaderboard": serialize_leaderboard(leaderboard),
            },
        )

    async def broadcast_game_finished(self, leaderboard):
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "game_finished_event", "message": build_game_finished_message(leaderboard)},
        )

    async def send_json(self, payload):
        await self.send(text_data=json.dumps(payload))

    async def lobby_update(self, event):
        await self.send_json({
            "type": "lobby_update",
            "players": event["players"],
        })

    async def question_show(self, event):
        self.schedule_from_question_message(event["message"])
        await self.send_json(event["message"])

    async def answer_stats(self, event):
        if getattr(self, "is_host", False):
            payload = {
                "type": "answer_stats",
                "stats": event["stats"],
            }
            if "leaderboard" in event:
                payload["leaderboard"] = event["leaderboard"]
            await self.send_json(payload)

    async def reveal_answer(self, event):
        self.schedule_from_reveal_message(event["message"])
        await self.send_json(event["message"])

    async def chat_message(self, event):
        await self.send_json({
            "type": "chat_message",
            "player": event["player"],
            "text": event["text"],
        })

    async def reaction_event(self, event):
        await self.send_json({
            "type": "reaction",
            "player": event["player"],
            "emoji": event["emoji"],
            "reaction_id": event.get("reaction_id"),
        })

    async def game_finished_event(self, event):
        self.cancel_timing_sync()
        await self.send_json(event["message"])


@database_sync_to_async
def db_get_lobby(code):
    return Lobby.objects.filter(code=code).first()


@database_sync_to_async
def db_get_lobby_status(lobby_id):
    return Lobby.objects.filter(id=lobby_id).values_list("status", flat=True).first()


@database_sync_to_async
def db_get_lobby_state(lobby_id):
    return Lobby.objects.filter(id=lobby_id).values(
        "status",
        "current_question_index",
        "current_question_id",
        "question_ids",
        "question_started_at",
        "question_revealed_at",
    ).get()


@database_sync_to_async
def db_has_host(lobby_id):
    return Player.objects.filter(lobby_id=lobby_id, is_host=True).exists()


@database_sync_to_async
def db_is_current_host(lobby_id, player_id, channel_name):
    return Player.objects.filter(
        id=player_id,
        lobby_id=lobby_id,
        channel_name=channel_name,
        is_host=True,
    ).exists()


@database_sync_to_async
def db_delete_host(lobby_id):
    Player.objects.filter(lobby_id=lobby_id, is_host=True).delete()


@database_sync_to_async
def db_create_player(lobby_id, name, avatar, is_host, channel_name):
    player = Player.objects.create(
        lobby_id=lobby_id,
        name=name,
        avatar=avatar,
        is_host=is_host,
        channel_name=channel_name,
    )
    return player.id


@database_sync_to_async
def db_delete_player_by_channel(channel_name):
    Player.objects.filter(channel_name=channel_name).delete()


@database_sync_to_async
def db_update_player_channel(player_id, channel_name):
    Player.objects.filter(id=player_id).update(channel_name=channel_name)


@database_sync_to_async
def db_get_player_id_by_channel(channel_name):
    return Player.objects.filter(channel_name=channel_name).values_list("id", flat=True).first()


@database_sync_to_async
def db_get_player_by_channel(channel_name):
    player = Player.objects.filter(channel_name=channel_name).first()
    if not player:
        return None

    return {
        "id": player.id,
        "name": player.name,
        "avatar": player.avatar,
        "exp": player.exp,
        "is_host": player.is_host,
    }


@database_sync_to_async
def db_get_player_by_token(token):
    player = Player.objects.filter(token=token).first()
    if not player:
        return None

    return {
        "id": player.id,
        "name": player.name,
        "avatar": player.avatar,
        "exp": player.exp,
        "is_host": player.is_host,
        "lobby_id": player.lobby_id,
    }


@database_sync_to_async
def db_get_player_token(player_id):
    return Player.objects.get(id=player_id).token


@database_sync_to_async
def db_get_players_serialized(lobby_id):
    return [
        {
            "id": player.id,
            "name": player.name,
            "avatar": player.avatar,
            "exp": player.exp,
            "is_host": player.is_host,
        }
        for player in Player.objects.filter(lobby_id=lobby_id).order_by("-exp", "id")
    ]


@database_sync_to_async
def db_load_random_question_ids(limit):
    return list(Question.objects.order_by("?").values_list("id", flat=True)[:limit])


@database_sync_to_async
def db_prepare_game(lobby_id, question_ids):
    Lobby.objects.filter(id=lobby_id).update(
        status="play",
        current_question_index=-1,
        current_question_id=None,
        question_ids=question_ids,
        question_started_at=None,
        question_revealed_at=None,
    )
    Player.objects.filter(lobby_id=lobby_id, is_host=False).update(exp=0, last_answer=None)


@database_sync_to_async
def db_begin_question(lobby_id, question_id, index):
    question = Question.objects.filter(id=question_id).first()
    if not question:
        return None

    started_at = timezone.now()
    Lobby.objects.filter(id=lobby_id).update(
        status="play",
        current_question_index=index,
        current_question_id=question.id,
        question_started_at=started_at,
        question_revealed_at=None,
    )
    Player.objects.filter(lobby_id=lobby_id, is_host=False).update(last_answer=None)
    payload = serialize_question(question)
    payload["started_at"] = started_at
    payload["revealed_at"] = None
    return payload


@database_sync_to_async
def db_get_current_question(lobby_id):
    lobby = Lobby.objects.filter(id=lobby_id).values(
        "current_question_id",
        "question_started_at",
        "question_revealed_at",
    ).first()
    if not lobby or not lobby["current_question_id"]:
        return None

    question = Question.objects.filter(id=lobby["current_question_id"]).first()
    payload = serialize_question(question)
    if not payload:
        return None

    payload["started_at"] = lobby["question_started_at"]
    payload["revealed_at"] = lobby["question_revealed_at"]
    return payload


@database_sync_to_async
def db_save_answer(player_id, option_index):
    updated = Player.objects.filter(
        id=player_id,
        last_answer__isnull=True,
        is_host=False,
    ).update(last_answer=option_index)
    return updated == 1


@database_sync_to_async
def db_add_exp(player_id, amount):
    Player.objects.filter(id=player_id).update(exp=F("exp") + amount)


@database_sync_to_async
def db_get_answer_stats(lobby_id):
    lobby = Lobby.objects.filter(id=lobby_id).values("current_question_id").first()
    if not lobby or not lobby["current_question_id"]:
        return {}

    options = Question.objects.filter(id=lobby["current_question_id"]).values_list("options", flat=True).first() or []
    stats = {str(index): 0 for index in range(len(options))}

    for answer in Player.objects.filter(lobby_id=lobby_id, is_host=False).exclude(last_answer=None).values_list("last_answer", flat=True):
        key = str(answer)
        stats[key] = stats.get(key, 0) + 1

    return stats


@database_sync_to_async
def db_finish_lobby(lobby_id):
    Lobby.objects.filter(id=lobby_id).update(
        status="finish",
        current_question_id=None,
        question_started_at=None,
        question_revealed_at=None,
    )


@database_sync_to_async
def db_player_already_answered(player_id):
    return Player.objects.filter(id=player_id, last_answer__isnull=False).exists()


@database_sync_to_async
def db_sync_lobby_timing(lobby_id, expected_question_id=None):
    with transaction.atomic():
        lobby = Lobby.objects.select_for_update().filter(id=lobby_id).first()
        if not lobby or lobby.status != "play" or not lobby.current_question_id or not lobby.question_started_at:
            return {"event": None}
        if expected_question_id is not None and lobby.current_question_id != expected_question_id:
            return {"event": None}

        now = timezone.now()
        reveal_deadline = lobby.question_started_at + timedelta(seconds=QUESTION_DURATION_SECONDS)

        current_question = Question.objects.filter(id=lobby.current_question_id).first()
        if not current_question:
            lobby.status = "finish"
            lobby.current_question_id = None
            lobby.question_started_at = None
            lobby.question_revealed_at = None
            lobby.save(update_fields=["status", "current_question_id", "question_started_at", "question_revealed_at"])
            return {
                "event": "game_finished",
                "leaderboard": [
                    {
                        "id": player.id,
                        "name": player.name,
                        "avatar": player.avatar,
                        "exp": player.exp,
                        "is_host": player.is_host,
                    }
                    for player in Player.objects.filter(lobby_id=lobby_id).order_by("-exp", "id")
                ],
            }

        if lobby.question_revealed_at is None:
            if now < reveal_deadline:
                return {"event": None}

            lobby.question_revealed_at = now
            lobby.save(update_fields=["question_revealed_at"])
            question = serialize_question(current_question)
            question["started_at"] = lobby.question_started_at
            question["revealed_at"] = lobby.question_revealed_at
            return {"event": "reveal_answer", "question": question}

        advance_deadline = lobby.question_revealed_at + timedelta(seconds=QUESTION_REVEAL_SECONDS)
        if now < advance_deadline:
            return {"event": None}

        next_index = lobby.current_question_index + 1
        question_ids = lobby.question_ids or []
        if next_index >= len(question_ids):
            lobby.status = "finish"
            lobby.current_question_id = None
            lobby.question_started_at = None
            lobby.question_revealed_at = None
            lobby.save(update_fields=["status", "current_question_id", "question_started_at", "question_revealed_at"])
            return {
                "event": "game_finished",
                "leaderboard": [
                    {
                        "id": player.id,
                        "name": player.name,
                        "avatar": player.avatar,
                        "exp": player.exp,
                        "is_host": player.is_host,
                    }
                    for player in Player.objects.filter(lobby_id=lobby_id).order_by("-exp", "id")
                ],
            }

        next_question = Question.objects.filter(id=question_ids[next_index]).first()
        if not next_question:
            lobby.status = "finish"
            lobby.current_question_id = None
            lobby.question_started_at = None
            lobby.question_revealed_at = None
            lobby.save(update_fields=["status", "current_question_id", "question_started_at", "question_revealed_at"])
            return {
                "event": "game_finished",
                "leaderboard": [
                    {
                        "id": player.id,
                        "name": player.name,
                        "avatar": player.avatar,
                        "exp": player.exp,
                        "is_host": player.is_host,
                    }
                    for player in Player.objects.filter(lobby_id=lobby_id).order_by("-exp", "id")
                ],
            }

        started_at = now
        lobby.current_question_index = next_index
        lobby.current_question_id = next_question.id
        lobby.question_started_at = started_at
        lobby.question_revealed_at = None
        lobby.save(
            update_fields=[
                "current_question_index",
                "current_question_id",
                "question_started_at",
                "question_revealed_at",
            ]
        )
        Player.objects.filter(lobby_id=lobby_id, is_host=False).update(last_answer=None)

        question = serialize_question(next_question)
        question["started_at"] = started_at
        question["revealed_at"] = None
        return {"event": "question_show", "question": question, "index": next_index}
