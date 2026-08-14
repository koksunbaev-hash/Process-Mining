"""Кто какие разделы видит.

Одно место на всё приложение. До этого меню в base.html было общим списком из
шестнадцати пунктов, одинаковым для оператора замеса и для директора, а роли
жили отдельно и решали только, кому можно нажать «Сохранить». Оператору
приходилось искать доску среди Process Mining и журнала действий.

Здесь описано и то, что показывать в меню, и то, что пускать по прямой ссылке:
скрытый пункт, до которого можно дойти, набрав адрес руками, - это не
разграничение, а вежливая просьба. Поэтому у раздела есть `routes` - все
адреса, которые он закрывает, включая формы и страницы отдельных записей.

Списки ролей заданы через группы, а не перечислением по разделу: групп шесть,
разделов семнадцать, и перечисление разъехалось бы с первой же новой ролью.
"""

from dataclasses import dataclass, field

from .permissions import user_role


# ---------------------------------------------------------------------------
# Роли
# ---------------------------------------------------------------------------

ADMIN = frozenset({"admin"})
#: Контора: распоряжается производством и справочниками, но не системой.
OFFICE = frozenset({"admin", "manager"})
#: Все три уровня. Раздел с этим набором виден каждому вошедшему.
EVERYONE = frozenset({"admin", "manager", "user"})

# Роль по умолчанию для пользователя без профиля. Профиль заводится сигналом при
# создании пользователя, но если его почему-то нет, пустое меню выглядит как
# поломка. Самый узкий уровень - честнее, чем пустой экран.
FALLBACK_ROLE = "user"


# ---------------------------------------------------------------------------
# Разделы
# ---------------------------------------------------------------------------

GROUPS = ["Производство", "Справочники", "Контроль", "Система"]


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    url_name: str
    group: str
    roles: frozenset
    #: остальные адреса раздела - формы, карточки записей, служебные обработчики
    routes: tuple = field(default=())
    #: Из меню убран, но раздел остаётся: адреса по-прежнему под охраной
    #: посредника, а ссылки из других мест не превращаются в 404. Убрать
    #: раздел совсем значило бы открыть его всем ролям разом.
    hidden: bool = False

    @property
    def all_routes(self):
        return (self.url_name,) + self.routes


SECTIONS = [
    Section("dashboard", "Панель", "dashboard:index", "Производство", OFFICE),
    Section(
        "kanban", "Производственная доска", "bakery:kanban", "Производство", EVERYONE,
        routes=("bakery:kanban_partial", "bakery:kanban_events", "bakery:move_batch", "bakery:batch_action"),
    ),
    Section("production_sheet", "Заказ на производство", "bakery:production_sheet", "Производство", OFFICE),
    Section("forecast", "Прогноз на неделю", "bakery:forecast", "Производство", OFFICE),
    Section(
        "orders", "Заказы", "bakery:orders", "Производство", OFFICE,
        routes=("bakery:order_new", "bakery:order_detail", "bakery:order_edit"),
    ),
    Section(
        "batches", "Производственные партии", "bakery:batches", "Производство", EVERYONE,
        routes=("bakery:batch_detail",),
    ),
    Section(
        "voice", "Голосовые сообщения", "bakery:voice", "Производство", EVERYONE,
        routes=("bakery:voice_upload", "bakery:voice_audio", "bakery:voice_delete"),
    ),
    # Склад виден всем: отдельной роли кладовщика больше нет, а без этой
    # страницы тому, кто принимает готовую продукцию, работать не с чем.
    Section("stock", "Склад", "bakery:stock", "Производство", EVERYONE),
    Section(
        "products", "Продукты", "bakery:products", "Справочники", OFFICE,
        routes=("bakery:product_new", "bakery:product_detail", "bakery:product_edit", "bakery:product_disable"),
    ),
    Section(
        "recipes", "Рецептуры", "bakery:recipes", "Справочники", EVERYONE,
        routes=("bakery:recipe_new", "bakery:recipe_detail", "bakery:recipe_edit"),
    ),
    Section(
        "ingredients", "Ингредиенты", "bakery:ingredients", "Справочники", OFFICE,
        routes=("bakery:ingredient_new", "bakery:ingredient_edit"),
    ),
    Section("nonconformities", "Проблемы", "nonconformities:list", "Контроль", EVERYONE),
    Section("reports", "Отчёты", "bakery:reports", "Контроль", OFFICE),
    Section("process_mining", "Process Mining", "process_mining:dashboard", "Контроль", OFFICE),
    Section("audit", "Журнал действий", "audit:logs", "Контроль", OFFICE),
    Section("notifications", "Уведомления", "notifications:list", "Система", EVERYONE, hidden=True),
    Section("settings", "Настройки", "accounts:settings", "Система", EVERYONE),
]

BY_KEY = {section.key: section for section in SECTIONS}

# Адрес -> раздел. Строится один раз: посредник обращается к нему на каждый
# запрос, и перебирать семнадцать разделов там незачем.
ROUTE_SECTION = {route: section.key for section in SECTIONS for route in section.all_routes}

#: Меню сворачивается в один список, если пунктов не больше этого числа.
#: Заголовки групп над списком из одной строки - разлиновка ради разлиновки.
FLAT_MENU_LIMIT = 8


def role_of(user):
    """Роль пользователя так, как её понимает навигация."""
    return user_role(user) or FALLBACK_ROLE


def can_view(user, key):
    section = BY_KEY.get(key)
    if section is None:
        return True
    if not user or not user.is_authenticated:
        return False
    return role_of(user) in section.roles


def section_for_route(view_name):
    """Раздел, которому принадлежит адрес, или None - адрес вне разграничения.

    Вне разграничения остаются API (у него свои разрешения DRF), админка Django
    (там `is_staff`) и разделы качества, которых в меню никогда не было.
    """
    return ROUTE_SECTION.get(view_name)


def sections_for(user):
    if not user or not user.is_authenticated:
        return []
    role = role_of(user)
    return [section for section in SECTIONS if role in section.roles]


def menu_sections(user):
    """Только то, что рисуется в меню.

    Отличается от `sections_for` на скрытые разделы: те доступны по ссылке и
    охраняются посредником, но пункта в меню не имеют.
    """
    return [section for section in sections_for(user) if not section.hidden]


def grouped_sections(user):
    """Разделы пользователя, разложенные по группам, в порядке GROUPS."""
    visible = menu_sections(user)
    by_group = {name: [] for name in GROUPS}
    for section in visible:
        by_group[section.group].append(section)
    return [{"title": name, "items": items} for name, items in by_group.items() if items]


def home_section(user):
    """Куда вести пользователя, у которого нет доступа к запрошенному разделу.

    Первый доступный ему раздел: для конторы это панель, для цеха - доска.
    """
    visible = sections_for(user)
    return visible[0] if visible else None
