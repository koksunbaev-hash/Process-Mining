(function () {
  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  // Remembers which batch was moved last, so after the board reloads that card
  // can flash once - on a wall screen a silent swap is easy to miss.
  let lastMovedBatch = null;

  // Сколько переносов сейчас ждут ответа сервера.
  let movesInFlight = 0;

  // Sits outside [data-kanban-board-shell] so a board refresh does not wipe it.
  let boardErrorTimer = null;
  function showBoardError(text) {
    const shell = document.querySelector("[data-kanban-board-shell]");
    if (!shell || !text) return;
    let box = document.querySelector("[data-kanban-error]");
    if (!box) {
      box = document.createElement("div");
      box.className = "message error";
      box.setAttribute("data-kanban-error", "");
      shell.parentNode.insertBefore(box, shell);
    }
    box.textContent = text;
    window.clearTimeout(boardErrorTimer);
    boardErrorTimer = window.setTimeout(() => box.remove(), 6000);
  }

  /* Куда положить карточку внутри колонки.
   *
   * Порядок задаёт Meta.ordering модели: planned_finish, затем id. Класть в
   * конец было проще, но тогда карточка занимала чужое место и перескакивала
   * при первом же обновлении доски - перенос выглядел так, будто он не
   * сохранился, а потом сам себя переиграл.
   */
  function insertInOrder(lane, card) {
    const key = (el) => [el.dataset.finish || "99999999999999", Number(el.dataset.batch) || 0];
    const mine = key(card);
    const before = [...lane.querySelectorAll(".kanban-card")].find((other) => {
      if (other === card) return false;
      const theirs = key(other);
      return theirs[0] > mine[0] || (theirs[0] === mine[0] && theirs[1] > mine[1]);
    });
    if (before) lane.insertBefore(card, before);
    else lane.appendChild(card);
  }

  function recount() {
    document.querySelectorAll(".kanban-column").forEach((column) => {
      const badge = column.querySelector("[data-kanban-count]");
      if (badge) badge.textContent = column.querySelectorAll(".kanban-card").length;

      // Дорожки: занятость и счётчик ожидающих. Без этого перенесённая
      // карточка стояла на печи, а печь до следующего обновления доски всё
      // ещё писала «свободно» - и оператор нёс на неё вторую партию.
      let busy = 0;
      let slots = 0;
      column.querySelectorAll(".kanban-lane").forEach((lane) => {
        const held = lane.querySelectorAll(".kanban-card").length;
        const pool = lane.classList.contains("is-pool");
        lane.classList.toggle("is-busy", held > 0);
        if (!pool) {
          slots += 1;
          if (held) busy += 1;
        }
        const counter = lane.querySelector(".kanban-lane__count");
        if (counter) counter.textContent = held;
        const state = lane.querySelector(".kanban-lane__state");
        if (state && !lane.classList.contains("is-blocked")) {
          state.textContent = held ? "занято" : "свободно";
          state.classList.toggle("is-busy", held > 0);
        }
        const empty = lane.querySelector(".kanban-lane__empty");
        if (empty) empty.hidden = held > 0;
      });
      const load = column.querySelector(".kanban-head__load");
      if (load && slots) {
        load.textContent = `${busy}/${slots}`;
        load.classList.toggle("is-full", busy >= slots);
      }
    });
  }

  /* Перетаскивание карточек.
   *
   * Собственное, на указателях, а не встроенное в браузер drag-and-drop.
   * У встроенного три беды, и все три видны на этой доске:
   *
   *   - оно рисует свой полупрозрачный снимок карточки и двигает его рывками,
   *     кадр в кадр с dragover, а не с курсором;
   *   - цель броска - тот элемент, над которым сработал dragover, и попасть в
   *     нужную колонку на узких колонках и при боковой прокрутке трудно;
   *   - на сенсорном экране оно не работает вовсе, а доска висит в цеху.
   *
   * Здесь карточка едет за пальцем сама, колонка под курсором определяется по
   * координатам, и то же самое работает мышью, пером и пальцем.
   */
  function bindDragAndDrop() {
    document.querySelectorAll(".kanban-card").forEach((card) => {
      card.addEventListener("pointerdown", (event) => startDrag(event, card));
    });

    if (lastMovedBatch) {
      const moved = document.querySelector(`.kanban-card[data-batch="${lastMovedBatch}"]`);
      if (moved) moved.classList.add("just-moved");
      lastMovedBatch = null;
    }
  }

  let drag = null;

  /* Сколько палец должен пролежать на карточке, прежде чем она поедет.
   *
   * Мышью карточку берут сразу: у курсора нет другого назначения. Пальцем -
   * есть: доска шире экрана, и тем же движением её прокручивают. Поэтому на
   * сенсоре решает время: короткий свайп - прокрутка, задержался - перенос.
   * Так же ведут себя все мобильные доски, и смена этого не заучивает.
   *
   * 300 мс - меньше, чем ощущается пауза, но больше, чем длится смахивание. */
  const HOLD_MS = 300;

  // Сколько палец может сползти за время удержания, не отменяя его. Рука на
  // весу не стоит неподвижно, а 10 px - это уже намерение прокрутить.
  const HOLD_SLACK = 10;

  function isTouch(event) {
    return event.pointerType !== "mouse";
  }

  function startDrag(event, card) {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    // Кнопки внутри карточки должны нажиматься, а не таскать её.
    if (event.target.closest("a, button, input, select, textarea")) return;

    drag = {
      card,
      id: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      home: card.parentElement,
      next: card.nextElementSibling,
      active: false,
      loop: 0,
      touch: isTouch(event),
      // Мышь вооружена сразу, палец - после удержания.
      armed: !isTouch(event),
      holdTimer: null,
    };

    if (drag.touch) {
      card.classList.add("is-holding");
      drag.holdTimer = window.setTimeout(() => armDrag(event.pointerId), HOLD_MS);
    } else {
      card.setPointerCapture(event.pointerId);
    }
  }

  /* Удержание состоялось: карточка переходит в руки скрипта.
   *
   * Захват указателя берётся здесь, а не в pointerdown: до этого момента жест
   * ещё может оказаться прокруткой, и забирать его у браузера рано. */
  function armDrag(pointerId) {
    if (!drag || drag.id !== pointerId || drag.armed) return;
    drag.armed = true;
    drag.holdTimer = null;
    drag.card.classList.remove("is-holding");
    drag.card.classList.add("is-armed");
    document.body.classList.add("kanban-holding");
    try {
      drag.card.setPointerCapture(pointerId);
    } catch (error) {
      // Палец уже отпустили - ловить нечего, отпускание разберётся само.
    }
    // Короткий отклик: на стекле его ждут, и он же говорит «карточка твоя».
    if (navigator.vibrate) navigator.vibrate(15);
  }

  function cancelHold() {
    if (!drag) return;
    if (drag.holdTimer) window.clearTimeout(drag.holdTimer);
    drag.holdTimer = null;
    drag.card.classList.remove("is-holding");
  }

  function moveDrag(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;

    // Палец пошёл раньше, чем истекло удержание - значит человек прокручивает
    // доску, а не берёт карточку. Отпускаем жест браузеру и забываем о нём.
    if (!drag.armed) {
      if (Math.abs(dx) + Math.abs(dy) > HOLD_SLACK) {
        cancelHold();
        drag = null;
      }
      return;
    }

    if (!drag.active) {
      // Четыре пикселя отделяют нажатие от переноса: дрожание руки в них
      // укладывается, а осмысленное движение - нет. Иначе любой промах по
      // кнопке утаскивал бы карточку.
      if (Math.abs(dx) + Math.abs(dy) < 4) return;
      drag.active = true;

      const box = drag.card.getBoundingClientRect();
      drag.offsetX = drag.startX - box.left;
      drag.offsetY = drag.startY - box.top;
      drag.originX = box.left;
      drag.originY = box.top;
      drag.width = box.width;

      // Место карточки занимает пустышка тех же размеров: без неё колонка
      // схлопывается под курсором и вся доска дёргается.
      drag.ghost = document.createElement("div");
      drag.ghost.className = "kanban-ghost";
      drag.ghost.style.height = box.height + "px";
      drag.home.insertBefore(drag.ghost, drag.card);

      drag.card.classList.add("dragging");
      drag.card.style.width = box.width + "px";

      // Рамки контейнеров снимаются один раз за перенос. Дальше они не
      // меняются: карточка вынута из потока, её место держит пустышка, а
      // автопрокрутка двигает содержимое, а не сам контейнер. Читать их
      // каждый кадр - значит каждый кадр заставлять браузер пересчитывать
      // раскладку сразу после того, как мы её тронули.
      drag.board = document.querySelector("[data-kanban-board]");
      drag.boardBox = drag.board ? drag.board.getBoundingClientRect() : null;
      drag.laneBoxes = new Map();
      drag.homeLane = drag.home.closest(".kanban-lane");
      drag.highlight = null;
      drag.hitX = undefined;
      drag.hitY = undefined;
      drag.lane = null;
      drag.drawnX = undefined;
      drag.drawnY = undefined;
      drag.scrollRest = { x: 0, y: 0 };
      // Точка отсчёта задаётся один раз координатами, дальше карточка едет
      // трансформацией: left/top пересчитывают раскладку всей доски каждый
      // кадр, translate3d - только слой самой карточки. На доске из трёх
      // сотен элементов это разница в семь раз, и видна она именно на
      // планшете, где запаса по скорости нет.
      drag.card.style.left = box.left + "px";
      drag.card.style.top = box.top + "px";
      drag.card.style.willChange = "transform";
      document.body.classList.add("kanban-dragging");
      // Цикл заводится ниже, уже после того, как записаны координаты пальца:
      // заведённый здесь, он успевал сделать первый кадр по пустым pendingX
      // и pendingY - и падал на испытании точки с нечисловыми координатами.
    }

    // Прокрутку это не отменяет - ею занимается слушатель touchmove ниже.
    // Здесь отмена нужна ради совместимостных событий мыши: без неё касание
    // порождает ещё и click, и карточка на отпускании открывает партию.
    if (event.cancelable) event.preventDefault();
    // Палец шлёт события чаще, чем экран рисует кадры, а иногда и пачками.
    // Считать подсветку и прокрутку на каждое - работа впустую: до экрана
    // доедет только последнее. Копим и применяем раз в кадр.
    drag.pendingX = event.clientX;
    drag.pendingY = event.clientY;
    startDragLoop();
  }

  /* Один цикл на весь перенос.
   *
   * Он крутится, пока карточку держат, - даже когда палец стоит. У края
   * доски он как раз и стоит, ожидая, пока подъедет соседняя колонка: если
   * ждать событий движения, доска будет ехать, а попадание под пальцем
   * считаться по старым координатам. И прокрутка, и карточка обновляются
   * здесь, в одном кадре, - порознь они расходились.
   */
  function startDragLoop() {
    if (!drag || !drag.active || drag.loop) return;
    drag.lastFrame = 0;
    const tick = (now) => {
      if (!drag || !drag.active) return;
      // Долгий кадр не должен превращаться в прыжок: вкладку свернули,
      // браузер задумался - ограничиваем шаг четырьмя кадрами.
      const step = drag.lastFrame ? Math.min(now - drag.lastFrame, 64) : 16;
      drag.lastFrame = now;
      drag.loop = requestAnimationFrame(tick);
      applyDragFrame(step);
    };
    drag.loop = requestAnimationFrame(tick);
  }

  function applyDragFrame(elapsed) {
    if (!drag || !drag.active) return;
    const x = drag.pendingX;
    const y = drag.pendingY;
    const scrolled = runAutoScroll(x, y, elapsed);

    // Наклон дописан сюда же: css задаёт его на .dragging, но inline-стиль
    // перекрывает правило целиком, и без этого карточка ехала прямой.
    // Пишем только на новых координатах: цикл крутится каждый кадр, а палец
    // у края стоит, и переписывать одно и то же значение стиля незачем.
    if (x !== drag.drawnX || y !== drag.drawnY) {
      drag.drawnX = x;
      drag.drawnY = y;
      drag.card.style.transform =
        "translate3d(" + (x - drag.offsetX - drag.originX) + "px," +
        (y - drag.offsetY - drag.originY) + "px,0) rotate(1deg)";
    }

    // Испытание точки - самая дорогая работа кадра: браузер обходит дерево и
    // ищет, что под пальцем. Дорожки шириной в сотни пикселей, и переспрашивать
    // на каждый пиксель незачем: пока палец не ушёл на восемь, ответ тот же.
    // Карточка при этом едет каждый кадр - за пальцем она не отстаёт.
    // Испытывать точку заново нужно и когда доска уехала: палец на месте, а
    // дорожки под ним - уже другие.
    const moved = Math.abs(x - drag.hitX) + Math.abs(y - drag.hitY);
    if (moved >= 8 || scrolled || drag.hitX === undefined) {
      drag.hitX = x;
      drag.hitY = y;
      drag.lane = laneAt(x, y);
    }
    const lane = drag.lane;
    if (lane !== drag.target) {
      // Подсветка трогается только на смене дорожки. Класс на элементе - это
      // пересчёт стиля и перерисовка полосы с тенью; делать это шестьдесят
      // раз в секунду, пока палец ходит внутри одной дорожки, незачем.
      if (drag.highlight) {
        drag.highlight.classList.remove("drop-target", "drop-refused");
        drag.highlight = null;
      }
      if (lane && lane !== drag.homeLane) {
        // Занятое устройство подсвечивается отказом, а не приглашением: на нём
        // помещается одна партия, и узнать об этом лучше до броска.
        lane.classList.add(laneRefusal(lane) ? "drop-refused" : "drop-target");
        drag.highlight = lane;
      }
      drag.target = lane;
    }
  }

  /* Прокрутка под курсором во время переноса.
   *
   * Без неё доска недостижима с двух сторон. По вертикали: «Не распределено»
   * набирает три десятка карточек, и пять печей уезжают на экран ниже - донести
   * до них карточку было нельзя, потому что колонка под курсором не едет. По
   * горизонтали то же самое с семью колонками на широкой доске.
   *
   * Скорость растёт по мере захода в краевую полосу: у самой границы - быстро,
   * на её краю - едва заметно, чтобы можно было остановиться там, где нужно.
   */
  /* Краевая полоса и скорость - доли контейнера, а не пиксели.
   *
   * Семьдесят два пикселя на широкой доске - это узкая кромка, а на телефоне
   * шириной в триста пятьдесят - почти половина экрана: палец почти всюду
   * запускал прокрутку, и доска убегала из-под карточки. Скорость так же:
   * пятнадцать пикселей за кадр - это девятьсот в секунду, две с половиной
   * ширины телефона. Считаем от размера - и на любом экране прокрутка идёт
   * примерно одинаково быстро относительно того, что человек видит.
   */
  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  // Доли подобраны так, чтобы прокрутка проходила контейнер примерно за
  // секунду на любом экране: и на телефоне в 347 пикселей, и на доске в
  // 1400. Полоса - около четверти на маленьком экране и десятой части на
  // большом; там, где экран узкий, без неё до соседней колонки не добраться.
  function edgeZone(size) {
    return clamp(size * 0.12, 28, 56);
  }

  /* Скорость - в пикселях в секунду, а не за кадр.
   *
   * За кадр было удобно, пока кадры ровные. Пропущенный кадр при этом даёт
   * рывок на двойную величину, и на слабом телефоне прокрутка идёт
   * ступеньками. От времени - идёт ровно при любой частоте.
   */
  function edgeSpeed(near, far, position, size) {
    const zone = edgeZone(size);
    const top = clamp(size * 0.9, 180, 720);
    if (position < near + zone) {
      return -((near + zone - position) / zone) * top;
    }
    if (position > far - zone) {
      return ((position - (far - zone)) / zone) * top;
    }
    return 0;
  }

  function boxOf(element) {
    // Рамка контейнера за перенос не меняется - снимаем один раз и помним.
    if (!drag) return element.getBoundingClientRect();
    let box = drag.laneBoxes.get(element);
    if (!box) {
      box = element.getBoundingClientRect();
      drag.laneBoxes.set(element, box);
    }
    return box;
  }

  /* Сдвинуть доску под пальцем. Возвращает, уехала ли она на самом деле.

     Дробный остаток копится: у края полосы скорость невелика, и без него
     каждый кадр округлялся бы в ноль - прокрутка бы просто стояла. */
  function shift(element, axis, speed, elapsed, rest, key) {
    const wanted = speed * elapsed / 1000 + rest[key];
    const whole = Math.trunc(wanted);
    rest[key] = wanted - whole;
    if (!whole) return false;
    const before = element[axis];
    element[axis] = before + whole;
    // Доска могла упереться в край - тогда ничего не двинулось, и
    // переспрашивать попадание незачем.
    return element[axis] !== before;
  }

  function runAutoScroll(x, y, elapsed) {
    if (!drag) return false;
    const rest = drag.scrollRest;
    let moved = false;

    const vertical = drag.lane ? drag.lane.closest(".kanban-lanes") : null;
    if (vertical) {
      const box = boxOf(vertical);
      const speed = edgeSpeed(box.top, box.bottom, y, box.height);
      if (speed) moved = shift(vertical, "scrollTop", speed, elapsed, rest, "y") || moved;
      else rest.y = 0;
    } else {
      rest.y = 0;
    }

    if (drag.board && drag.boardBox) {
      const box = drag.boardBox;
      const speed = edgeSpeed(box.left, box.right, x, box.width);
      if (speed) moved = shift(drag.board, "scrollLeft", speed, elapsed, rest, "x") || moved;
      else rest.x = 0;
    }
    return moved;
  }

  /* Почему бросок сюда невозможен, или пустая строка. */
  function laneRefusal(lane) {
    if (lane.classList.contains("is-pool")) return "";
    if (lane.classList.contains("is-blocked")) {
      return `«${lane.dataset.laneName}» сейчас недоступно.`;
    }
    const held = [...lane.querySelectorAll(".kanban-card")].filter((card) => card !== (drag && drag.card));
    if (held.length) {
      const number = held[0].dataset.batchNumber || "";
      return `«${lane.dataset.laneName}» занято: партия ${number}.`;
    }
    return "";
  }

  function clearDropTargets(keep) {
    document.querySelectorAll(".kanban-lane.drop-target, .kanban-lane.drop-refused").forEach((lane) => {
      if (lane !== keep) lane.classList.remove("drop-target", "drop-refused");
    });
  }

  /* Колонка под курсором.
   *
   * Через elementFromPoint, а не через события над элементами: карточка едет
   * под курсором и сама перехватывала бы их. На время замера она исключается
   * из попадания.
   */
  function laneAt(x, y) {
    // Стиль карточки здесь не трогаем: класс .dragging уже держит на ней
    // pointer-events: none. Прежняя пара записей вокруг каждого замера
    // сбрасывала стиль дважды за кадр и обходилась в двенадцать раз дороже
    // самого замера.
    const element = document.elementFromPoint(x, y);
    if (!element) return null;
    const lane = element.closest(".kanban-lane");
    if (lane) return lane;
    // Промах между дорожками - но внутри колонки - читается как «в эту
    // колонку»: партия встаёт в «Не распределено», а не отпрыгивает назад.
    const column = element.closest(".kanban-column");
    return column ? column.querySelector(".kanban-lane.is-pool") : null;
  }

  async function endDrag(event) {
    if (!drag || event.pointerId !== drag.id) return;
    const { card, home, next, target, active, loop, highlight } = drag;
    cancelHold();
    if (loop) cancelAnimationFrame(loop);
    drag = null;
    card.classList.remove("is-armed");
    document.body.classList.remove("kanban-holding");

    if (!active) return;   // просто нажатие, переноса не было

    card.classList.remove("dragging");
    card.style.left = card.style.top = card.style.width = "";
    card.style.transform = "";
    card.style.willChange = "";
    document.body.classList.remove("kanban-dragging");
    if (highlight) highlight.classList.remove("drop-target", "drop-refused");
    // Подчистка на всякий случай: подсветку мог оставить прерванный перенос.
    clearDropTargets(null);

    const ghost = document.querySelector(".kanban-ghost");
    const homeLane = home.closest(".kanban-lane");
    const lane = target;
    const slot = lane && lane.querySelector(".kanban-cards");
    const refusal = lane ? laneRefusal(lane) : "";
    const sameLane = !lane || lane === homeLane;

    const goHome = () => {
      if (next) home.insertBefore(card, next);
      else home.appendChild(card);
    };
    // Перенос закончился в любом случае - удачей, отказом или возвратом на
    // место. Отложенное обновление ждало именно этого.
    const settled = () => window.dispatchEvent(new CustomEvent("kanban:move-settled"));

    if (ghost) ghost.remove();
    if (sameLane || !slot) {
      // Вернуть ровно туда, откуда взяли, а не в конец дорожки.
      goHome();
      settled();
      return;
    }
    if (refusal) {
      goHome();
      showBoardError(refusal);
      settled();
      return;
    }

    card.classList.add("is-moving");
    insertInOrder(slot, card);
    recount();

    const form = new FormData();
    form.append("stage", lane.dataset.stage);
    form.append("from_stage", homeLane.dataset.stage);
    // Пустая строка - это «в Не распределено», а не «параметр не передан»:
    // снять партию с печи броском должно быть можно.
    form.append("unit", lane.dataset.unit || "");
    form.append("comment", "Перенос на Kanban-доске");
    let result = {};
    let ok = false;
    movesInFlight += 1;
    try {
      const response = await fetch(card.dataset.moveUrl || `/bakery/batches/${card.dataset.batch}/move/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
        body: form,
        credentials: "same-origin",
      });
      // Отказ тоже отвечает 200, поэтому response.ok говорит лишь о том, что
      // запрос дошёл. Доверие к нему превращало отклонённый перенос в карточку,
      // которая отпрыгнула назад без объяснений.
      result = await response.json().catch(() => ({}));
      ok = response.ok && result.ok;
    } catch (error) {
      result = { error: "Сеть недоступна. Перенос не сохранён." };
    }
    movesInFlight -= 1;
    window.dispatchEvent(new CustomEvent("kanban:move-settled"));

    card.classList.remove("is-moving");
    if (ok) {
      card.classList.add("just-moved");
      window.setTimeout(() => card.classList.remove("just-moved"), 1200);
    } else {
      goHome();
      recount();
      showBoardError(result.error || "Не удалось перенести партию.");
    }
  }

  // Слушатели на документе, а не на карточках: карточка может уехать из-под
  // курсора, а захват указателя всё равно шлёт события ей - через всплытие они
  // доходят сюда, и перенос не обрывается на полпути.
  // Долгое нажатие на стекле вызывает контекстное меню и выделение текста -
  // ровно поверх карточки, которую в этот момент берут в руку.
  document.addEventListener("contextmenu", (event) => {
    if (drag && drag.touch && event.target.closest(".kanban-card")) event.preventDefault();
  });

  // Поворот экрана и появление клавиатуры меняют раскладку под пальцем -
  // запомненные рамки после этого врут, и прокрутка сходит с ума.
  window.addEventListener("resize", () => {
    if (!drag || !drag.active) return;
    drag.laneBoxes.clear();
    drag.boardBox = drag.board ? drag.board.getBoundingClientRect() : null;
  });

  /* Единственный способ удержать доску на месте под пальцем.
   *
   * Слушатель неленивый - иначе отмена молча ничего не сделает, - и висит на
   * документе, потому что карточка уезжает из-под пальца, а касание всё равно
   * адресовано ей. Отменяем только вооружённый перенос: пока карточку не
   * взяли, тем же движением доску прокручивают, и жест принадлежит браузеру.
   */
  document.addEventListener("touchmove", (event) => {
    if (drag && drag.armed && event.cancelable) event.preventDefault();
  }, { passive: false });

  document.addEventListener("pointermove", moveDrag);
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !drag || !drag.active) return;
    const { card, home, next } = drag;
    cancelHold();
    if (drag.loop) cancelAnimationFrame(drag.loop);
    // Подсветку снимает clearDropTargets ниже - отдельного цикла прокрутки,
    // который надо было бы гасить, больше нет.
    drag = null;
    card.classList.remove("dragging", "is-armed");
    card.style.transform = "";
    card.style.willChange = "";
    document.body.classList.remove("kanban-holding");
    card.style.left = card.style.top = card.style.width = "";
    document.body.classList.remove("kanban-dragging");
    clearDropTargets(null);
    const ghost = document.querySelector(".kanban-ghost");
    if (ghost) ghost.remove();
    if (next) home.insertBefore(card, next);
    else home.appendChild(card);
    window.dispatchEvent(new CustomEvent("kanban:move-settled"));
  });

  // Exposed so the voice widget can redraw the board after a command runs:
  // the widget floats above the page and otherwise leaves stale markup behind,
  // which looks exactly like "the command did nothing".
  window.kanbanRefresh = () => refreshBoard();

  async function refreshBoard() {
    const shell = document.querySelector("[data-kanban-board-shell]");
    if (!shell) return;
    const url = new URL("/bakery/board/partial/", window.location.origin);
    // Refresh whatever the page is actually showing. This used to force
    // demo=demo, which silently emptied the board for anyone looking at real
    // batches: the redraw asked for a set the visible board did not contain.
    const params = new URLSearchParams(window.location.search);
    url.search = params.toString();
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) return;
    const scroll = readScroll(shell);
    shell.innerHTML = await response.text();
    restoreScroll(shell, scroll);
    bindDragAndDrop();
  }

  // Replacing the shell's HTML throws away every scroll position with it. The
  // board is wider than any screen and the demo redraws it every 0.1-5 seconds,
  // so without this it snapped back to the first column continuously and could
  // not be read at all on a laptop, let alone a tablet.
  function readScroll(shell) {
    const board = shell.querySelector("[data-kanban-board]");
    const lanes = {};
    shell.querySelectorAll(".kanban-column").forEach((column) => {
      const cards = column.querySelector(".kanban-cards");
      if (cards && cards.scrollTop) lanes[column.dataset.stageCode] = cards.scrollTop;
    });
    return { left: board ? board.scrollLeft : 0, lanes };
  }

  function restoreScroll(shell, scroll) {
    const board = shell.querySelector("[data-kanban-board]");
    if (board && scroll.left) board.scrollLeft = scroll.left;
    shell.querySelectorAll(".kanban-column").forEach((column) => {
      const top = scroll.lanes[column.dataset.stageCode];
      const cards = column.querySelector(".kanban-cards");
      if (cards && top) cards.scrollTop = top;
    });
  }

  function bindDemoPanel() {
    const root = document.querySelector("[data-kanban-demo]");
    if (!root) return;
    const $ = (name) => root.querySelector(`[data-demo-${name}]`);
    const box = $("box");
    const error = $("error");
    let runId = null;
    let timer = null;
    let speedMs = 2000;

    function setError(text) {
      error.textContent = text || "";
    }

    function renderStatus(data) {
      if (!data) return;
      runId = data.id || runId;
      if (runId) root.dataset.demoRunId = String(runId);
      $("state").textContent = `Статус: ${data.status || "-"}`;
      $("progress").textContent = `${data.progress_percent || 0}%`;
      $("total").textContent = `${data.total_batches || 0} партий`;
      $("done").textContent = `${data.completed_batches || 0} готово`;
      const stages = data.stages || {};
      $("stage-stats").innerHTML = Object.entries(stages)
        .map(([stage, count]) => `<span>${stage}: <strong>${count}</strong></span>`)
        .join("");
      setError(data.last_error || (data.errors && data.errors.length ? data.errors[0].error : ""));
      if (data.status === "completed" || data.status === "stopped" || data.status === "failed") stopLoop();
    }

    async function post(url, body) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : "{}",
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Ошибка demo API");
      return data;
    }

    async function action(name) {
      if (!runId) {
        setError("Сначала создайте демо.");
        return null;
      }
      const data = await post(`/api/kanban-demo/${runId}/${name}/`);
      renderStatus(data);
      return data;
    }

    async function tick() {
      if (!runId) return;
      try {
        const data = await action("tick");
        await refreshBoard();
        if (data && data.status === "running") startLoop();
      } catch (err) {
        setError(err.message);
        stopLoop();
      }
    }

    function stopLoop() {
      if (timer) window.clearTimeout(timer);
      timer = null;
    }

    function startLoop() {
      stopLoop();
      timer = window.setTimeout(tick, speedMs);
    }

    $("toggle").addEventListener("click", () => {
      box.hidden = !box.hidden;
    });
    $("create").addEventListener("click", async () => {
      setError("");
      speedMs = Number($("speed").value) * 1000;
      try {
        const data = await post("/api/kanban-demo/create/", {
          count: Number($("count").value || 100),
          speed_seconds: Number($("speed").value || 2),
          mode: $("mode").value,
          client_request_id: `kanban-demo-${Date.now()}`,
          reset: true,
          simulate_pauses: $("pauses").checked,
          simulate_problems: $("problems").checked,
          simulate_returns: $("returns").checked,
        });
        renderStatus(data);
        await refreshBoard();
      } catch (err) {
        setError(err.message);
      }
    });
    $("start").addEventListener("click", async () => {
      const data = await action("start");
      if (data && data.status === "running") startLoop();
    });
    $("pause").addEventListener("click", async () => {
      stopLoop();
      await action("pause");
    });
    $("resume").addEventListener("click", async () => {
      const data = await action("resume");
      if (data && data.status === "running") startLoop();
    });
    $("stop").addEventListener("click", async () => {
      stopLoop();
      await action("stop");
    });
    $("reset").addEventListener("click", async () => {
      if (!runId || !window.confirm("Будут удалены только демонстрационные данные этого запуска.")) return;
      stopLoop();
      await action("reset");
      runId = null;
      renderStatus({ status: "reset", progress_percent: 0, total_batches: 0, completed_batches: 0, stages: {} });
      await refreshBoard();
    });
  }

  function startBoardEventRefresh() {
    const shell = document.querySelector("[data-kanban-board-shell]");
    if (!shell) return;
    if (!window.EventSource) return;
    let refreshing = false;
    let lastMarker = null;
    let source = null;
    let pendingRefresh = false;

    async function refreshFromEvent(marker) {
      if (lastMarker === null) {
        lastMarker = marker;
        return;
      }
      if (marker === lastMarker) return;
      lastMarker = marker;
      if (refreshing) return;
      if (document.hidden) {
        pendingRefresh = true;
        return;
      }
      if (document.querySelector(".kanban-card.dragging")) {
        // Не просто return: lastMarker уже сдвинут, и второй раз этот повод не
        // придёт. Отброшенное здесь обновление доска потеряла бы навсегда -
        // именно так автообновление и «иногда не работало».
        pendingRefresh = true;
        return;
      }
      if (movesInFlight) {
        // Не теряем повод обновиться: как только перенос подтвердится,
        // доска догонит сама.
        pendingRefresh = true;
        return;
      }

      refreshing = true;
      try {
        await refreshBoard();
        pendingRefresh = false;
      } finally {
        refreshing = false;
      }
    }

    function connect() {
      if (source) source.close();
      source = new EventSource("/bakery/board/events/");
      source.addEventListener("ready", (event) => {
        lastMarker = event.data || "0";
      });
      source.addEventListener("changed", (event) => {
        refreshFromEvent(event.data || "");
      });
      source.onerror = () => {
        if (source) source.close();
        source = null;
        window.setTimeout(connect, 3000);
      };
    }

    connect();
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && pendingRefresh) refreshBoard().then(() => {
        pendingRefresh = false;
      });
    });

    // Доска, отложенная из-за переноса, догоняет сама - иначе она осталась бы
    // с нашей оптимистичной раскладкой до следующего чужого изменения.
    window.addEventListener("kanban:move-settled", () => {
      if (!pendingRefresh || movesInFlight) return;
      pendingRefresh = false;
      refreshBoard();
    });
  }

  // Анимация появления - только для первой отрисовки. Снимаем метку, как
  // только она отыграла, чтобы обновления доски проходили без каскада.
  document.body.classList.add("kanban-boot");
  window.setTimeout(() => document.body.classList.remove("kanban-boot"), 900);

  bindDragAndDrop();
  bindDemoPanel();
  startBoardEventRefresh();
  window.KanbanDemo = { refreshBoard };
})();
