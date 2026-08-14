/* Карта процесса: раскладка и отрисовка.
 *
 * Граф приходит из API как узлы и рёбра (format=json), а не картинкой. Картинку
 * рисует Graphviz, и она приходит чёрным по белому - перекрасить её под тёмную
 * тему нечем, у нас нет контроля над её внутренностями. Поэтому раскладку
 * считаем сами: тогда узел - это обычный SVG-прямоугольник, который слушается
 * CSS, подсвечивается и кликается.
 *
 * Раскладка послойная (упрощённый Сугияма): слой = самый длинный путь от входа,
 * порядок внутри слоя подбирается барицентром по соседям. Точного минимума
 * пересечений это не даёт, но для графов процесса в два-три десятка узлов
 * разница незаметна, а считается мгновенно и без зависимостей.
 *
 * Состав узла - как принято в процессной аналитике: доля кейсов кружком слева,
 * название, под ним главная величина. Начало и конец процесса - отдельные узлы
 * со счётчиком кейсов, а не просто первая и последняя активность: иначе не
 * видно, сколько кейсов здесь стартовало и сколько дошло до конца.
 */
window.ProcMap = (function () {
  "use strict";

  var NODE_W = 208;
  var NODE_H = 58;
  var TERM_W = 152;
  var TERM_H = 42;
  var GAP_X = 34;
  var GAP_Y = 62;
  var PAD = 52;

  var SVG_NS = "http://www.w3.org/2000/svg";

  /* Разделитель ключа "откуда-куда". Собирается из кода символа, а не пишется
   * в исходник как есть: сырой ноль делает файл для git бинарным, и diff по
   * нему перестаёт показываться. В названиях активностей такого символа нет. */
  var SEP = String.fromCharCode(0);

  var START_ID = SEP + "start";
  var FINISH_ID = SEP + "finish";

  function el(name, attrs, text) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
      if (attrs[key] !== null && attrs[key] !== undefined) node.setAttribute(key, attrs[key]);
    }
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function shortDuration(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return "";
    var s = Math.max(0, Number(seconds));
    var round = function (value, digits) {
      return value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
    };
    if (s < 60) return round(s, 0) + " с";
    if (s < 3600) return round(s / 60, 0) + " мин";
    if (s < 86400) return round(s / 3600, 1) + " ч";
    if (s < 86400 * 30) return round(s / 86400, 1) + " дн.";
    return round(s / (86400 * 30), 1) + " мес.";
  }

  function shortCount(value) {
    return Number(value || 0).toLocaleString("ru-RU");
  }

  /* ------------------------------------------------------------ раскладка */

  /* Обратные рёбра ищем обходом в глубину: ребро в узел, который сейчас в
   * стеке, замыкает цикл. Их нельзя учитывать при расчёте слоёв - иначе
   * "самый длинный путь" уходит в бесконечность. */
  function findBackEdges(ids, out) {
    var state = {};
    var back = {};
    ids.forEach(function (id) { state[id] = 0; });

    function visit(id) {
      state[id] = 1;
      (out[id] || []).forEach(function (edge) {
        if (state[edge.target] === 1) back[edge.source + SEP + edge.target] = true;
        else if (state[edge.target] === 0) visit(edge.target);
      });
      state[id] = 2;
    }
    ids.forEach(function (id) { if (state[id] === 0) visit(id); });
    return back;
  }

  function layout(graph, options) {
    options = options || {};
    var nodes = (graph && graph.nodes) || [];
    var edges = (graph && graph.edges) || [];
    if (!nodes.length) return null;

    var byId = {};
    var ids = [];
    nodes.forEach(function (n) {
      if (byId[n.id]) return;
      var silent = Boolean(n.metrics && n.metrics.silent) || (n.type === "transition" && !n.label);
      byId[n.id] = {
        id: n.id,
        label: n.label || (n.type === "place" ? "" : n.id),
        kind: n.type === "place" ? "place" : (silent ? "silent" : "activity"),
        freq: n.frequency || 0,
        cases: (n.metrics && n.metrics.cases) || 0,
      };
      ids.push(n.id);
    });

    /* Начало и конец процесса. Только для графа переходов: у сети Петри и
     * дерева процесса концы графа - это позиции, они уже нарисованы, и вторая
     * пара терминалов рядом означала бы одно и то же дважды. */
    var starts = graph.start_activities || {};
    var ends = graph.end_activities || {};
    var terminals = options.terminals !== false &&
      Object.keys(starts).some(function (name) { return byId[name] && byId[name].kind === "activity"; });

    var extra = [];
    if (terminals) {
      var started = 0, finished = 0;
      Object.keys(starts).forEach(function (name) {
        if (!byId[name]) return;
        started += starts[name];
        extra.push({ source: START_ID, target: name, freq: starts[name], terminal: true });
      });
      Object.keys(ends).forEach(function (name) {
        if (!byId[name]) return;
        finished += ends[name];
        extra.push({ source: name, target: FINISH_ID, freq: ends[name], terminal: true });
      });
      byId[START_ID] = { id: START_ID, label: "Начало процесса", kind: "start", freq: started, cases: started };
      byId[FINISH_ID] = { id: FINISH_ID, label: "Конец процесса", kind: "finish", freq: finished, cases: finished };
      ids.unshift(START_ID);
      ids.push(FINISH_ID);
    }

    var out = {}, inn = {};
    var clean = [];
    edges.forEach(function (e) {
      if (e.source === e.target) {
        // Петля: рисуется дугой у самого узла, в раскладку слоёв не идёт.
        if (byId[e.source]) {
          byId[e.source].loop = {
            freq: e.frequency || 0, mean: e.mean_duration_seconds, median: e.median_duration_seconds,
          };
        }
        return;
      }
      if (!byId[e.source] || !byId[e.target]) return;
      clean.push({
        source: e.source, target: e.target, freq: e.frequency || 0,
        mean: e.mean_duration_seconds, median: e.median_duration_seconds,
      });
    });
    extra.forEach(function (e) { clean.push(e); });
    clean.forEach(function (e) {
      (out[e.source] = out[e.source] || []).push(e);
      (inn[e.target] = inn[e.target] || []).push(e);
    });

    var back = findBackEdges(ids, out);
    clean.forEach(function (e) { e.back = !!back[e.source + SEP + e.target]; });

    // Слой = длина самого длинного пути от узла без входящих рёбер.
    var layer = {};
    ids.forEach(function (id) { layer[id] = 0; });
    var roots = ids.filter(function (id) {
      return !(inn[id] || []).some(function (e) { return !e.back; });
    });
    if (!roots.length) roots = [ids[0]];

    var queue = roots.slice();
    var guard = ids.length * ids.length + 64;
    while (queue.length && guard-- > 0) {
      var id = queue.shift();
      (out[id] || []).forEach(function (e) {
        if (e.back) return;
        if (layer[e.target] < layer[id] + 1) {
          layer[e.target] = layer[id] + 1;
          queue.push(e.target);
        }
      });
    }
    // Конец процесса всегда внизу, даже если часть кейсов обрывается раньше.
    if (terminals) {
      var deepest = 0;
      ids.forEach(function (id) { if (id !== FINISH_ID && layer[id] > deepest) deepest = layer[id]; });
      layer[FINISH_ID] = deepest + 1;
    }

    var rows = [];
    ids.forEach(function (id) {
      var lv = layer[id];
      (rows[lv] = rows[lv] || []).push(id);
    });
    rows.forEach(function (row) {
      row.sort(function (a, b) { return byId[b].freq - byId[a].freq; });
    });

    // Барицентр: узел тянется к среднему положению соседей на соседнем слое.
    // Четырёх проходов хватает, дальше картинка перестаёт меняться.
    for (var pass = 0; pass < 4; pass++) {
      var downward = pass % 2 === 0;
      var order = downward ? rows : rows.slice().reverse();
      order.forEach(function (row, index) {
        if (!row || (downward && index === 0)) return;
        var pos = {};
        rows.forEach(function (r) { (r || []).forEach(function (id, i) { pos[id] = i; }); });
        var score = {};
        row.forEach(function (id) {
          var neighbours = (downward ? inn[id] : out[id]) || [];
          var values = neighbours.filter(function (e) { return !e.back; })
            .map(function (e) { return pos[downward ? e.source : e.target]; })
            .filter(function (v) { return v !== undefined; });
          score[id] = values.length
            ? values.reduce(function (a, b) { return a + b; }, 0) / values.length
            : pos[id];
        });
        row.sort(function (a, b) { return score[a] - score[b]; });
      });
    }

    ids.forEach(function (id) {
      var node = byId[id];
      if (node.kind === "place") { node.w = 30; node.h = 30; }
      else if (node.kind === "silent") { node.w = 46; node.h = 30; }
      else if (node.kind === "start" || node.kind === "finish") { node.w = TERM_W; node.h = TERM_H; }
      else { node.w = NODE_W; node.h = NODE_H; }
    });

    var width = 0;
    rows.forEach(function (row) {
      if (!row) return;
      var rowWidth = row.reduce(function (sum, id) { return sum + byId[id].w; }, 0) + (row.length - 1) * GAP_X;
      if (rowWidth > width) width = rowWidth;
    });

    var top = PAD;
    rows.forEach(function (row, lv) {
      if (!row) return;
      var rowHeight = row.reduce(function (max, id) { return Math.max(max, byId[id].h); }, 0);
      var rowWidth = row.reduce(function (sum, id) { return sum + byId[id].w; }, 0) + (row.length - 1) * GAP_X;
      var left = PAD + (width - rowWidth) / 2;
      row.forEach(function (id) {
        var node = byId[id];
        node.x = left;
        node.y = top + (rowHeight - node.h) / 2;
        node.layer = lv;
        left += node.w + GAP_X;
      });
      top += rowHeight + GAP_Y;
    });

    return {
      nodes: ids.map(function (id) { return byId[id]; }),
      edges: clean,
      byId: byId,
      // Запас справа под дуги возвратов и петель.
      width: width + PAD * 2 + 56,
      height: top - GAP_Y + PAD,
    };
  }

  /* ----------------------------------------------------------- отрисовка */

  function truncate(text, max) {
    return text.length > max ? text.slice(0, max - 1) + "…" : text;
  }

  function edgeGeometry(a, b) {
    if (b.layer <= a.layer) {
      // Возврат: ведём сбоку, чтобы дуга не легла поверх прямых стрелок.
      var side = Math.max(a.x + a.w, b.x + b.w) + 36;
      return {
        d: "M" + (a.x + a.w) + " " + (a.y + a.h / 2) +
          " C" + side + " " + (a.y + a.h / 2) + " " + side + " " + (b.y + b.h / 2) +
          " " + (b.x + b.w + 8) + " " + (b.y + b.h / 2),
        label: [side - 2, (a.y + a.h / 2 + b.y + b.h / 2) / 2],
        anchor: "start",
      };
    }
    var x1 = a.x + a.w / 2, y1 = a.y + a.h;
    var x2 = b.x + b.w / 2, y2 = b.y - 8;
    var mid = (y1 + y2) / 2;
    return {
      d: "M" + x1 + " " + y1 + " C" + x1 + " " + mid + " " + x2 + " " + mid + " " + x2 + " " + y2,
      // У кубической кривой с такими опорами середина приходится ровно на
      // середину отрезка; подпись сдвигаем вбок, чтобы не легла на линию.
      label: [(x1 + x2) / 2 + 8, (y1 + y2) / 2],
      anchor: "start",
    };
  }

  function loopPath(n) {
    var right = n.x + n.w, middle = n.y + n.h / 2;
    return "M" + (right - 16) + " " + (n.y + 3) +
      " C" + (right + 50) + " " + (n.y - 16) +
      " " + (right + 50) + " " + (middle + 16) +
      " " + (right + 3) + " " + (middle + 4);
  }

  /* mode: "frequency" - вес рёбер по числу переходов, "performance" - по времени. */
  function render(target, graph, options) {
    options = options || {};
    var model = layout(graph, options);
    target.textContent = "";
    if (!model) return null;

    var totalCases = options.cases || 0;
    var hot = options.hot || {};
    var durations = options.durations || {};
    var byTime = options.mode === "performance";

    var maxWeight = 1;
    model.edges.forEach(function (e) {
      if (e.terminal) return;
      var value = byTime ? (e.median || e.mean || 0) : e.freq;
      if (value > maxWeight) maxWeight = value;
    });

    var svg = el("svg", {
      width: model.width, height: model.height,
      viewBox: "0 0 " + model.width + " " + model.height,
      xmlns: SVG_NS,
    });

    var defs = el("defs");
    [["arrow", "#5b8cff"], ["arrowHot", "#f43f5e"], ["arrowSoft", "#6a6a86"]].forEach(function (pair) {
      var marker = el("marker", {
        id: "pm-" + pair[0], viewBox: "0 0 10 10", refX: 8, refY: 5,
        markerWidth: 5, markerHeight: 5, orient: "auto-start-reverse",
      });
      marker.appendChild(el("path", { d: "M0 1L9 5L0 9z", fill: pair[1], stroke: "none" }));
      defs.appendChild(marker);
    });
    svg.appendChild(defs);

    var edgeLayer = el("g", { class: "map-edges" });
    model.edges.forEach(function (e) {
      var a = model.byId[e.source], b = model.byId[e.target];
      if (!a || !b) return;
      var geometry = edgeGeometry(a, b);
      var weight = e.terminal ? 0 : (byTime ? (e.median || e.mean || 0) : e.freq) / maxWeight;

      var cls = "map-edge";
      if (e.terminal) cls += " terminal";
      else if (e.back) cls += " loop";
      else if (weight > 0.66) cls += " is-heavy";

      var path = el("path", {
        class: cls,
        d: geometry.d,
        "stroke-width": (e.terminal ? 1.2 : 1.1 + weight * 3.4).toFixed(2),
        "marker-end": e.terminal ? "url(#pm-arrowSoft)"
          : (weight > 0.66 ? "url(#pm-arrowHot)" : "url(#pm-arrow)"),
      });
      path.appendChild(el("title", {}, a.label + " → " + b.label +
        ": " + shortCount(e.freq) + (e.terminal ? " кейсов" : " переходов") +
        (e.median ? ", медиана " + shortDuration(e.median) : "")));

      if (options.onEdge && !e.terminal) {
        path.style.cursor = "pointer";
        path.addEventListener("click", function () { options.onEdge(e); });
      }
      edgeLayer.appendChild(path);

      var caption = e.terminal
        ? shortCount(e.freq)
        : (byTime
          ? shortDuration(e.median !== null && e.median !== undefined ? e.median : e.mean)
          : shortCount(e.freq));
      if (caption) {
        edgeLayer.appendChild(el("text", {
          class: "map-edge-label" + (e.terminal ? " is-terminal" : ""),
          x: geometry.label[0], y: geometry.label[1], "text-anchor": geometry.anchor,
        }, caption));
      }
    });
    svg.appendChild(edgeLayer);

    var nodeLayer = el("g", { class: "map-nodes" });
    model.nodes.forEach(function (n) {
      var group = el("g", { transform: "translate(" + n.x + "," + n.y + ")" });

      if (n.kind === "place") {
        group.setAttribute("class", "node-box is-place" +
          ((graph.start_activities || {})[n.id] ? " is-start" : "") +
          ((graph.end_activities || {})[n.id] ? " is-end" : ""));
        group.appendChild(el("circle", { cx: n.w / 2, cy: n.h / 2, r: n.w / 2 }));
        group.appendChild(el("title", {}, "Позиция сети Петри"));
        nodeLayer.appendChild(group);
        return;
      }

      if (n.kind === "silent") {
        group.setAttribute("class", "node-box is-silent");
        group.appendChild(el("rect", { width: n.w, height: n.h, rx: 6 }));
        group.appendChild(el("title", {}, "Невидимый переход: нужен модели, событий в журнале ему не соответствует"));
        nodeLayer.appendChild(group);
        return;
      }

      if (n.kind === "start" || n.kind === "finish") {
        group.setAttribute("class", "node-term is-" + n.kind);
        group.appendChild(el("circle", { class: "term-mark", cx: 17, cy: n.h / 2, r: 12 }));
        group.appendChild(n.kind === "start"
          ? el("path", { class: "term-icon", d: "M14 " + (n.h / 2 - 5) + "l7 5-7 5z" })
          : el("rect", { class: "term-icon", x: 13, y: n.h / 2 - 4, width: 8, height: 8, rx: 1.5 }));
        group.appendChild(el("text", { class: "term-label", x: 37, y: n.h / 2 - 2 }, n.label));
        group.appendChild(el("text", { class: "term-count", x: 37, y: n.h / 2 + 12 },
          shortCount(n.cases) + " кейсов"));
        nodeLayer.appendChild(group);
        return;
      }

      // ------------------------------------------------------ активность
      group.setAttribute("class", "node-box" + (hot[n.id] ? " is-hot" : ""));
      group.appendChild(el("rect", { width: n.w, height: n.h, rx: 13 }));

      var share = totalCases ? Math.min(1, n.cases / totalCases) : 0;
      var badge = el("g", { class: "node-badge" });
      // Насыщенность по доле кейсов: беглый взгляд отделяет магистраль процесса
      // от редких ответвлений, не читая чисел.
      badge.appendChild(el("circle", {
        cx: 28, cy: n.h / 2, r: 17,
        style: "fill-opacity:" + (0.2 + share * 0.8).toFixed(2),
      }));
      badge.appendChild(el("text", { x: 28, y: n.h / 2 + 4, "text-anchor": "middle" },
        totalCases ? Math.round(share * 100) + "%" : "—"));
      group.appendChild(badge);

      group.appendChild(el("text", { class: "node-name", x: 55, y: n.h / 2 - 3 }, truncate(n.label, 19)));
      // В режиме времени под названием стоит время, и только оно. Подставлять
      // сюда число событий, когда паузы нет, значило бы смешивать единицы в
      // одном столбце: у последнего шага кейса ждать нечего, так и пишем.
      group.appendChild(el("text", { class: "node-metric", x: 55, y: n.h / 2 + 14 },
        byTime
          ? (durations[n.id] !== undefined ? shortDuration(durations[n.id]) : "нет ожидания")
          : shortCount(n.freq) + " событий"));

      group.appendChild(el("title", {}, n.label +
        " — событий: " + shortCount(n.freq) + ", кейсов: " + shortCount(n.cases) +
        (n.loop ? ", повторов подряд: " + shortCount(n.loop.freq) : "")));

      if (n.loop) {
        var loop = el("path", { class: "map-edge self-loop", d: loopPath(n), "marker-end": "url(#pm-arrowHot)" });
        loop.appendChild(el("title", {}, "Шаг повторяется подряд: " + shortCount(n.loop.freq) + " раз"));
        nodeLayer.appendChild(loop);
        nodeLayer.appendChild(el("text", {
          class: "map-edge-label is-loop", x: n.x + n.w + 24, y: n.y - 4,
        }, byTime ? shortDuration(n.loop.median || n.loop.mean) : shortCount(n.loop.freq)));
      }

      if (options.onNode) {
        group.style.cursor = "pointer";
        group.addEventListener("click", function () { options.onNode(n); });
      }
      nodeLayer.appendChild(group);
    });
    svg.appendChild(nodeLayer);

    target.appendChild(svg);
    return model;
  }

  /* ---------------------------------------------- перетаскивание и масштаб */

  function attachPanZoom(canvas, stage, levelOut) {
    var view = { x: 0, y: 0, k: 1 };
    var drag = null;

    function apply() {
      stage.style.transform = "translate(" + view.x + "px," + view.y + "px) scale(" + view.k + ")";
      if (levelOut) levelOut.textContent = Math.round(view.k * 100) + "%";
    }

    function zoomAt(factor, cx, cy) {
      var next = Math.min(2.6, Math.max(0.25, view.k * factor));
      var ratio = next / view.k;
      view.x = cx - (cx - view.x) * ratio;
      view.y = cy - (cy - view.y) * ratio;
      view.k = next;
      apply();
    }

    canvas.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      // Гасим действие браузера по умолчанию: иначе нажатие на подпись узла
      // начинает выделение текста, и дальше мышь тянет выделение, а не карту.
      // Запрета в CSS мало - выделение может начаться от соседнего элемента.
      event.preventDefault();
      drag = { x: event.clientX - view.x, y: event.clientY - view.y };
      canvas.classList.add("dragging");
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove", function (event) {
      if (!drag) return;
      view.x = event.clientX - drag.x;
      view.y = event.clientY - drag.y;
      apply();
    });
    ["pointerup", "pointercancel"].forEach(function (name) {
      canvas.addEventListener(name, function () { drag = null; canvas.classList.remove("dragging"); });
    });
    canvas.addEventListener("wheel", function (event) {
      event.preventDefault();
      var box = canvas.getBoundingClientRect();
      zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX - box.left, event.clientY - box.top);
    }, { passive: false });

    return {
      zoomIn: function () { var b = canvas.getBoundingClientRect(); zoomAt(1.2, b.width / 2, b.height / 2); },
      zoomOut: function () { var b = canvas.getBoundingClientRect(); zoomAt(1 / 1.2, b.width / 2, b.height / 2); },
      /* Вписать. Масштаб не опускаем ниже 55%: длинный линейный процесс на
       * два десятка шагов ужался бы до нечитаемых подписей. Если после этого
       * граф выше холста - прижимаем к верху и оставляем прокрутку мышью:
       * читать сверху вниз удобнее, чем разглядывать нечитаемую середину. */
      fit: function (model) {
        if (!model) return;
        var box = canvas.getBoundingClientRect();
        if (!box.width || !box.height) return;
        var raw = Math.min(box.width / model.width, box.height / model.height) * 0.94;
        view.k = Math.min(1, Math.max(0.55, raw));
        var scaledH = model.height * view.k;
        view.x = (box.width - model.width * view.k) / 2;
        view.y = scaledH > box.height ? 14 : (box.height - scaledH) / 2;
        apply();
      },
      reset: function () { view = { x: 0, y: 0, k: 1 }; apply(); },
    };
  }

  return { layout: layout, render: render, attachPanZoom: attachPanZoom };
})();
