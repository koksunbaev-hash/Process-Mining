from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .navigation import BY_KEY, can_view, home_section, section_for_route


class SectionAccessMiddleware:
    """Не пускает по прямой ссылке туда, чего нет в меню.

    Скрыть пункт мало: адреса короткие, ссылки уходят в переписку, а браузер
    помнит историю. Проверка стоит посредником, а не декоратором на каждом виде,
    потому что раздел - это не один адрес: у продуктов их пять, у заказов
    четыре, и декоратор пришлось бы не забыть навесить на каждый.

    Отказ - это перенаправление на свой раздел с объяснением, а не голый 403.
    Так сделано ради обычного случая: LOGIN_REDIRECT_URL ведёт на панель, а
    оператор цеха панель не видит, и первым, что он получал бы после входа,
    была бы страница ошибки.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None:
            return None
        key = section_for_route(match.view_name)
        if key is None:
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            # Пусть дальше отработает login_required и уведёт на форму входа с
            # ?next= - иначе адрес потеряется и после входа человек окажется не
            # там, куда шёл.
            return None
        if can_view(user, key):
            return None

        home = home_section(user)
        # Отказ на собственной начальной странице означал бы бесконечное
        # перенаправление на самого себя.
        if home is None or home.key == key:
            raise PermissionDenied(f"Раздел «{BY_KEY[key].label}» недоступен для вашей роли")
        messages.error(request, f"Раздел «{BY_KEY[key].label}» недоступен для вашей роли.")
        return redirect(reverse(home.url_name))
