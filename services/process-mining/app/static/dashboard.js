/* Панель управления: боковое меню и панели, которых нет в app.js.
 *
 * Ничего не считает сам и никуда не ходит. Всё, что здесь показывается,
 * прочитано из таблиц, которые app.js уже отрисовал: маршруты, узкие места,
 * активности, показатели. Отсюда два следствия.
 *
 * Первое: ни одной выдуманной величины. На макете были «+12.5% с прошлого
 * месяца» - сравнивать не с чем, в журнале нет прошлого месяца, и таких
 * подписей здесь нет. Спарклайн рисуется по настоящему ряду из таблицы, и в
 * подсказке написано, по какому именно.
 *
 * Второе: app.js не тронут. Он длинный, привязан к своим идентификаторам, и
 * вписываться в него ради оформления - верный способ сломать разбор. Связь
 * односторонняя: он рисует, мы читаем.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const rows = (id) => [...document.querySelectorAll("#" + id + " tr")];
  const cells = (tr) => [...tr.children].map((td) => td.textContent.trim());

  /** Число из строки вида "71,7 %" или "1 284". Разделители - любые. */
  function toNumber(text) {
    const cleaned = (text || "").replace(/[^\d,.-]/g, "").replace(/\s/g, "").replace(",", ".");
    const value = parseFloat(cleaned);
    return Number.isFinite(value) ? value : null;
  }

  // ------------------------------------------------------------ спарклайны
  /** Плавная линия по ряду значений. Пустой ряд - пустая картинка. */
  function drawSpark(svg, series, hint) {
    svg.textContent = "";
    svg.removeAttribute("title");
    const values = (series || []).filter((v) => typeof v === "number" && Number.isFinite(v));
    if (values.length < 2) return;

    const W = 120, H = 40, pad = 3;
    const max = Math.max(...values), min = Math.min(...values);
    const span = max - min || 1;
    const step = (W - pad * 2) / (values.length - 1);
    const points = values.map((v, i) => [
      pad + i * step,
      H - pad - ((v - min) / span) * (H - pad * 2),
    ]);

    // Кривая Катмулла-Рома в кубические Безье: ломаная на сорока пикселях
    // читается как шум, сглаженная - как форма.
    let d = `M ${points[0][0]} ${points[0][1]}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i - 1] || points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;
      d += ` C ${p1[0] + (p2[0] - p0[0]) / 6} ${p1[1] + (p2[1] - p0[1]) / 6},` +
           ` ${p2[0] - (p3[0] - p1[0]) / 6} ${p2[1] - (p3[1] - p1[1]) / 6},` +
           ` ${p2[0]} ${p2[1]}`;
    }

    const ns = "http://www.w3.org/2000/svg";
    const accent = svg.closest(".metric")?.dataset.accent || "violet";
    const gradientId = "sparkfill-" + accent;

    if (!svg.ownerDocument.getElementById(gradientId)) {
      const defs = document.createElementNS(ns, "defs");
      const grad = document.createElementNS(ns, "linearGradient");
      grad.setAttribute("id", gradientId);
      grad.setAttribute("x1", "0"); grad.setAttribute("y1", "0");
      grad.setAttribute("x2", "0"); grad.setAttribute("y2", "1");
      for (const [offset, opacity] of [["0", "0.38"], ["1", "0"]]) {
        const stop = document.createElementNS(ns, "stop");
        stop.setAttribute("offset", offset);
        stop.setAttribute("stop-color", "currentColor");
        stop.setAttribute("stop-opacity", opacity);
        grad.appendChild(stop);
      }
      defs.appendChild(grad);
      svg.appendChild(defs);
    }

    const area = document.createElementNS(ns, "path");
    area.setAttribute("d", `${d} L ${W - pad} ${H} L ${pad} ${H} Z`);
    area.setAttribute("fill", `url(#${gradientId})`);
    svg.appendChild(area);

    const line = document.createElementNS(ns, "path");
    line.setAttribute("d", d);
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", "currentColor");
    line.setAttribute("stroke-width", "2");
    line.setAttribute("stroke-linecap", "round");
    line.setAttribute("stroke-linejoin", "round");
    svg.appendChild(line);

    if (hint) {
      const title = document.createElementNS(ns, "title");
      title.textContent = hint;
      svg.appendChild(title);
    }
  }

  // ------------------------------------------------------------- диаграмма
  function drawWaitChart(activities) {
    const box = $("waitChart");
    if (!box) return;
    box.textContent = "";
    if (!activities.length) {
      const empty = document.createElement("div");
      empty.className = "chart-empty";
      empty.textContent = window.I18N ? "" : "";
      empty.dataset.i18n = "perf.empty";
      box.appendChild(empty);
      return;
    }
    const max = Math.max(...activities.map((a) => a.wait || 0)) || 1;
    activities.slice(0, 8).forEach((activity) => {
      const row = document.createElement("div");
      row.className = "chart-row";

      const name = document.createElement("span");
      name.className = "chart-name";
      name.textContent = activity.name;

      const track = document.createElement("span");
      track.className = "chart-track";
      const fill = document.createElement("span");
      fill.className = "chart-fill";
      fill.style.width = Math.max(2, ((activity.wait || 0) / max) * 100) + "%";
      track.appendChild(fill);

      const value = document.createElement("span");
      value.className = "chart-value";
      value.textContent = activity.waitText;

      row.append(name, track, value);
      box.appendChild(row);
    });
  }

  // -------------------------------------------------------------- находки
  function renderInsights(data) {
    const grid = $("insightGrid");
    const section = $("cardInsights");
    if (!grid || !section) return;
    grid.textContent = "";

    const found = [];
    if (data.topBottleneck) {
      found.push({
        tone: "amber",
        icon: "⚠",
        title: "Самый дорогой переход",
        text: `«${data.topBottleneck.name}» занимает ${data.topBottleneck.shareText} всего времени процесса.`,
      });
    }
    if (data.reworkText && data.reworkValue > 0) {
      found.push({
        tone: "rose",
        icon: "↺",
        title: "Повторные шаги",
        text: `${data.reworkText} кейсов проходят какой-то шаг больше одного раза.`,
      });
    }
    if (data.topVariant) {
      found.push({
        tone: "violet",
        icon: "⇉",
        title: "Основной маршрут",
        text: `Самый частый путь покрывает ${data.topVariant.shareText} кейсов из ${data.cases || "—"}.`,
      });
    }
    if (data.slowestActivity) {
      found.push({
        tone: "blue",
        icon: "◷",
        title: "Дольше всего ждут после",
        text: `После шага «${data.slowestActivity.name}» в среднем проходит ${data.slowestActivity.waitText}.`,
      });
    }

    found.forEach((item) => {
      const card = document.createElement("article");
      card.className = "insight";
      card.dataset.tone = item.tone;

      const head = document.createElement("div");
      head.className = "insight-head";
      const icon = document.createElement("span");
      icon.className = "insight-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = item.icon;
      const title = document.createElement("strong");
      title.textContent = item.title;
      head.append(icon, title);

      const text = document.createElement("p");
      text.textContent = item.text;

      card.append(head, text);
      grid.appendChild(card);
    });

    section.hidden = found.length === 0;
  }

  // -------------------------------------------------- сбор того, что есть
  function collect() {
    const variants = rows("variantsBody").map((tr) => {
      const c = cells(tr);
      return { rank: c[0], path: c[1], cases: toNumber(c[2]), shareText: c[3], share: toNumber(c[3]) };
    });
    const bottlenecks = rows("bottlenecksBody").map((tr) => {
      const c = cells(tr);
      return { name: c[0], count: toNumber(c[1]), medianText: c[2], shareText: c[5], share: toNumber(c[5]) };
    });
    const activities = rows("activitiesBody").map((tr) => {
      const c = cells(tr);
      return { name: c[0], events: toNumber(c[1]), cases: toNumber(c[2]), waitText: c[4], wait: toNumber(c[4]) };
    });
    const rework = rows("reworkBody").map((tr) => toNumber(cells(tr)[2]));

    return {
      variants, bottlenecks, activities, rework,
      cases: ($("mCases") || {}).textContent,
      reworkText: ($("mRework") || {}).textContent,
      reworkValue: toNumber(($("mRework") || {}).textContent),
      topBottleneck: bottlenecks[0] || null,
      topVariant: variants[0] || null,
      slowestActivity: activities.slice().sort((a, b) => (b.wait || 0) - (a.wait || 0))[0] || null,
    };
  }

  function refresh() {
    const data = collect();

    document.querySelectorAll("[data-spark]").forEach((svg) => {
      const kind = svg.dataset.spark;
      if (kind === "events") drawSpark(svg, data.activities.map((a) => a.events), "События по активностям");
      if (kind === "cases") drawSpark(svg, data.variants.map((v) => v.cases), "Кейсы по маршрутам");
      if (kind === "cycle") drawSpark(svg, data.bottlenecks.map((b) => b.share), "Доля времени по переходам");
      if (kind === "rework") drawSpark(svg, data.rework.length ? data.rework : data.activities.map((a) => a.cases), "Повторы по активностям");
    });

    const perf = {
      cycle: ($("mCycle") || {}).textContent || "—",
      p95: (($("mP95") || {}).textContent || "").replace(/^p95:\s*/i, "") || "—",
      slowest: data.topBottleneck ? data.topBottleneck.medianText : "—",
      routes: ($("cVariants") || {}).textContent || String(data.variants.length || "—"),
    };
    document.querySelectorAll("[data-perf]").forEach((el) => {
      el.textContent = perf[el.dataset.perf] || "—";
    });

    drawWaitChart(data.activities.slice().sort((a, b) => (b.wait || 0) - (a.wait || 0)));
    renderInsights(data);

    // Точки перед маршрутом: один цвет на активность, как на макете.
    const palette = ["#8b5cf6", "#3b82f6", "#22d3ee", "#10b981", "#f59e0b", "#f43f5e", "#a78bfa", "#38bdf8"];
    const colourOf = new Map();
    rows("variantsBody").forEach((tr) => {
      const cell = tr.children[1];
      if (!cell || cell.querySelector(".path-dots")) return;
      const steps = cell.textContent.split("→").map((s) => s.trim()).filter(Boolean);
      const strip = document.createElement("span");
      strip.className = "path-dots";
      steps.forEach((step) => {
        if (!colourOf.has(step)) colourOf.set(step, palette[colourOf.size % palette.length]);
        const dot = document.createElement("i");
        dot.style.background = colourOf.get(step);
        dot.title = step;
        strip.appendChild(dot);
      });
      cell.prepend(strip);
    });

    // Полоса тяжести рядом с долей времени.
    rows("bottlenecksBody").forEach((tr) => {
      const cell = tr.children[5];
      if (!cell || cell.querySelector(".sev")) return;
      const share = toNumber(cell.textContent) || 0;
      const bar = document.createElement("span");
      bar.className = "sev";
      const fill = document.createElement("i");
      fill.style.width = Math.min(100, share) + "%";
      fill.dataset.level = share >= 30 ? "high" : share >= 15 ? "mid" : "low";
      bar.appendChild(fill);
      cell.prepend(bar);
    });

    ["Variants", "Bottlenecks", "Activities"].forEach((name) => {
      const target = $("rail" + name);
      const source = $("c" + name);
      if (target && source) target.textContent = source.textContent;
    });

    const chip = $("rangeChip");
    const chipText = $("rangeChipText");
    const range = ($("mEventsSub") || {}).textContent || "";
    if (chip && chipText && range.includes("→")) {
      chipText.textContent = range;
      chip.hidden = false;
    }
  }

  // ---------------------------------------------------------- боковое меню
  function wireRail() {
    document.querySelectorAll(".rail-item").forEach((item) => {
      item.addEventListener("click", () => {
        document.querySelectorAll(".rail-item").forEach((i) => i.classList.remove("is-active"));
        item.classList.add("is-active");

        // Вкладки скрыты, но app.js держится за них: поиск по карте и её
        // инструменты включаются только когда выбрана вкладка карты.
        const tab = item.dataset.tab;
        if (tab) {
          const button = document.querySelector(`.tab[data-tab="${tab}"]`);
          if (button) button.click();
        }
        const target = $(item.dataset.goto);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
        document.body.classList.remove("rail-open");
      });
    });

    $("railToggle")?.addEventListener("click", () => {
      document.body.classList.toggle("rail-collapsed");
    });
    $("railOpen")?.addEventListener("click", () => {
      document.body.classList.toggle("rail-open");
    });
  }

  function start() {
    wireRail();
    refresh();
    // app.js перерисовывает таблицы, когда приходит ответ; отдельного события
    // он не шлёт, поэтому следим за самими таблицами.
    const watch = ["variantsBody", "bottlenecksBody", "activitiesBody", "reworkBody"]
      .map($).filter(Boolean);
    const observer = new MutationObserver(() => refresh());
    watch.forEach((node) => observer.observe(node, { childList: true, subtree: true }));
    const metrics = $("mEvents");
    if (metrics) observer.observe(metrics, { childList: true, characterData: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
