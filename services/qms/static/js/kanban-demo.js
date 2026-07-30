(function () {
  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function bindDragAndDrop() {
    document.querySelectorAll(".kanban-card").forEach((card) => {
      card.addEventListener("dragstart", (event) => event.dataTransfer.setData("text/plain", card.dataset.batch));
    });
    document.querySelectorAll(".kanban-column").forEach((column) => {
      column.addEventListener("dragover", (event) => event.preventDefault());
      column.addEventListener("drop", async (event) => {
        event.preventDefault();
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
        if (response.ok) refreshBoard();
      });
    });
  }

  async function refreshBoard() {
    const shell = document.querySelector("[data-kanban-board-shell]");
    if (!shell) return;
    const url = new URL("/bakery/board/partial/", window.location.origin);
    const params = new URLSearchParams(window.location.search);
    if (!params.get("demo")) params.set("demo", "demo");
    url.search = params.toString();
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) return;
    shell.innerHTML = await response.text();
    bindDragAndDrop();
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

  bindDragAndDrop();
  bindDemoPanel();
  window.KanbanDemo = { refreshBoard };
})();
