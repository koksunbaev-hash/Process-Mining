(function () {
  const root = document.querySelector("[data-voice-widget]");
  if (!root) return;

  const $ = (name) => root.querySelector(`[data-voice-${name}]`);
  const panel = $("panel");
  const startBtn = $("start");
  const stopBtn = $("stop");
  const confirmBtn = $("confirm");
  const rejectBtn = $("reject");
  const result = $("result");
  const state = $("state");
  const timer = $("timer");
  const message = $("message");
  let recorder = null;
  let stream = null;
  let chunks = [];
  let startedAt = null;
  let tick = null;
  let poll = null;
  let commandId = null;
  let voiceId = null;

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setState(text) {
    state.textContent = text;
  }

  function setMessage(text) {
    message.textContent = text || "";
  }

  function formatTime(ms) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  function stopPolling() {
    if (poll) window.clearInterval(poll);
    poll = null;
  }

  function resetRecording() {
    chunks = [];
    startedAt = null;
    if (tick) window.clearInterval(tick);
    tick = null;
    timer.textContent = "00:00";
    startBtn.hidden = false;
    stopBtn.hidden = true;
  }

  function preferredMimeType() {
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    return types.find((type) => window.MediaRecorder && MediaRecorder.isTypeSupported(type)) || "";
  }

  async function startRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      setState("Ошибка");
      setMessage("Браузер не поддерживает запись голоса.");
      return;
    }
    try {
      setState("Запрос разрешения микрофона");
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(stream, preferredMimeType() ? { mimeType: preferredMimeType() } : undefined);
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      recorder.onstop = uploadRecording;
      recorder.start();
      startedAt = Date.now();
      setState("Запись");
      startBtn.hidden = true;
      stopBtn.hidden = false;
      result.hidden = true;
      tick = window.setInterval(() => {
        const elapsed = Date.now() - startedAt;
        timer.textContent = formatTime(elapsed);
        if (elapsed >= 30000 && recorder && recorder.state === "recording") stopRecording();
      }, 250);
    } catch (error) {
      setState("Ошибка");
      setMessage("Микрофон недоступен или разрешение запрещено.");
      resetRecording();
    }
  }

  function stopRecording() {
    if (recorder && recorder.state === "recording") recorder.stop();
    if (stream) stream.getTracks().forEach((track) => track.stop());
    setState("Отправка");
    startBtn.hidden = true;
    stopBtn.hidden = true;
  }

  async function uploadRecording() {
    if (tick) window.clearInterval(tick);
    const mime = recorder.mimeType || "audio/webm";
    const blob = new Blob(chunks, { type: mime });
    if (!blob.size) {
      setState("Ошибка");
      setMessage("Запись пустая.");
      resetRecording();
      return;
    }
    const ext = mime.includes("ogg") ? "ogg" : mime.includes("mp4") ? "m4a" : "webm";
    const form = new FormData();
    form.append("audio_file", blob, `voice-${Date.now()}.${ext}`);
    form.append("client_request_id", crypto.randomUUID ? crypto.randomUUID() : `voice-${Date.now()}`);
    try {
      const response = await fetch("/api/voice-messages/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        body: form,
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("upload failed");
      const data = await response.json();
      voiceId = data.id;
      setState("Обработка");
      startPolling();
    } catch (error) {
      setState("Ошибка");
      setMessage("Не удалось отправить голосовую команду.");
      resetRecording();
    }
  }

  function startPolling() {
    stopPolling();
    const deadline = Date.now() + 45000;
    poll = window.setInterval(async () => {
      if (Date.now() > deadline) {
        stopPolling();
        setState("Ошибка");
        setMessage("Истекло время ожидания распознавания.");
        resetRecording();
        return;
      }
      const response = await fetch(`/api/voice-messages/${voiceId}/status/`, { credentials: "same-origin" });
      if (!response.ok) return;
      const data = await response.json();
      if (data.status === "failed") {
        stopPolling();
        setState("Ошибка");
        setMessage(data.processing_error || "Process Mining вернул ошибку.");
        resetRecording();
      }
      if (data.command) {
        stopPolling();
        showCommand(data);
      }
    }, 400);
  }

  function showCommand(data) {
    const cmd = data.command;
    const extracted = cmd.extracted_data || {};
    commandId = cmd.id;
    setState(cmd.status === "needs_review" ? "Ожидание подтверждения" : "Команда распознана");
    $("transcript").textContent = data.transcript || "";
    $("batch").textContent = extracted.batch_number || "-";
    $("current").textContent = extracted.current_stage || "-";
    $("next").textContent = extracted.next_stage || extracted.to_stage || "-";
    $("comment").textContent = extracted.comment || "-";
    $("confidence").textContent = cmd.confidence == null ? "-" : `${Math.round(cmd.confidence * 100)}%`;
    $("warning").hidden = !(cmd.confidence != null && cmd.confidence < 0.8);
    result.hidden = false;
    resetRecording();
  }

  async function confirmCommand() {
    if (!commandId) return;
    setState("Выполнение");
    const response = await fetch(`/api/voice-commands/${commandId}/confirm/`, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      setState("Ошибка");
      setMessage(data.detail || "Не удалось выполнить команду.");
      return;
    }
    setState("Успешно");
    setMessage("Команда выполнена.");
    result.hidden = true;
  }

  async function rejectCommand() {
    if (commandId) {
      await fetch(`/api/voice-commands/${commandId}/reject/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        credentials: "same-origin",
      });
    }
    result.hidden = true;
    commandId = null;
    setState("Готов к записи");
    setMessage("");
  }

  $("open").addEventListener("click", () => {
    panel.hidden = !panel.hidden;
  });
  $("close").addEventListener("click", () => {
    panel.hidden = true;
    stopPolling();
  });
  startBtn.addEventListener("click", startRecording);
  stopBtn.addEventListener("click", stopRecording);
  confirmBtn.addEventListener("click", confirmCommand);
  rejectBtn.addEventListener("click", rejectCommand);
})();
