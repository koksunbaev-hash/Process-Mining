from django.urls import reverse

from .navigation import FLAT_MENU_LIMIT, grouped_sections, section_for_route, sections_for


def navigation(request):
    """Меню текущего пользователя - готовое к отрисовке.

    Считается здесь, а не в шаблоне: base.html обслуживает каждую страницу, и
    условия по ролям в разметке разъезжаются с настоящими правами при первой же
    правке. В шаблоне остаётся цикл.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    visible = sections_for(user)
    match = getattr(request, "resolver_match", None)
    return {
        # Подсветка текущего пункта берётся из того же соответствия
        # адрес -> раздел, что и проверка доступа: карточка продукта подсветит
        # «Продукты», а не оставит меню без единого отмеченного пункта.
        "active_section": section_for_route(match.view_name) if match else None,
        "nav_groups": grouped_sections(user),
        "nav_flat": [
            {"key": section.key, "label": section.label, "url": reverse(section.url_name)}
            for section in visible
        ],
        # У оператора пунктов меньше десятка - группировать нечего.
        "nav_grouped": len(visible) > FLAT_MENU_LIMIT,
    }
