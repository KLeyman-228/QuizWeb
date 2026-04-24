from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from GameQuiz.asgi import application
from .consumers import DEFAULT_PLAYER_NAME, QUESTION_DURATION_SECONDS, QUESTION_REVEAL_SECONDS
from .models import AVATARS_LIST, Lobby, Player, Question


class LobbyViewTests(TestCase):
    def test_unknown_lobby_returns_404(self):
        response = self.client.get("/lobby/ABC123/")

        self.assertEqual(response.status_code, 404)


class QuizConsumerTests(TransactionTestCase):
    def setUp(self):
        self.lobby = Lobby.objects.create(code="ABC123")
        for index in range(5):
            Question.objects.create(
                text=f"Question {index}",
                options=["A", "B", "C", "D"],
                correct_index=index % 4,
            )

    def test_join_player_without_profile_uses_safe_defaults(self):
        async_to_sync(self._test_join_player_without_profile_uses_safe_defaults)()

    async def _test_join_player_without_profile_uses_safe_defaults(self):
        player = await self.connect_socket()
        await player.send_json_to({
            "type": "join_player",
            "name": None,
            "avatar": None,
        })

        token_message = await self.receive_by_type(player, "your_token")
        self.assertTrue(token_message["token"])

        db_player = await self.get_non_host_player()
        self.assertEqual(db_player.name, DEFAULT_PLAYER_NAME)
        self.assertEqual(db_player.avatar, AVATARS_LIST[0])

        await player.disconnect()

    def test_player_cannot_join_started_game_without_saved_token(self):
        async_to_sync(self._test_player_cannot_join_started_game_without_saved_token)()

    async def _test_player_cannot_join_started_game_without_saved_token(self):
        host = await self.connect_socket()
        await host.send_json_to({"type": "join_host"})
        await self.receive_by_type(host, "lobby_update")

        await host.send_json_to({"type": "start_game"})
        await self.receive_by_type(host, "question_show")

        late_player = await self.connect_socket()
        await late_player.send_json_to({
            "type": "join_player",
            "name": "Late",
            "avatar": AVATARS_LIST[1],
        })

        denied_message = await self.receive_by_type(late_player, "join_denied")
        self.assertIn("Игра уже началась", denied_message["message"])
        self.assertEqual(await self.count_non_host_players(), 0)

        await host.send_json_to({"type": "finish_game"})
        await self.receive_by_type(host, "game_finished")
        await late_player.disconnect()
        await host.disconnect()

    def test_reconnecting_player_restores_question_and_answer_state(self):
        async_to_sync(self._test_reconnecting_player_restores_question_and_answer_state)()

    async def _test_reconnecting_player_restores_question_and_answer_state(self):
        player = await self.connect_socket()
        await player.send_json_to({
            "type": "join_player",
            "name": "Mira",
            "avatar": AVATARS_LIST[2],
        })
        token_message = await self.receive_by_type(player, "your_token")
        player_token = token_message["token"]
        await self.receive_by_type(player, "lobby_update")

        host = await self.connect_socket()
        await host.send_json_to({"type": "join_host"})
        await self.receive_by_type(host, "lobby_update")
        await self.receive_by_type(player, "lobby_update")

        await host.send_json_to({"type": "start_game"})
        player_question = await self.receive_by_type(player, "question_show")
        self.assertEqual(player_question["index"], 0)
        self.assertIsNotNone(player_question["started_at"])
        self.assertEqual(player_question["duration_seconds"], QUESTION_DURATION_SECONDS)
        await self.receive_by_type(host, "question_show")

        current_question = await self.get_question(player_question["question"]["id"])
        await player.send_json_to({
            "type": "answer",
            "option_index": current_question.correct_index,
        })
        await self.receive_by_type(host, "answer_stats")
        await player.disconnect()

        reconnected_player = await self.connect_socket()
        await reconnected_player.send_json_to({
            "type": "join_player",
            "token": player_token,
        })

        reconnect_token_message = await self.receive_by_type(reconnected_player, "your_token")
        self.assertEqual(reconnect_token_message["token"], player_token)

        restored_question = await self.receive_by_type(reconnected_player, "question_show")
        self.assertEqual(restored_question["question"]["id"], current_question.id)
        self.assertIsNotNone(restored_question["started_at"])
        await self.receive_by_type(reconnected_player, "already_answered")

        await host.send_json_to({"type": "finish_game"})
        await self.receive_by_type(host, "game_finished")
        await reconnected_player.disconnect()
        await host.disconnect()

    def test_timer_expiration_reveals_and_advances_question(self):
        async_to_sync(self._test_timer_expiration_reveals_and_advances_question)()

    async def _test_timer_expiration_reveals_and_advances_question(self):
        player = await self.connect_socket()
        await player.send_json_to({
            "type": "join_player",
            "name": "Mira",
            "avatar": AVATARS_LIST[2],
        })
        await self.receive_by_type(player, "your_token")
        await self.receive_by_type(player, "lobby_update")

        host = await self.connect_socket()
        await host.send_json_to({"type": "join_host"})
        await self.receive_by_type(host, "lobby_update")
        await self.receive_by_type(player, "lobby_update")

        await host.send_json_to({"type": "start_game"})
        first_question_player = await self.receive_by_type(player, "question_show")
        await self.receive_by_type(host, "question_show")

        await self.set_question_times(
            started_at=timezone.now() - timedelta(seconds=QUESTION_DURATION_SECONDS + 1),
            revealed_at=None,
        )
        await player.send_json_to({"type": "timer_expired", "question_id": first_question_player["question_id"]})

        player_reveal = await self.receive_by_type(player, "reveal_answer")
        host_reveal = await self.receive_by_type(host, "reveal_answer")
        self.assertEqual(player_reveal["question_id"], first_question_player["question_id"])
        self.assertEqual(host_reveal["question_id"], first_question_player["question_id"])

        await self.set_question_times(
            started_at=timezone.now() - timedelta(seconds=QUESTION_DURATION_SECONDS + QUESTION_REVEAL_SECONDS + 1),
            revealed_at=timezone.now() - timedelta(seconds=QUESTION_REVEAL_SECONDS + 1),
        )
        await host.send_json_to({"type": "reveal_expired", "question_id": first_question_player["question_id"]})

        next_question_player = await self.receive_by_type(player, "question_show")
        next_question_host = await self.receive_by_type(host, "question_show")
        self.assertEqual(next_question_player["index"], 1)
        self.assertEqual(next_question_host["index"], 1)

        await host.send_json_to({"type": "finish_game"})
        await self.receive_by_type(host, "game_finished")
        await self.receive_by_type(player, "game_finished")
        await player.disconnect()
        await host.disconnect()

    async def connect_socket(self):
        communicator = WebsocketCommunicator(application, f"/ws/lobby/{self.lobby.code}/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def receive_by_type(self, communicator, expected_type, attempts=8, timeout=1):
        for _ in range(attempts):
            message = await communicator.receive_json_from(timeout=timeout)
            if message["type"] == expected_type:
                return message
        raise AssertionError(f"Message {expected_type!r} was not received")

    @database_sync_to_async
    def get_non_host_player(self):
        return Player.objects.get(is_host=False)

    @database_sync_to_async
    def count_non_host_players(self):
        return Player.objects.filter(is_host=False).count()

    @database_sync_to_async
    def get_question(self, question_id):
        return Question.objects.get(id=question_id)

    @database_sync_to_async
    def set_question_times(self, started_at, revealed_at):
        Lobby.objects.filter(id=self.lobby.id).update(
            question_started_at=started_at,
            question_revealed_at=revealed_at,
        )
