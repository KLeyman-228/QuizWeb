from django.db import models
import random
import string
import uuid



AVATARS_LIST = ['🦊', '🐺', '🦁', '🐯', '🐻', '🦝', '🐸', 
                '🦄', '🐲', '👾', '🦐', '🦎', '👽', '🐧']


def generate_player_token():
    return uuid.uuid4().hex



class Lobby(models.Model):
    STATUS_CHOICES = [
        ("wait", "Waiting"),
        ("play", "Playing"),
        ("finish", "Finished")
    ]
    code = models.CharField(max_length=6, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="wait")
    current_question_index = models.IntegerField(default=-1)
    current_question_id = models.PositiveIntegerField(null=True, blank=True)
    question_ids = models.JSONField(default=list, blank=True)
    question_started_at = models.DateTimeField(null=True, blank=True)
    question_revealed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def generate_code():
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not Lobby.objects.filter(code=code).exists():
                return code


class Player(models.Model):
    lobby = models.ForeignKey(Lobby, on_delete=models.CASCADE, related_name="players")
    name = models.CharField(max_length=30)
    avatar = models.CharField(max_length=10, default=AVATARS_LIST[0])
    exp = models.IntegerField(default=0)
    is_host = models.BooleanField(default=False)
    last_answer = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    channel_name = models.CharField(max_length=255, blank=True)
    token = models.CharField(max_length=64, unique=True, default=generate_player_token)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lobby"],
                condition=models.Q(is_host=True),
                name="one_host_per_lobby",
            )
        ]



class Question(models.Model):
    text = models.CharField(max_length=300)
    options = models.JSONField(default=list)
    correct_index = models.IntegerField()
    category = models.CharField(max_length=50, blank=True)
    difficulty = models.IntegerField(default=1)
