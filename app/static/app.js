/* Process Mining console.
 *
 * One screen, one round-trip: `/api/v1/mine` returns the SVG, the KPIs, the
 * variants and the bottlenecks together, so every tab is filled from a single
 * upload. The map is injected as *inline* SVG (not an <img>) - that is what
 * makes fit-to-screen, cursor-anchored zoom and activity search possible.
 */
(function () {
  "use strict";

  // ------------------------------------------------------------------ utils
  const $ = (id) => document.getElementById(id);
  const MAX_MB = 64;
  const ACCEPTED = /\.(csv|tsv|txt|xes|xes\.gz|gz|json|jsonl|ndjson)$/i;

  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v === null ? fallback : v; }
      catch { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, value); } catch { /* private mode */ }
    },
  };

  const state = {
    lang: store.get("pm-lang", (navigator.language || "en").slice(0, 2)),
    theme: store.get("pm-theme", ""),
    file: null,
    data: null,
    svg: null,
    zoom: 1,
    panX: 0,
    panY: 0,
    natural: { w: 0, h: 0 },
    authRequired: false,
  };
  if (!window.I18N.SUPPORTED.includes(state.lang)) state.lang = "en";

  const t = (key, params) => window.I18N.translate(state.lang, key, params);
  const locale = () => t("meta.locale");

  function formatNumber(value) {
    if (value === null || value === undefined || Number.isNaN(value)) return "—";
    return new Intl.NumberFormat(locale()).format(value);
  }

  function formatPercent(value, digits) {
    if (value === null || value === undefined || Number.isNaN(value)) return "—";
    return new Intl.NumberFormat(locale(), {
      style: "percent",
      minimumFractionDigits: digits === undefined ? 1 : digits,
      maximumFractionDigits: digits === undefined ? 1 : digits,
    }).format(value);
  }

  /** Seconds -> the largest unit that still reads naturally. */
  function formatDuration(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
    const n = Math.abs(Math.round(seconds));
    const fmt = (v, unit) =>
      new Intl.NumberFormat(locale(), { maximumFractionDigits: v < 10 ? 1 : 0 }).format(v) +
      " " + t("unit." + unit);
    if (n < 90) return fmt(n, "s");
    if (n < 5400) return fmt(n / 60, "min");
    if (n < 172800) return fmt(n / 3600, "h");
    return fmt(n / 86400, "d");
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }

  function formatDate(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return new Intl.DateTimeFormat(locale(), { dateStyle: "medium" }).format(d);
  }

  let toastTimer = null;
  function notify(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
  }

  function showError(message, detail) {
    const box = $("error");
    box.textContent = "";
    const title = document.createElement("div");
    title.className = "msg-title";
    title.textContent = message;
    box.appendChild(title);
    if (detail) {
      const code = document.createElement("code");
      code.textContent = detail;
      box.appendChild(code);
    }
    box.classList.add("show");
  }

  function clearError() {
    $("error").classList.remove("show");
    $("error").textContent = "";
  }

  function showWarnings(list, detected) {
    const box = $("warnings");
    box.textContent = "";
    const items = (list || []).slice();
    if (!items.length && !detected) { box.classList.remove("show"); return; }

    if (items.length) {
      const title = document.createElement("div");
      title.className = "msg-title";
      title.textContent = t("warnings.title");
      box.appendChild(title);
      const ul = document.createElement("ul");
      items.forEach((w) => {
        const li = document.createElement("li");
        li.textContent = w;
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    if (detected) {
      const pairs = Object.entries(detected)
        .filter(([, v]) => v)
        .map(([k, v]) => k + " → " + v)
        .join(", ");
      if (pairs) {
        const line = document.createElement("div");
        line.style.marginTop = items.length ? "8px" : "0";
        line.textContent = t("detected.title") + ": " + pairs;
        box.appendChild(line);
      }
    }
    box.classList.toggle("show", box.childNodes.length > 0);
  }

  // --------------------------------------------------------------- i18n
  function applyLanguage() {
    document.documentElement.lang = state.lang;

    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.title = t(el.dataset.i18nTitle);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      el.setAttribute("aria-label", t(el.dataset.i18nAria));
    });

    $("language").value = state.lang;
    updateStatusText();
    updateCoverageOutput();
    updateNoiseOutput();

    // Re-render everything that contains formatted numbers or dates.
    if (state.data) {
      renderMetrics(state.data);
      renderTables(state.data);
    } else {
      renderEmptyTables();
    }
    // Stored-log labels embed counts, so they are language-dependent too.
    if ($("storedLog").options.length > 1) loadStoredLogs();
  }

  // -------------------------------------------------------------- theme
  function preferredTheme() {
    if (state.theme === "light" || state.theme === "dark") return state.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function applyTheme() {
    document.documentElement.setAttribute("data-theme", preferredTheme());
  }

  // ------------------------------------------------------------- health
  function updateStatusText() {
    $("statusText").textContent = t("status." + $("status").dataset.state);
  }

  function setStatus(stateName) {
    $("status").dataset.state = stateName;
    updateStatusText();
  }

  async function checkHealth() {
    try {
      const response = await fetch("/health/ready", { headers: { Accept: "application/json" } });
      const body = await response.json();
      const checks = body.checks || {};
      state.authRequired = Boolean(checks.auth_enabled);

      $("version").textContent = body.service + " v" + body.version;
      fillProfiles(checks.mapping_profiles || []);

      if (state.authRequired && !$("apiKey").value.trim()) {
        setStatus("auth");
        $("apiKey").classList.add("needed");
      } else if (checks.graphviz && checks.graphviz.ok === false) {
        setStatus("nographviz");
      } else {
        setStatus("online");
        $("apiKey").classList.remove("needed");
      }
    } catch {
      setStatus("offline");
    }
  }

  function fillProfiles(profiles) {
    const select = $("profile");
    const current = select.value;
    while (select.options.length > 1) select.remove(1);
    profiles.forEach((id) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      select.appendChild(option);
    });
    if (current) select.value = current;
  }

  // --------------------------------------------------------------- file
  function setFile(file) {
    if (!file) {
      state.file = null;
      $("file").value = "";
      $("fileChip").classList.remove("show");
      return;
    }
    if (!ACCEPTED.test(file.name)) {
      showError(t("error.badType"));
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      showError(t("error.tooLarge", { mb: MAX_MB }));
      return;
    }
    clearError();
    state.file = file;
    $("fileName").textContent = file.name;
    $("fileSize").textContent = formatBytes(file.size);
    $("fileChip").classList.add("show");
  }

  function wireDropzone() {
    const zone = $("dropzone");
    const input = $("file");

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });
    input.addEventListener("change", () => setFile(input.files[0] || null));

    ["dragenter", "dragover"].forEach((type) =>
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        zone.classList.add("dragover");
      })
    );
    ["dragleave", "drop"].forEach((type) =>
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        if (type === "dragleave" && zone.contains(event.relatedTarget)) return;
        zone.classList.remove("dragover");
      })
    );
    zone.addEventListener("drop", (event) => {
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) setFile(file);
    });

    // The whole window accepts a drop, so users do not have to aim.
    window.addEventListener("dragover", (event) => event.preventDefault());
    window.addEventListener("drop", (event) => {
      event.preventDefault();
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) setFile(file);
    });

    $("fileRemove").addEventListener("click", (event) => {
      event.stopPropagation();
      setFile(null);
    });

    $("loadSample").addEventListener("click", async () => {
      try {
        const response = await fetch("/ui/sample_log.csv");
        if (!response.ok) throw new Error("HTTP " + response.status);
        const blob = await response.blob();
        setFile(new File([blob], "sample_log.csv", { type: "text/csv" }));
        notify(t("toast.sample"));
      } catch {
        showError(t("error.network"));
      }
    });
  }

  // -------------------------------------------------------- stored logs
  /* Logs pushed in by a source system (see /api/event-logs/import/) never pass
   * through the file picker, so without this list they would be invisible in
   * the UI - analysable only by hand-crafting API calls. */
  async function loadStoredLogs() {
    const key = $("apiKey").value.trim();
    let items = [];
    try {
      const response = await fetch("/api/v1/logs?limit=100", {
        headers: key ? { "X-API-Key": key } : {},
      });
      if (!response.ok) return;
      items = (await response.json()).items || [];
    } catch {
      return;
    }

    const select = $("storedLog");
    const current = select.value;
    while (select.options.length > 1) select.remove(1);

    items.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.log_id;
      option.textContent =
        item.name + " — " +
        t("logs.events", { n: formatNumber(item.events), c: formatNumber(item.cases) });
      select.appendChild(option);
    });
    if (current && Array.from(select.options).some((o) => o.value === current)) {
      select.value = current;
    }
    toggleSourceMode();
  }

  function toggleSourceMode() {
    const stored = Boolean($("storedLog").value);
    $("uploadArea").style.display = stored ? "none" : "";
  }

  /** Reshapes the stateful endpoints into the same body /mine returns, so
   *  every render function below works unchanged for both paths. */
  async function runStoredLog(logId, headers) {
    const filters = buildFilters();
    const body = {
      algorithm: $("algorithm").value,
      format: "svg",
      noise_threshold: parseFloat($("noise").value),
      render: { rankdir: $("rankdir").value },
    };
    if (filters) body.filters = JSON.parse(filters);

    const json = { ...headers, "Content-Type": "application/json" };
    const [discover, statistics, bottlenecks, variants] = await Promise.all([
      fetch(`/api/v1/logs/${logId}/discover`, {
        method: "POST", headers: json, body: JSON.stringify(body),
      }),
      fetch(`/api/v1/logs/${logId}/statistics`, { headers }),
      fetch(`/api/v1/logs/${logId}/bottlenecks?limit=10`, { headers }),
      fetch(`/api/v1/logs/${logId}/variants?limit=10`, { headers }),
    ]);

    if (!discover.ok) return { ok: false, response: discover, body: await discover.json() };

    return {
      ok: true,
      body: {
        result: await discover.json(),
        statistics: statistics.ok ? await statistics.json() : {},
        bottlenecks: bottlenecks.ok ? await bottlenecks.json() : {},
        variants: variants.ok ? await variants.json() : {},
        warnings: [],
      },
    };
  }

  // ---------------------------------------------------------------- run
  function buildFilters() {
    const coverage = parseFloat($("coverage").value);
    const filters = {};
    if (coverage < 1) filters.variant_coverage = coverage;
    return Object.keys(filters).length ? JSON.stringify(filters) : null;
  }

  async function run() {
    const storedId = $("storedLog").value;
    if (!storedId && !state.file) {
      notify(t("error.noFile"));
      $("dropzone").classList.add("dragover");
      setTimeout(() => $("dropzone").classList.remove("dragover"), 700);
      return;
    }

    const button = $("run");
    button.classList.add("loading");
    button.disabled = true;
    button.textContent = t("actions.running");
    clearError();

    if (storedId) {
      await runStored(storedId, button);
      return;
    }

    const form = new FormData();
    form.append("file", state.file);
    form.append("algorithm", $("algorithm").value);
    form.append("format", "svg");
    form.append("rankdir", $("rankdir").value);
    form.append("noise_threshold", $("noise").value);
    form.append("include_statistics", "true");
    if ($("profile").value) form.append("mapping_profile", $("profile").value);
    const filters = buildFilters();
    if (filters) form.append("filters", filters);

    const key = $("apiKey").value.trim();
    const headers = key ? { "X-API-Key": key } : {};

    let response;
    try {
      response = await fetch("/api/v1/mine", { method: "POST", headers, body: form });
    } catch {
      showError(t("error.network"));
      resetButton(button);
      setStatus("offline");
      return;
    }

    let body;
    try {
      body = await response.json();
    } catch {
      showError(t("error.generic"), "HTTP " + response.status);
      resetButton(button);
      return;
    }

    if (!response.ok) {
      const err = body && body.error;
      if (response.status === 401) {
        showError(t("error.auth"));
        $("apiKey").classList.add("needed");
        $("apiKey").focus();
        setStatus("auth");
      } else {
        showError(
          (err && err.message) || t("error.generic"),
          err ? err.code + " · " + err.request_id : "HTTP " + response.status
        );
      }
      resetButton(button);
      return;
    }

    setStatus("online");
    $("apiKey").classList.remove("needed");
    renderResult(body, button);
  }

  async function runStored(logId, button) {
    const key = $("apiKey").value.trim();
    const headers = key ? { "X-API-Key": key } : {};
    let outcome;
    try {
      outcome = await runStoredLog(logId, headers);
    } catch {
      showError(t("error.network"));
      setStatus("offline");
      resetButton(button);
      return;
    }
    if (!outcome.ok) {
      const err = outcome.body && outcome.body.error;
      showError((err && err.message) || t("error.generic"), err && err.code);
      resetButton(button);
      return;
    }
    setStatus("online");
    renderResult(outcome.body, button);
  }

  function renderResult(body, button) {
    const image = body.result && body.result.image;
    if (!image) {
      showError(t("error.noImage"));
      resetButton(button);
      return;
    }

    state.data = body;
    mountSvg(image);
    renderMetrics(body);
    renderTables(body);
    showWarnings(body.warnings, body.detected_columns);

    const result = body.result;
    $("mapMeta").textContent =
      "pm4py · " + result.algorithm + " · " + Math.round(result.computed_in_ms) + " ms";

    notify(t("toast.ready"));
    resetButton(button);
  }

  function resetButton(button) {
    button.classList.remove("loading");
    button.disabled = false;
    button.textContent = t("actions.run");
  }

  // ----------------------------------------------------------- map view
  function mountSvg(source) {
    const stage = $("stage");
    stage.textContent = "";

    const parsed = new DOMParser().parseFromString(source, "image/svg+xml");
    const svg = parsed.documentElement;
    if (!svg || svg.nodeName === "parsererror" || svg.querySelector("parsererror")) {
      showError(t("error.noImage"));
      return;
    }

    // Graphviz sizes the root in points; the viewBox is the honest geometry.
    const viewBox = (svg.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number);
    const width = viewBox.length === 4 && viewBox[2] ? viewBox[2] : svg.clientWidth || 800;
    const height = viewBox.length === 4 && viewBox[3] ? viewBox[3] : svg.clientHeight || 600;

    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.removeAttribute("style");

    state.natural = { w: width, h: height };
    stage.appendChild(document.importNode(svg, true));
    state.svg = stage.firstElementChild;

    $("empty").style.display = "none";
    $("mapSearch").value = "";
    initialView();
  }

  function applyTransform() {
    $("stage").style.transform =
      "translate(" + state.panX + "px," + state.panY + "px) scale(" + state.zoom + ")";
    $("zoomReadout").textContent = Math.round(state.zoom * 100) + "%";
  }

  function setZoom(next, anchorX, anchorY) {
    const clamped = Math.max(0.1, Math.min(8, next));
    if (anchorX === undefined) {
      const rect = $("viewport").getBoundingClientRect();
      anchorX = rect.width / 2;
      anchorY = rect.height / 2;
    }
    // Keep the point under the cursor pinned while the scale changes.
    const worldX = (anchorX - state.panX) / state.zoom;
    const worldY = (anchorY - state.panY) / state.zoom;
    state.zoom = clamped;
    state.panX = anchorX - worldX * clamped;
    state.panY = anchorY - worldY * clamped;
    applyTransform();
  }

  /** Scale at which the entire graph is visible. */
  function fitScale(rect) {
    return Math.min(rect.width / state.natural.w, rect.height / state.natural.h) * 0.94;
  }

  function fitMap() {
    if (!state.svg) return;
    const rect = $("viewport").getBoundingClientRect();
    state.zoom = Math.max(0.1, Math.min(8, fitScale(rect)));
    state.panX = (rect.width - state.natural.w * state.zoom) / 2;
    state.panY = (rect.height - state.natural.h * state.zoom) / 2;
    applyTransform();
  }

  /* Directly-follows graphs come out as long ribbons - a 2800x200 chain fits
   * the viewport only at ~27%, where the labels are unreadable. So the *first*
   * view never goes below READABLE_MIN: it anchors at the start of the process
   * and the user pans. The fit button still shows the whole graph. */
  const READABLE_MIN = 0.45;

  function initialView() {
    if (!state.svg) return;
    const rect = $("viewport").getBoundingClientRect();
    const scale = fitScale(rect);
    if (scale >= READABLE_MIN) { fitMap(); return; }
    state.zoom = READABLE_MIN;
    state.panX = 16;
    state.panY = Math.max(0, (rect.height - state.natural.h * state.zoom) / 2);
    applyTransform();
  }

  function actualSize() {
    if (!state.svg) return;
    const rect = $("viewport").getBoundingClientRect();
    state.zoom = 1;
    state.panX = (rect.width - state.natural.w) / 2;
    state.panY = (rect.height - state.natural.h) / 2;
    applyTransform();
  }

  function wireMap() {
    const viewport = $("viewport");
    let dragging = false;
    let originX = 0;
    let originY = 0;

    viewport.addEventListener("wheel", (event) => {
      if (!state.svg) return;
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      const factor = Math.exp(-event.deltaY * 0.0015);
      setZoom(state.zoom * factor, event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });

    viewport.addEventListener("pointerdown", (event) => {
      if (!state.svg) return;
      dragging = true;
      originX = event.clientX - state.panX;
      originY = event.clientY - state.panY;
      viewport.classList.add("dragging");
      viewport.setPointerCapture(event.pointerId);
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      state.panX = event.clientX - originX;
      state.panY = event.clientY - originY;
      applyTransform();
    });
    const endDrag = () => { dragging = false; viewport.classList.remove("dragging"); };
    viewport.addEventListener("pointerup", endDrag);
    viewport.addEventListener("pointercancel", endDrag);
    viewport.addEventListener("dblclick", fitMap);

    $("zoomIn").addEventListener("click", () => setZoom(state.zoom * 1.25));
    $("zoomOut").addEventListener("click", () => setZoom(state.zoom / 1.25));
    $("zoomReset").addEventListener("click", actualSize);
    $("fitMap").addEventListener("click", fitMap);

    $("fullscreen").addEventListener("click", () => {
      if (document.fullscreenElement) document.exitFullscreen();
      else viewport.requestFullscreen && viewport.requestFullscreen();
    });
    document.addEventListener("fullscreenchange", () => setTimeout(fitMap, 60));

    window.addEventListener("resize", () => { if (state.svg) fitMap(); });

    // Keyboard: +/-/0/f while not typing in a field.
    document.addEventListener("keydown", (event) => {
      const tag = (event.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea") return;
      if (event.key === "+" || event.key === "=") setZoom(state.zoom * 1.25);
      else if (event.key === "-") setZoom(state.zoom / 1.25);
      else if (event.key === "0") actualSize();
      else if (event.key.toLowerCase() === "f") fitMap();
    });

    $("mapSearch").addEventListener("input", (event) => searchMap(event.target.value));
    $("dlSvg").addEventListener("click", downloadSvg);
    $("dlPng").addEventListener("click", downloadPng);
  }

  /** Highlights matching graphviz nodes; dims the rest. */
  function searchMap(query) {
    if (!state.svg) return;
    const nodes = state.svg.querySelectorAll("g.node");
    const term = query.trim().toLowerCase();

    if (!term) {
      nodes.forEach((node) => node.classList.remove("pm-hit", "pm-dim"));
      return;
    }
    let hits = 0;
    nodes.forEach((node) => {
      const title = node.querySelector("title");
      const label = (title ? title.textContent : "") + " " +
        Array.from(node.querySelectorAll("text")).map((n) => n.textContent).join(" ");
      const match = label.toLowerCase().includes(term);
      node.classList.toggle("pm-hit", match);
      node.classList.toggle("pm-dim", !match);
      if (match) hits += 1;
    });
    $("zoomReadout").textContent = hits ? t("map.matches", { n: hits }) : t("map.noMatches");
    setTimeout(applyTransform, 1400);
  }

  function currentSvgText() {
    if (!state.svg) return null;
    const clone = state.svg.cloneNode(true);
    clone.querySelectorAll(".pm-hit, .pm-dim").forEach((node) =>
      node.classList.remove("pm-hit", "pm-dim")
    );
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
    return new XMLSerializer().serializeToString(clone);
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify(t("toast.downloaded"));
  }

  function downloadSvg() {
    const text = currentSvgText();
    if (!text) return;
    saveBlob(new Blob([text], { type: "image/svg+xml;charset=utf-8" }), "process-map.svg");
  }

  function downloadPng() {
    const text = currentSvgText();
    if (!text) return;
    const scale = 2;
    const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml;charset=utf-8" }));
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = state.natural.w * scale;
      canvas.height = state.natural.h * scale;
      const context = canvas.getContext("2d");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => {
        if (blob) saveBlob(blob, "process-map.png");
      }, "image/png");
    };
    image.onerror = () => { URL.revokeObjectURL(url); showError(t("error.generic")); };
    image.src = url;
  }

  // ------------------------------------------------------------ metrics
  function renderMetrics(body) {
    const stats = body.statistics || {};
    const bottlenecks = body.bottlenecks || {};

    $("mEvents").textContent = formatNumber(stats.events || 0);
    $("mCases").textContent = formatNumber(stats.cases || 0);

    const from = formatDate(stats.start_time);
    const to = formatDate(stats.end_time);
    $("mEventsSub").textContent = from && to ? t("metrics.span", { from, to }) : t("metrics.waiting");
    $("mCasesSub").textContent =
      formatNumber(stats.variants || 0) + " · " + t("metrics.paths").toLowerCase();

    const throughput = stats.throughput_seconds || {};
    $("mCycle").textContent = formatDuration(throughput.median);
    $("mP95").textContent = t("metrics.p95", { v: formatDuration(throughput.p95) });

    const reworkCases = (bottlenecks.rework || []).reduce(
      (sum, item) => Math.max(sum, item.cases_with_rework || 0), 0
    );
    $("mRework").textContent = stats.cases ? formatPercent(reworkCases / stats.cases) : "0%";
    $("mReworkSub").textContent = t("metrics.repeated");
  }

  // ------------------------------------------------------------- tables
  function cell(row, text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    row.appendChild(td);
    return td;
  }

  function barCell(row, text, ratio) {
    const td = cell(row, text, "num");
    const bar = document.createElement("span");
    bar.className = "bar";
    const fill = document.createElement("i");
    fill.style.width = Math.max(2, Math.min(100, ratio * 100)) + "%";
    bar.appendChild(fill);
    td.appendChild(bar);
    return td;
  }

  function renderTables(body) {
    renderVariants((body.variants && body.variants.items) || []);
    renderBottlenecks(body.bottlenecks || {});
    renderActivities((body.statistics && body.statistics.activity_stats) || []);
  }

  function renderEmptyTables() {
    renderVariants([]);
    renderBottlenecks({});
    renderActivities([]);
  }

  function renderVariants(items) {
    const tbody = $("variantsBody");
    tbody.textContent = "";
    $("variantsEmpty").style.display = items.length ? "none" : "block";
    $("cVariants").textContent = items.length ? items.length : "";

    items.forEach((item) => {
      const row = document.createElement("tr");
      cell(row, item.rank, "num");

      const seq = document.createElement("td");
      seq.className = "seq";
      (item.sequence || []).forEach((step, index) => {
        if (index) {
          const arrow = document.createElement("span");
          arrow.className = "seq-arrow";
          arrow.textContent = "→";
          seq.appendChild(arrow);
        }
        const chip = document.createElement("span");
        chip.className = "seq-step";
        chip.textContent = step;
        seq.appendChild(chip);
      });
      row.appendChild(seq);

      cell(row, formatNumber(item.cases), "num");
      barCell(row, formatPercent(item.share), item.share || 0);
      cell(row, formatDuration(item.median_duration_seconds), "num");
      cell(row, formatDuration(item.mean_duration_seconds), "num");
      tbody.appendChild(row);
    });
  }

  function renderBottlenecks(data) {
    const items = data.bottlenecks || [];
    const tbody = $("bottlenecksBody");
    tbody.textContent = "";
    $("bottlenecksEmpty").style.display = items.length ? "none" : "block";
    $("cBottlenecks").textContent = items.length ? items.length : "";

    items.forEach((item) => {
      const row = document.createElement("tr");
      cell(row, (item.source || "?") + " → " + (item.target || "?"));
      cell(row, formatNumber(item.occurrences), "num");
      cell(row, formatDuration(item.median_duration_seconds), "num");
      cell(row, formatDuration(item.p95_duration_seconds), "num");
      cell(row, formatDuration(item.total_duration_seconds), "num");
      barCell(row, formatPercent(item.share_of_total_time), item.share_of_total_time || 0);
      tbody.appendChild(row);
    });

    const rework = data.rework || [];
    const reworkBody = $("reworkBody");
    reworkBody.textContent = "";
    $("reworkBlock").hidden = rework.length === 0;
    rework.forEach((item) => {
      const row = document.createElement("tr");
      cell(row, item.activity);
      cell(row, formatNumber(item.cases_with_rework), "num");
      cell(row, formatNumber(item.total_repetitions), "num");
      reworkBody.appendChild(row);
    });
  }

  function renderActivities(items) {
    const tbody = $("activitiesBody");
    tbody.textContent = "";
    $("activitiesEmpty").style.display = items.length ? "none" : "block";
    $("cActivities").textContent = items.length ? items.length : "";

    items.forEach((item) => {
      const row = document.createElement("tr");
      cell(row, item.activity);
      cell(row, formatNumber(item.occurrences), "num");
      cell(row, formatNumber(item.cases), "num");
      barCell(row, formatPercent(item.share_of_events), item.share_of_events || 0);
      cell(row, formatDuration(item.mean_waiting_after_seconds), "num");
      tbody.appendChild(row);
    });
  }

  // --------------------------------------------------------------- tabs
  function wireTabs() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((other) =>
          other.setAttribute("aria-selected", String(other === tab))
        );
        document.querySelectorAll(".tabpanel").forEach((panel) =>
          panel.classList.toggle("active", panel.id === tab.getAttribute("aria-controls"))
        );
        $("mapTools").style.visibility = tab.dataset.tab === "map" ? "visible" : "hidden";
        if (tab.dataset.tab === "map" && state.svg) fitMap();
      });
    });
  }

  // -------------------------------------------------------------- reset
  function resetAll() {
    state.data = null;
    state.svg = null;
    setFile(null);
    $("storedLog").value = "";
    toggleSourceMode();
    $("stage").textContent = "";
    $("empty").style.display = "grid";
    $("mapMeta").textContent = "";
    $("mapSearch").value = "";
    $("zoomReadout").textContent = "100%";
    ["mEvents", "mCases", "mCycle", "mRework"].forEach((id) => ($(id).textContent = "—"));
    $("mEventsSub").textContent = t("metrics.waiting");
    $("mCasesSub").textContent = t("metrics.instances");
    $("mP95").textContent = t("metrics.p95", { v: "—" });
    $("mReworkSub").textContent = t("metrics.repeated");
    renderEmptyTables();
    clearError();
    $("warnings").classList.remove("show");
    notify(t("toast.cleared"));
  }

  // ------------------------------------------------------------- ranges
  function updateNoiseOutput() {
    $("noiseOut").textContent = Math.round(parseFloat($("noise").value) * 100) + "%";
  }
  function updateCoverageOutput() {
    const value = parseFloat($("coverage").value);
    $("coverageOut").textContent =
      value >= 1 ? t("controls.coverageAll") : Math.round(value * 100) + "%";
  }

  // --------------------------------------------------------------- boot
  function init() {
    applyTheme();
    applyLanguage();

    $("apiKey").value = store.get("pm-api-key", "");
    $("apiKey").addEventListener("input", (event) => {
      store.set("pm-api-key", event.target.value);
      if (event.target.value.trim()) {
        event.target.classList.remove("needed");
        if ($("status").dataset.state === "auth") setStatus("online");
        loadStoredLogs();
      }
    });

    $("language").addEventListener("change", (event) => {
      state.lang = event.target.value;
      store.set("pm-lang", state.lang);
      applyLanguage();
    });

    $("themeToggle").addEventListener("click", () => {
      state.theme = preferredTheme() === "dark" ? "light" : "dark";
      store.set("pm-theme", state.theme);
      applyTheme();
    });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (!state.theme) applyTheme();
    });

    $("noise").addEventListener("input", updateNoiseOutput);
    $("coverage").addEventListener("input", updateCoverageOutput);
    $("run").addEventListener("click", run);
    $("clear").addEventListener("click", resetAll);
    $("storedLog").addEventListener("change", toggleSourceMode);

    wireDropzone();
    wireTabs();
    wireMap();
    renderEmptyTables();
    checkHealth().then(loadStoredLogs);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
