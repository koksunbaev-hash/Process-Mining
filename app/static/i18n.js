/* Translations for the Process Mining console.
 *
 * Markup drives translation through `data-i18n` attributes, so adding a string
 * means adding one key here and one attribute in index.html - there is no
 * id-to-key map to keep in sync (the previous version had one, and it silently
 * broke every time an element was renamed).
 *
 * Variants: `data-i18n` sets textContent, `data-i18n-placeholder`,
 * `data-i18n-title` and `data-i18n-aria` set the matching attribute.
 */
(function (global) {
  "use strict";

  const STRINGS = {
    en: {
      "meta.locale": "en-US",
      "meta.title": "Process Mining Console",

      "brand.name": "Process Mining",
      "status.checking": "Checking service…",
      "status.online": "Service ready",
      "status.auth": "API key required",
      "status.offline": "Service unreachable",
      "status.nographviz": "Graphviz missing",
      "apikey.placeholder": "API key",
      "apikey.title": "Sent as X-API-Key. Stored in this browser only.",
      "language.title": "Interface language",
      "theme.title": "Toggle light / dark",

      "hero.eyebrow": "Event log analytics",
      "hero.title": "See the process clearly.",
      "hero.lead":
        "Upload an event log and pm4py reveals the real path, the pauses, and the steps worth fixing.",

      "upload.title": "Event log",
      "upload.drop": "Drop a file here or click to browse",
      "upload.hint": "CSV, TSV, XES(.gz), JSON or JSONL · up to 64 MB",
      "upload.sample": "Try sample log",
      "upload.remove": "Remove",
      "upload.reading": "Reading file…",

      "controls.title": "Analysis",
      "controls.algorithm": "Algorithm",
      "controls.direction": "Layout",
      "controls.profile": "Activity profile",
      "controls.profileAuto": "Auto (default)",
      "controls.noise": "Noise filter",
      "controls.noiseHint": "Drops rare behaviour. Only affects inductive / heuristics miners.",
      "controls.coverage": "Variant coverage",
      "controls.coverageHint": "Keep only the top variants covering this share of cases.",
      "controls.coverageAll": "All variants",
      "controls.advanced": "Advanced options",

      "algo.dfg_frequency": "Directly-follows · frequency",
      "algo.dfg_performance": "Directly-follows · performance",
      "algo.petri_net_inductive": "Petri net · inductive",
      "algo.petri_net_heuristics": "Petri net · heuristics",
      "algo.process_tree": "Process tree",
      "algo.bpmn": "BPMN",

      "dir.LR": "Left to right",
      "dir.TB": "Top to bottom",

      "actions.run": "Run analysis",
      "actions.running": "Analysing…",
      "actions.clear": "Reset",

      "tabs.map": "Process map",
      "tabs.variants": "Variants",
      "tabs.bottlenecks": "Bottlenecks",
      "tabs.activities": "Activities",

      "map.empty.title": "Your process map will appear here",
      "map.empty.text": "Pick an event log, then run the analysis.",
      "map.search": "Find activity…",
      "map.zoomIn": "Zoom in",
      "map.zoomOut": "Zoom out",
      "map.reset": "Actual size",
      "map.fit": "Fit to screen",
      "map.fullscreen": "Fullscreen",
      "map.downloadSvg": "Download SVG",
      "map.downloadPng": "Download PNG",
      "map.hint": "Scroll to zoom · drag to pan · double-click to fit",
      "map.matches": "{n} match(es)",
      "map.noMatches": "No match",

      "unit.s": "s",
      "unit.min": "min",
      "unit.h": "h",
      "unit.d": "d",

      "metrics.events": "Events",
      "metrics.cases": "Cases",
      "metrics.activities": "Activities",
      "metrics.variants": "Variants",
      "metrics.cycle": "Median cycle",
      "metrics.rework": "Rework",
      "metrics.waiting": "Waiting for data",
      "metrics.instances": "Process instances",
      "metrics.distinct": "Distinct steps",
      "metrics.paths": "Distinct paths",
      "metrics.p95": "p95: {v}",
      "metrics.repeated": "Cases with a repeated step",
      "metrics.span": "{from} → {to}",

      "variants.rank": "#",
      "variants.sequence": "Path",
      "variants.cases": "Cases",
      "variants.share": "Share",
      "variants.median": "Median",
      "variants.mean": "Mean",
      "variants.empty": "No variants yet.",

      "bottlenecks.transition": "Transition",
      "bottlenecks.occurrences": "Count",
      "bottlenecks.median": "Median wait",
      "bottlenecks.p95": "p95",
      "bottlenecks.total": "Total time",
      "bottlenecks.share": "Share of time",
      "bottlenecks.empty": "No bottlenecks yet.",
      "bottlenecks.reworkTitle": "Repeated activities",
      "bottlenecks.reworkActivity": "Activity",
      "bottlenecks.reworkCases": "Cases",
      "bottlenecks.reworkTotal": "Repetitions",

      "activities.activity": "Activity",
      "activities.occurrences": "Events",
      "activities.cases": "Cases",
      "activities.share": "Share of events",
      "activities.wait": "Avg wait after",
      "activities.empty": "No activities yet.",

      "warnings.title": "Import notes",
      "detected.title": "Detected columns",

      "error.noFile": "Choose an event log first.",
      "error.tooLarge": "File is larger than {mb} MB.",
      "error.badType": "Unsupported file type. Use CSV, TSV, XES(.gz), JSON or JSONL.",
      "error.network": "Cannot reach the service. Is it running on this host?",
      "error.auth": "The service requires an API key. Enter it in the top-right field.",
      "error.noImage": "The service returned no image. Check that Graphviz is installed.",
      "error.generic": "Analysis failed",

      "toast.ready": "Analysis ready",
      "toast.cleared": "Cleared",
      "toast.copied": "Copied",
      "toast.downloaded": "Downloaded",
      "toast.sample": "Sample log loaded",

      "glossary.title": "Read the numbers.",
      "glossary.p95.term": "p95",
      "glossary.p95.text":
        "95% of cases finish within this time. The slowest 5% take longer.",
      "glossary.share.term": "Share of time",
      "glossary.share.text":
        "The percentage of total process time consumed by a single transition.",
      "glossary.rework.term": "Rework",
      "glossary.rework.text":
        "An activity repeated inside the same case - often a signal of defects or waiting.",
      "glossary.variant.term": "Variant",
      "glossary.variant.text":
        "One distinct end-to-end path through the process. Few variants means a disciplined process.",

      "footer.docs": "API docs",
      "footer.health": "Health",
    },

    ru: {
      "meta.locale": "ru-RU",
      "meta.title": "Process Mining — консоль",

      "brand.name": "Process Mining",
      "status.checking": "Проверка сервиса…",
      "status.online": "Сервис готов",
      "status.auth": "Нужен API-ключ",
      "status.offline": "Сервис недоступен",
      "status.nographviz": "Нет Graphviz",
      "apikey.placeholder": "API-ключ",
      "apikey.title": "Отправляется как X-API-Key. Хранится только в этом браузере.",
      "language.title": "Язык интерфейса",
      "theme.title": "Светлая / тёмная тема",

      "hero.eyebrow": "Аналитика журналов событий",
      "hero.title": "Увидьте процесс целиком.",
      "hero.lead":
        "Загрузите журнал событий — pm4py покажет реальный маршрут, паузы и шаги, которые стоит исправить.",

      "upload.title": "Журнал событий",
      "upload.drop": "Перетащите файл сюда или нажмите для выбора",
      "upload.hint": "CSV, TSV, XES(.gz), JSON или JSONL · до 64 МБ",
      "upload.sample": "Взять пример",
      "upload.remove": "Убрать",
      "upload.reading": "Чтение файла…",

      "controls.title": "Анализ",
      "controls.algorithm": "Алгоритм",
      "controls.direction": "Раскладка",
      "controls.profile": "Профиль активностей",
      "controls.profileAuto": "Авто (по умолчанию)",
      "controls.noise": "Фильтр шума",
      "controls.noiseHint": "Убирает редкое поведение. Работает для inductive / heuristics.",
      "controls.coverage": "Покрытие вариантов",
      "controls.coverageHint": "Оставить только топ-варианты, покрывающие эту долю кейсов.",
      "controls.coverageAll": "Все варианты",
      "controls.advanced": "Дополнительно",

      "algo.dfg_frequency": "Directly-follows · частота",
      "algo.dfg_performance": "Directly-follows · время",
      "algo.petri_net_inductive": "Сеть Петри · inductive",
      "algo.petri_net_heuristics": "Сеть Петри · heuristics",
      "algo.process_tree": "Дерево процесса",
      "algo.bpmn": "BPMN",

      "dir.LR": "Слева направо",
      "dir.TB": "Сверху вниз",

      "actions.run": "Запустить анализ",
      "actions.running": "Анализ…",
      "actions.clear": "Сбросить",

      "tabs.map": "Карта процесса",
      "tabs.variants": "Варианты",
      "tabs.bottlenecks": "Узкие места",
      "tabs.activities": "Активности",

      "map.empty.title": "Здесь появится карта процесса",
      "map.empty.text": "Выберите журнал событий и запустите анализ.",
      "map.search": "Найти активность…",
      "map.zoomIn": "Приблизить",
      "map.zoomOut": "Отдалить",
      "map.reset": "Реальный размер",
      "map.fit": "Вписать в экран",
      "map.fullscreen": "Во весь экран",
      "map.downloadSvg": "Скачать SVG",
      "map.downloadPng": "Скачать PNG",
      "map.hint": "Колесо — масштаб · перетаскивание — сдвиг · двойной клик — вписать",
      "map.matches": "Совпадений: {n}",
      "map.noMatches": "Не найдено",

      "unit.s": "с",
      "unit.min": "мин",
      "unit.h": "ч",
      "unit.d": "дн",

      "metrics.events": "События",
      "metrics.cases": "Кейсы",
      "metrics.activities": "Активности",
      "metrics.variants": "Варианты",
      "metrics.cycle": "Медианный цикл",
      "metrics.rework": "Переделки",
      "metrics.waiting": "Нет данных",
      "metrics.instances": "Экземпляры процесса",
      "metrics.distinct": "Уникальных шагов",
      "metrics.paths": "Уникальных маршрутов",
      "metrics.p95": "p95: {v}",
      "metrics.repeated": "Кейсы с повтором шага",
      "metrics.span": "{from} → {to}",

      "variants.rank": "#",
      "variants.sequence": "Маршрут",
      "variants.cases": "Кейсы",
      "variants.share": "Доля",
      "variants.median": "Медиана",
      "variants.mean": "Среднее",
      "variants.empty": "Вариантов пока нет.",

      "bottlenecks.transition": "Переход",
      "bottlenecks.occurrences": "Кол-во",
      "bottlenecks.median": "Медианное ожидание",
      "bottlenecks.p95": "p95",
      "bottlenecks.total": "Суммарное время",
      "bottlenecks.share": "Доля времени",
      "bottlenecks.empty": "Узких мест пока нет.",
      "bottlenecks.reworkTitle": "Повторяющиеся активности",
      "bottlenecks.reworkActivity": "Активность",
      "bottlenecks.reworkCases": "Кейсы",
      "bottlenecks.reworkTotal": "Повторов",

      "activities.activity": "Активность",
      "activities.occurrences": "События",
      "activities.cases": "Кейсы",
      "activities.share": "Доля событий",
      "activities.wait": "Ожидание после",
      "activities.empty": "Активностей пока нет.",

      "warnings.title": "Замечания при импорте",
      "detected.title": "Распознанные колонки",

      "error.noFile": "Сначала выберите журнал событий.",
      "error.tooLarge": "Файл больше {mb} МБ.",
      "error.badType": "Неподдерживаемый тип файла. Используйте CSV, TSV, XES(.gz), JSON или JSONL.",
      "error.network": "Сервис недоступен. Он запущен на этом хосте?",
      "error.auth": "Сервис требует API-ключ. Введите его в поле справа сверху.",
      "error.noImage": "Сервис не вернул изображение. Проверьте, установлен ли Graphviz.",
      "error.generic": "Анализ не выполнен",

      "toast.ready": "Анализ готов",
      "toast.cleared": "Очищено",
      "toast.copied": "Скопировано",
      "toast.downloaded": "Файл сохранён",
      "toast.sample": "Загружен пример журнала",

      "glossary.title": "Как читать цифры.",
      "glossary.p95.term": "p95",
      "glossary.p95.text":
        "95% кейсов укладываются в это время. Самые медленные 5% идут дольше.",
      "glossary.share.term": "Доля времени",
      "glossary.share.text":
        "Процент общего времени процесса, который съедает один переход.",
      "glossary.rework.term": "Переделка",
      "glossary.rework.text":
        "Активность повторилась внутри одного кейса — частый признак брака или ожидания.",
      "glossary.variant.term": "Вариант",
      "glossary.variant.text":
        "Один уникальный сквозной маршрут процесса. Мало вариантов — процесс дисциплинирован.",

      "footer.docs": "Документация API",
      "footer.health": "Статус",
    },

    kk: {
      "meta.locale": "kk-KZ",
      "meta.title": "Process Mining — консоль",

      "brand.name": "Process Mining",
      "status.checking": "Сервис тексерілуде…",
      "status.online": "Сервис дайын",
      "status.auth": "API-кілт қажет",
      "status.offline": "Сервис қолжетімсіз",
      "status.nographviz": "Graphviz жоқ",
      "apikey.placeholder": "API-кілт",
      "apikey.title": "X-API-Key ретінде жіберіледі. Тек осы браузерде сақталады.",
      "language.title": "Интерфейс тілі",
      "theme.title": "Жарық / қараңғы тақырып",

      "hero.eyebrow": "Оқиғалар журналының аналитикасы",
      "hero.title": "Процесті анық көріңіз.",
      "hero.lead":
        "Оқиғалар журналын жүктеңіз — pm4py нақты маршрутты, үзілістерді және түзетуге тұрарлық қадамдарды көрсетеді.",

      "upload.title": "Оқиғалар журналы",
      "upload.drop": "Файлды осында сүйреңіз немесе таңдау үшін басыңыз",
      "upload.hint": "CSV, TSV, XES(.gz), JSON немесе JSONL · 64 МБ дейін",
      "upload.sample": "Үлгіні алу",
      "upload.remove": "Алып тастау",
      "upload.reading": "Файл оқылуда…",

      "controls.title": "Талдау",
      "controls.algorithm": "Алгоритм",
      "controls.direction": "Орналасу",
      "controls.profile": "Активтілік профилі",
      "controls.profileAuto": "Авто (әдепкі)",
      "controls.noise": "Шу сүзгісі",
      "controls.noiseHint": "Сирек мінез-құлықты алып тастайды. Inductive / heuristics үшін.",
      "controls.coverage": "Варианттарды қамту",
      "controls.coverageHint": "Кейстердің осы үлесін қамтитын үздік варианттарды ғана қалдыру.",
      "controls.coverageAll": "Барлық варианттар",
      "controls.advanced": "Қосымша параметрлер",

      "algo.dfg_frequency": "Directly-follows · жиілік",
      "algo.dfg_performance": "Directly-follows · уақыт",
      "algo.petri_net_inductive": "Петри желісі · inductive",
      "algo.petri_net_heuristics": "Петри желісі · heuristics",
      "algo.process_tree": "Процесс ағашы",
      "algo.bpmn": "BPMN",

      "dir.LR": "Солдан оңға",
      "dir.TB": "Жоғарыдан төменге",

      "actions.run": "Талдауды бастау",
      "actions.running": "Талдау…",
      "actions.clear": "Тазалау",

      "tabs.map": "Процесс картасы",
      "tabs.variants": "Варианттар",
      "tabs.bottlenecks": "Тар жерлер",
      "tabs.activities": "Активтіліктер",

      "map.empty.title": "Процесс картасы осында пайда болады",
      "map.empty.text": "Журналды таңдап, талдауды іске қосыңыз.",
      "map.search": "Активтілікті табу…",
      "map.zoomIn": "Жақындату",
      "map.zoomOut": "Алыстату",
      "map.reset": "Нақты өлшем",
      "map.fit": "Экранға сыйдыру",
      "map.fullscreen": "Толық экран",
      "map.downloadSvg": "SVG жүктеу",
      "map.downloadPng": "PNG жүктеу",
      "map.hint": "Дөңгелек — масштаб · сүйреу — жылжыту · қос басу — сыйдыру",
      "map.matches": "Сәйкестік: {n}",
      "map.noMatches": "Табылмады",

      "unit.s": "с",
      "unit.min": "мин",
      "unit.h": "сағ",
      "unit.d": "күн",

      "metrics.events": "Оқиғалар",
      "metrics.cases": "Кейстер",
      "metrics.activities": "Активтіліктер",
      "metrics.variants": "Варианттар",
      "metrics.cycle": "Медианалық цикл",
      "metrics.rework": "Қайта өңдеу",
      "metrics.waiting": "Дерек жоқ",
      "metrics.instances": "Процесс даналары",
      "metrics.distinct": "Бірегей қадамдар",
      "metrics.paths": "Бірегей маршруттар",
      "metrics.p95": "p95: {v}",
      "metrics.repeated": "Қадамы қайталанған кейстер",
      "metrics.span": "{from} → {to}",

      "variants.rank": "#",
      "variants.sequence": "Маршрут",
      "variants.cases": "Кейстер",
      "variants.share": "Үлес",
      "variants.median": "Медиана",
      "variants.mean": "Орташа",
      "variants.empty": "Варианттар әзірге жоқ.",

      "bottlenecks.transition": "Өту",
      "bottlenecks.occurrences": "Саны",
      "bottlenecks.median": "Медианалық күту",
      "bottlenecks.p95": "p95",
      "bottlenecks.total": "Жалпы уақыт",
      "bottlenecks.share": "Уақыт үлесі",
      "bottlenecks.empty": "Тар жерлер әзірге жоқ.",
      "bottlenecks.reworkTitle": "Қайталанатын активтіліктер",
      "bottlenecks.reworkActivity": "Активтілік",
      "bottlenecks.reworkCases": "Кейстер",
      "bottlenecks.reworkTotal": "Қайталанулар",

      "activities.activity": "Активтілік",
      "activities.occurrences": "Оқиғалар",
      "activities.cases": "Кейстер",
      "activities.share": "Оқиға үлесі",
      "activities.wait": "Кейінгі күту",
      "activities.empty": "Активтіліктер әзірге жоқ.",

      "warnings.title": "Импорт ескертпелері",
      "detected.title": "Анықталған бағандар",

      "error.noFile": "Алдымен оқиғалар журналын таңдаңыз.",
      "error.tooLarge": "Файл {mb} МБ-тан үлкен.",
      "error.badType": "Қолдау көрсетілмейтін файл түрі. CSV, TSV, XES(.gz), JSON немесе JSONL қолданыңыз.",
      "error.network": "Сервиске қосылу мүмкін емес. Ол осы хостта іске қосылған ба?",
      "error.auth": "Сервис API-кілтті талап етеді. Оны жоғарғы оң жақтағы өріске енгізіңіз.",
      "error.noImage": "Сервис сурет қайтармады. Graphviz орнатылғанын тексеріңіз.",
      "error.generic": "Талдау орындалмады",

      "toast.ready": "Талдау дайын",
      "toast.cleared": "Тазаланды",
      "toast.copied": "Көшірілді",
      "toast.downloaded": "Файл сақталды",
      "toast.sample": "Үлгі журнал жүктелді",

      "glossary.title": "Сандарды қалай оқу керек.",
      "glossary.p95.term": "p95",
      "glossary.p95.text":
        "Кейстердің 95%-ы осы уақытта аяқталады. Ең баяу 5%-ы ұзағырақ.",
      "glossary.share.term": "Уақыт үлесі",
      "glossary.share.text":
        "Бір өту процестің жалпы уақытының қанша пайызын алатыны.",
      "glossary.rework.term": "Қайта өңдеу",
      "glossary.rework.text":
        "Бір кейс ішінде қайталанған активтілік — көбіне ақау немесе күтудің белгісі.",
      "glossary.variant.term": "Вариант",
      "glossary.variant.text":
        "Процестің бір бірегей ұштан-ұшқа маршруты. Варианттар аз болса — процесс тәртіпті.",

      "footer.docs": "API құжаттамасы",
      "footer.health": "Күйі",
    },
  };

  const FALLBACK = "en";
  const SUPPORTED = Object.keys(STRINGS);

  /** Looks a key up in `lang`, then in English, then returns the key itself. */
  function translate(lang, key, params) {
    const table = STRINGS[lang] || STRINGS[FALLBACK];
    let value = table[key];
    if (value === undefined) value = STRINGS[FALLBACK][key];
    if (value === undefined) return key;
    if (!params) return value;
    return value.replace(/\{(\w+)\}/g, (match, name) =>
      Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
    );
  }

  global.I18N = { STRINGS, SUPPORTED, FALLBACK, translate };
})(window);
