from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/lobby/(?P<lobby_code>[A-Z0-9]{6})/$", consumers.QuizConsumer.as_asgi()),
]