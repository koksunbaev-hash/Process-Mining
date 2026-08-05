(function () {
  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  // Remembers which batch was moved last, so after the board reloads that card
  // can flash once - on a wall screen a silent swap is easy to miss.
  let lastMovedBatch = null;

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

  function bindDragAndDrop() {
    document.querySelectorAll(".kanban-card").forEach((card) => {
      card.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", card.dataset.batch);
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", () => card.classList.remove("dragging"));
    });
    document.querySelectorAll(".kanban-column").forEach((column) => {
      column.addEventListener("dragover", (event) => {
        event.preventDefault();
        column.classList.add("drop-target");
      });
      column.addEventListener("dragleave", (event) => {
        if (!column.contains(event.relatedTarget)) column.classList.remove("drop-target");
      });
      column.addEventListener("drop", async (event) => {
        event.preventDefault();
        column.classList.remove("drop-target");
        const batch = event.dataTransfer.getData("text/plain");
        const form = new FormData();
        form.append("stage", column.dataset.stage);
        form.append("comment", "Перенос на Kanban-доске");
        const response = await fetch(`/bakery/batches/${batch}/move/`, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
          body: form,
          credentials: "same-origin",
        });
        // A refused move still answers 200, so response.ok only says the
        // request arrived. Trusting it made a rejected transition look like a
        // card that simply snapped back for no reason.
        const result = await response.json().catch(() => ({}));
        if (response.ok && result.ok) {
          lastMovedBatch = batch;
          refreshBoard();
        } else {
          showBoardError(result.error || "Не удалось перенести партию.");
        }
      });
    });

    if (lastMovedBatch) {
      const moved = document.querySelector(`.kanban-card[data-batch="${lastMovedBatch}"]`);
      if (moved) moved.classList.add("just-moved");
      lastMovedBatch = null;
    }
  }

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

  function startBoardAutoRefresh() {
    const shell = document.querySelector("[data-kanban-board-shell]");
    if (!shell) return;

    const REFRESH_MS = 5000;
    let refreshing = false;

    async function refreshIfVisible() {
      if (refreshing) return;
      if (document.hidden) return;
      if (document.querySelector(".kanban-card.dragging")) return;

      refreshing = true;
      try {
        await refreshBoard();
      } finally {
        refreshing = false;
      }
    }

    window.setInterval(refreshIfVisible, REFRESH_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refreshIfVisible();
    });
    window.addEventListener("focus", refreshIfVisible);
  }

  bindDragAndDrop();
  bindDemoPanel();
  startBoardAutoRefresh();
  window.KanbanDemo = { refreshBoard };
})();
