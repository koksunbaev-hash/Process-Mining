/* Замер переноса на настоящем устройстве.
 *
 * Включается только адресом с ?debug=drag - на рабочей доске его нет.
 * Пока карточку ведут, накладка считает кадры и длинные задачи; после
 * отпускания печатает итог крупно, чтобы его можно было сфотографировать.
 *
 * Зачем: рывок рывку рознь. Длинные кадры на главном потоке - одна болезнь
 * (виноват скрипт или раскладка), ровные кадры при рваной картинке - другая
 * (виновата отрисовка и композиция), подмена разметки под пальцем - третья.
 * Снаружи они выглядят одинаково, а лечатся по-разному, и различить их
 * можно только цифрами с того самого устройства, где рвётся.
 */
(function () {
  "use strict";
  if (!/[?&]debug=drag/.test(window.location.search)) return;

  const hud = document.createElement("div");
  hud.style.cssText =
    "position:fixed;left:8px;right:8px;bottom:8px;z-index:9999;" +
    "background:rgba(10,14,24,.92);color:#e8eefc;border-radius:10px;" +
    "padding:10px 12px;font:600 13px/1.45 system-ui,sans-serif;" +
    "pointer-events:none;white-space:pre-wrap";
  hud.textContent = "Замер переноса включён.\nВозьмите карточку и поводите её между колонками.";
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(hud));

  // Длинные задачи главного потока: всё, что дольше 50 мс. Наблюдатель может
  // быть недоступен - тогда об этом честно пишется в итоге.
  let longTasks = [];
  let longTasksSupported = false;
  try {
    new PerformanceObserver((list) => {
      longTasks.push(...list.getEntries().map((e) => Math.round(e.duration)));
    }).observe({ entryTypes: ["longtask"] });
    longTasksSupported = true;
  } catch (error) { /* старый браузер */ }

  let run = null;

  function board() {
    return document.querySelector("[data-kanban-board]");
  }

  function tick(now) {
    if (!run) return;
    if (run.last) {
      const delta = now - run.last;
      const el = board();
      const scrolled = el && el.scrollLeft !== run.scrollLeft;
      if (el) run.scrollLeft = el.scrollLeft;
      run.frames.push({ delta, scrolled });
    } else if (board()) {
      run.scrollLeft = board().scrollLeft;
    }
    run.last = now;
    requestAnimationFrame(tick);
  }

  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".kanban-card")) return;
    longTasks = [];
    run = { frames: [], last: 0, scrollLeft: 0, card: event.target.closest(".kanban-card") };
    requestAnimationFrame(tick);
    hud.textContent = "Идёт замер…";
  }, true);

  function finish() {
    if (!run) return;
    const active = run.frames;
    const detached = run.card && !document.contains(run.card);
    run = null;
    if (active.length < 5) {
      hud.textContent = "Слишком короткий жест - поводите карточку подольше.";
      return;
    }
    const deltas = active.map((f) => f.delta).sort((a, b) => a - b);
    const median = deltas[Math.floor(deltas.length / 2)];
    const worst = deltas[deltas.length - 1];
    const over25 = active.filter((f) => f.delta > 25);
    const over50 = active.filter((f) => f.delta > 50);
    const scrollFrames = active.filter((f) => f.scrolled);
    const scrollJank = over25.filter((f) => f.scrolled).length;
    const tasksTotal = longTasks.reduce((a, b) => a + b, 0);

    // Приговор по цифрам, чтобы не разгадывать их на месте.
    let verdict;
    if (detached) {
      verdict = "ДОСКУ ПОДМЕНИЛИ ПОД ПАЛЬЦЕМ - гонка с обновлением";
    } else if (over50.length || tasksTotal > 100) {
      verdict = "ГЛАВНЫЙ ПОТОК ЗАНЯТ - виноват скрипт или раскладка";
    } else if (over25.length > active.length * 0.1) {
      verdict = scrollJank > over25.length / 2
        ? "КАДРЫ ПРОСЕДАЮТ ИМЕННО ПРИ ПРОКРУТКЕ - дорогая отрисовка доски"
        : "КАДРЫ ПРОСЕДАЮТ БЕЗ ПРОКРУТКИ - что-то стороннее на странице";
    } else {
      verdict = "КАДРЫ РОВНЫЕ - если картинку рвёт, это композиция, не скрипт";
    }

    hud.textContent =
      "== ЗАМЕР ПЕРЕНОСА ==\n" +
      "кадров: " + active.length +
      "  медиана: " + median.toFixed(1) + " мс" +
      "  худший: " + worst.toFixed(1) + " мс\n" +
      "дольше 25 мс: " + over25.length +
      "  дольше 50 мс: " + over50.length +
      "  из них при прокрутке: " + scrollJank + "\n" +
      "кадров с прокруткой: " + scrollFrames.length + "\n" +
      "длинные задачи: " + (longTasksSupported
        ? longTasks.length + " шт, " + Math.round(tasksTotal) + " мс (" +
          (longTasks.slice(0, 5).join(", ") || "-") + ")"
        : "замер недоступен в этом браузере") + "\n" +
      "вердикт: " + verdict + "\n" +
      "Сфотографируйте этот экран.";
  }

  document.addEventListener("pointerup", () => setTimeout(finish, 80), true);
  document.addEventListener("pointercancel", () => setTimeout(finish, 80), true);
})();
