from django.db import models
import random
import string




AVATARS_LIST = ['🦊', '🐺', '🦁', '🐯', '🐻', '🦝', '🐸', 
                '🦄', '🐲', '👾', '🦐', '🦎', '👽', '🐧']



class Lobby(models.Model):
    STATUS_CHOICES = [
        ("wait", "Waiting"),
        ("play", "Playing"),
        ("finish", "Finished")
    ]
    code = models.CharField(max_length=6, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="wait")
    current_question_index = models.IntegerField(default=-1)
    created_at = models.DateTimeField(auto_now_add=True)
    


class Player(models.Model):
    lobby = models.ForeignKey(Lobby, on_delete=models.CASCADE, related_name="players")
    name = models.CharField(max_length=30)
    avatar = models.CharField(max_length=10, choices=AVATARS_LIST, default='🦊')
    exp = models.IntegerField(default=0)
    is_host = models.BooleanField(default=False)
    channel_name = models.CharField(max_length=255, blank=True)
    last_answer = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)



class Question(models.Model):
    text = models.CharField(max_length=300)
    options = models.JSONField(default=list)
    correct_index = models.IntegerField()
    category = models.CharField(max_length=50, blank=True)
    difficulty = models.IntegerField(default=1)




@staticmethod
def generate_code():
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Lobby.objects.filter(code=code).exists():
            return code