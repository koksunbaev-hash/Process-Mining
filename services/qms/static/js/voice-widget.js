/* Push-to-talk voice commands.
 *
 * Hold the microphone button - or the space bar - speak, let go. That is the
 * whole interaction. The previous version asked for two deliberate clicks
 * around the sentence ("start", then "stop"), which is one click too many when
 * the operator's hands are covered in flour.
 *
 * Releasing sends automatically. Sliding off the button or pressing Escape
 * while still holding cancels without sending, so a mistake costs nothing.
 */
(function () {
  const root = document.querySelector("[data-voice-widget]");
  if (!root) return;

  const $ = (name) => root.querySelector(`[data-voice-${name}]`);
  const panel = $("panel");
  const ptt = $("ptt");
  const state = $("state");
  const message = $("message");
  const hint = $("hint");
  const live = $("live");
  const level = $("level");
  const timer = $("timer");
  const result = $("result");

  const MIN_HOLD_MS = 300;      // below this it was a slip, not a command
  const MAX_HOLD_MS = 30000;    // hard stop, matches the server's limit
  const RECOGNITION_TIMEOUT_MS = 45000;

  let recorder = null;
  let stream = null;
  let audioCtx = null;
  let analyser = null;
  let meterRaf = null;
  let chunks = [];
  let startedAt = null;
  let tick = null;
  let poll = null;
  let commandId = null;
  let voiceId = null;
  let holding = false;
  let cancelled = false;

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setMode(mode) {
    root.dataset.voiceMode = mode;
  }

  function setState(text) {
    state.textContent = text;
  }

  function setMessage(text) {
    message.textContent = text || "";
  }

  function openPanel() {
    panel.hidden = false;
  }

  function stopPolling() {
    if (poll && typeof poll.stop === "function") {
      const handle = poll;
      poll = null;
      handle.stop();
      return;
    }
    poll = null;
  }

  function teardownAudio() {
    if (meterRaf) cancelAnimationFrame(meterRaf);
    meterRaf = null;
    if (tick) window.clearInterval(tick);
    tick = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    if (audioCtx && audioCtx.state !== "closed") audioCtx.close().catch(() => {});
    audioCtx = null;
    analyser = null;
    live.hidden = true;
    level.style.width = "0%";
  }

  function preferredMimeType() {
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    return types.find((type) => window.MediaRecorder && MediaRecorder.isTypeSupported(type)) || "";
  }

  /* A level meter is not decoration: without it a muted or wrong input device
   * looks exactly like a working one until the transcript comes back empty. */
  function startMeter(mediaStream) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtx = new Ctx();
      const source = audioCtx.createMediaStreamSource(mediaStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const buffer = new Uint8Array(analyser.frequencyBinCount);
      const draw = () => {
        if (!analyser) return;
        analyser.getByteTimeDomainData(buffer);
        let peak = 0;
        for (let i = 0; i < buffer.length; i += 1) {
          peak = Math.max(peak, Math.abs(buffer[i] - 128));
        }
        level.style.width = Math.min(100, Math.round((peak / 128) * 160)) + "%";
        meterRaf = requestAnimationFrame(draw);
      };
      draw();
    } catch {
      /* the meter is a nicety - never let it break recording */
    }
  }

  async function beginHold() {
    if (holding || recorder) return;
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      openPanel();
      setMode("error");
      setState("Ошибка");
      setMessage("Браузер не поддерживает запись голоса.");
      return;
    }

    holding = true;
    cancelled = false;
    chunks = [];
    stopPolling();
    result.hidden = true;
    setMessage("");
    openPanel();
    setMode("requesting");
    setState("Разрешите доступ к микрофону");

    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      holding = false;
      setMode("error");
      setState("Ошибка");
      setMessage("Микрофон недоступен или доступ запрещён.");
      teardownAudio();
      return;
    }

    // The user may have let go while the permission dialog was up.
    if (!holding) {
      teardownAudio();
      setMode("idle");
      setState("Готов к записи");
      return;
    }

    const mime = preferredMimeType();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size) chunks.push(event.data);
    };
    recorder.onstop = onRecorderStopped;
    recorder.start();

    startedAt = Date.now();
    setMode("recording");
    setState("Говорите…");
    live.hidden = false;
    startMeter(stream);

    tick = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      timer.textContent = (elapsed / 1000).toFixed(1) + " с";
      if (elapsed >= MAX_HOLD_MS) endHold();
    }, 100);
  }

  function endHold(options) {
    const abort = Boolean(options && options.abort);
    if (!holding) return;
    holding = false;

    if (!recorder || recorder.state !== "recording") {
      teardownAudio();
      setMode("idle");
      setState("Готов к записи");
      return;
    }

    const elapsed = Date.now() - startedAt;
    cancelled = abort || elapsed < MIN_HOLD_MS;
    recorder.stop();

    if (cancelled) {
      setMode("idle");
      setState("Готов к записи");
      setMessage(abort ? "Запись отменена." : "Слишком коротко - удерживайте кнопку, пока говорите.");
    } else {
      setMode("sending");
      setState("Отправка…");
    }
  }

  async function onRecorderStopped() {
    const mime = (recorder && recorder.mimeType) || "audio/webm";
    const blob = new Blob(chunks, { type: mime });
    recorder = null;
    teardownAudio();

    if (cancelled) return;
    if (!blob.size) {
      setMode("error");
      setState("Ошибка");
      setMessage("Запись пустая - похоже, микрофон ничего не услышал.");
      return;
    }

    const ext = mime.includes("ogg") ? "ogg" : mime.includes("mp4") ? "m4a" : "webm";
    const form = new FormData();
    form.append("audio_file", blob, `voice-${Date.now()}.${ext}`);
    form.append(
      "client_request_id",
      crypto.randomUUID ? crypto.randomUUID() : `voice-${Date.now()}`
    );

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
      setMode("recognizing");
      setState("Распознаю…");
      startPolling();
    } catch {
      setMode("error");
      setState("Ошибка");
      setMessage("Не удалось отправить голосовую команду.");
    }
  }

  /* Recognition takes about a second and a half, so a fixed 400ms poll spent
   * most of its life asking a server that had nothing new to say - up to a
   * hundred round trips per phrase. Ask often while an answer is plausible,
   * then back off. */
  function pollDelay(waitedMs) {
    if (waitedMs < 3000) return 300;
    if (waitedMs < 10000) return 800;
    return 1500;
  }

  function startPolling() {
    stopPolling();
    const startedPolling = Date.now();
    let stopped = false;

    const stop = () => {
      stopped = true;
      stopPolling();
    };
    poll = { stop: stop };

    const step = async () => {
      if (stopped) return;
      const waited = Date.now() - startedPolling;

      if (waited > RECOGNITION_TIMEOUT_MS) {
        stop();
        setMode("error");
        setState("Ошибка");
        setMessage("Истекло время ожидания распознавания.");
        return;
      }
      setState(`Распознаю… ${(waited / 1000).toFixed(0)} с`);

      let data;
      try {
        const response = await fetch(`/api/voice-messages/${voiceId}/status/`, {
          credentials: "same-origin",
        });
        if (response.ok) data = await response.json();
      } catch {
        /* a dropped poll is not an error - try again on the next tick */
      }

      if (stopped) return;
      if (data && data.status === "failed") {
        stop();
        setMode("error");
        setState("Ошибка");
        setMessage(data.processing_error || "Распознавание не удалось.");
        return;
      }
      if (data && data.command) {
        stop();
        showCommand(data);
        return;
      }
      window.setTimeout(step, pollDelay(waited));
    };

    step();
  }

  function showCommand(data) {
    const cmd = data.command;
    const extracted = cmd.extracted_data || {};
    commandId = cmd.id;
    setMode("result");
    setState("Проверьте и подтвердите");
    setMessage("");
    $("transcript").textContent = data.transcript || "";
    $("batch").textContent = extracted.batch_number || "-";
    $("current").textContent = extracted.current_stage || "-";
    $("next").textContent = extracted.next_stage || extracted.to_stage || "-";
    $("comment").textContent = extracted.comment || "-";
    $("confidence").textContent =
      cmd.confidence == null ? "-" : `${Math.round(cmd.confidence * 100)}%`;
    $("warning").hidden = !(cmd.confidence != null && cmd.confidence < 0.8);
    result.hidden = false;
  }

  async function confirmCommand() {
    if (!commandId) return;
    setState("Выполняю…");
    try {
      const response = await fetch(`/api/voice-commands/${commandId}/confirm/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setMode("error");
        setState("Ошибка");
        setMessage(data.detail || "Не удалось выполнить команду.");
        return;
      }
      setMode("done");
      setState("Готово");
      setMessage("Команда выполнена.");
      result.hidden = true;
      commandId = null;

      // The batch has already moved in the database; without this the board
      // still shows it in the old column and the command looks ignored.
      if (typeof window.kanbanRefresh === "function") {
        window.kanbanRefresh();
      } else if (/\/bakery\/board/.test(window.location.pathname)) {
        window.location.reload();
      }

      window.setTimeout(resetIdle, 2500);
    } catch {
      setMode("error");
      setState("Ошибка");
      setMessage("Сеть недоступна.");
    }
  }

  async function rejectCommand() {
    if (commandId) {
      try {
        await fetch(`/api/voice-commands/${commandId}/reject/`, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken() },
          credentials: "same-origin",
        });
      } catch {
        /* rejecting is best-effort - the record stays unconfirmed either way */
      }
    }
    commandId = null;
    result.hidden = true;
    resetIdle();
  }

  function resetIdle() {
    setMode("idle");
    setState("Готов к записи");
    setMessage("");
    timer.textContent = "0.0 с";
  }

  // ---- input: pointer -------------------------------------------------
  ptt.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    ptt.setPointerCapture(event.pointerId);
    beginHold();
  });
  ptt.addEventListener("pointerup", () => endHold());
  ptt.addEventListener("pointercancel", () => endHold({ abort: true }));
  // Sliding a finger off the button is the natural "never mind".
  ptt.addEventListener("pointerleave", () => {
    if (holding) endHold({ abort: true });
  });
  ptt.addEventListener("contextmenu", (event) => event.preventDefault());

  // ---- input: space bar ------------------------------------------------
  const typingIn = (el) =>
    el && (/^(input|textarea|select)$/i.test(el.tagName) || el.isContentEditable);

  document.addEventListener("keydown", (event) => {
    if (event.code !== "Space" || event.repeat || typingIn(event.target)) return;
    event.preventDefault();
    beginHold();
  });
  document.addEventListener("keyup", (event) => {
    if (event.code !== "Space" || typingIn(event.target)) return;
    event.preventDefault();
    endHold();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && holding) endHold({ abort: true });
  });
  // Releasing the key outside the window would otherwise leave it recording.
  window.addEventListener("blur", () => {
    if (holding) endHold({ abort: true });
  });

  $("close").addEventListener("click", () => {
    panel.hidden = true;
    stopPolling();
  });
  $("confirm").addEventListener("click", confirmCommand);
  $("reject").addEventListener("click", rejectCommand);

  hint.hidden = false;
})();
