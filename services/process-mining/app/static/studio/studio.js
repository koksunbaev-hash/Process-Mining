/* Studio - вторая консоль process mining.
 *
 * Одностраничное приложение без сборки: разделы рисуются в JS, адрес держится
 * в якоре (#/cases). Сборщик сюда не затащен намеренно - консоль отдаётся тем
 * же FastAPI, что и API, и лишний шаг сборки в образе означал бы, что правку
 * стиля нельзя выкатить, не собрав фронтенд.
 *
 * Данные берутся из того же публичного API, что и первая консоль. Ничего не
 * досчитывается на сервере специально для Studio: всё, что показано ниже,
 * выводится из /statistics, /variants, /bottlenecks, /discover и страниц
 * событий. Где число получено расчётом, а не приходит из API, рядом стоит
 * пояснение - иначе оценку не отличить от факта.
 */
(function () {
  "use strict";

  // ======================================================== мелкие утилиты

  var $ = function (id) { return document.getElementById(id); };

  /* Разделитель ключа "откуда-куда". Escape-последовательностью, а не сырым
   * байтом в исходнике: сырой ноль делает файл для git бинарным, и diff по
   * нему перестаёт показываться. В названиях активностей такого символа нет. */
  var SEP = String.fromCharCode(0);

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  var store = {
    get: function (key, fallback) {
      try { var v = localStorage.getItem(key); return v === null ? fallback : v; }
      catch (e) { return fallback; }
    },
    set: function (key, value) { try { localStorage.setItem(key, value); } catch (e) { /* приватный режим */ } },
    json: function (key, fallback) {
      try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch (e) { return fallback; }
    },
  };

  // ------------------------------------------------------------ форматы

  /* Язык и формат чисел - одно и то же решение: переключивший интерфейс на
   * английский ждёт и «1,234.5» вместо «1 234,5». Поэтому отдельной
   * настройки формата больше нет, она идёт за языком. */
  var i18n = window.PMI18n;
  var t = i18n.t;
  var plural = i18n.plural;

  function num(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return Number(value).toLocaleString(i18n.locale, {
      minimumFractionDigits: digits || 0, maximumFractionDigits: digits === undefined ? 0 : digits,
    });
  }

  /* Длительность словами. Крупные единицы округляются до десятых: "2,4 ч"
   * читается быстрее, чем "2 ч 26 мин", а точность здесь всё равно оценочная. */
  function dur(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return "—";
    var s = Math.max(0, Number(seconds));
    if (s < 60) return num(s, 0) + " " + i18n.unit("s");
    if (s < 3600) return num(s / 60, 0) + " " + i18n.unit("min");
    if (s < 86400) return num(s / 3600, 1) + " " + i18n.unit("h");
    if (s < 86400 * 30) return num(s / 86400, 1) + " " + i18n.unit("d");
    return num(s / (86400 * 30), 1) + " " + i18n.unit("mo");
  }

  function pct(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return num(value * 100, digits === undefined ? 1 : digits) + " %";
  }

  function dateShort(value) {
    if (!value) return "—";
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d)) return "—";
    return d.toLocaleDateString(i18n.locale, { day: "numeric", month: "short" });
  }

  function dateTime(value) {
    if (!value) return "—";
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d)) return "—";
    return d.toLocaleString(i18n.locale, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function dayKey(date) {
    return date.toISOString().slice(0, 10);
  }

  /* Устойчивый цвет активности: одно и то же название всегда одного цвета во
   * всех разделах, иначе точки маршрутов не сравнить между строками. */
  var PALETTE = ["#7c5cff", "#3b82f6", "#22d3ee", "#34d399", "#f59e0b", "#f43f5e", "#a78bfa", "#60a5fa", "#2dd4bf", "#fb923c"];
  function activityColor(name) {
    var hash = 0;
    for (var i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    return PALETTE[hash % PALETTE.length];
  }

  function quantile(sorted, q) {
    if (!sorted.length) return null;
    var pos = (sorted.length - 1) * q;
    var base = Math.floor(pos);
    var rest = pos - base;
    if (sorted[base + 1] === undefined) return sorted[base];
    return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
  }

  // =============================================================== значки

  var ICONS = {
    overview: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8.5"/>',
    map: '<circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="7" r="2.4"/><circle cx="12" cy="17" r="2.4"/><path d="M8 8.4l2.6 6.4M16 8.4l-2.6 6.4M8.4 7h7.2"/>',
    events: '<path d="M4 6h3M4 12h3M4 18h3M10 6h10M10 12h10M10 18h10"/>',
    analysis: '<path d="M4 19V9M9.5 19V5M15 19v-7M20.5 19v-4"/>',
    cases: '<rect x="3.5" y="6.5" width="17" height="13" rx="2.5"/><path d="M9 6.5V5a2 2 0 012-2h2a2 2 0 012 2v1.5"/>',
    metrics: '<path d="M4.5 20V4.5M4.5 20H20"/><rect x="8" y="11" width="3" height="6" rx="1"/><rect x="13.5" y="7" width="3" height="10" rx="1"/>',
    predictions: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M6.2 6.2l2.1 2.1M15.7 15.7l2.1 2.1M17.8 6.2l-2.1 2.1M8.3 15.7l-2.1 2.1"/><circle cx="12" cy="12" r="3"/>',
    dashboards: '<rect x="3.5" y="3.5" width="7" height="8" rx="2"/><rect x="13.5" y="3.5" width="7" height="5" rx="2"/><rect x="3.5" y="14.5" width="7" height="6" rx="2"/><rect x="13.5" y="11.5" width="7" height="9" rx="2"/>',
    sources: '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/><path d="M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"/>',
    integrations: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M6 8.5v7M8.5 6h5a4 4 0 014 4v5.5"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-1.8-.3 1.6 1.6 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.6 1.6 0 00-1-1.5 1.6 1.6 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 00-1.5-1H3a2 2 0 110-4h.1a1.6 1.6 0 001.5-1 1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H9a1.6 1.6 0 001-1.5V3a2 2 0 114 0v.1a1.6 1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8V9a1.6 1.6 0 001.5 1H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3.5v3M16 3.5v3"/>',
    filter: '<path d="M4 5h16l-6.2 7.3V19l-3.6 1.8v-8.5z"/>',
    analyst: '<path d="M12 3.5a5.5 5.5 0 013.4 9.8c-.6.5-.9 1.2-.9 2v.7h-5v-.7c0-.8-.3-1.5-.9-2A5.5 5.5 0 0112 3.5z"/><path d="M10 19h4M10.5 21h3"/>',
    chevron: '<path d="M6 9l6 6 6-6"/>',
    expand: '<path d="M8 3.5H4.5V7M16 3.5h3.5V7M8 20.5H4.5V17M16 20.5h3.5V17"/>',
    shuffle: '<path d="M3.5 6.5h4l9 11h4M3.5 17.5h4l3-3.6M15 8.1l1.5-1.6h4"/><path d="M18 3.5l2.5 3-2.5 3M18 14.5l2.5 3-2.5 3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    fit: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9z"/>',
    arrow: '<path d="M5 12h13M13 7l5 5-5 5"/>',
    alert: '<path d="M12 4.5l8.5 15h-17z"/><path d="M12 10v4"/><circle cx="12" cy="16.6" r=".7" fill="currentColor"/>',
    repeat: '<path d="M4 9a5 5 0 015-5h9M20 15a5 5 0 01-5 5H6"/><path d="M15.5 1.5L18.5 4l-3 2.5M8.5 17.5L5.5 20l3 2.5"/>',
    spark: '<path d="M13 3l-8 10h6l-2 8 8-10h-6z"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    upload: '<path d="M12 16V4M8 8l4-4 4 4"/><path d="M4 15v3.5A1.5 1.5 0 005.5 20h13a1.5 1.5 0 001.5-1.5V15"/>',
    inbox: '<path d="M3.5 13.5h5l1.5 3h4l1.5-3h5"/><path d="M5.5 4.5h13l2 9v5a1.5 1.5 0 01-1.5 1.5h-14A1.5 1.5 0 013.5 18.5v-5z"/>',
    key: '<circle cx="8" cy="12" r="3.2"/><path d="M11.2 12H20M17 12v3M20 12v2.5"/>',
    copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5v-3a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2h3"/>',
    trash: '<path d="M4.5 6.5h15M9.5 6.5V4.5h5v2M6.5 6.5l1 13h9l1-13"/>',
    play: '<path d="M7 4.5l12 7.5-12 7.5z"/>',
    save: '<path d="M5 4.5h11L19.5 8v11.5a1 1 0 01-1 1h-13a1 1 0 01-1-1v-14a1 1 0 011-1z"/><path d="M8 4.5v5h7v-5M8 20.5v-6h8v6"/>',
  };

  function icon(name, cls) {
    return '<svg class="' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[name] || "") + "</svg>";
  }

  // ============================================================ клиент API

  var api = {
    key: "",
    headers: function (extra) {
      var head = extra || {};
      if (api.key) head["X-API-Key"] = api.key;
      return head;
    },
    get: function (path) {
      return fetch(path, { headers: api.headers({ Accept: "application/json" }) }).then(api.unwrap);
    },
    post: function (path, body) {
      return fetch(path, {
        method: "POST",
        headers: api.headers({ "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify(body || {}),
      }).then(api.unwrap);
    },
    upload: function (path, form) {
      return fetch(path, { method: "POST", headers: api.headers(), body: form }).then(api.unwrap);
    },
    unwrap: function (response) {
      if (response.status === 204) return null;
      return response.json().catch(function () { return null; }).then(function (payload) {
        if (response.ok) return payload;
        var message = (payload && payload.error && payload.error.message) || ("HTTP " + response.status);
        var error = new Error(message);
        error.status = response.status;
        error.code = payload && payload.error && payload.error.code;
        throw error;
      });
    },
  };

  // ============================================================= состояние

  var MAX_EVENTS = 60000; // предел для клиентского индекса кейсов

  var state = {
    online: false,
    authRequired: false,
    logs: [],
    logId: "",
    summary: null,
    stats: null,
    variants: null,
    necks: null,
    analyst: null,
    graph: null,
    cases: [],
    events: [],
    rawEvents: [],
    rawLogId: "",
    truncated: false,
    algorithm: store.get("pm-studio-algo", "dfg_frequency"),
    mapMode: store.get("pm-studio-mapmode", "frequency"),
    loading: false,
    error: "",
    version: "",
  };

  var listeners = [];
  function onChange(fn) { listeners.push(fn); }
  function emit() { listeners.forEach(function (fn) { fn(); }); }

  // ------------------------------------------------------------- фильтры

  /* Отбор событий. Период, активности и исполнители уходят и в API, и в
   * клиентский индекс кейсов - иначе плитки считались бы по одному набору
   * данных, а список кейсов по другому. Охват маршрутов применяется только на
   * сервере: он отбрасывает целые варианты, и повторять эту логику в браузере
   * значило бы писать второй pm4py. Так и написано в панели отбора. */
  var filters = store.json("pm-studio-filters", {
    dateFrom: "", dateTo: "", activities: [], resources: [], coverage: "",
  });

  function filtersActive() {
    return Boolean(filters.dateFrom || filters.dateTo || filters.coverage ||
      (filters.activities || []).length || (filters.resources || []).length);
  }

  function saveFilters() { store.set("pm-studio-filters", JSON.stringify(filters)); }

  function filterQuery() {
    var parts = [];
    if (filters.dateFrom) parts.push("date_from=" + encodeURIComponent(filters.dateFrom + "T00:00:00"));
    if (filters.dateTo) parts.push("date_to=" + encodeURIComponent(filters.dateTo + "T23:59:59"));
    (filters.activities || []).forEach(function (name) { parts.push("activities=" + encodeURIComponent(name)); });
    (filters.resources || []).forEach(function (name) { parts.push("resources=" + encodeURIComponent(name)); });
    if (filters.coverage) parts.push("variant_coverage=" + filters.coverage);
    return parts.length ? "&" + parts.join("&") : "";
  }

  function filterBody() {
    var body = {};
    if (filters.dateFrom) body.date_from = filters.dateFrom + "T00:00:00";
    if (filters.dateTo) body.date_to = filters.dateTo + "T23:59:59";
    if ((filters.activities || []).length) body.activities_include = filters.activities;
    if ((filters.resources || []).length) body.resources = filters.resources;
    if (filters.coverage) body.variant_coverage = Number(filters.coverage);
    return body;
  }

  function applyLocalFilters() {
    var from = filters.dateFrom ? new Date(filters.dateFrom + "T00:00:00") : null;
    var to = filters.dateTo ? new Date(filters.dateTo + "T23:59:59") : null;
    var keepActivity = (filters.activities || []).length
      ? filters.activities.reduce(function (acc, name) { acc[name] = true; return acc; }, {}) : null;
    var keepResource = (filters.resources || []).length
      ? filters.resources.reduce(function (acc, name) { acc[name] = true; return acc; }, {}) : null;

    state.events = state.rawEvents.filter(function (event) {
      var moment = new Date(event.timestamp);
      if (from && moment < from) return false;
      if (to && moment > to) return false;
      if (keepActivity && !keepActivity[event.activity]) return false;
      if (keepResource && !keepResource[event.resource]) return false;
      return true;
    });
    state.cases = buildCases(state.events);
  }

  // ------------------------------------------------------ загрузка данных

  function loadLogs() {
    return api.get("/api/v1/logs?limit=100").then(function (page) {
      state.logs = (page && page.items) || [];
      if (!state.logs.length) { state.logId = ""; return null; }
      var wanted = store.get("pm-studio-log", "");
      var found = state.logs.filter(function (l) { return l.log_id === wanted; })[0];
      state.logId = (found || state.logs[0]).log_id;
      store.set("pm-studio-log", state.logId);
      return state.logId;
    });
  }

  function loadCore() {
    if (!state.logId) return Promise.resolve();
    var id = state.logId;
    state.loading = true;
    state.error = "";
    emit();

    var query = filterQuery();
    return Promise.all([
      api.post("/api/v1/logs/" + id + "/discover", {
        algorithm: state.algorithm, format: "json", filters: filterBody(),
      }),
      api.get("/api/v1/logs/" + id + "/statistics" + (query ? "?" + query.slice(1) : "")),
      api.get("/api/v1/logs/" + id + "/variants?limit=25" + query),
      api.get("/api/v1/logs/" + id + "/bottlenecks?limit=25" + query),
      api.get("/api/v1/logs/" + id),
      api.get("/api/v1/logs/" + id + "/analyst" + (query ? "?" + query.slice(1) : "")),
    ]).then(function (results) {
      if (state.logId !== id) return; // пользователь успел переключить журнал
      state.graph = results[0] && results[0].graph;
      state.stats = results[1];
      state.variants = results[2];
      state.necks = results[3];
      state.summary = results[4];
      state.analyst = results[5];
      state.loading = false;
      // События перевыкачиваем только при смене журнала: отбор по периоду,
      // активностям и исполнителям применяется к уже скачанному набору.
      if (state.rawLogId === id && state.rawEvents.length) {
        applyLocalFilters();
        emit();
        return;
      }
      emit();
      return loadEvents(id);
    }).catch(function (error) {
      state.loading = false;
      state.error = error.message;
      if (error.status === 401 || error.status === 403) state.authRequired = true;
      emit();
    });
  }

  /* Индекс кейсов строится в браузере из страниц событий. Всё, что ниже зависит
   * от длительности отдельного кейса - распределение, список кейсов, прогнозы -
   * считается по нему: отдельной ручки "верни мне кейсы" в API нет, а гнать
   * такой запрос в pm4py на каждый чих дороже, чем один раз выкачать события. */
  function loadEvents(id) {
    var collected = [];
    state.truncated = false;

    function page(offset) {
      return api.get("/api/v1/logs/" + id + "/events?limit=5000&offset=" + offset).then(function (chunk) {
        if (!chunk || state.logId !== id) return;
        collected = collected.concat(chunk.items || []);
        var next = offset + (chunk.limit || 5000);
        if (next < chunk.total && collected.length < MAX_EVENTS) return page(next);
        if (next < chunk.total) state.truncated = true;
      });
    }

    return page(0).then(function () {
      if (state.logId !== id) return;
      state.rawEvents = collected;
      state.rawLogId = id;
      applyLocalFilters();
      emit();
    }).catch(function (error) {
      state.error = error.message;
      emit();
    });
  }

  /* Шаг, которым процесс нормально заканчивается: самый частый последний шаг
   * кейса. Раньше он брался из end_activities построенной модели - и это
   * молча ломалось на сети Петри и дереве процесса, где концы графа не
   * активности, а позиции ("p:sink"). Ни один кейс с ними не совпадал, и все
   * до одного числились незавершёнными. Журнал знает ответ сам, без модели. */
  var finalStep = "";

  function finalActivity() { return finalStep; }

  function buildCases(events) {
    var map = {};
    events.forEach(function (event) {
      var bucket = map[event.case_id] || (map[event.case_id] = { id: event.case_id, steps: [] });
      bucket.steps.push(event);
    });
    var items = Object.keys(map).map(function (id) {
      var item = map[id];
      item.steps.sort(function (a, b) { return new Date(a.timestamp) - new Date(b.timestamp); });
      var first = new Date(item.steps[0].timestamp);
      var last = new Date(item.steps[item.steps.length - 1].timestamp);
      item.start = first;
      item.end = last;
      item.duration = (last - first) / 1000;
      item.last = item.steps[item.steps.length - 1].activity;
      item.first = item.steps[0].activity;
      item.sequence = item.steps.map(function (s) { return s.activity; });
      item.variant = item.sequence.join(" → ");
      item.resources = item.steps.map(function (s) { return s.resource; }).filter(Boolean);
      // Возврат: активность встретилась в кейсе больше одного раза.
      var seen = {};
      item.rework = 0;
      item.sequence.forEach(function (a) { if (seen[a]) item.rework++; seen[a] = true; });
      return item;
    });

    var tally = {};
    items.forEach(function (item) { tally[item.last] = (tally[item.last] || 0) + 1; });
    finalStep = Object.keys(tally).sort(function (a, b) { return tally[b] - tally[a]; })[0] || "";
    items.forEach(function (item) { item.done = Boolean(finalStep) && item.last === finalStep; });

    return items.sort(function (a, b) { return b.start - a.start; });
  }

  // -------------------------------------------------- производные величины

  /* Дельта считается делением периода журнала пополам: вторая половина против
   * первой. Никакого "прошлого месяца" в данных нет - есть только сам журнал,
   * и сравнивать можно лишь его с собой. */
  function halves() {
    if (!state.cases.length) return null;
    var times = state.cases.map(function (c) { return c.start.getTime(); });
    var min = Math.min.apply(null, times), max = Math.max.apply(null, times);
    if (max <= min) return null;
    var mid = min + (max - min) / 2;
    var older = state.cases.filter(function (c) { return c.start.getTime() < mid; });
    var newer = state.cases.filter(function (c) { return c.start.getTime() >= mid; });
    return { older: older, newer: newer };
  }

  function delta(pick) {
    var parts = halves();
    if (!parts || !parts.older.length || !parts.newer.length) return null;
    var before = pick(parts.older), after = pick(parts.newer);
    if (!before) return null;
    return (after - before) / before;
  }

  function median(values) {
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    return quantile(sorted, 0.5);
  }

  function daySeries(pick) {
    var buckets = {};
    state.cases.forEach(function (item) {
      var key = dayKey(item.start);
      (buckets[key] = buckets[key] || []).push(item);
    });
    return Object.keys(buckets).sort().map(function (key) {
      return { day: key, value: pick(buckets[key]) };
    });
  }

  function activeCases() { return state.cases.filter(function (c) { return !c.done; }); }
  function doneCases() { return state.cases.filter(function (c) { return c.done; }); }

  // ================================================================ графики

  var SVG_NS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) if (attrs[key] !== null && attrs[key] !== undefined) node.setAttribute(key, attrs[key]);
    return node;
  }

  /* Плавная кривая через точки: Catmull-Rom, переведённый в кубические Безье.
   * Ломаная по узлам выглядит как черновик, а сплайн не врёт: он проходит
   * ровно через измеренные значения, а не сглаживает их. */
  function smoothPath(points) {
    if (points.length < 2) return "";
    var d = "M" + points[0][0] + " " + points[0][1];
    for (var i = 0; i < points.length - 1; i++) {
      var p0 = points[i - 1] || points[i];
      var p1 = points[i], p2 = points[i + 1];
      var p3 = points[i + 2] || p2;
      var c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      var c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += " C" + c1x + " " + c1y + " " + c2x + " " + c2y + " " + p2[0] + " " + p2[1];
    }
    return d;
  }

  function drawSpark(svg, values, color) {
    svg.textContent = "";
    var clean = (values || []).filter(function (v) { return v !== null && !isNaN(v); });
    if (clean.length < 2) return;

    var w = 120, h = 46, pad = 4;
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("preserveAspectRatio", "none");

    var min = Math.min.apply(null, clean), max = Math.max.apply(null, clean);
    var span = max - min || 1;
    var points = clean.map(function (value, i) {
      return [
        pad + (i * (w - pad * 2)) / (clean.length - 1),
        h - pad - ((value - min) / span) * (h - pad * 2),
      ];
    });

    var id = "sp" + Math.abs(color.split("").reduce(function (a, c) { return a + c.charCodeAt(0); }, 0)) + clean.length;
    var defs = svgEl("defs");
    var grad = svgEl("linearGradient", { id: id, x1: 0, y1: 0, x2: 0, y2: 1 });
    grad.appendChild(svgEl("stop", { offset: "0%", "stop-color": color, "stop-opacity": ".38" }));
    grad.appendChild(svgEl("stop", { offset: "100%", "stop-color": color, "stop-opacity": "0" }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    var line = smoothPath(points);
    svg.appendChild(svgEl("path", {
      d: line + " L" + points[points.length - 1][0] + " " + h + " L" + points[0][0] + " " + h + " Z",
      fill: "url(#" + id + ")", stroke: "none",
    }));
    svg.appendChild(svgEl("path", { d: line, fill: "none", stroke: color, "stroke-width": 2, "stroke-linecap": "round" }));
  }

  function drawArea(svg, series, options) {
    options = options || {};
    svg.textContent = "";
    if (!series || series.length < 2) return;

    var w = 640, h = 168, left = 34, right = 8, top = 10, bottom = 24;
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("preserveAspectRatio", "none");

    var values = series.map(function (p) { return p.value; });
    var max = Math.max.apply(null, values) || 1;
    var step = Math.pow(10, Math.floor(Math.log10(max)));
    var top4 = Math.ceil(max / step) * step;
    var ticks = [0, top4 / 3, (top4 * 2) / 3, top4];

    ticks.forEach(function (tick) {
      var y = h - bottom - (tick / top4) * (h - top - bottom);
      svg.appendChild(svgEl("line", { class: "grid-line", x1: left, y1: y, x2: w - right, y2: y }));
      var label = svgEl("text", { class: "axis", x: left - 7, y: y + 3.5, "text-anchor": "end" });
      label.textContent = num(Math.round(tick));
      svg.appendChild(label);
    });

    var points = series.map(function (point, i) {
      return [
        left + (i * (w - left - right)) / (series.length - 1),
        h - bottom - (point.value / top4) * (h - top - bottom),
      ];
    });

    var grad = svgEl("linearGradient", { id: "areaFill", x1: 0, y1: 0, x2: 1, y2: 0 });
    grad.appendChild(svgEl("stop", { offset: "0%", "stop-color": "#3b82f6" }));
    grad.appendChild(svgEl("stop", { offset: "100%", "stop-color": "#a855f7" }));
    var gradFill = svgEl("linearGradient", { id: "areaFillDown", x1: 0, y1: 0, x2: 0, y2: 1 });
    gradFill.appendChild(svgEl("stop", { offset: "0%", "stop-color": "#7c5cff", "stop-opacity": ".42" }));
    gradFill.appendChild(svgEl("stop", { offset: "100%", "stop-color": "#7c5cff", "stop-opacity": "0" }));
    var defs = svgEl("defs");
    defs.appendChild(grad);
    defs.appendChild(gradFill);
    svg.appendChild(defs);

    var line = smoothPath(points);
    svg.appendChild(svgEl("path", {
      class: "area", d: line + " L" + points[points.length - 1][0] + " " + (h - bottom) + " L" + points[0][0] + " " + (h - bottom) + " Z",
      fill: "url(#areaFillDown)",
    }));
    svg.appendChild(svgEl("path", { class: "curve", d: line, stroke: "url(#areaFill)" }));

    (options.xLabels || []).forEach(function (label) {
      var x = left + label.at * (w - left - right);
      var text = svgEl("text", { class: "axis", x: x, y: h - 6, "text-anchor": "middle" });
      text.textContent = label.text;
      svg.appendChild(text);
    });
  }

  // ================================================= распределение и прогноз

  var BUCKETS = [
    { limit: 60, label: "1 мин" },
    { limit: 300, label: "5 мин" },
    { limit: 900, label: "15 мин" },
    { limit: 3600, label: "1 час" },
    { limit: 3 * 3600, label: "3 часа" },
    { limit: 6 * 3600, label: "6 часов" },
    { limit: 12 * 3600, label: "12 часов" },
    { limit: 86400, label: "1 дн." },
    { limit: 2 * 86400, label: "2 дн." },
    { limit: 3 * 86400, label: "3 дн." },
    { limit: 7 * 86400, label: "1 нед." },
    { limit: 14 * 86400, label: "2 нед." },
    { limit: 30 * 86400, label: "1 мес." },
    { limit: Infinity, label: "> 1 мес." },
  ];

  function durationHistogram() {
    var counts = BUCKETS.map(function (bucket) { return { day: bucket.label, value: 0 }; });
    state.cases.forEach(function (item) {
      for (var i = 0; i < BUCKETS.length; i++) {
        if (item.duration <= BUCKETS[i].limit) { counts[i].value++; return; }
      }
    });
    return counts;
  }

  /* Ожидаемое остаточное время незавершённого кейса: берём самый частый
   * маршрут, находим в нём текущий шаг и складываем медианные длительности
   * оставшихся переходов. Это оценка по прошлому, а не предсказание модели -
   * так и подписано в разделе. */
  function edgeMedians() {
    var map = {};
    ((state.graph && state.graph.edges) || []).forEach(function (edge) {
      var value = edge.median_duration_seconds;
      if (value === null || value === undefined) value = edge.mean_duration_seconds;
      if (value !== null && value !== undefined) map[edge.source + SEP + edge.target] = value;
    });
    return map;
  }

  function forecast() {
    var items = (state.variants && state.variants.items) || [];
    if (!items.length) return [];
    var main = items[0].sequence || [];
    var medians = edgeMedians();
    var fallback = state.stats && state.stats.throughput_seconds && state.stats.throughput_seconds.median;

    return activeCases().map(function (item) {
      var position = main.lastIndexOf(item.last);
      var remaining = position === -1 ? [] : main.slice(position);
      var seconds = 0;
      var known = true;
      for (var i = 0; i < remaining.length - 1; i++) {
        var value = medians[remaining[i] + SEP + remaining[i + 1]];
        if (value === undefined) { known = false; continue; }
        seconds += value;
      }
      var stepsLeft = Math.max(0, remaining.length - 1);
      var eta = position === -1 ? null : new Date(item.end.getTime() + seconds * 1000);
      var projected = item.duration + seconds;
      var p95 = (state.stats && state.stats.throughput_seconds && state.stats.throughput_seconds.p95) || fallback;
      return {
        id: item.id,
        last: item.last,
        elapsed: item.duration,
        stepsLeft: stepsLeft,
        remaining: position === -1 ? null : seconds,
        eta: eta,
        projected: projected,
        offRoute: position === -1,
        partial: !known,
        risk: p95 && projected > p95 ? "high" : (p95 && projected > p95 * 0.75 ? "mid" : "low"),
      };
    }).sort(function (a, b) {
      var order = { high: 0, mid: 1, low: 2 };
      return order[a.risk] - order[b.risk] || b.elapsed - a.elapsed;
    });
  }

  // ================================================================ разделы

  /* Названия разделов переводятся при отрисовке, а не здесь: список строится
   * один раз, а язык переключают на ходу. */
  var ROUTES = [
    { id: "overview", label: "Обзор процессов", icon: "overview", render: pageOverview },
    { id: "map", label: "Карта процесса", icon: "map", render: pageMap },
    { id: "events", label: "Журнал событий", icon: "events", render: pageEvents },
    { id: "analysis", label: "Анализ", icon: "analysis", render: pageAnalysis },
    { id: "analyst", label: "Аналитик", icon: "analyst", render: pageAnalyst },
    { id: "cases", label: "Кейсы", icon: "cases", render: pageCases },
    { id: "metrics", label: "Показатели", icon: "metrics", render: pageMetrics },
    { id: "predictions", label: "Предсказания", icon: "predictions", render: pagePredictions },
    { id: "dashboards", label: "Дашборды", icon: "dashboards", render: pageDashboards },
    { group: "Управление" },
    { id: "sources", label: "Источники данных", icon: "sources", render: pageSources },
    { id: "integrations", label: "Интеграции", icon: "integrations", render: pageIntegrations },
    { id: "settings", label: "Настройки", icon: "settings", render: pageSettings },
  ];

  function routeById(id) {
    return ROUTES.filter(function (r) { return r.id === id; })[0];
  }

  // ------------------------------------------------------------ обзор

  function hasData() { return Boolean(state.stats && state.graph); }

  function emptyState(title, text, action) {
    return '<div class="card"><div class="empty-state">' + icon("inbox") +
      "<h3>" + esc(title) + "</h3><p>" + esc(text) + "</p>" + (action || "") + "</div></div>";
  }

  /* invert: рост показателя - это плохо (длительность, возвраты). Само число
   * при этом остаётся честным, меняется только цвет: показывать "-1,1 %" там,
   * где время выросло на 1,1 %, значит врать в цифре ради красивой стрелки. */
  function kpiCard(label, value, deltaValue, sparkId, color, note, invert) {
    var deltaHtml = "";
    if (deltaValue !== null && deltaValue !== undefined && isFinite(deltaValue)) {
      var up = deltaValue >= 0;
      var good = invert ? !up : up;
      deltaHtml = '<div class="kpi-delta ' + (good ? "up" : "down") + '"><b>' +
        (up ? "+" : "") + num(deltaValue * 100, 1) + " %</b> " + esc(note || "к прошлому периоду") + "</div>";
    } else if (note) {
      deltaHtml = '<div class="kpi-delta">' + esc(note) + "</div>";
    }
    return '<div class="kpi">' +
      '<div class="kpi-label">' + esc(label) + "</div>" +
      '<div class="kpi-body"><div class="kpi-value">' + esc(value) + "</div>" +
      '<svg class="kpi-spark" id="' + sparkId + '" data-color="' + color + '"></svg></div>' +
      deltaHtml + "</div>";
  }

  function pathCell(sequence) {
    var shown = sequence.slice(0, 8);
    var html = '<span class="path-seq">';
    shown.forEach(function (activity, index) {
      html += '<i style="background:' + activityColor(activity) + '" title="' + esc(activity) + '"></i>';
      if (index < shown.length - 1) html += icon("arrow");
    });
    if (sequence.length > shown.length) html += '<span class="path-more">+' + (sequence.length - shown.length) + "</span>";
    return html + "</span>";
  }

  function neckLabel(neck) {
    return neck.kind === "transition" ? neck.source + " → " + neck.target : neck.activity;
  }

  /* Диагноз узкого места: три разных беды выглядят в таблице одинаково, если не
   * разделить их явно. Возврат виден по перечню rework, разброс - по отношению
   * p95 к медиане, всё остальное - просто долгий шаг. */
  function neckProblem(neck) {
    var reworked = ((state.necks && state.necks.rework) || []).some(function (item) {
      return item.activity === neck.activity || item.activity === neck.target;
    });
    if (reworked) return { text: "Частые возвраты", tone: "amber" };
    if (neck.median_duration_seconds && neck.p95_duration_seconds / neck.median_duration_seconds > 3) {
      return { text: "Нестабильное время", tone: "amber" };
    }
    if (neck.share_of_total_time >= 0.2) return { text: "Высокая длительность", tone: "rose" };
    return { text: "Узкое место", tone: "violet" };
  }

  function pageOverview() {
    if (!hasData()) return skeletonPage();

    var stats = state.stats;
    var thr = stats.throughput_seconds || {};
    var total = state.cases.length || stats.cases;
    var active = activeCases().length;
    var done = doneCases().length;

    var eventsDelta = delta(function (list) {
      return list.reduce(function (sum, item) { return sum + item.steps.length; }, 0);
    });
    var activeDelta = delta(function (list) { return list.filter(function (i) { return !i.done; }).length; });
    var cycleDelta = delta(function (list) { return median(list.map(function (i) { return i.duration; })); });
    var doneDelta = delta(function (list) { return list.filter(function (i) { return i.done; }).length; });

    var range = stats.start_time && stats.end_time
      ? dateShort(stats.start_time) + " – " + dateShort(stats.end_time)
      : "весь журнал";

    var kpis =
      kpiCard("Всего событий", num(stats.events), eventsDelta, "spEvents", "#7c5cff") +
      kpiCard("Активных кейсов", num(active),
        active ? activeDelta : null, "spCases", "#3b82f6",
        active ? "не дошли до «" + finalActivity() + "»" : "все кейсы дошли до финала", true) +
      kpiCard("Средняя длительность", dur(thr.mean), cycleDelta, "spCycle", "#f43f5e", null, true) +
      kpiCard("Завершено кейсов", num(done), doneDelta, "spDone", "#34d399");

    var variants = ((state.variants && state.variants.items) || []).slice(0, 5);
    var necks = ((state.necks && state.necks.bottlenecks) || []).slice(0, 5);

    return (
      '<section class="surface page">' +
        '<div class="hero">' +
          "<div><h1>Добро пожаловать, " + esc(userName()) + " 👋</h1>" +
          "<p>Анализируйте процессы и находите возможности для улучшения</p></div>" +
          '<div class="hero-tools">' +
            '<button class="chip" id="rangeChip" type="button">' + icon("calendar") +
              "<span>" + esc(range) + "</span>" + icon("chevron", "chev") + "</button>" +
            '<button class="icon-square' + (filtersActive() ? " is-on" : "") +
              '" id="filterChip" type="button" title="Отбор данных">' + icon("filter") + "</button>" +
          "</div>" +
        "</div>" +

        '<div class="kpis">' + kpis + "</div>" +

        '<div class="cols cols-2-1">' +
          '<div class="card">' +
            '<div class="card-head"><h3>Карта процесса</h3><div class="tools">' +
              '<button class="mini-square" id="mapFit" type="button" title="Вписать">' + icon("fit") + "</button>" +
              '<button class="mini-square" id="mapFull" type="button" title="Открыть раздел">' + icon("expand") + "</button>" +
              '<div class="select-wrap"><select id="mapMode">' +
                '<option value="frequency"' + (state.mapMode === "frequency" ? " selected" : "") + ">Частота</option>" +
                '<option value="performance"' + (state.mapMode === "performance" ? " selected" : "") + ">Время</option>" +
              "</select>" + icon("chevron", "chev") + "</div>" +
            "</div></div>" +
            '<div class="map-shell"><div class="map-canvas" id="mapCanvas"><div class="map-stage" id="mapStage"></div></div>' +
              '<div class="map-zoom"><button id="zoomIn" type="button" aria-label="Приблизить">' + icon("plus") + "</button>" +
              '<button id="zoomOut" type="button" aria-label="Отдалить">' + icon("minus") + "</button>" +
              '<button id="zoomFit" type="button" aria-label="Вписать">' + icon("fit") + "</button>" +
              '<div class="level" id="zoomLevel">100%</div></div>' +
            "</div>" +
          "</div>" +

          '<div class="card">' +
            '<div class="card-head"><h3>Анализ производительности</h3></div>' +
            '<div class="card-body flush">' +
              '<div class="stat-row">' +
                "<div><b>" + dur(thr.mean) + "</b><span>Средняя длительность</span></div>" +
                "<div><b>" + dur(thr.median) + "</b><span>Медианная длительность</span></div>" +
                "<div><b>" + dur(thr.max) + "</b><span>Максимальная</span></div>" +
                "<div><b>" + dur(thr.min) + "</b><span>Минимальная</span></div>" +
              "</div>" +
              '<div style="padding:15px 19px 19px;display:grid;gap:12px">' +
                '<div class="chart-title">Распределение длительности кейсов</div>' +
                '<svg class="chart-box" id="distChart"></svg>' +
              "</div>" +
            "</div>" +
          "</div>" +
        "</div>" +

        '<div class="cols cols-1-1">' +
          '<div class="card">' +
            '<div class="card-head"><h3>Наиболее частые пути</h3><div class="tools">' +
              '<button class="link-btn" data-goto="analysis" type="button">Смотреть все</button></div></div>' +
            '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
              '<thead><tr><th>Путь</th><th class="num">Частота</th></tr></thead><tbody>' +
              (variants.length ? variants.map(function (variant) {
                return "<tr><td>" + pathCell(variant.sequence) + '</td><td class="num strong">' +
                  pct(variant.share) + "</td></tr>";
              }).join("") : '<tr><td colspan="2" class="empty">Нет маршрутов</td></tr>') +
            "</tbody></table></div></div>" +
          "</div>" +

          '<div class="card">' +
            '<div class="card-head"><h3>Проблемные места</h3><div class="tools">' +
              '<button class="link-btn" data-goto="analysis" type="button">Смотреть все</button></div></div>' +
            '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
              "<thead><tr><th>Этап</th><th>Проблема</th><th class=\"num\">Влияние</th></tr></thead><tbody>" +
              (necks.length ? necks.map(function (neck) {
                var problem = neckProblem(neck);
                var level = neck.share_of_total_time >= 0.2 ? "high" : (neck.share_of_total_time >= 0.1 ? "mid" : "low");
                return "<tr><td>" + esc(neckLabel(neck)) + "</td>" +
                  '<td><span class="tag" data-tone="' + problem.tone + '">' + esc(problem.text) + "</span></td>" +
                  '<td class="num"><span class="impact"><span class="bar"><i data-level="' + level +
                  '" style="width:' + Math.min(100, Math.round(neck.share_of_total_time * 100 * 2)) + '%"></i></span>' +
                  dur(neck.median_duration_seconds) + "</span></td></tr>";
              }).join("") : '<tr><td colspan="3" class="empty">Узких мест не найдено</td></tr>') +
            "</tbody></table></div></div>" +
          "</div>" +
        "</div>" +

        "<div><h3 style=\"margin-bottom:14px\">Инсайты и рекомендации</h3>" +
          '<div class="insights">' + insightCards() + "</div></div>" +
      "</section>"
    );
  }

  function insightCards() {
    var cards = [];
    var necks = (state.necks && state.necks.bottlenecks) || [];
    var rework = (state.necks && state.necks.rework) || [];
    var variants = (state.variants && state.variants.items) || [];
    var stats = state.stats || {};

    if (necks[0]) {
      cards.push({
        tone: "amber", icon: "alert", title: "Узкое место обнаружено",
        text: "Этап «" + neckLabel(necks[0]) + "» забирает " + pct(necks[0].share_of_total_time, 0) +
          " всего времени процесса, медиана — " + dur(necks[0].median_duration_seconds) + ".",
        goto: "analysis",
      });
    }
    if (rework[0]) {
      var share = state.cases.length ? rework[0].cases_with_rework / state.cases.length : null;
      cards.push({
        tone: "rose", icon: "repeat", title: "Высокий процент возвратов",
        text: (share === null ? rework[0].cases_with_rework + " кейсов" : pct(share, 0) + " кейсов") +
          " проходят «" + rework[0].activity + "» повторно, всего " + num(rework[0].total_repetitions) + " повторов.",
        goto: "analysis",
      });
    }
    if (variants[0]) {
      cards.push({
        tone: "green", icon: "spark", title: "Основной маршрут",
        text: "По одному пути из " + num(state.variants.total_variants) + " идёт " + pct(variants[0].share, 0) +
          " кейсов — на нём и окупается автоматизация.",
        goto: "analysis",
      });
    }
    var thr = stats.throughput_seconds || {};
    if (thr.p95 && thr.median) {
      var factor = thr.p95 / thr.median;
      cards.push({
        tone: "violet", icon: "clock", title: "Оптимизация процесса",
        text: "Долгие кейсы идут в " + num(factor, 1) + "× дольше медианных. Подтянув хвост к медиане, процесс сокращается на " +
          dur(thr.p95 - thr.median) + ".",
        goto: "predictions",
      });
    }

    if (!cards.length) return '<div class="note">Пока нечего рекомендовать: слишком мало данных.</div>';

    return cards.slice(0, 4).map(function (card) {
      return '<div class="insight" data-tone="' + card.tone + '">' +
        '<div class="insight-head"><span class="insight-icon">' + icon(card.icon) + "</span><b>" + esc(card.title) + "</b></div>" +
        "<p>" + esc(card.text) + "</p>" +
        '<button class="link-btn" data-goto="' + card.goto + '" type="button">Подробнее</button></div>';
    }).join("");
  }

  function afterOverview() {
    if (!hasData()) return;

    var sparks = [
      ["spEvents", daySeries(function (list) { return list.reduce(function (s, i) { return s + i.steps.length; }, 0); })],
      ["spCases", daySeries(function (list) { return list.length; })],
      ["spCycle", daySeries(function (list) { return median(list.map(function (i) { return i.duration; })); })],
      ["spDone", daySeries(function (list) { return list.filter(function (i) { return i.done; }).length; })],
    ];
    sparks.forEach(function (pair) {
      var svg = $(pair[0]);
      if (svg) drawSpark(svg, pair[1].map(function (p) { return p.value; }), svg.dataset.color);
    });

    var dist = $("distChart");
    if (dist) {
      drawArea(dist, durationHistogram(), {
        xLabels: [
          { at: 0, text: "1 мин" },
          { at: 3 / 13, text: "1 час" },
          { at: 7 / 13, text: "1 дн." },
          { at: 9 / 13, text: "3 дн." },
          { at: 10 / 13, text: "1 нед." },
          { at: 12 / 13, text: "1 мес." },
        ],
      });
    }

    mountMap("mapCanvas", "mapStage", "zoomLevel");
    var toSection = $("mapFull");
    if (toSection) toSection.addEventListener("click", function () { go("map"); });
    var modeSelect = $("mapMode");
    if (modeSelect) modeSelect.addEventListener("change", function (event) {
      state.mapMode = event.target.value;
      store.set("pm-studio-mapmode", state.mapMode);
      render();
    });
    var range = $("rangeChip");
    if (range) range.addEventListener("click", openFilters);
    var filter = $("filterChip");
    if (filter) filter.addEventListener("click", openFilters);
  }

  var mapControl = null;

  function mountMap(canvasId, stageId, levelId) {
    var canvas = $(canvasId), stage = $(stageId);
    if (!canvas || !stage) return;

    var hot = {};
    ((state.necks && state.necks.bottlenecks) || []).slice(0, 3).forEach(function (neck) {
      if (neck.activity) hot[neck.activity] = true;
      if (neck.target) hot[neck.target] = true;
    });

    // Время шага - это пауза до следующего шага: собственной длительности у
    // мгновенного события в журнале нет, и выдумывать её нечем.
    var durations = {};
    ((state.stats && state.stats.activity_stats) || []).forEach(function (item) {
      if (item.mean_waiting_after_seconds) durations[item.activity] = item.mean_waiting_after_seconds;
    });

    var model = window.ProcMap.render(stage, state.graph, {
      cases: state.stats ? state.stats.cases : 0,
      mode: state.mapMode,
      hot: hot,
      durations: durations,
      onNode: function (node) { showActivity(node.id); },
      onEdge: function (edge) { showTransition(edge); },
    });
    if (!model) {
      canvas.insertAdjacentHTML("beforeend", '<div class="map-empty">Граф пуст: в журнале нет переходов между активностями.</div>');
      return;
    }

    // Держим свой экземпляр, а не общий mapControl: пока ждём кадра, читатель
    // мог уйти в другой раздел, и общий уже обнулён перерисовкой.
    if (mapControl && mapControl.stopWatching) mapControl.stopWatching();
    var control = window.ProcMap.attachPanZoom(canvas, stage, $(levelId));
    mapControl = control;
    // Сразу: высота холста задана в CSS, мерить можно уже сейчас. И ещё раз на
    // следующем кадре, если раскладка к этому моменту ещё не устоялась. Полагаться
    // на один requestAnimationFrame нельзя - в фоновой вкладке он не приходит, и
    // карта осталась бы в масштабе 100% за краем экрана. Повтор безвреден: fit
    // выходит сам, пока холст нулевой ширины.
    control.fit(model);
    requestAnimationFrame(function () { control.fit(model); });
    // Планшет поворачивают - холст меняет обе стороны, и прежний вид уезжает
    // за край. Отписку держим на самом контроле: следующая перерисовка карты
    // создаёт новый, а этот вместе с наблюдателем должен уйти.
    if (control.watchResize) control.stopWatching = control.watchResize(model);

    [["zoomIn", "zoomIn"], ["zoomOut", "zoomOut"]].forEach(function (pair) {
      var button = $(pair[0]);
      if (button) button.addEventListener("click", function () { control[pair[1]](); });
    });
    ["zoomFit", "mapFit"].forEach(function (id) {
      var button = $(id);
      if (button) button.addEventListener("click", function () { control.fit(model); });
    });
  }

  // ------------------------------------------------------- карта процесса

  /* Подпись под заголовком. У графа переходов и у сети Петри узлы означают
   * разное, и общее "N активностей" на сети Петри было бы просто неправдой:
   * половина её узлов - позиции, а один переход невидимый. */
  function graphCaption() {
    var stats = (state.graph && state.graph.stats) || {};
    var parts = [];
    if (stats.places !== undefined) {
      parts.push(num(stats.places) + " позиций");
      parts.push(num(stats.transitions) + " переходов");
      if (stats.silent_transitions) parts.push("из них " + num(stats.silent_transitions) + " невидимых");
    } else {
      parts.push(num(stats.activities !== undefined ? stats.activities : (state.graph.nodes || []).length) + " активностей");
      parts.push(num(stats.arcs !== undefined ? stats.arcs : (state.graph.edges || []).length) + " переходов");
    }
    return parts.join(", ") + ". Алгоритм: " + algoLabel(state.algorithm);
  }

  function pageMap() {
    if (!hasData()) return skeletonPage();

    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Карта процесса</h1>' +
        "<p>" + esc(graphCaption()) + "</p></div>" +
        '<div class="hero-tools">' +
          '<div class="select-wrap" style="height:42px"><select id="algoSelect" style="height:42px;border-radius:9px">' +
            algoOptions() + "</select>" + icon("chevron", "chev") + "</div>" +
          '<div class="select-wrap" style="height:42px"><select id="mapMode" style="height:42px;border-radius:9px">' +
            '<option value="frequency"' + (state.mapMode === "frequency" ? " selected" : "") + ">Толщина: частота</option>" +
            '<option value="performance"' + (state.mapMode === "performance" ? " selected" : "") + ">Толщина: время</option>" +
          "</select>" + icon("chevron", "chev") + "</div>" +
        "</div></div>" +

        '<div class="card"><div class="map-shell tall">' +
          '<div class="map-canvas" id="mapCanvas"><div class="map-stage" id="mapStage"></div></div>' +
          '<div class="map-zoom"><button id="zoomIn" type="button" aria-label="Приблизить">' + icon("plus") + "</button>" +
          '<button id="zoomOut" type="button" aria-label="Отдалить">' + icon("minus") + "</button>" +
          '<button id="zoomFit" type="button" aria-label="Вписать">' + icon("fit") + "</button>" +
          '<div class="level" id="zoomLevel">100%</div></div>' +
        "</div></div>" +

        '<div class="note">Кружок слева в узле — доля кейсов, прошедших через шаг; чем насыщеннее, тем чаще. ' +
        "Синяя стрелка — переход, красная — самый нагруженный, оранжевая пунктирная — возврат назад по процессу, " +
        "красная дуга сбоку — повтор шага подряд. Нажмите на узел или на стрелку, чтобы увидеть их показатели." +
        (((state.graph.stats || {}).places !== undefined)
          ? " У сети Петри кружки — позиции, глухая планка — невидимый переход: модели он нужен, событий в журнале ему не соответствует."
          : "") + "</div>" +
      "</section>"
    );
  }

  function algoLabel(value) {
    return ({
      dfg_frequency: "граф переходов (частота)",
      dfg_performance: "граф переходов (время)",
      petri_net_inductive: "сеть Петри, индуктивный",
      petri_net_heuristics: "сеть Петри, эвристический",
      process_tree: "дерево процесса",
      bpmn: "BPMN",
    })[value] || value;
  }

  function algoOptions() {
    return ["dfg_frequency", "dfg_performance", "petri_net_inductive", "petri_net_heuristics", "process_tree", "bpmn"]
      .map(function (value) {
        return '<option value="' + value + '"' + (state.algorithm === value ? " selected" : "") + ">" + esc(algoLabel(value)) + "</option>";
      }).join("");
  }

  function afterMap() {
    if (!hasData()) return;
    mountMap("mapCanvas", "mapStage", "zoomLevel");
    var algo = $("algoSelect");
    if (algo) algo.addEventListener("change", function (event) {
      state.algorithm = event.target.value;
      store.set("pm-studio-algo", state.algorithm);
      loadCore();
    });
    var mode = $("mapMode");
    if (mode) mode.addEventListener("change", function (event) {
      state.mapMode = event.target.value;
      store.set("pm-studio-mapmode", state.mapMode);
      render();
    });
  }

  function showActivity(name) {
    var stat = ((state.stats && state.stats.activity_stats) || []).filter(function (item) {
      return item.activity === name;
    })[0];
    var neck = ((state.necks && state.necks.bottlenecks) || []).filter(function (item) {
      return item.activity === name || item.target === name;
    })[0];
    var rework = ((state.necks && state.necks.rework) || []).filter(function (item) { return item.activity === name; })[0];

    openSheet(name, (
      '<div class="stat-row" style="border:1px solid var(--line-soft);border-radius:12px;overflow:hidden">' +
        "<div><b>" + num(stat && stat.occurrences) + "</b><span>Событий</span></div>" +
        "<div><b>" + num(stat && stat.cases) + "</b><span>Кейсов</span></div>" +
        "<div><b>" + dur(stat && stat.mean_waiting_after_seconds) + "</b><span>Ожидание после</span></div>" +
      "</div>" +
      (neck ? '<div class="note"><b>Узкое место.</b> Медиана ' + dur(neck.median_duration_seconds) +
        ", p95 " + dur(neck.p95_duration_seconds) + ", доля всего времени процесса " + pct(neck.share_of_total_time) + ".</div>" : "") +
      (rework ? '<div class="note" data-tone="warn"><b>Возвраты.</b> ' + num(rework.cases_with_rework) +
        " кейсов проходят шаг повторно, максимум " + num(rework.max_repetitions_in_case) + " раза в одном кейсе.</div>" : "") +
      '<button class="btn secondary" id="sheetToCases" type="button">' + icon("cases") + " Кейсы с этим шагом</button>"
    ));

    var button = $("sheetToCases");
    if (button) button.addEventListener("click", function () {
      closeSheet();
      caseFilter = name;
      go("cases");
    });
  }

  /* Панель перехода. Узкое место в таблице - это строка; здесь то же самое,
   * но от конкретной стрелки на карте, по которой человек и щёлкнул. */
  function showTransition(edge) {
    var neck = ((state.necks && state.necks.bottlenecks) || []).filter(function (item) {
      return item.kind === "transition" && item.source === edge.source && item.target === edge.target;
    })[0];
    var metrics = neck || {};

    openSheet(edge.source + " → " + edge.target, (
      '<div class="stat-row" style="border:1px solid var(--line-soft);border-radius:12px;overflow:hidden">' +
        "<div><b>" + num(edge.freq) + "</b><span>Переходов</span></div>" +
        "<div><b>" + dur(edge.median !== null && edge.median !== undefined ? edge.median : edge.mean) +
          "</b><span>Медианное время</span></div>" +
      "</div>" +
      (neck
        ? '<div class="tbl-wrap"><table class="tbl"><tbody>' +
          [["Общее время", dur(metrics.total_duration_seconds)],
           ["Среднее", dur(metrics.mean_duration_seconds)],
           ["Медиана", dur(metrics.median_duration_seconds)],
           ["p95", dur(metrics.p95_duration_seconds)],
           ["Доля всего времени процесса", pct(metrics.share_of_total_time)]].map(function (row) {
            return "<tr><td>" + esc(row[0]) + '</td><td class="num strong">' + row[1] + "</td></tr>";
          }).join("") + "</tbody></table></div>"
        : '<div class="note">Этот переход не попал в список узких мест: по суммарному времени он не в верхних ' +
          num(((state.necks && state.necks.bottlenecks) || []).length) + ".</div>") +
      '<button class="btn secondary" id="sheetToCases" type="button">' + icon("cases") +
      " Кейсы с этим шагом</button>"
    ));

    var button = $("sheetToCases");
    if (button) button.addEventListener("click", function () {
      closeSheet();
      caseFilter = edge.target;
      caseStatus = "all";
      casePage = 0;
      go("cases");
    });
  }

  // ------------------------------------------------------ журнал событий

  var eventPage = 0, eventQuery = "";
  var EVENTS_PER_PAGE = 50;

  function filteredEvents() {
    var query = eventQuery.trim().toLowerCase();
    if (!query) return state.events;
    return state.events.filter(function (event) {
      return (event.case_id + " " + event.activity + " " + (event.resource || "")).toLowerCase().indexOf(query) !== -1;
    });
  }

  function pageEvents() {
    if (!state.events.length) return state.loading ? skeletonPage() : emptyState("Событий нет", "Загрузите журнал в разделе «Источники данных».", "");

    var rows = filteredEvents();
    var pages = Math.max(1, Math.ceil(rows.length / EVENTS_PER_PAGE));
    if (eventPage >= pages) eventPage = pages - 1;
    var slice = rows.slice(eventPage * EVENTS_PER_PAGE, (eventPage + 1) * EVENTS_PER_PAGE);

    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Журнал событий</h1>' +
        "<p>" + num(rows.length) + " из " + num(state.events.length) + " событий" +
        (state.truncated ? " · показаны первые " + num(MAX_EVENTS) : "") + "</p></div>" +
        '<div class="hero-tools" style="flex:1;max-width:360px">' +
          '<div class="field" style="flex:1"><input type="search" id="eventSearch" placeholder="Кейс, активность или исполнитель" value="' + esc(eventQuery) + '"></div>' +
        "</div></div>" +

        (state.truncated ? '<div class="note" data-tone="warn">Журнал больше ' + num(MAX_EVENTS) +
          " событий. Разделы «Кейсы», «Предсказания» и распределение длительности построены по этой части — остальное не выгружалось в браузер.</div>" : "") +

        '<div class="card"><div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
          "<thead><tr><th>Время</th><th>Кейс</th><th>Активность</th><th>Исполнитель</th><th>Стадия</th></tr></thead><tbody>" +
          (slice.length ? slice.map(function (event) {
            return "<tr><td>" + dateTime(event.timestamp) + "</td>" +
              '<td class="strong">' + esc(event.case_id) + "</td>" +
              "<td>" + activityDot(event.activity) + esc(event.activity) + "</td>" +
              "<td>" + esc(event.resource || "—") + "</td>" +
              "<td>" + esc(event.lifecycle || "—") + "</td></tr>";
          }).join("") : '<tr><td colspan="5" class="empty">Ничего не найдено</td></tr>') +
        "</tbody></table></div></div></div>" +

        pager(eventPage, pages, "eventPager")
      + "</section>"
    );
  }

  function activityDot(name) {
    return '<i style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;vertical-align:middle;background:' +
      activityColor(name) + '"></i>';
  }

  function pager(current, pages, id) {
    if (pages <= 1) return "";
    return '<div class="btn-row" id="' + id + '" style="justify-content:center;align-items:center">' +
      '<button class="btn secondary" data-page="' + (current - 1) + '"' + (current === 0 ? " disabled" : "") + ">Назад</button>" +
      '<span style="color:var(--muted);font-size:13px">Страница ' + (current + 1) + " из " + pages + "</span>" +
      '<button class="btn secondary" data-page="' + (current + 1) + '"' + (current >= pages - 1 ? " disabled" : "") + ">Вперёд</button></div>";
  }

  function afterEvents() {
    var search = $("eventSearch");
    if (search) {
      search.addEventListener("input", function (event) {
        eventQuery = event.target.value;
        eventPage = 0;
        render();
        var again = $("eventSearch");
        if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
      });
    }
    wirePager("eventPager", function (page) { eventPage = page; render(); });
  }

  function wirePager(id, apply) {
    var root = $(id);
    if (!root) return;
    root.querySelectorAll("button[data-page]").forEach(function (button) {
      button.addEventListener("click", function () {
        apply(parseInt(button.dataset.page, 10));
        var view = $("view");
        if (view) view.scrollIntoView({ block: "start" });
      });
    });
  }

  // --------------------------------------------------------------- анализ

  function pageAnalysis() {
    if (!hasData()) return skeletonPage();

    var activities = (state.stats.activity_stats || []).slice();
    var resources = (state.stats.resource_stats || []).slice();
    var necks = (state.necks && state.necks.bottlenecks) || [];
    var rework = (state.necks && state.necks.rework) || [];
    var variants = (state.variants && state.variants.items) || [];
    var maxOcc = Math.max.apply(null, activities.map(function (a) { return a.occurrences || 0; }).concat([1]));

    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Анализ</h1>' +
        "<p>Маршруты, узкие места, возвраты и соответствие модели</p></div>" +
        '<div class="hero-tools"><button class="btn secondary" id="runConformance" type="button">' +
          icon("play") + " Проверить соответствие</button></div></div>" +

        '<div class="cols cols-1-1">' +
          '<div class="card"><div class="card-head"><h3>Маршруты</h3>' +
            '<div class="tools"><span class="tag">' + num(state.variants.total_variants) + " всего</span></div></div>" +
            '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
            '<thead><tr><th>Путь</th><th class="num">Кейсов</th><th class="num">Доля</th><th class="num">Медиана</th></tr></thead><tbody>' +
            (variants.length ? variants.map(function (variant) {
              return '<tr data-variant="' + variant.rank + '"><td>' + pathCell(variant.sequence) + "</td>" +
                '<td class="num">' + num(variant.cases) + "</td>" +
                '<td class="num strong">' + pct(variant.share) + "</td>" +
                '<td class="num">' + dur(variant.median_duration_seconds) + "</td></tr>";
            }).join("") : '<tr><td colspan="4" class="empty">Нет данных</td></tr>') +
            "</tbody></table></div></div></div>" +

          '<div class="card"><div class="card-head"><h3>Узкие места</h3>' +
            '<div class="tools"><span class="tag">по доле времени</span></div></div>' +
            '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
            '<thead><tr><th>Этап</th><th class="num">Медиана</th><th class="num">p95</th><th class="num">Доля времени</th></tr></thead><tbody>' +
            (necks.length ? necks.map(function (neck) {
              return "<tr><td>" + esc(neckLabel(neck)) + "</td>" +
                '<td class="num">' + dur(neck.median_duration_seconds) + "</td>" +
                '<td class="num">' + dur(neck.p95_duration_seconds) + "</td>" +
                '<td class="num strong">' + pct(neck.share_of_total_time) + "</td></tr>";
            }).join("") : '<tr><td colspan="4" class="empty">Нет данных</td></tr>') +
            "</tbody></table></div></div></div>" +
        "</div>" +

        '<div class="cols cols-1-1">' +
          '<div class="card"><div class="card-head"><h3>Активности</h3>' +
            '<div class="tools"><span class="tag">ожидание — до следующего шага</span></div></div>' +
            '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
            '<thead><tr><th>Активность</th><th class="num">Событий</th><th class="num">Кейсов</th><th class="num">Ожидание</th></tr></thead><tbody>' +
            (activities.length ? activities.map(function (item) {
              return '<tr><td>' + activityDot(item.activity) + esc(item.activity) +
                '<span class="bar" style="display:block;height:4px;margin-top:6px;border-radius:999px;background:var(--panel-3)">' +
                '<i style="display:block;height:100%;border-radius:999px;width:' +
                Math.round((item.occurrences / maxOcc) * 100) + '%;background:' + activityColor(item.activity) + '"></i></span></td>' +
                '<td class="num">' + num(item.occurrences) + "</td>" +
                '<td class="num">' + num(item.cases) + "</td>" +
                '<td class="num">' + dur(item.mean_waiting_after_seconds) + "</td></tr>";
            }).join("") : '<tr><td colspan="4" class="empty">Нет данных</td></tr>') +
            "</tbody></table></div></div></div>" +

          '<div class="card"><div class="card-head"><h3>Возвраты</h3></div>' +
            '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
            '<thead><tr><th>Активность</th><th class="num">Кейсов</th><th class="num">Повторов</th><th class="num">Макс. в кейсе</th></tr></thead><tbody>' +
            (rework.length ? rework.map(function (item) {
              return "<tr><td>" + activityDot(item.activity) + esc(item.activity) + "</td>" +
                '<td class="num">' + num(item.cases_with_rework) + "</td>" +
                '<td class="num">' + num(item.total_repetitions) + "</td>" +
                '<td class="num strong">' + num(item.max_repetitions_in_case) + "</td></tr>";
            }).join("") : '<tr><td colspan="4" class="empty">Возвратов не найдено</td></tr>') +
            "</tbody></table></div></div></div>" +
        "</div>" +

        '<div id="conformanceBox"></div>' +

        (resources.length ? '<div class="card"><div class="card-head"><h3>Исполнители</h3></div>' +
          '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
          '<thead><tr><th>Исполнитель</th><th class="num">Событий</th><th class="num">Кейсов</th><th class="num">Активностей</th></tr></thead><tbody>' +
          resources.map(function (item) {
            return "<tr><td>" + esc(item.resource) + "</td>" +
              '<td class="num">' + num(item.events) + "</td>" +
              '<td class="num">' + num(item.cases) + "</td>" +
              '<td class="num">' + num(item.activities) + "</td></tr>";
          }).join("") + "</tbody></table></div></div></div>" : "") +
      "</section>"
    );
  }

  function afterAnalysis() {
    var button = $("runConformance");
    if (!button) return;
    button.addEventListener("click", function () {
      button.disabled = true;
      button.textContent = "Считаем…";
      api.post("/api/v1/logs/" + state.logId + "/conformance", { algorithm: "petri_net_inductive", compute_precision: true })
        .then(function (result) {
          var box = $("conformanceBox");
          if (!box) return;
          var fitness = result.fitness || {};
          box.innerHTML = '<div class="card"><div class="card-head"><h3>Соответствие модели</h3></div>' +
            '<div class="card-body flush"><div class="stat-row">' +
            "<div><b>" + pct(fitness.average_trace_fitness || fitness.averageFitness || fitness.log_fitness) + "</b><span>Соответствие трасс</span></div>" +
            "<div><b>" + (result.precision === null || result.precision === undefined ? "—" : pct(result.precision)) + "</b><span>Точность модели</span></div>" +
            "<div><b>" + num(result.deviating_cases) + "</b><span>Кейсов с отклонением</span></div>" +
            "<div><b>" + num(result.traces_evaluated) + "</b><span>Трасс проверено</span></div>" +
            "</div></div></div>";
        })
        .catch(function (error) { toast(error.message, "bad"); })
        .then(function () { button.disabled = false; button.innerHTML = icon("play") + " Проверить соответствие"; });
    });
  }

  // ---------------------------------------------------------------- кейсы

  var casePage = 0, caseFilter = "", caseStatus = "all";
  var CASES_PER_PAGE = 25;

  function filteredCases() {
    var query = caseFilter.trim().toLowerCase();
    return state.cases.filter(function (item) {
      if (caseStatus === "active" && item.done) return false;
      if (caseStatus === "done" && !item.done) return false;
      if (caseStatus === "rework" && !item.rework) return false;
      if (!query) return true;
      return (item.id + " " + item.variant).toLowerCase().indexOf(query) !== -1;
    });
  }

  /* Аналитик: то же, что видно на других экранах, но словами.
   *
   * Считает и пишет сервер - здесь только показ. Смысл экрана в том, чтобы
   * человек, открывший консоль впервые, за десять секунд понял, что с
   * процессом не так; таблицы на «Анализе» отвечают на тот же вопрос, но
   * требуют читать их глазами аналитика. */
  function pageAnalyst() {
    if (state.loading) return skeletonPage();
    // Журнала нет - выводить нечего, но спросить «что это вообще такое»
    // человек хочет как раз до того, как что-то загрузит.
    if (!hasData()) {
      return '<section class="surface page">' +
        '<div class="hero"><div><h1>Аналитик</h1>' +
        "<p>Журнала пока нет - но спросить о process mining можно и без него</p></div></div>" +
        emptyState("Данных нет", "Загрузите журнал событий, и здесь появятся сводка и находки.",
                   '<button class="btn secondary" id="emptyAsk">Спросить о process mining</button>') +
        "</section>";
    }

    var report = state.analyst || {};
    var digest = report.digest || [];
    var analysis = report.analysis || {};
    var anomalies = analysis.anomalies || [];
    var necks = analysis.bottlenecks || [];
    var trend = analysis.trend;

    var cards = [
      { label: "Кейсов в разборе", value: num(analysis.cases || 0) },
      { label: "Типичный путь", value: dur((analysis.throughput_seconds || {}).median) },
      { label: "Застрявших", value: num(anomalies.length), tone: anomalies.length ? "warn" : "ok" },
      // Тон - только на заметном сдвиге: колебание в несколько процентов это
      // обычная неделя, и красить его тревожным цветом значит звать зря.
      trend
        ? { label: "Поток за неделю", value: (trend.change_pct > 0 ? "+" : "") + trend.change_pct + "%",
            tone: trend.change_pct >= 15 ? "ok" : (trend.change_pct <= -15 ? "warn" : "") }
        : { label: "Узких мест", value: num(necks.length) },
    ];

    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Аналитик</h1>' +
        "<p>Что происходит с процессом - человеческим языком, по свежим данным</p></div></div>" +

        '<div class="kpis">' +
        cards.map(function (card) {
          return '<div class="kpi' + (card.tone ? " is-" + card.tone : "") + '">' +
            '<div class="kpi-label">' + esc(card.label) + "</div>" +
            '<div class="kpi-value">' + card.value + "</div></div>";
        }).join("") +
        "</div>" +

        '<div class="card"><div class="card-head"><h3>Сводка</h3>' +
          '<div class="tools"><span class="tag">' +
          (report.narrator === "llm" ? "написано моделью по этим числам" : "обновляется вместе с журналом") +
          "</span></div></div>" +
          '<div class="card-body"><div class="digest">' +
          (digest.length
            ? digest.map(function (line) { return "<p>" + esc(line) + "</p>"; }).join("")
            : '<p class="empty">Сводка появится, когда наберётся история.</p>') +
          "</div></div></div>" +

        '<div class="card"><div class="card-head"><h3>Застрявшие кейсы</h3>' +
          '<div class="tools"><span class="tag">ждали дольше обычного</span></div></div>' +
          '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
          "<thead><tr><th>Кейс</th><th>Ждал перед</th><th class=\"num\">Простоял</th>" +
          "<th class=\"num\">Обычно</th><th class=\"num\">Во сколько раз</th></tr></thead><tbody>" +
          (anomalies.length ? anomalies.map(function (item) {
            return '<tr data-case="' + esc(item.case_id) + '">' +
              "<td>" + esc(item.case_id) + "</td>" +
              "<td>" + esc(item.target) + "</td>" +
              '<td class="num strong">' + dur(item.waited_seconds) + "</td>" +
              '<td class="num">' + dur(item.typical_seconds) + "</td>" +
              '<td class="num">×' + item.ratio + "</td></tr>";
          }).join("") : '<tr><td colspan="5" class="empty">Ничего не застряло</td></tr>') +
          "</tbody></table></div></div></div>" +
      "</section>"
    );
  }

  /* Помощник: тот же журнал, но вопросом-ответом.
   *
   * Переписка живёт здесь, а не в state: на state завязана перерисовка всей
   * страницы, и она стирала бы недописанный вопрос при каждом обновлении
   * данных. Сервер её тоже не хранит - историю присылает браузер, поэтому
   * разговор исчезает вместе со вкладкой. */
  var chatTurns = [];
  var chatBusy = false;
  var chatLogId = "";

  var CHAT_HINTS = [
    "Где мы теряем больше всего времени?",
    "Какие кейсы застряли и насколько?",
    "Какой этап чаще всего повторяется?",
    "Что такое process mining?",
  ];

  // Без журнала спрашивать про узкие места не у чего - подсказки становятся
  // про сам предмет, иначе первый же клик упрётся в «данных нет».
  var CHAT_HINTS_EMPTY = [
    "Что такое process mining?",
    "Какой журнал событий нужен, чтобы начать?",
    "Что показывает карта процесса?",
    "Что значит узкое место в процессе?",
  ];

  // Имена инструментов человеку ни о чём не говорят, а знать, куда помощник
  // ходил за числом, полезно: так видно, что оно не выдумано.
  var STEP_NAMES = {
    overview: "общие показатели", bottlenecks: "узкие места", anomalies: "застрявшие кейсы",
    activity: "этап", resources: "исполнители", case: "путь кейса",
    variants: "маршруты", slowest_cases: "самые долгие кейсы",
  };

  function chatBody() {
    if (!chatTurns.length) {
      return '<div class="chat-hints">' +
        (hasData() ? CHAT_HINTS : CHAT_HINTS_EMPTY).map(function (hint) {
          return '<button class="chip" data-ask="' + esc(hint) + '">' + esc(hint) + "</button>";
        }).join("") + "</div>";
    }
    return chatTurns.map(function (turn) {
      var steps = turn.steps && turn.steps.length
        ? '<div class="chat-steps">смотрел: ' +
          esc(turn.steps.map(function (step) { return STEP_NAMES[step.tool] || step.tool; }).join(", ")) +
          "</div>"
        : "";
      // Переносы строк модель ставит осмысленно, абзацами, и склеивать их в
      // кирпич значит терять её же разметку.
      var text = esc(turn.content).split("\n").filter(Boolean)
        .map(function (line) { return "<p>" + line + "</p>"; }).join("");
      return '<div class="chat-turn is-' + turn.role + (turn.muted ? " is-muted" : "") + '">' +
        text + steps + "</div>";
    }).join("");
  }

  function askOpen() { return !$("askPanel").hidden; }

  function openAsk(question) {
    $("askPanel").hidden = false;
    $("askFab").setAttribute("aria-expanded", "true");
    document.body.classList.add("ask-open");
    paintChat();
    if (question) askAssistant(question);
    else $("chatInput").focus();
  }

  function closeAsk() {
    $("askPanel").hidden = true;
    $("askFab").setAttribute("aria-expanded", "false");
    document.body.classList.remove("ask-open");
  }

  function clearChat() {
    chatTurns = [];
    paintChat();
    $("chatInput").focus();
  }

  /* Подпись в шапке окна: по журналу отвечает помощник или по существу.
   * Журнал в консоли меняют, окно при этом остаётся открытым - подпись
   * пересобирается на каждой отрисовке, а не один раз при открытии. */
  function paintScope() {
    var scope = $("askScope");
    if (!scope) return;
    var log = state.logs.filter(function (item) { return item.log_id === state.logId; })[0];
    var name = hasData() && log ? log.name : "";
    scope.textContent = name ? "по журналу «" + name + "»" : "журнала нет";
  }

  function paintChat() {
    var box = $("chatLog");
    if (!box) return;
    paintScope();
    box.innerHTML = chatBody();
    box.scrollTop = box.scrollHeight;
    bindChatHints();
    var send = $("chatSend");
    if (send) {
      send.disabled = chatBusy;
      send.textContent = chatBusy ? "Думает…" : "Спросить";
    }
  }

  function bindChatHints() {
    Array.prototype.forEach.call($("askPanel").querySelectorAll("[data-ask]"), function (chip) {
      chip.addEventListener("click", function () { askAssistant(chip.dataset.ask); });
    });
  }

  function askAssistant(question) {
    question = (question || "").trim();
    if (!question || chatBusy) return;

    // Сменили журнал - прошлый разговор к новому не относится, а модель,
    // получив его в истории, продолжит рассуждать о чужих числах.
    if (state.logId !== chatLogId) {
      chatTurns = [];
      chatLogId = state.logId;
    }

    chatTurns.push({ role: "user", content: question });
    chatBusy = true;
    paintChat();

    // Истории уходит хвост: сервер всё равно берёт последние реплики, гонять
    // по сети весь разговор незачем.
    var history = chatTurns.slice(0, -1).slice(-6).map(function (turn) {
      return { role: turn.role, content: turn.content };
    });

    // С журналом вопрос уходит к нему и к текущему отбору; без журнала -
    // на общий маршрут, где у помощника нет функций к данным и он это знает.
    var request = hasData() && state.logId
      ? api.post("/api/v1/logs/" + state.logId + "/assistant", {
          question: question, history: history, filters: filterBody(),
        })
      : api.post("/api/v1/assistant", { question: question, history: history });

    request.then(function (reply) {
      chatTurns.push({
        role: "assistant",
        content: (reply && reply.answer) || "Пустой ответ.",
        steps: (reply && reply.steps) || [],
        muted: !(reply && reply.available),
      });
    }).catch(function (error) {
      chatTurns.push({ role: "assistant", content: error.message, muted: true });
    }).then(function () {
      chatBusy = false;
      paintChat();
    });
  }

  /* Пересказ моделью догоняет страницу.
   *
   * Шаблонная сводка уже на экране - её посчитали вместе с остальными
   * данными. Модель пишет несколько секунд, и держать ради этого весь
   * экран в скелетах незачем: текст подменяется, когда придёт. Не придёт -
   * останется шаблонный, и человек не узнает, что кто-то не ответил. */
  var narrated = "";

  function fetchNarration() {
    var box = document.querySelector(".digest");
    var tag = document.querySelector("#view .card .tools .tag");
    if (!box || !state.logId) return;
    if (narrated === state.logId) return;

    var query = filterQuery();
    api.get("/api/v1/logs/" + state.logId + "/analyst?narrate=1" + query)
      .then(function (report) {
        if (!report || report.narrator !== "llm" || currentRoute() !== "analyst") return;
        narrated = state.logId;
        state.analyst = report;
        box.innerHTML = (report.digest || []).map(function (line) {
          return "<p>" + esc(line) + "</p>";
        }).join("");
        if (tag) tag.textContent = "написано моделью по этим числам";
      })
      .catch(function () { /* остаётся шаблонная сводка */ });
  }

  function bindAsk() {
    var input = $("chatInput");
    var send = $("chatSend");

    function submit() {
      var question = input.value;
      input.value = "";
      input.style.height = "";
      askAssistant(question);
    }

    $("askFab").addEventListener("click", function () { openAsk(); });
    $("askClose").addEventListener("click", closeAsk);
    $("askClear").addEventListener("click", clearChat);
    send.addEventListener("click", submit);
    input.addEventListener("keydown", function (event) {
      // Enter отправляет, Shift+Enter переносит строку: вопрос обычно в одну
      // строку, и тянуться к кнопке ради каждого - лишнее.
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
    });
    input.addEventListener("input", function () {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 160) + "px";
    });
    paintChat();
  }

  function afterAnalyst() {
    if (hasData()) fetchNarration();
    var ask = $("emptyAsk");
    if (ask) ask.addEventListener("click", function () { openAsk(); });
  }

  function pageCases() {
    if (!state.cases.length) return state.loading ? skeletonPage() : emptyState("Кейсов нет", "Загрузите журнал событий, и кейсы соберутся автоматически.", "");

    var rows = filteredCases();
    var pages = Math.max(1, Math.ceil(rows.length / CASES_PER_PAGE));
    if (casePage >= pages) casePage = pages - 1;
    var slice = rows.slice(casePage * CASES_PER_PAGE, (casePage + 1) * CASES_PER_PAGE);
    var final = finalActivity();

    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Кейсы</h1>' +
        "<p>" + num(rows.length) + " из " + num(state.cases.length) + " экземпляров процесса. " +
        "Завершённым считается кейс, дошедший до «" + esc(final || "—") + "»</p></div>" +
        '<div class="hero-tools">' +
          '<div class="select-wrap" style="height:42px"><select id="caseStatus" style="height:42px;border-radius:9px">' +
            '<option value="all"' + (caseStatus === "all" ? " selected" : "") + ">Все</option>" +
            '<option value="active"' + (caseStatus === "active" ? " selected" : "") + ">Активные</option>" +
            '<option value="done"' + (caseStatus === "done" ? " selected" : "") + ">Завершённые</option>" +
            '<option value="rework"' + (caseStatus === "rework" ? " selected" : "") + ">С возвратами</option>" +
          "</select>" + icon("chevron", "chev") + "</div>" +
          '<div class="field" style="flex:1 1 180px"><input type="search" id="caseSearch" placeholder="Номер кейса или шаг" value="' + esc(caseFilter) + '"></div>' +
        "</div></div>" +

        '<div class="card"><div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
          '<thead><tr><th>Кейс</th><th>Маршрут</th><th class="num">Шагов</th><th>Начало</th>' +
          '<th class="num">Длительность</th><th>Текущий шаг</th><th>Статус</th></tr></thead><tbody>' +
          (slice.length ? slice.map(function (item) {
            return '<tr data-case="' + esc(item.id) + '" style="cursor:pointer">' +
              '<td class="strong">' + esc(item.id) + "</td>" +
              "<td>" + pathCell(item.sequence) + "</td>" +
              '<td class="num">' + num(item.steps.length) + "</td>" +
              "<td>" + dateTime(item.start) + "</td>" +
              '<td class="num">' + dur(item.duration) + "</td>" +
              "<td>" + esc(item.last) + "</td>" +
              '<td><span class="tag" data-tone="' + (item.done ? "green" : (item.rework ? "amber" : "violet")) + '">' +
              (item.done ? "Завершён" : (item.rework ? "Возвраты" : "В работе")) + "</span></td></tr>";
          }).join("") : '<tr><td colspan="7" class="empty">Ничего не найдено</td></tr>') +
        "</tbody></table></div></div></div>" +

        pager(casePage, pages, "casePager") +
      "</section>"
    );
  }

  function afterCases() {
    var search = $("caseSearch");
    if (search) search.addEventListener("input", function (event) {
      caseFilter = event.target.value;
      casePage = 0;
      render();
      var again = $("caseSearch");
      if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
    });
    var status = $("caseStatus");
    if (status) status.addEventListener("change", function (event) {
      caseStatus = event.target.value;
      casePage = 0;
      render();
    });
    wirePager("casePager", function (page) { casePage = page; render(); });

    document.querySelectorAll("tr[data-case]").forEach(function (row) {
      row.addEventListener("click", function () { showCase(row.dataset.case); });
    });
  }

  function showCase(id) {
    var item = state.cases.filter(function (c) { return c.id === id; })[0];
    if (!item) return;
    var previous = null;

    openSheet("Кейс " + id, (
      '<div class="stat-row" style="border:1px solid var(--line-soft);border-radius:12px;overflow:hidden">' +
        "<div><b>" + num(item.steps.length) + "</b><span>Шагов</span></div>" +
        "<div><b>" + dur(item.duration) + "</b><span>Длительность</span></div>" +
        "<div><b>" + num(item.rework) + "</b><span>Возвратов</span></div>" +
      "</div>" +
      '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Шаг</th><th>Время</th><th class="num">Пауза</th></tr></thead><tbody>' +
      item.steps.map(function (step) {
        var current = new Date(step.timestamp);
        var gap = previous ? (current - previous) / 1000 : null;
        previous = current;
        return "<tr><td>" + activityDot(step.activity) + esc(step.activity) +
          (step.resource ? '<div style="color:var(--muted);font-size:11.5px;margin-top:2px">' + esc(step.resource) + "</div>" : "") +
          "</td><td>" + dateTime(step.timestamp) + '</td><td class="num">' + (gap === null ? "—" : dur(gap)) + "</td></tr>";
      }).join("") +
      "</tbody></table></div>"
    ));
  }

  // ----------------------------------------------------------- показатели

  function pageMetrics() {
    if (!hasData()) return skeletonPage();
    var stats = state.stats;
    var thr = stats.throughput_seconds || {};
    var perDay = stats.cases_per_day || {};
    var days = Object.keys(perDay).sort();

    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Показатели</h1>' +
        "<p>Сводка по журналу «" + esc(state.summary ? state.summary.name : "") + "» за " +
        dateShort(stats.start_time) + " – " + dateShort(stats.end_time) + "</p></div></div>" +

        '<div class="card"><div class="card-body flush"><div class="stat-row">' +
          "<div><b>" + num(stats.events) + "</b><span>Событий</span></div>" +
          "<div><b>" + num(stats.cases) + "</b><span>Кейсов</span></div>" +
          "<div><b>" + num(stats.activities) + "</b><span>Активностей</span></div>" +
          "<div><b>" + num(stats.resources) + "</b><span>Исполнителей</span></div>" +
          "<div><b>" + num(stats.variants) + "</b><span>Маршрутов</span></div>" +
        "</div></div></div>" +

        '<div class="cols cols-1-1">' +
          '<div class="card"><div class="card-head"><h3>Время прохождения</h3></div>' +
            '<div class="card-body flush"><div class="stat-row">' +
            "<div><b>" + dur(thr.min) + "</b><span>Минимум</span></div>" +
            "<div><b>" + dur(thr.median) + "</b><span>Медиана</span></div>" +
            "<div><b>" + dur(thr.mean) + "</b><span>Среднее</span></div>" +
            "</div><div class=\"stat-row\" style=\"border-bottom:0\">" +
            "<div><b>" + dur(thr.p90) + "</b><span>p90</span></div>" +
            "<div><b>" + dur(thr.p95) + "</b><span>p95</span></div>" +
            "<div><b>" + dur(thr.max) + "</b><span>Максимум</span></div>" +
            "</div></div></div>" +

          '<div class="card"><div class="card-head"><h3>Кейсов в день</h3></div>' +
            '<div class="card-body"><svg class="chart-box" id="perDayChart"></svg>' +
            '<div class="chart-title">' + (days.length ? dateShort(days[0]) + " – " + dateShort(days[days.length - 1]) : "нет данных") + "</div></div></div>" +
        "</div>" +

        '<div class="card"><div class="card-head"><h3>Ожидание после активности</h3>' +
          '<div class="tools"><span class="tag">среднее время до следующего шага</span></div></div>' +
          '<div class="card-body" id="activityBars"></div></div>' +
      "</section>"
    );
  }

  function afterMetrics() {
    if (!hasData()) return;
    var perDay = state.stats.cases_per_day || {};
    var days = Object.keys(perDay).sort();
    var chart = $("perDayChart");
    if (chart && days.length > 1) {
      drawArea(chart, days.map(function (day) { return { day: day, value: perDay[day] }; }), {
        xLabels: [
          { at: 0, text: dateShort(days[0]) },
          { at: 0.5, text: dateShort(days[Math.floor(days.length / 2)]) },
          { at: 1, text: dateShort(days[days.length - 1]) },
        ],
      });
    }

    var bars = $("activityBars");
    if (!bars) return;
    var activities = (state.stats.activity_stats || []).slice().filter(function (item) {
      return item.mean_waiting_after_seconds;
    }).sort(function (a, b) { return b.mean_waiting_after_seconds - a.mean_waiting_after_seconds; });
    if (!activities.length) { bars.innerHTML = '<div class="note">В журнале нет пауз между шагами: у последнего шага кейса ждать нечего.</div>'; return; }
    var max = activities[0].mean_waiting_after_seconds;
    bars.innerHTML = activities.map(function (item) {
      return '<div style="display:grid;grid-template-columns:minmax(120px,26%) 1fr auto;gap:12px;align-items:center">' +
        '<span style="font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(item.activity) + "</span>" +
        '<span style="height:8px;border-radius:999px;background:var(--panel-3);overflow:hidden">' +
        '<i style="display:block;height:100%;border-radius:999px;width:' + Math.round((item.mean_waiting_after_seconds / max) * 100) +
        "%;background:linear-gradient(90deg," + activityColor(item.activity) + ',#3b82f6)"></i></span>' +
        '<span style="font-size:12px;color:var(--muted)">' + dur(item.mean_waiting_after_seconds) + "</span></div>";
    }).join("");
  }

  // --------------------------------------------------------- предсказания

  function pagePredictions() {
    if (!hasData()) return skeletonPage();
    var rows = forecast();
    var perDay = state.stats.cases_per_day || {};
    var days = Object.keys(perDay).sort();
    var trend = linearTrend(days.map(function (day, index) { return [index, perDay[day]]; }));
    var nextWeek = trend ? Math.max(0, Math.round((trend.slope * (days.length + 3) + trend.intercept) * 7)) : null;
    var atRisk = rows.filter(function (row) { return row.risk === "high"; }).length;

    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Предсказания</h1>' +
        "<p>Оценка по истории этого же журнала — не обученная модель</p></div></div>" +

        '<div class="note"><b>Как это считается.</b> Для каждого незавершённого кейса берётся самый частый маршрут, ' +
        "в нём находится текущий шаг, и складываются медианные длительности оставшихся переходов. " +
        "Прогноз нагрузки — линейный тренд по числу кейсов в день. " +
        "Кейс попадает в группу риска, если его ожидаемое общее время превышает p95 по журналу (" +
        dur(state.stats.throughput_seconds && state.stats.throughput_seconds.p95) + ").</div>" +

        '<div class="kpis">' +
          kpiCard("Кейсов в работе", num(rows.length), null, "spPredActive", "#3b82f6", "не дошли до финала") +
          kpiCard("В группе риска", num(atRisk), null, "spPredRisk", "#f43f5e", "прогноз превышает p95") +
          kpiCard("Ожидается за неделю", nextWeek === null ? "—" : num(nextWeek), null, "spPredLoad", "#7c5cff", "по линейному тренду") +
          kpiCard("Медиана цикла", dur(state.stats.throughput_seconds && state.stats.throughput_seconds.median), null, "spPredCycle", "#34d399", "база для оценки") +
        "</div>" +

        '<div class="card"><div class="card-head"><h3>Незавершённые кейсы</h3>' +
          '<div class="tools"><span class="tag">' + num(rows.length) + "</span></div></div>" +
          '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
          '<thead><tr><th>Кейс</th><th>Текущий шаг</th><th class="num">Идёт</th><th class="num">Шагов до конца</th>' +
          '<th class="num">Осталось</th><th>Ожидаемый финиш</th><th>Риск</th></tr></thead><tbody>' +
          (rows.length ? rows.slice(0, 100).map(function (row) {
            var tone = row.risk === "high" ? "rose" : (row.risk === "mid" ? "amber" : "green");
            var label = row.risk === "high" ? "Высокий" : (row.risk === "mid" ? "Средний" : "Низкий");
            return '<tr data-case="' + esc(row.id) + '" style="cursor:pointer">' +
              '<td class="strong">' + esc(row.id) + "</td>" +
              "<td>" + activityDot(row.last) + esc(row.last) + "</td>" +
              '<td class="num">' + dur(row.elapsed) + "</td>" +
              '<td class="num">' + (row.offRoute ? "—" : num(row.stepsLeft)) + "</td>" +
              '<td class="num">' + (row.offRoute ? "—" : dur(row.remaining) + (row.partial ? " *" : "")) + "</td>" +
              "<td>" + (row.eta ? dateTime(row.eta) : "вне основного маршрута") + "</td>" +
              '<td><span class="tag" data-tone="' + tone + '">' + label + "</span></td></tr>";
          }).join("") : '<tr><td colspan="7" class="empty">Все кейсы завершены</td></tr>') +
        "</tbody></table></div></div></div>" +

        (rows.some(function (r) { return r.partial; })
          ? '<div class="note">Звёздочка: часть переходов этого кейса ни разу не встретилась в журнале, их время в сумму не вошло — оценка занижена.</div>'
          : "") +
        (rows.some(function (r) { return r.offRoute; })
          ? '<div class="note" data-tone="warn">Часть кейсов стоит на шаге, которого нет в самом частом маршруте. ' +
            "Оценить остаток по нему нельзя — такие строки помечены прочерком.</div>"
          : "") +
      "</section>"
    );
  }

  function linearTrend(points) {
    if (points.length < 3) return null;
    var n = points.length;
    var sx = 0, sy = 0, sxy = 0, sxx = 0;
    points.forEach(function (p) { sx += p[0]; sy += p[1]; sxy += p[0] * p[1]; sxx += p[0] * p[0]; });
    var denom = n * sxx - sx * sx;
    if (!denom) return null;
    var slope = (n * sxy - sx * sy) / denom;
    return { slope: slope, intercept: (sy - slope * sx) / n };
  }

  function afterPredictions() {
    if (!hasData()) return;
    var rows = forecast();
    var buckets = {};
    rows.forEach(function (row) {
      var key = row.risk;
      buckets[key] = (buckets[key] || 0) + 1;
    });
    var perDay = state.stats.cases_per_day || {};
    var days = Object.keys(perDay).sort();

    var sparks = [
      ["spPredActive", daySeries(function (list) { return list.filter(function (i) { return !i.done; }).length; }).map(function (p) { return p.value; }), "#3b82f6"],
      ["spPredRisk", [buckets.low || 0, buckets.mid || 0, buckets.high || 0], "#f43f5e"],
      ["spPredLoad", days.map(function (day) { return perDay[day]; }), "#7c5cff"],
      ["spPredCycle", daySeries(function (list) { return median(list.map(function (i) { return i.duration; })); }).map(function (p) { return p.value; }), "#34d399"],
    ];
    sparks.forEach(function (item) {
      var svg = $(item[0]);
      if (svg) drawSpark(svg, item[1], item[2]);
    });

    document.querySelectorAll("tr[data-case]").forEach(function (row) {
      row.addEventListener("click", function () { showCase(row.dataset.case); });
    });
  }

  // ------------------------------------------------------------ дашборды

  function savedViews() { return store.json("pm-studio-views", []); }
  function saveViews(list) { store.set("pm-studio-views", JSON.stringify(list)); }

  function pageDashboards() {
    var views = savedViews();
    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Дашборды</h1>' +
        "<p>Сохранённые наборы: журнал, алгоритм и режим карты в один клик</p></div>" +
        '<div class="hero-tools"><button class="btn" id="saveView" type="button">' + icon("save") + " Сохранить текущий вид</button></div></div>" +

        (views.length
          ? '<div class="insights">' + views.map(function (view, index) {
              var log = state.logs.filter(function (l) { return l.log_id === view.logId; })[0];
              return '<div class="insight" data-tone="violet">' +
                '<div class="insight-head"><span class="insight-icon">' + icon("dashboards") + "</span><b>" + esc(view.name) + "</b></div>" +
                "<p>" + esc(log ? log.name : "журнал удалён") + "<br>" + esc(algoLabel(view.algorithm)) +
                " · " + (view.mapMode === "performance" ? "толщина по времени" : "толщина по частоте") + "</p>" +
                '<div class="btn-row"><button class="link-btn" data-open="' + index + '" type="button">Открыть</button>' +
                '<button class="link-btn" data-drop="' + index + '" type="button">Удалить</button></div></div>';
            }).join("") + "</div>"
          : '<div class="card"><div class="empty-state">' + icon("dashboards") +
            "<h3>Пока пусто</h3><p>Настройте журнал, алгоритм и режим карты, затем нажмите «Сохранить текущий вид» — набор появится здесь и будет открываться одним нажатием.</p></div></div>") +
      "</section>"
    );
  }

  function afterDashboards() {
    var save = $("saveView");
    if (save) save.addEventListener("click", function () {
      var log = state.logs.filter(function (l) { return l.log_id === state.logId; })[0];
      var views = savedViews();
      views.push({
        name: (log ? log.name : "Без журнала") + " · " + algoLabel(state.algorithm),
        logId: state.logId, algorithm: state.algorithm, mapMode: state.mapMode,
      });
      saveViews(views);
      toast("Вид сохранён", "good");
      render();
    });

    document.querySelectorAll("button[data-open]").forEach(function (button) {
      button.addEventListener("click", function () {
        var view = savedViews()[parseInt(button.dataset.open, 10)];
        if (!view) return;
        state.algorithm = view.algorithm;
        state.mapMode = view.mapMode;
        store.set("pm-studio-algo", state.algorithm);
        store.set("pm-studio-mapmode", state.mapMode);
        if (view.logId && view.logId !== state.logId) {
          state.logId = view.logId;
          store.set("pm-studio-log", state.logId);
        }
        go("overview");
        loadCore();
      });
    });
    document.querySelectorAll("button[data-drop]").forEach(function (button) {
      button.addEventListener("click", function () {
        var views = savedViews();
        views.splice(parseInt(button.dataset.drop, 10), 1);
        saveViews(views);
        render();
      });
    });
  }

  // ------------------------------------------------------ источники данных

  function pageSources() {
    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Источники данных</h1>' +
        "<p>Журналы событий, доступные этому сервису</p></div>" +
        '<div class="hero-tools"><button class="btn secondary" id="loadSample" type="button">Загрузить пример</button>' +
        '<button class="btn" id="pickFile" type="button">' + icon("upload") + " Загрузить файл</button></div></div>" +

        '<div class="dropzone" id="dropzone">' + icon("upload") +
          "<div>Перетащите CSV, XES или JSON сюда</div>" +
          '<div style="font-size:11.5px;color:var(--faint)">Колонки case / activity / timestamp определяются автоматически</div>' +
        "</div>" +

        '<div class="card"><div class="card-head"><h3>Журналы</h3>' +
          '<div class="tools"><span class="tag">' + num(state.logs.length) + "</span></div></div>" +
          '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
          '<thead><tr><th>Название</th><th class="num">Событий</th><th class="num">Кейсов</th><th class="num">Активностей</th>' +
          "<th>Период</th><th></th></tr></thead><tbody>" +
          (state.logs.length ? state.logs.map(function (log) {
            var active = log.log_id === state.logId;
            return "<tr><td class=\"strong\">" + esc(log.name) +
              (active ? ' <span class="tag" data-tone="violet">открыт</span>' : "") +
              '<div style="color:var(--faint);font-size:11.5px;margin-top:2px">' + esc(log.log_id) + "</div></td>" +
              '<td class="num">' + num(log.events) + "</td>" +
              '<td class="num">' + num(log.cases) + "</td>" +
              '<td class="num">' + num(log.activities) + "</td>" +
              "<td>" + dateShort(log.start_time) + " – " + dateShort(log.end_time) + "</td>" +
              '<td class="num"><div class="btn-row" style="justify-content:flex-end">' +
              (active ? "" : '<button class="link-btn" data-use="' + esc(log.log_id) + '" type="button">Открыть</button>') +
              '<button class="link-btn" data-drop-log="' + esc(log.log_id) + '" type="button">Удалить</button>' +
              "</div></td></tr>";
          }).join("") : '<tr><td colspan="6" class="empty">Журналов пока нет</td></tr>') +
          "</tbody></table></div></div></div>" +
      "</section>"
    );
  }

  function afterSources() {
    var picker = $("filePicker");
    var pick = $("pickFile");
    if (pick) pick.addEventListener("click", function () { picker.click(); });

    var zone = $("dropzone");
    if (zone) {
      zone.addEventListener("click", function () { picker.click(); });
      ["dragenter", "dragover"].forEach(function (name) {
        zone.addEventListener(name, function (event) { event.preventDefault(); zone.classList.add("over"); });
      });
      ["dragleave", "drop"].forEach(function (name) {
        zone.addEventListener(name, function (event) { event.preventDefault(); zone.classList.remove("over"); });
      });
      zone.addEventListener("drop", function (event) {
        if (event.dataTransfer.files && event.dataTransfer.files[0]) uploadFile(event.dataTransfer.files[0]);
      });
    }

    var sample = $("loadSample");
    if (sample) sample.addEventListener("click", function () {
      sample.disabled = true;
      fetch("/ui/sample_log.csv").then(function (r) { return r.blob(); }).then(function (blob) {
        return uploadFile(new File([blob], "sample_log.csv", { type: "text/csv" }));
      }).catch(function (error) { toast(error.message, "bad"); })
        .then(function () { sample.disabled = false; });
    });

    document.querySelectorAll("button[data-use]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.logId = button.dataset.use;
        store.set("pm-studio-log", state.logId);
        resetPaging();
        loadCore();
        go("overview");
      });
    });
    document.querySelectorAll("button[data-drop-log]").forEach(function (button) {
      button.addEventListener("click", function () {
        var id = button.dataset.dropLog;
        if (!window.confirm("Удалить журнал целиком? Событий: " + num((state.logs.filter(function (l) { return l.log_id === id; })[0] || {}).events) + ".")) return;
        fetch("/api/v1/logs/" + id, { method: "DELETE", headers: api.headers() }).then(function (response) {
          if (!response.ok && response.status !== 204) throw new Error("HTTP " + response.status);
          toast("Журнал удалён", "good");
          if (id === state.logId) { state.logId = ""; state.stats = null; state.graph = null; state.cases = []; state.events = []; }
          return loadLogs().then(loadCore);
        }).catch(function (error) { toast(error.message, "bad"); });
      });
    });
  }

  function uploadFile(file) {
    var form = new FormData();
    form.append("file", file);
    form.append("name", file.name);
    toast("Загружаем " + file.name + "…");
    return api.upload("/api/v1/logs/upload", form).then(function (result) {
      toast("Готово: " + num(result.log.events) + " событий", "good");
      state.logId = result.log.log_id;
      store.set("pm-studio-log", state.logId);
      resetPaging();
      return loadLogs().then(loadCore).then(function () { go("overview"); });
    }).catch(function (error) {
      toast(error.message, "bad");
      if (error.status === 401 || error.status === 403) openKeys();
    });
  }

  // ------------------------------------------------------------ интеграции

  function pageIntegrations() {
    var origin = location.origin;
    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Интеграции</h1>' +
        "<p>Как подать события в этот сервис из внешней системы</p></div>" +
        '<div class="hero-tools"><a class="btn secondary" href="/docs" target="_blank" rel="noopener">Справочник API</a>' +
        '<button class="btn" id="openKeys" type="button">' + icon("key") + " Ключ доступа</button></div></div>" +

        '<div class="cols cols-1-1">' +
          '<div class="card"><div class="card-head"><h3>Поток событий</h3></div><div class="card-body">' +
            '<p style="margin:0;color:var(--muted);font-size:13px">Каждое событие — один шаг процесса. ' +
            "Поле <code>event_id</code> делает доставку идемпотентной: повторная отправка того же события не задваивает шаг.</p>" +
            '<pre class="code">curl -X POST ' + esc(origin) + "/api/v1/logs/&lt;log_id&gt;/events \\\n" +
            '  -H "X-API-Key: &lt;ключ&gt;" \\\n  -H "Content-Type: application/json" \\\n' +
            '  -d \'{"events":[{"event_id":"e-1","case_id":"B-346",\n' +
            '        "activity":"proving","timestamp":"2026-08-14T09:15:00Z",\n' +
            '        "resource":"line-2"}]}\'</pre>' +
          "</div></div>" +

          '<div class="card"><div class="card-head"><h3>Разовый разбор файла</h3></div><div class="card-body">' +
            '<p style="margin:0;color:var(--muted);font-size:13px">Ничего не сохраняется на сервере: файл уходит, ' +
            "модель возвращается в ответе.</p>" +
            '<pre class="code">curl -X POST ' + esc(origin) + "/api/v1/mine \\\n" +
            '  -H "X-API-Key: &lt;ключ&gt;" \\\n  -F "file=@events.csv" \\\n  -F "algorithm=dfg_frequency"</pre>' +
          "</div></div>" +
        "</div>" +

        '<div class="card"><div class="card-head"><h3>Точки подключения</h3></div>' +
          '<div class="card-body flush"><div class="tbl-wrap"><table class="tbl">' +
          "<thead><tr><th>Назначение</th><th>Метод</th><th>Адрес</th></tr></thead><tbody>" +
          [
            ["Создать журнал из файла", "POST", "/api/v1/logs/upload"],
            ["Досылать события", "POST", "/api/v1/logs/{log_id}/events"],
            ["Модель процесса", "POST", "/api/v1/logs/{log_id}/discover"],
            ["Картинка карты", "GET", "/api/v1/logs/{log_id}/map"],
            ["Показатели", "GET", "/api/v1/logs/{log_id}/statistics"],
            ["Маршруты", "GET", "/api/v1/logs/{log_id}/variants"],
            ["Узкие места", "GET", "/api/v1/logs/{log_id}/bottlenecks"],
            ["Соответствие модели", "POST", "/api/v1/logs/{log_id}/conformance"],
            ["Профили нормализации", "GET", "/api/v1/profiles"],
            ["Готовность сервиса", "GET", "/health/ready"],
          ].map(function (row) {
            return "<tr><td>" + esc(row[0]) + '</td><td><span class="tag">' + row[1] + "</span></td>" +
              '<td><code style="font-size:12.5px;color:var(--ink-dim)">' + esc(row[2]) + "</code></td></tr>";
          }).join("") +
          "</tbody></table></div></div></div>" +

        '<div class="note">Ключ передаётся заголовком <b>X-API-Key</b> либо как <b>Authorization: Bearer</b>. ' +
        "Консоль, открытая ссылкой из КМС, работает по временному пропуску — он действует ограниченное время и только на чтение.</div>" +
      "</section>"
    );
  }

  function afterIntegrations() {
    var button = $("openKeys");
    if (button) button.addEventListener("click", openKeys);
  }

  // ------------------------------------------------------------- настройки

  function pageSettings() {
    var dark = document.documentElement.dataset.theme !== "light";
    return (
      '<section class="surface page">' +
        '<div class="hero"><div><h1>Настройки</h1><p>Параметры консоли и анализа</p></div></div>' +

        '<div class="cols cols-1-1">' +
          '<div class="card"><div class="card-head"><h3>Внешний вид</h3></div><div class="card-body">' +
            '<label class="switch"><input type="checkbox" id="setDark"' + (dark ? " checked" : "") + '><span class="track"></span>' +
            "<span>Тёмная тема</span></label>" +
            '<div class="field"><label for="setLocale">Формат чисел и дат</label>' +
            '<select id="setLocale">' +
              '<option value="ru-RU"' + (locale === "ru-RU" ? " selected" : "") + ">Русский (1 234,5)</option>" +
              '<option value="en-US"' + (locale === "en-US" ? " selected" : "") + ">English (1,234.5)</option>" +
              '<option value="kk-KZ"' + (locale === "kk-KZ" ? " selected" : "") + ">Қазақша</option>" +
            "</select>" +
            '<span class="hint">Интерфейс Studio пока только на русском — переключается лишь запись чисел и дат.</span></div>' +
          "</div></div>" +

          '<div class="card"><div class="card-head"><h3>Анализ</h3></div><div class="card-body">' +
            '<div class="field"><label for="setAlgo">Алгоритм построения модели</label>' +
            '<select id="setAlgo">' + algoOptions() + "</select></div>" +
            '<div class="field"><label for="setLog">Журнал событий</label><select id="setLog">' +
              (state.logs.length ? state.logs.map(function (log) {
                return '<option value="' + esc(log.log_id) + '"' + (log.log_id === state.logId ? " selected" : "") + ">" +
                  esc(log.name) + " (" + num(log.events) + ")</option>";
              }).join("") : "<option>нет журналов</option>") +
            "</select></div>" +
            '<div class="btn-row"><button class="btn" id="applySettings" type="button">Применить</button></div>' +
          "</div></div>" +
        "</div>" +

        '<div class="card"><div class="card-head"><h3>Доступ</h3></div><div class="card-body">' +
          '<div class="field"><label for="setKey">API-ключ</label>' +
          '<input type="password" id="setKey" value="' + esc(api.key) + '" placeholder="ключ или временный пропуск" autocomplete="off">' +
          '<span class="hint">Хранится только в этом браузере. Пропуск из КМС начинается с «c1.» и живёт ограниченное время.</span></div>' +
          '<div class="btn-row"><button class="btn secondary" id="saveKey" type="button">Сохранить ключ</button>' +
          '<button class="btn danger" id="dropKey" type="button">' + icon("trash") + " Забыть ключ</button></div>" +
        "</div></div>" +

        '<div class="card"><div class="card-head"><h3>О сервисе</h3></div>' +
          '<div class="card-body flush"><div class="stat-row" style="border-bottom:0">' +
          "<div><b>" + esc(state.version || "—") + "</b><span>Версия сервиса</span></div>" +
          "<div><b>" + (state.online ? "на связи" : "нет связи") + "</b><span>Состояние</span></div>" +
          "<div><b>" + num(state.logs.length) + "</b><span>Журналов</span></div>" +
          "<div><b>" + num(MAX_EVENTS) + "</b><span>Предел выгрузки событий</span></div>" +
        "</div></div></div>" +
      "</section>"
    );
  }

  function afterSettings() {
    var dark = $("setDark");
    if (dark) dark.addEventListener("change", function () { setTheme(dark.checked ? "dark" : "light"); });

    var loc = $("setLocale");
    if (loc) loc.addEventListener("change", function () {
      locale = loc.value;
      store.set("pm-studio-locale", locale);
      var select = $("language");
      if (select) select.value = locale.slice(0, 2);
      render();
    });

    var apply = $("applySettings");
    if (apply) apply.addEventListener("click", function () {
      var algo = $("setAlgo"), log = $("setLog");
      if (algo) { state.algorithm = algo.value; store.set("pm-studio-algo", state.algorithm); }
      if (log && log.value && log.value !== state.logId) {
        state.logId = log.value;
        store.set("pm-studio-log", state.logId);
        resetPaging();
      }
      loadCore();
      toast("Применено", "good");
    });

    var save = $("saveKey");
    if (save) save.addEventListener("click", function () {
      var field = $("setKey");
      api.key = field.value.trim();
      store.set("pm-api-key", api.key);
      toast("Ключ сохранён", "good");
      boot();
    });
    var drop = $("dropKey");
    if (drop) drop.addEventListener("click", function () {
      api.key = "";
      store.set("pm-api-key", "");
      var field = $("setKey");
      if (field) field.value = "";
      toast("Ключ удалён");
      boot();
    });
  }

  // ---------------------------------------------------------- заглушки

  function skeletonPage() {
    if (state.error) {
      return '<section class="surface page"><div class="empty-state">' + icon("alert") +
        "<h3>Не удалось получить данные</h3><p>" + esc(state.error) + "</p>" +
        '<div class="btn-row"><button class="btn" id="retryLoad" type="button">Повторить</button>' +
        (state.authRequired ? '<button class="btn secondary" id="errKeys" type="button">Ввести ключ</button>' : "") +
        "</div></div></section>";
    }
    /* Пустой список журналов и закрытый доступ выглядят одинаково - экран без
     * данных, - но чинятся по-разному. Не разделив их, мы предлагали загрузить
     * файл человеку, которому просто нужен пропуск. */
    if (state.authRequired && !api.key) {
      return '<section class="surface page"><div class="empty-state">' + icon("key") +
        "<h3>Нужен доступ</h3><p>Сервис закрыт ключом. Откройте консоль ссылкой «Открыть консоль» из КМС — " +
        "она принесёт временный пропуск, вводить ничего не придётся. Либо введите ключ вручную.</p>" +
        '<button class="btn" id="emptyKeys" type="button">' + icon("key") + " Ввести ключ</button></div></section>";
    }
    if (!state.logId && !state.loading) {
      return '<section class="surface page"><div class="empty-state">' + icon("inbox") +
        "<h3>Нет журналов событий</h3><p>Загрузите файл в разделе «Источники данных» — карта, показатели и кейсы соберутся сами.</p>" +
        '<button class="btn" data-goto="sources" type="button">' + icon("upload") + " Перейти к загрузке</button></div></section>";
    }
    var block = function (h) { return '<div class="skeleton" style="height:' + h + 'px"></div>'; };
    return '<section class="surface page"><div class="skeleton sk-value"></div>' +
      '<div class="kpis">' + block(104) + block(104) + block(104) + block(104) + "</div>" +
      '<div class="cols cols-2-1">' + block(430) + block(430) + "</div>" +
      '<div class="cols cols-1-1">' + block(240) + block(240) + "</div></section>";
  }

  // ============================================================ оболочка

  function userName() { return store.get("pm-studio-user", "Admin"); }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    store.set("pm-studio-theme", theme);
  }

  function renderNav() {
    var current = currentRoute();
    $("railNav").innerHTML = ROUTES.map(function (route) {
      if (route.group) return '<div class="nav-group">' + esc(t(route.group)) + "</div>";
      var count = "";
      if (route.id === "cases" && state.cases.length) count = '<span class="nav-count">' + num(state.cases.length) + "</span>";
      if (route.id === "events" && state.events.length) count = '<span class="nav-count">' + num(state.events.length) + "</span>";
      if (route.id === "dashboards" && savedViews().length) count = '<span class="nav-count">' + savedViews().length + "</span>";
      return '<button class="nav-item' + (route.id === current ? " is-active" : "") + '" data-goto="' + route.id + '" type="button">' +
        icon(route.icon) + "<span>" + esc(t(route.label)) + "</span>" + count + "</button>";
    }).join("");
  }

  function currentRoute() {
    var hash = location.hash.replace(/^#\/?/, "").split("?")[0];
    return routeById(hash) ? hash : "overview";
  }

  function go(id) {
    location.hash = "#/" + id;
  }

  var AFTER = {
    overview: afterOverview, map: afterMap, events: afterEvents, analysis: afterAnalysis,
    analyst: afterAnalyst, cases: afterCases, metrics: afterMetrics, predictions: afterPredictions,
    dashboards: afterDashboards, sources: afterSources, integrations: afterIntegrations,
    settings: afterSettings,
  };

  function render() {
    var id = currentRoute();
    var route = routeById(id);
    var view = $("view");

    mapControl = null;
    view.innerHTML = route.render();
    renderNav();
    $("crumb").textContent = t(route.label);
    document.title = t(route.label) + " — Process Mining Studio";

    var retry = $("retryLoad");
    if (retry) retry.addEventListener("click", function () { state.error = ""; boot(); });
    ["errKeys", "emptyKeys"].forEach(function (id) {
      var button = $(id);
      if (button) button.addEventListener("click", openKeys);
    });

    if (AFTER[id]) AFTER[id]();
    refreshBell();
  }

  function resetPaging() {
    eventPage = 0; casePage = 0; eventQuery = ""; caseFilter = ""; caseStatus = "all";
  }

  // -------------------------------------------------------- шторка и тосты

  function openSheet(title, html) {
    $("sheetTitle").textContent = title;
    $("sheetBody").innerHTML = html;
    $("sheet").hidden = false;
    $("scrim").hidden = false;
  }
  function closeSheet() {
    $("sheet").hidden = true;
    $("scrim").hidden = true;
  }

  function openFilters() {
    var activities = ((state.stats && state.stats.activity_stats) || []).map(function (item) { return item.activity; });
    var resources = ((state.stats && state.stats.resource_stats) || []).map(function (item) { return item.resource; });
    var bounds = state.summary || {};
    var minDay = bounds.start_time ? String(bounds.start_time).slice(0, 10) : "";
    var maxDay = bounds.end_time ? String(bounds.end_time).slice(0, 10) : "";

    function boxes(list, chosen, name) {
      if (!list.length) return '<span class="hint">нет данных</span>';
      return '<div style="display:grid;gap:7px;max-height:190px;overflow-y:auto">' + list.map(function (value) {
        var on = chosen.indexOf(value) !== -1;
        return '<label class="switch" style="gap:9px"><input type="checkbox" data-' + name + '="' + esc(value) + '"' +
          (on ? " checked" : "") + '><span class="track"></span><span style="font-size:13px">' + esc(value) + "</span></label>";
      }).join("") + "</div>";
    }

    openSheet("Отбор данных", (
      '<div class="field"><label>Период</label><div class="field-row">' +
        '<input type="date" id="fFrom" value="' + esc(filters.dateFrom) + '" min="' + minDay + '" max="' + maxDay + '">' +
        '<input type="date" id="fTo" value="' + esc(filters.dateTo) + '" min="' + minDay + '" max="' + maxDay + '">' +
      '</div><span class="hint">Журнал: ' + esc(minDay || "—") + " – " + esc(maxDay || "—") + "</span></div>" +

      '<div class="field"><label>Активности</label>' + boxes(activities, filters.activities || [], "activity") + "</div>" +
      (resources.length ? '<div class="field"><label>Исполнители</label>' + boxes(resources, filters.resources || [], "resource") + "</div>" : "") +

      '<div class="field"><label for="fCoverage">Охват маршрутов</label><select id="fCoverage">' +
        ['', "0.95", "0.9", "0.8", "0.5"].map(function (value) {
          var label = value ? "самые частые маршруты до " + Math.round(value * 100) + " % кейсов" : "все маршруты";
          return '<option value="' + value + '"' + (String(filters.coverage) === value ? " selected" : "") + ">" + label + "</option>";
        }).join("") +
      '</select><span class="hint">Считается на сервере: отбрасываются целые варианты. ' +
      "Влияет на карту, маршруты и узкие места; список кейсов остаётся полным.</span></div>" +

      '<div class="btn-row"><button class="btn" id="fApply" type="button">Применить</button>' +
      '<button class="btn secondary" id="fReset" type="button">Сбросить</button></div>'
    ));

    var apply = $("fApply");
    if (apply) apply.addEventListener("click", function () {
      filters.dateFrom = $("fFrom").value;
      filters.dateTo = $("fTo").value;
      filters.coverage = $("fCoverage").value;
      filters.activities = [].slice.call(document.querySelectorAll("[data-activity]:checked"))
        .map(function (box) { return box.dataset.activity; });
      filters.resources = [].slice.call(document.querySelectorAll("[data-resource]:checked"))
        .map(function (box) { return box.dataset.resource; });
      saveFilters();
      closeSheet();
      resetPaging();
      loadCore();
    });
    var reset = $("fReset");
    if (reset) reset.addEventListener("click", function () {
      filters = { dateFrom: "", dateTo: "", activities: [], resources: [], coverage: "" };
      saveFilters();
      closeSheet();
      resetPaging();
      loadCore();
    });
  }

  /* Что требует внимания.
   *
   * Колокольчик раньше просто перебрасывал в раздел «Анализ». Значок обещает
   * список - и должен его показывать, а не уводить туда, где читателю снова
   * искать глазами, из-за чего он загорелся.
   */
  /* Что считать непрочитанным.
   *
   * Гасить значок навсегда после первого открытия нельзя: узкие места
   * меняются вместе с данными, и новое затерялось бы в тишине. Поэтому
   * помним не «открывал ли», а какие именно находки человек видел, - и
   * считаем непрочитанным то, чего в этом списке нет.
   *
   * Ключ привязан к журналу: в другом журнале шаг с тем же названием - другая
   * находка, и показать её надо заново.
   */
  function findingList() {
    var necks = ((state.necks && state.necks.bottlenecks) || []).slice(0, 4);
    var rework = ((state.necks && state.necks.rework) || []).slice(0, 3);
    return { necks: necks, rework: rework };
  }

  function findingKeys() {
    var found = findingList();
    return found.necks.map(function (neck) { return "n:" + neckLabel(neck); })
      .concat(found.rework.map(function (item) { return "r:" + item.activity; }));
  }

  function seenKey() { return "pm-studio-seen:" + (state.logId || "-"); }

  function unreadFindings() {
    var seen = store.json(seenKey(), []);
    return findingKeys().filter(function (key) { return seen.indexOf(key) === -1; });
  }

  function markFindingsSeen() {
    store.set(seenKey(), JSON.stringify(findingKeys()));
    refreshBell();
  }

  function refreshBell() {
    var badge = $("bellBadge");
    if (!badge) return;
    var unread = unreadFindings().length;
    badge.hidden = !unread;
    badge.textContent = unread || "";
  }

  function openFindings() {
    var box = $("findings");
    var button = $("bellBtn");
    if (!box) return;
    if (!box.hidden) return closeFindings();

    var found = findingList();
    var necks = found.necks;
    var rework = found.rework;
    // Считаем ДО пометки прочитанными - иначе к моменту отрисовки новых уже нет.
    var fresh = unreadFindings();
    var isNew = function (key) { return fresh.indexOf(key) !== -1; };

    if (!necks.length && !rework.length) {
      box.innerHTML = '<p class="empty">' +
        (hasData()
          ? "Ни узких мест, ни возвратов не нашлось — процесс идёт ровно."
          : "Данных пока нет. Загрузите журнал, и находки появятся здесь.") + "</p>";
    } else {
      var rows = necks.map(function (neck) {
        var problem = neckProblem(neck);
        return {
          fresh: isNew("n:" + neckLabel(neck)),
          html: '<b>' + esc(neckLabel(neck)) + "</b>" +
            '<span class="tag" data-tone="' + problem.tone + '">' + pct(neck.share_of_total_time, 0) + "</span>" +
            "<span>" + esc(problem.text) + " · " + dur(neck.median_duration_seconds) + "</span>",
        };
      }).concat(rework.map(function (item) {
        return {
          fresh: isNew("r:" + item.activity),
          html: '<b>' + esc(item.activity) + "</b>" +
            '<span class="tag" data-tone="amber">×' + num(item.total_repetitions) + "</span>" +
            "<span>повторы в " + num(item.cases_with_rework) + " кейсах</span>",
        };
      }));

      var draw = function (list, cls) {
        return list.map(function (row) {
          return '<button class="finding' + cls + '" type="button">' + row.html + "</button>";
        }).join("");
      };
      var freshRows = rows.filter(function (row) { return row.fresh; });
      var oldRows = rows.filter(function (row) { return !row.fresh; });

      // Новое сверху и с пометкой; прежнее - ниже, под своим заголовком. Так
      // видно, что именно добавилось, не сверяясь с памятью.
      box.innerHTML =
        (freshRows.length ? '<div class="group">Новое</div>' + draw(freshRows, " is-new") : "") +
        (oldRows.length ? (freshRows.length ? '<div class="group">Просмотрено ранее</div>' : "") + draw(oldRows, "") : "") +
        '<button class="foot" type="button">Открыть анализ →</button>';
    }

    box.hidden = false;
    button.setAttribute("aria-expanded", "true");
    markFindingsSeen();
    box.querySelectorAll("button").forEach(function (element) {
      element.addEventListener("click", function () { closeFindings(); go("analysis"); });
    });
    // Закрытие по щелчку мимо. Слушатель ставится следующим кадром, иначе он
    // поймает тот же щелчок, которым выноску открыли, и она мигнёт.
    window.setTimeout(function () { document.addEventListener("click", outsideFindings); }, 0);
  }

  function closeFindings() {
    var box = $("findings");
    if (!box || box.hidden) return;
    box.hidden = true;
    $("bellBtn").setAttribute("aria-expanded", "false");
    document.removeEventListener("click", outsideFindings);
  }

  function outsideFindings(event) {
    var wrap = document.querySelector(".bell-wrap");
    if (wrap && !wrap.contains(event.target)) closeFindings();
  }

  function openKeys() {
    openSheet("Доступ к API", (
      '<div class="field"><label for="sheetKey">API-ключ или временный пропуск</label>' +
      '<input type="password" id="sheetKey" value="' + esc(api.key) + '" autocomplete="off" placeholder="X-API-Key"></div>' +
      '<div class="note">Ключ хранится только в этом браузере и уходит лишь на этот сервис. ' +
      "Ссылка из КМС приносит временный пропуск — вводить ничего не нужно.</div>" +
      '<div class="btn-row"><button class="btn" id="sheetKeySave" type="button">Сохранить</button>' +
      '<a class="btn secondary" href="/docs" target="_blank" rel="noopener">Справочник API</a></div>'
    ));
    var save = $("sheetKeySave");
    if (save) save.addEventListener("click", function () {
      api.key = $("sheetKey").value.trim();
      store.set("pm-api-key", api.key);
      closeSheet();
      toast("Ключ сохранён", "good");
      boot();
    });
  }

  function toast(message, tone) {
    var node = document.createElement("div");
    node.className = "toast";
    if (tone) node.dataset.tone = tone;
    node.textContent = message;
    $("toasts").appendChild(node);
    setTimeout(function () { node.remove(); }, 4200);
  }

  // ------------------------------------------------------------- состояние

  function setStatus(stateName, text) {
    var pill = $("apiStatus");
    pill.dataset.state = stateName;
    $("apiStatusText").textContent = text;
  }

  function checkHealth() {
    return fetch("/health/ready", { headers: { Accept: "application/json" } })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        state.online = true;
        state.version = payload.version;
        // Поле называется auth_enabled. Читая несуществующее checks.auth, мы
        // всегда получали false: консоль рисовала зелёное "API подключен" там,
        // где ключа нет, и молча показывала пустой экран вместо приглашения.
        state.authRequired = Boolean(payload.checks && payload.checks.auth_enabled);
        if (state.authRequired && !api.key) {
          setStatus("auth", "Нужен ключ");
          return false;
        }
        setStatus("online", "API подключен");
        return true;
      })
      .catch(function () {
        state.online = false;
        setStatus("offline", "Сервис недоступен");
        return false;
      });
  }

  function boot() {
    return checkHealth().then(function (ready) {
      if (!ready) { state.error = ""; render(); return; }
      return loadLogs().then(function () { return loadCore(); });
    }).catch(function (error) {
      /* Список журналов - первый запрос, требующий ключа. Без этой ветки его
       * отказ никто не ловил, и человек видел "Нет журналов событий" там, где
       * дело было в отсутствующем пропуске. */
      if (error && (error.status === 401 || error.status === 403)) {
        state.authRequired = true;
        state.logs = [];
        state.logId = "";
        setStatus("auth", "Нужен ключ");
      } else if (error) {
        state.error = error.message;
      }
      render();
    });
  }

  // ------------------------------------------------------------- запуск

  /* Пропуск приходит якорем "#t=...", а якорь у нас занят маршрутом. Читаем его
   * и сразу стираем: иначе он осядет в закладке и в пересланной ссылке, а
   * маршрутизатор споткнётся о неизвестный раздел.
   *
   * Вызывается и при запуске, и на смену якоря. Одного запуска мало: если
   * консоль уже открыта, переход по ссылке из КМС на тот же адрес меняет только
   * якорь, страница не перезагружается - и пропуск проходил мимо. */
  function takePassFromLink() {
    var token = new URLSearchParams(location.hash.replace(/^#\/?/, "")).get("t");
    if (!token) return false;
    store.set("pm-api-key", token);
    api.key = token;
    history.replaceState(null, "", location.pathname + location.search + "#/overview");
    return true;
  }

  function init() {
    setTheme(store.get("pm-studio-theme", "dark"));

    takePassFromLink();
    api.key = store.get("pm-api-key", "");

    var languageSelect = $("language");
    languageSelect.value = i18n.lang;
    languageSelect.addEventListener("change", function (event) {
      i18n.setLang(event.target.value);
      // Перерисовываем всё: подписи разложены по разделам, и подменять их
      // на месте пришлось бы тем же обходом дерева, от которого ушли.
      render();
      paintChat();
    });

    $("railToggle").addEventListener("click", function () {
      document.body.classList.toggle("rail-collapsed");
      store.set("pm-studio-rail", document.body.classList.contains("rail-collapsed") ? "1" : "0");
    });
    if (store.get("pm-studio-rail", "0") === "1") document.body.classList.add("rail-collapsed");

    /* Переходы ловим на документе, а не на перерисованных узлах. Пункты меню
     * живут в боковой колонке, а не внутри #view, и навешивание обработчиков
     * "на то, что сейчас в #view" молча оставляло всё меню мёртвым. */
    document.addEventListener("click", function (event) {
      var target = event.target.closest ? event.target.closest("[data-goto]") : null;
      if (target) go(target.dataset.goto);
    });

    $("railOpen").addEventListener("click", function () { document.body.classList.toggle("rail-open"); });
    $("scrim").addEventListener("click", closeSheet);
    $("sheetClose").addEventListener("click", closeSheet);
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      closeSheet();
      closeFindings();
      if (askOpen()) closeAsk();
    });

    $("themeToggle").addEventListener("click", function () {
      setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
    });
    $("keysBtn").addEventListener("click", openKeys);
    $("helpBtn").addEventListener("click", function () { go("integrations"); });
    $("newBtn").addEventListener("click", function () { go("sources"); });
    $("userCard").addEventListener("click", function () { go("settings"); });
    $("bellBtn").addEventListener("click", openFindings);
    bindAsk();

    $("filePicker").addEventListener("change", function (event) {
      if (event.target.files && event.target.files[0]) uploadFile(event.target.files[0]);
      event.target.value = "";
    });

    window.addEventListener("hashchange", function () {
      document.body.classList.remove("rail-open");
      closeFindings();
      if (takePassFromLink()) {
        toast("Пропуск принят", "good");
        boot();
        return; // boot перерисует сам, когда данные приедут
      }
      render();
    });

    onChange(function () {
      render();
      // Колокольчик отмечает узкие места - единственное, что стоит внимания.
      refreshBell();
    });

    if (!location.hash) location.hash = "#/overview";
    render();
    boot();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
