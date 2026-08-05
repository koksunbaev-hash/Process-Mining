# Public STT for Render

Render cannot resolve the Docker Compose hostname `http://stt:8080`.
That hostname only works inside `docker compose`, where the `stt` container
exists next to `process-mining`.

For the Render deployment use a real public HTTPS URL for the STT server:

```text
phone -> pushtotalk Render -> process-mining Render -> public STT URL -> text
```

The `process-mining` service calls:

```text
POST <PM_STT_URL>/stt?lang=ru
Content-Type: audio/wav
```

So if the public STT base URL is:

```text
https://your-stt-domain.example
```

then set this in Render on the `process-mining` service:

```env
PM_STT_URL=https://your-stt-domain.example
PM_STT_LANGUAGE=ru
```

Do not set `PM_STT_URL=http://stt:8080` on Render.

## Option A: STT on the Docker host

On the machine/server where Docker Compose runs:

```powershell
docker compose up -d stt
```

Check locally:

```powershell
curl http://127.0.0.1:8080
```

Expose this local service through a tunnel that gives HTTPS, for example:

- Tailscale Funnel
- Cloudflare Tunnel
- ngrok
- a reverse proxy on a VPS

The public URL must reach the STT server root. `process-mining` appends `/stt`
itself.

## Option B: quick tunnel with ngrok

If STT is listening on local port `8080`:

```powershell
ngrok http 8080
```

ngrok will print something like:

```text
https://abc-123.ngrok-free.app
```

Then set in Render `process-mining`:

```env
PM_STT_URL=https://abc-123.ngrok-free.app
PM_STT_SKIP_NGROK_WARNING=true
```

Redeploy `process-mining`.

## Render variables

`process-mining`:

```env
PM_STT_URL=https://your-public-stt-url
PM_STT_LANGUAGE=ru
PM_API_KEYS=<same token used by PTT_TRANSCRIBE_TOKEN>
```

`pushtotalk`:

```env
PTT_TRANSCRIBE_URL=https://process-mining-7daf.onrender.com/api/transcriptions/sync
PTT_TRANSCRIBE_TOKEN=<same token as PM_API_KEYS>
```

## Manual check

1. Open:

```text
https://process-mining-7daf.onrender.com/api/transcriptions/capabilities
```

or check the service logs. This proves the transcription endpoint exists; the
real STT check happens when an audio request reaches `/api/transcriptions/sync`.

2. Send audio from the phone.

3. In `pushtotalk` logs a successful path looks like:

```text
POST /api/speech/transcribe status=200
Published PushToTalk text to MQTT topic=voice/commands/recognized
```

4. In `voice-gateway` logs:

```text
MQTT voice event routed status=ok project=kms
```

5. In KMS:

```text
Голосовые сообщения -> команда появилась -> Подтвердить
```
