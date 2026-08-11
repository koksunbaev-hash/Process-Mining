from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from apps.bakery.models import Ingredient, Product, ProductionStage, Recipe
from apps.bakery.permissions import can_manage_catalog
from apps.bakery.stages import StageError, move_stage, rename_stages, set_stage_active

from .forms import ProfileForm


def catalog_summary():
    """Три справочника одной строкой каждый: сколько всего и сколько живых.

    Менеджер приходит сюда с вопросом «что у нас заведено», а не «покажи
    таблицу» - счётчик отвечает на него, не открывая раздел.
    """
    return [
        {
            "label": "Продукты",
            "url_name": "bakery:products",
            "total": Product.objects.count(),
            "active": Product.objects.filter(is_active=True).count(),
            "hint": "Ассортимент: коды, вес, режимы выпечки",
        },
        {
            "label": "Рецептуры",
            "url_name": "bakery:recipes",
            "total": Recipe.objects.count(),
            "active": Recipe.objects.filter(is_active=True).count(),
            "hint": "Закладка на замес, версии, утверждение",
        },
        {
            "label": "Ингредиенты",
            "url_name": "bakery:ingredients",
            "total": Ingredient.objects.count(),
            "active": Ingredient.objects.filter(is_active=True).count(),
            "hint": "Сырьё, остатки, минимальный запас",
        },
    ]


def is_stage_post(request):
    return bool(request.POST.get("move")) or request.POST.get("action") == "stages"


def handle_stage_post(request):
    """Правки этапов: названия, включённость и порядок - одной формой.

    Стрелка «вверх» - такая же кнопка отправки той же формы, поэтому вместе с
    ней приезжают и поля названий. Их сохраняем: иначе набранное имя пропадало
    бы от нажатия на соседнюю стрелку, а причину было бы не угадать. Кнопка
    несёт одну пару имя-значение, отсюда `move=up:12` вместо двух полей.
    """
    changed = rename_stages(request.POST)
    refused = 0
    for stage in ProductionStage.objects.all():
        try:
            changed += int(set_stage_active(stage, f"stage_active_{stage.pk}" in request.POST))
        except StageError as error:
            refused += 1
            messages.error(request, str(error))

    move = request.POST.get("move", "")
    if move:
        direction, _, pk = move.partition(":")
        stage = get_object_or_404(ProductionStage, pk=pk)
        try:
            neighbour = move_stage(stage, -1 if direction == "up" else 1)
        except StageError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"«{stage.name}» и «{neighbour.name}» поменялись местами.")
    elif changed:
        messages.success(request, f"Этапы сохранены: изменений — {changed}.")
    elif not refused:
        messages.success(request, "Этапы без изменений.")


@login_required
def settings_view(request):
    user = request.user
    may_configure = can_manage_catalog(user)
    profile_form = ProfileForm.for_user(user)
    password_form = PasswordChangeForm(user)

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "profile":
            profile_form = ProfileForm.for_user(user, data=request.POST)
            if profile_form.is_valid():
                profile_form.save(user)
                messages.success(request, "Личные данные сохранены.")
                return redirect("accounts:settings")
        elif action == "password":
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                password_form.save()
                # Смена пароля обновляет хеш сессии, и без этого пользователь
                # выкидывается на форму входа сразу после успешной смены.
                update_session_auth_hash(request, user)
                messages.success(request, "Пароль изменён.")
                return redirect("accounts:settings")
        elif is_stage_post(request):
            if may_configure:
                handle_stage_post(request)
            else:
                messages.error(request, "Настройка этапов доступна менеджеру и администратору.")
            return redirect("accounts:settings")

    context = {
        "profile_form": profile_form,
        "password_form": password_form,
        "may_configure": may_configure,
        "catalog": catalog_summary() if may_configure else [],
        "stages": (
            ProductionStage.objects.annotate(held=Count("batches")).order_by("sequence")
            if may_configure
            else []
        ),
    }
    return render(request, "accounts/settings.html", context)
