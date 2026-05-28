from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import AVATARS_LIST, Lobby, REACTIONS_LIST
from .qr import make_qr_svg


@ensure_csrf_cookie
def index_view(request):
    return render(request, "index.html", {"avatars": AVATARS_LIST})


def lobby_view(request, code):
    lobby = get_object_or_404(Lobby, code=code.upper())
    return render(request, "lobby.html", {"code": lobby.code, "reactions": REACTIONS_LIST})


def host_view(request, code):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Доступ запрещён")
    lobby = get_object_or_404(Lobby, code=code.upper())
    lobby_url = request.build_absolute_uri(f"{reverse('index')}?{urlencode({'code': lobby.code})}")
    return render(
        request,
        "host.html",
        {
            "code": lobby.code,
            "lobby_url": lobby_url,
            "qr_url": reverse("lobby-qr", args=[lobby.code]),
            "reactions": REACTIONS_LIST,
        },
    )


@require_POST
def new_lobby_api(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Доступ запрещён")
    code = Lobby.generate_code()
    Lobby.objects.create(code=code)
    return JsonResponse({"code": code})


def lobby_qr_api(request, code):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Доступ запрещён")

    lobby = get_object_or_404(Lobby, code=code.upper())
    lobby_url = request.build_absolute_uri(f"{reverse('index')}?{urlencode({'code': lobby.code})}")
    return HttpResponse(make_qr_svg(lobby_url), content_type="image/svg+xml")


def page_not_found(request, exception):
    return render(request, "404.html", status=404)
