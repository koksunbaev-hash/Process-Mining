(function () {
  "use strict";

  const STORAGE_KEY = "qms-ui-language";
  const SUPPORTED = new Set(["ru", "kk", "en"]);
  const translations = {
    "Управление качеством": ["Сапаны басқару", "Quality management"],
    "Управление качеством производства": ["Өндіріс сапасын басқару", "Production quality management"],
    "Хлебозавод": ["Нан зауыты", "Bakery"],
    "Панель": ["Басқару тақтасы", "Dashboard"],
    "Производство": ["Өндіріс", "Production"],
    "Справочники": ["Анықтамалықтар", "Directories"],
    "Контроль": ["Бақылау", "Quality control"],
    "Система": ["Жүйе", "System"],
    "Производственная доска": ["Өндірістік тақта", "Production board"],
    "Заказ на производство": ["Өндірістік тапсырыс", "Production order"],
    "История заказов": ["Тапсырыстар тарихы", "Order history"],
    "Архив производства с количеством и временем выполнения": ["Саны мен орындалу уақыты көрсетілген өндіріс мұрағаты", "Production archive with quantities and completion times"],
    "Номер заказа или продукт": ["Тапсырыс нөмірі немесе өнім", "Order number or product"],
    "Показать": ["Көрсету", "Show"],
    "Создан": ["Құрылды", "Created"],
    "Запущен": ["Іске қосылды", "Started"],
    "Завершён": ["Аяқталды", "Completed"],
    "Выполнение": ["Орындалуы", "Progress"],
    "Нет позиций": ["Позициялар жоқ", "No items"],
    "Заказов не найдено": ["Тапсырыстар табылмады", "No orders found"],
    "Измените параметры поиска.": ["Іздеу параметрлерін өзгертіңіз.", "Change the search filters."],
    "Укажите продукцию и количество — заказ сразу попадёт в очередь канбан-доски": ["Өнім мен санын көрсетіңіз — тапсырыс бірден канбан тақтасының кезегіне түседі", "Enter products and quantities — the order will go directly to the Kanban queue"],
    "Новый производственный заказ": ["Жаңа өндірістік тапсырыс", "New production order"],
    "Можно добавить несколько видов продукции одним заказом.": ["Бір тапсырысқа бірнеше өнім түрін қосуға болады.", "You can add several products to one order."],
    "Сразу в очередь": ["Бірден кезекке", "Directly to queue"],
    "Количество в заказе": ["Тапсырыстағы саны", "Order quantity"],
    "Создать и отправить в очередь": ["Құрып, кезекке жіберу", "Create and send to queue"],
    "Последние производственные заказы": ["Соңғы өндірістік тапсырыстар", "Recent production orders"],
    "«Готово» обновляется по завершённым партиям.": ["«Дайын» аяқталған партиялар бойынша жаңартылады.", "Ready is updated from completed batches."],
    "Открыть канбан": ["Канбанды ашу", "Open Kanban"],
    "Заказ / время": ["Тапсырыс / уақыт", "Order / time"],
    "Заказано": ["Тапсырыс берілді", "Ordered"],
    "В очереди": ["Кезекте", "Queued"],
    "Производственных заказов пока нет.": ["Өндірістік тапсырыстар әзірге жоқ.", "No production orders yet."],
    "Выбрать": ["Таңдау", "Select"],
    "В канбан": ["Канбанға", "To Kanban"],
    "Отправить выбранное в очередь": ["Таңдалғандарды кезекке жіберу", "Send selected to queue"],
    "Уже в канбан": ["Канбанда бар", "Already in Kanban"],
    "Новая партия": ["Жаңа партия", "New batch"],
    "Количество в канбан": ["Канбандағы саны", "Kanban quantity"],
    "Добавить заказ": ["Тапсырыс қосу", "Add order"],
    "Прогноз на неделю": ["Апталық болжам", "Weekly forecast"],
    "Заказы": ["Тапсырыстар", "Orders"],
    "Производственные партии": ["Өндірістік партиялар", "Production batches"],
    "Голосовые сообщения": ["Дауыстық хабарламалар", "Voice messages"],
    "Продукты": ["Өнімдер", "Products"],
    "Рецептуры": ["Рецептуралар", "Recipes"],
    "Ингредиенты": ["Ингредиенттер", "Ingredients"],
    "Проблемы": ["Мәселелер", "Problems"],
    "Отчёты": ["Есептер", "Reports"],
    "Журнал действий": ["Әрекеттер журналы", "Activity log"],
    "Уведомления": ["Хабарландырулар", "Notifications"],
    "Настройки": ["Баптаулар", "Settings"],
    "Пользователи": ["Пайдаланушылар", "Users"],
    "Администрирование": ["Әкімшілендіру", "Administration"],
    "Выйти": ["Шығу", "Sign out"],
    "Войти": ["Кіру", "Sign in"],
    "Вход в QMS": ["QMS жүйесіне кіру", "Sign in to QMS"],
    "Логин": ["Логин", "Username"],
    "Пароль": ["Құпиясөз", "Password"],
    "Личные данные": ["Жеке деректер", "Personal details"],
    "Общая информация": ["Жалпы ақпарат", "General information"],
    "Разделы настроек": ["Баптау бөлімдері", "Settings sections"],
    "Изменить пароль": ["Құпиясөзді өзгерту", "Change password"],
    "Роль": ["Рөл", "Role"],
    "Подразделение": ["Бөлімше", "Department"],
    "Сохранить": ["Сақтау", "Save"],
    "Сохранить черновик": ["Жобаны сақтау", "Save draft"],
    "Сохранить количество": ["Санды сақтау", "Save quantity"],
    "Сохранить этапы": ["Кезеңдерді сақтау", "Save stages"],
    "Создать": ["Құру", "Create"],
    "Добавить": ["Қосу", "Add"],
    "+ Добавить строку": ["+ Жол қосу", "+ Add row"],
    "Изменить": ["Өзгерту", "Edit"],
    "Редактировать": ["Өңдеу", "Edit"],
    "Удалить": ["Жою", "Delete"],
    "Удалить заказ": ["Тапсырысты жою", "Delete order"],
    "Убрать": ["Алып тастау", "Remove"],
    "Отмена": ["Бас тарту", "Cancel"],
    "Закрыть": ["Жабу", "Close"],
    "Открыть": ["Ашу", "Open"],
    "Обновить": ["Жаңарту", "Refresh"],
    "Применить": ["Қолдану", "Apply"],
    "Фильтр": ["Сүзгі", "Filter"],
    "Поиск": ["Іздеу", "Search"],
    "Общий поиск": ["Жалпы іздеу", "Global search"],
    "Поиск в колонке": ["Бағаннан іздеу", "Search column"],
    "Найти": ["Табу", "Find"],
    "Все": ["Барлығы", "All"],
    "Все статусы": ["Барлық күйлер", "All statuses"],
    "Все продукты": ["Барлық өнімдер", "All products"],
    "Все категории": ["Барлық санаттар", "All categories"],
    "Все единицы": ["Барлық бірліктер", "All units"],
    "Все заказы": ["Барлық тапсырыстар", "All orders"],
    "Все партии": ["Барлық партиялар", "All batches"],
    "Все типы": ["Барлық түрлер", "All types"],
    "Любая активность": ["Кез келген әрекет", "Any activity"],
    "Новый заказ": ["Жаңа тапсырыс", "New order"],
    "Новый продукт": ["Жаңа өнім", "New product"],
    "Новый ингредиент": ["Жаңа ингредиент", "New ingredient"],
    "Новая рецептура": ["Жаңа рецептура", "New recipe"],
    "Новый объект": ["Жаңа нысан", "New object"],
    "Создать заказ": ["Тапсырыс құру", "Create order"],
    "Создать объект": ["Нысан құру", "Create object"],
    "Создать несоответствие": ["Сәйкессіздік құру", "Create nonconformity"],
    "Добавить товар": ["Тауар қосу", "Add item"],
    "Добавить ингредиент": ["Ингредиент қосу", "Add ingredient"],
    "Продукт": ["Өнім", "Product"],
    "Продукция": ["Өнім", "Product"],
    "Ингредиент": ["Ингредиент", "Ingredient"],
    "Рецептура": ["Рецептура", "Recipe"],
    "Заказ": ["Тапсырыс", "Order"],
    "Партия": ["Партия", "Batch"],
    "Объект": ["Нысан", "Object"],
    "Задания": ["Тапсырмалар", "Tasks"],
    "Документ": ["Құжат", "Document"],
    "Данные": ["Деректер", "Data"],
    "Название": ["Атауы", "Name"],
    "Наименование": ["Атауы", "Name"],
    "Код": ["Код", "Code"],
    "Номер": ["Нөмір", "Number"],
    "Категория": ["Санат", "Category"],
    "Тип": ["Түрі", "Type"],
    "Статус": ["Күйі", "Status"],
    "Количество": ["Саны", "Quantity"],
    "Количество заказа": ["Тапсырыс саны", "Order quantity"],
    "Единица": ["Бірлік", "Unit"],
    "Единица выхода": ["Шығым бірлігі", "Output unit"],
    "Ед.": ["Бірл.", "Unit"],
    "Версия": ["Нұсқа", "Version"],
    "Выход": ["Шығым", "Output"],
    "Описание": ["Сипаттама", "Description"],
    "Изображение": ["Сурет", "Image"],
    "Вес 1 шт.": ["1 дана салмағы", "Weight per item"],
    "Срок годности, часов": ["Жарамдылық мерзімі, сағат", "Shelf life, hours"],
    "Температура выпечки": ["Пісіру температурасы", "Baking temperature"],
    "Выпечка, мин": ["Пісіру, мин", "Baking, min"],
    "Расстойка, мин": ["Толықсыту, мин", "Proofing, min"],
    "Замес, мин": ["Илеу, мин", "Mixing, min"],
    "Текущий запас": ["Ағымдағы қор", "Current stock"],
    "Цена за ед.": ["Бірлік бағасы", "Cost per unit"],
    "Активен": ["Белсенді", "Active"],
    "Активна": ["Белсенді", "Active"],
    "Примечание": ["Ескертпе", "Note"],
    "Комментарий": ["Түсініктеме", "Comment"],
    "Ответственный": ["Жауапты", "Assignee"],
    "Исполнитель": ["Орындаушы", "Assignee"],
    "Пользователь": ["Пайдаланушы", "User"],
    "Автор": ["Автор", "Author"],
    "Кто": ["Кім", "Who"],
    "Когда": ["Қашан", "When"],
    "Дата": ["Күні", "Date"],
    "Начало": ["Басталуы", "Start"],
    "Длительность": ["Ұзақтығы", "Duration"],
    "Минут": ["Минут", "Minutes"],
    "Действие": ["Әрекет", "Action"],
    "Действия": ["Әрекеттер", "Actions"],
    "История": ["Тарих", "History"],
    "История изменений": ["Өзгерістер тарихы", "Change history"],
    "История статусов": ["Күйлер тарихы", "Status history"],
    "История этапов": ["Кезеңдер тарихы", "Stage history"],
    "История пока пуста.": ["Тарих әзірше бос.", "History is empty."],
    "История пуста.": ["Тарих бос.", "History is empty."],
    "Записей пока нет.": ["Әзірше жазба жоқ.", "No records yet."],
    "Заказов нет.": ["Тапсырыс жоқ.", "No orders."],
    "Партий нет.": ["Партия жоқ.", "No batches."],
    "Пусто": ["Бос", "Empty"],
    "Страница": ["Бет", "Page"],
    "Страница из": ["Бет, барлығы", "Page of"],
    "Назад": ["Артқа", "Back"],
    "← Назад": ["← Артқа", "← Back"],
    "Вперёд": ["Алға", "Next"],
    "Дальше →": ["Келесі →", "Next →"],
    "Предыдущий день": ["Алдыңғы күн", "Previous day"],
    "Следующий день": ["Келесі күн", "Next day"],
    "Неделя назад": ["Алдыңғы апта", "Previous week"],
    "Неделя вперёд": ["Келесі апта", "Next week"],
    "Рассчитать": ["Есептеу", "Calculate"],
    "Итог": ["Қорытынды", "Total"],
    "Итого": ["Барлығы", "Total"],
    "Итого в день": ["Күндік жиынтық", "Daily total"],
    "План": ["Жоспар", "Plan"],
    "Факт": ["Нақты", "Actual"],
    "Остаток": ["Қалдық", "Balance"],
    "Минимум": ["Минимум", "Minimum"],
    "Поставщик": ["Жеткізуші", "Supplier"],
    "Срок": ["Мерзім", "Due date"],
    "Срок годности": ["Жарамдылық мерзімі", "Shelf life"],
    "Истекает": ["Мерзімі аяқталады", "Expires"],
    "Поступило": ["Келіп түсті", "Received"],
    "Место": ["Орын", "Location"],
    "Готовая продукция": ["Дайын өнім", "Finished goods"],
    "Складские записи": ["Қойма жазбалары", "Stock records"],
    "Новые заказы": ["Жаңа тапсырыстар", "New orders"],
    "Партий сейчас": ["Қазіргі партиялар", "Current batches"],
    "Готово сегодня": ["Бүгін дайын", "Completed today"],
    "Открытые НС": ["Ашық сәйкессіздіктер", "Open nonconformities"],
    "Открытые": ["Ашық", "Open"],
    "Закрытые": ["Жабық", "Closed"],
    "Активные": ["Белсенді", "Active"],
    "Завершённые": ["Аяқталған", "Completed"],
    "Новые": ["Жаңа", "New"],
    "Просроченные": ["Мерзімі өткен", "Overdue"],
    "Просрочено": ["Мерзімі өткен", "Overdue"],
    "В работе": ["Жұмыста", "In progress"],
    "Ожидание": ["Күтуде", "Waiting"],
    "Требует внимания": ["Назар аударуды қажет етеді", "Needs attention"],
    "Проблемные партии": ["Мәселелі партиялар", "Problem batches"],
    "Проблемные этапы": ["Мәселелі кезеңдер", "Problem stages"],
    "Критические дефекты": ["Сындарлы ақаулар", "Critical defects"],
    "Последние проблемы": ["Соңғы мәселелер", "Recent problems"],
    "Последние несоответствия": ["Соңғы сәйкессіздіктер", "Recent nonconformities"],
    "Проблем нет.": ["Мәселе жоқ.", "No problems."],
    "Дефект": ["Ақау", "Defect"],
    "Дефекты": ["Ақаулар", "Defects"],
    "Критичность": ["Маңыздылығы", "Severity"],
    "Описание дефекта": ["Ақау сипаттамасы", "Defect description"],
    "Корректирующие действия": ["Түзету әрекеттері", "Corrective actions"],
    "План действий": ["Әрекет жоспары", "Action plan"],
    "Повторный контроль": ["Қайта бақылау", "Reinspection"],
    "Начать контроль": ["Бақылауды бастау", "Start inspection"],
    "Завершить контроль": ["Бақылауды аяқтау", "Complete inspection"],
    "Результат": ["Нәтиже", "Result"],
    "Параметр": ["Параметр", "Parameter"],
    "Номинал": ["Номинал", "Nominal"],
    "Нижний": ["Төменгі", "Lower"],
    "Верхний": ["Жоғарғы", "Upper"],
    "Отклонение": ["Ауытқу", "Deviation"],
    "Объекты": ["Нысандар", "Objects"],
    "Карточка объекта": ["Нысан картасы", "Object card"],
    "Маршрут": ["Бағыт", "Route"],
    "Пост": ["Бекет", "Post"],
    "Связанные задания": ["Байланысты тапсырмалар", "Related tasks"],
    "Контролёр": ["Бақылаушы", "Inspector"],
    "Фото": ["Фото", "Photo"],
    "Аудио": ["Аудио", "Audio"],
    "Вложения": ["Тіркемелер", "Attachments"],
    "Фото или документ": ["Фото немесе құжат", "Photo or document"],
    "Тип файла": ["Файл түрі", "File type"],
    "Скачать": ["Жүктеп алу", "Download"],
    "Скачать CSV": ["CSV жүктеу", "Download CSV"],
    "Скачать Excel": ["Excel жүктеу", "Download Excel"],
    "Скачать PDF": ["PDF жүктеу", "Download PDF"],
    "Печать": ["Басып шығару", "Print"],
    "Предварительный просмотр": ["Алдын ала қарау", "Preview"],
    "Аналитика процессов": ["Процестер аналитикасы", "Process analytics"],
    "Карта процесса": ["Процесс картасы", "Process map"],
    "Диаграмма": ["Диаграмма", "Chart"],
    "Событий": ["Оқиғалар", "Events"],
    "Последние экспорты": ["Соңғы экспорттар", "Recent exports"],
    "Экспортов пока нет.": ["Әзірше экспорт жоқ.", "No exports yet."],
    "Отправить сейчас": ["Қазір жіберу", "Send now"],
    "Повторить ошибки": ["Қателерді қайталау", "Retry failures"],
    "Проверить соединение": ["Қосылымды тексеру", "Test connection"],
    "Открыть консоль →": ["Консольді ашу →", "Open console →"],
    "Последняя ошибка": ["Соңғы қате", "Last error"],
    "Последний ответ": ["Соңғы жауап", "Last response"],
    "Ошибка": ["Қате", "Error"],
    "Команда": ["Пәрмен", "Command"],
    "Текст": ["Мәтін", "Text"],
    "Уверенность": ["Сенімділік", "Confidence"],
    "Подтвердить": ["Растау", "Confirm"],
    "Подтвердить и создать партии": ["Растап, партиялар құру", "Confirm and create batches"],
    "Возобновить": ["Жалғастыру", "Resume"],
    "Остановить": ["Тоқтату", "Stop"],
    "Сбросить": ["Қалпына келтіру", "Reset"],
    "Передать": ["Жіберу", "Move to"],
    "Следующий этап": ["Келесі кезең", "Next stage"],
    "Текущий этап": ["Ағымдағы кезең", "Current stage"],
    "Этап": ["Кезең", "Stage"],
    "Этапы": ["Кезеңдер", "Stages"],
    "Этапы производства": ["Өндіріс кезеңдері", "Production stages"],
    "Откуда": ["Қайдан", "From"],
    "Куда": ["Қайда", "To"],
    "Причина возврата": ["Қайтару себебі", "Return reason"],
    "Есть блокирующая проблема": ["Бұғаттайтын мәселе бар", "Blocking problem exists"],
    "Демонстрационная партия": ["Демо партия", "Demo batch"],
    "Товары и расчёт ингредиентов": ["Тауарлар және ингредиенттер есебі", "Items and ingredient calculation"],
    "Нет активной рецептуры.": ["Белсенді рецептура жоқ.", "No active recipe."],
    "Рецептура ещё не создана.": ["Рецептура әлі құрылмаған.", "Recipe has not been created yet."],
    "На партию": ["Партияға", "Per batch"],
    "На 1 штуку": ["1 данаға", "Per item"],
    "Порядок": ["Реті", "Order"],
    "Включён": ["Қосулы", "Enabled"],
    "Отключённые": ["Өшірілген", "Disabled"],
    "Зарегистрировать": ["Тіркеу", "Register"],
    "Серийный": ["Сериялық нөмір", "Serial number"],
    "СИ": ["ӨҚ", "Measuring equipment"],
    "Следующая поверка": ["Келесі тексеру", "Next verification"],
    "Изготовитель": ["Өндіруші", "Manufacturer"],
    "Модель": ["Модель", "Model"],
    "Инвентарный номер": ["Түгендеу нөмірі", "Inventory number"],
    "Диапазон измерений": ["Өлшеу ауқымы", "Measurement range"],
    "Класс точности": ["Дәлдік класы", "Accuracy class"],
    "Последняя поверка": ["Соңғы тексеру", "Last verification"],
    "Организация поверки": ["Тексеру ұйымы", "Verification organization"],
    "На эту дату заказов нет.": ["Бұл күнге тапсырыс жоқ.", "There are no orders for this date."],
    "По выбранным фильтрам данные не найдены": ["Таңдалған сүзгілер бойынша дерек табылмады", "No data found for the selected filters"],
    "Уведомлений нет.": ["Хабарландыру жоқ.", "No notifications."],
    "Отметить прочитанным": ["Оқылды деп белгілеу", "Mark as read"],
    "Доступ к этому разделу закрыт для вашей роли.": ["Сіздің рөліңіз үшін бұл бөлімге қолжетімділік жабық.", "Your role does not have access to this section."],
    "Если он нужен для работы — права меняет администратор.": ["Жұмыс үшін қажет болса, құқықтарды әкімші өзгертеді.", "If you need it for work, ask an administrator to change your access."],
    "Открыть меню": ["Мәзірді ашу", "Open menu"],
    "Показать меню": ["Мәзірді көрсету", "Show menu"],
    "Свернуть меню": ["Мәзірді жию", "Collapse menu"],
    "Язык интерфейса": ["Интерфейс тілі", "Interface language"],
    "черновик": ["жоба", "draft"],
    "подтверждён": ["расталған", "confirmed"],
    "в очереди": ["кезекте", "queued"],
    "в производстве": ["өндірісте", "in production"],
    "готов": ["дайын", "ready"],
    "отгружен": ["жөнелтілген", "shipped"],
    "отменён": ["болдырылмаған", "cancelled"],
    "низкий": ["төмен", "low"],
    "обычный": ["қалыпты", "normal"],
    "высокий": ["жоғары", "high"],
    "срочный": ["шұғыл", "urgent"],
    "Обязательное поле.": ["Міндетті өріс.", "This field is required."],
    "Введите правильное значение.": ["Дұрыс мән енгізіңіз.", "Enter a valid value."],
    "Выберите продукт": ["Өнімді таңдаңыз", "Select a product"],
    "Выберите": ["Таңдаңыз", "Select"],
    "Заказ сохранён.": ["Тапсырыс сақталды.", "Order saved."],
    "Заказ с продуктами создан.": ["Өнімдері бар тапсырыс құрылды.", "Order with products created."],
    "Заказ создан и отправлен в очередь производства.": ["Тапсырыс құрылып, өндіріс кезегіне жіберілді.", "Order created and sent to the production queue."],
    "Укажите количество новой партии для канбана.": ["Канбан үшін жаңа партия санын көрсетіңіз.", "Enter the new batch quantity for Kanban."],
    "Количество новой партии должно быть больше нуля.": ["Жаңа партия саны нөлден көп болуы керек.", "The new batch quantity must be greater than zero."],
    "Позиция добавлена.": ["Позиция қосылды.", "Item added."],
    "Продукт сохранён.": ["Өнім сақталды.", "Product saved."],
    "Ингредиент сохранён.": ["Ингредиент сақталды.", "Ingredient saved."],
    "Рецептура сохранена.": ["Рецептура сақталды.", "Recipe saved."]
  };

  const translationsLower = new Map(
    Object.entries(translations).map(([key, value]) => [key.toLocaleLowerCase("ru"), value])
  );

  const originalText = new WeakMap();
  const originalAttrs = new WeakMap();
  let currentLanguage = "ru";
  let applying = false;
  const originalDocumentTitle = document.title;

  function selectedTranslation(source, language) {
    if (language === "ru") return source;
    const index = language === "kk" ? 0 : 1;
    const normalized = source.replace(/\s+/g, " ").trim();
    if (!normalized) return source;

    let key = normalized;
    let colon = "";
    if (key.endsWith(":")) {
      key = key.slice(0, -1).trim();
      colon = ":";
    }
    let values = translations[key];
    if (!values) {
      values = translationsLower.get(key.toLocaleLowerCase("ru"));
      if (values && key[0] === key[0].toLocaleLowerCase("ru")) {
        values = values.map(value => value ? value[0].toLocaleLowerCase(currentLanguage) + value.slice(1) : value);
      }
    }
    if (values) return values[index] + colon;

    const patterns = [
      [/^Заказ №\s*(.+)$/, ["Тапсырыс №$1", "Order #$1"]],
      [/^Партия:\s*(.+)$/, ["Партия: $1", "Batch: $1"]],
      [/^План:\s*(.+)$/, ["Жоспар: $1", "Plan: $1"]],
      [/^Вернуть на этап «(.+)»$/, ["«$1» кезеңіне қайтару", "Return to stage “$1”"]],
      [/^Этап (.+) включён$/, ["$1 кезеңі қосылды", "Stage $1 enabled"]],
      [/^Создано:\s*(.+)$/, ["Құрылды: $1", "Created: $1"]],
      [/^Страница (\d+) из (\d+)$/, ["$1 / $2 бет", "Page $1 of $2"]],
      [/^Удалить заказ №(.+)\? Это действие нельзя отменить\.$/, ["№$1 тапсырысын жою керек пе? Бұл әрекетті болдырмау мүмкін емес.", "Delete order #$1? This action cannot be undone."]],
      [/^Заказ №(.+) удалён\.$/, ["№$1 тапсырысы жойылды.", "Order #$1 deleted."]],
      [/^Заказ №(.+) создан: (.+) позиций отправлено в очередь\.$/, ["№$1 тапсырысы құрылды: $2 позиция кезекке жіберілді.", "Order #$1 created: $2 items sent to queue."]],
      [/^Сохранено позиций: (.+)\.$/, ["Сақталған позициялар: $1.", "Items saved: $1."]],
      [/^Количество в канбан: (.+)$/, ["Канбандағы саны: $1", "Kanban quantity: $1"]]
    ];
    for (const [pattern, values] of patterns) {
      if (pattern.test(normalized)) return normalized.replace(pattern, values[index]);
    }
    return source;
  }

  function translateTextNode(node) {
    if (!originalText.has(node)) originalText.set(node, node.nodeValue);
    const source = originalText.get(node);
    const trimmed = source.trim();
    if (!trimmed) return;
    const translated = selectedTranslation(trimmed, currentLanguage);
    node.nodeValue = source.replace(trimmed, translated);
  }

  function translateAttributes(element) {
    const names = ["placeholder", "title", "aria-label"];
    if (!originalAttrs.has(element)) originalAttrs.set(element, {});
    const originals = originalAttrs.get(element);
    for (const name of names) {
      if (element.hasAttribute(name) && !(name in originals)) originals[name] = element.getAttribute(name);
      if (name in originals) element.setAttribute(name, selectedTranslation(originals[name], currentLanguage));
    }
  }

  function translateTree(root) {
    if (!root) return;
    applying = true;
    try {
      if (root.nodeType === Node.TEXT_NODE) translateTextNode(root);
      if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          const parent = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
          if (!parent || parent.closest("script, style, template, [data-i18n-skip]")) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      });
      let node;
      while ((node = walker.nextNode())) {
        if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
        else translateAttributes(node);
      }
    } finally {
      applying = false;
    }
  }

  function setLanguage(language) {
    currentLanguage = SUPPORTED.has(language) ? language : "ru";
    localStorage.setItem(STORAGE_KEY, currentLanguage);
    document.documentElement.lang = currentLanguage;
    document.title = selectedTranslation(originalDocumentTitle, currentLanguage);
    document.querySelectorAll("[data-ui-language]").forEach(select => { select.value = currentLanguage; });
    translateTree(document.body);
    document.dispatchEvent(new CustomEvent("qms:languagechange", { detail: { language: currentLanguage } }));
  }

  window.qmsTranslate = function (source) {
    return selectedTranslation(String(source), currentLanguage);
  };

  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);
  window.confirm = message => nativeConfirm(window.qmsTranslate(message));
  window.alert = message => nativeAlert(window.qmsTranslate(message));

  document.addEventListener("DOMContentLoaded", function () {
    const saved = localStorage.getItem(STORAGE_KEY);
    const browserLanguage = (navigator.language || "ru").toLowerCase().startsWith("kk") ? "kk" : "ru";
    currentLanguage = SUPPORTED.has(saved) ? saved : browserLanguage;
    document.querySelectorAll("[data-ui-language]").forEach(select => {
      select.value = currentLanguage;
      select.addEventListener("change", event => setLanguage(event.target.value));
    });
    setLanguage(currentLanguage);

    new MutationObserver(mutations => {
      if (applying) return;
      for (const mutation of mutations) {
        mutation.addedNodes.forEach(translateTree);
      }
    }).observe(document.body, { childList: true, subtree: true });
  });
})();
