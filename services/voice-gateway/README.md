# Voice Gateway

Reusable bridge for voice commands.

It is intentionally separate from KMS and Process Mining:

1. The phone app or OVOS recognizes speech.
2. OVOS publishes a text event to MQTT.
3. Voice Gateway subscribes to the MQTT topic.
4. Voice Gateway routes the text to a project adapter.
5. The KMS adapter sends the text to `POST /api/pushtotalk/commands/`.
6. KMS creates `VoiceMessage` and `VoiceCommand`; the human still confirms the command in KMS.

Process Mining stays a separate brick. It analyzes event logs. It must not change bakery batches.

## Run locally

```powershell
cd services/voice-gateway
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Health:

```text
GET http://localhost:8010/health
```

Manual test without MQTT:

```powershell
curl -X POST http://localhost:8010/api/voice-events/ `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer <VOICE_GATEWAY_API_TOKEN>" `
  -d "{\"text\":\"Партия DEMO-B-0012 закончила замес\",\"project\":\"kms\",\"request_id\":\"test-1\"}"
```

## MQTT payload from OVOS

Topic by default:

```text
voice/commands/recognized
```

Message:

```json
{
  "project": "kms",
  "source": "ovos",
  "request_id": "android-001-20260804-153000",
  "device_id": "android-001",
  "user_id": "operator-1",
  "text": "Партия DEMO-B-0012 закончила замес, передать на формовку",
  "intent": "move_batch",
  "confidence": 0.91,
  "metadata": {
    "room": "замес"
  }
}
```

## Environment

```text
VOICE_GATEWAY_API_TOKEN=
VOICE_GATEWAY_PROJECT=kms

VOICE_GATEWAY_MQTT_HOST=
VOICE_GATEWAY_MQTT_PORT=1883
VOICE_GATEWAY_MQTT_USERNAME=
VOICE_GATEWAY_MQTT_PASSWORD=
VOICE_GATEWAY_MQTT_TLS=false
VOICE_GATEWAY_CLIENT_ID=voice-gateway
VOICE_GATEWAY_SUBSCRIBE_TOPIC=voice/commands/recognized

VOICE_GATEWAY_KMS_COMMAND_URL=https://qms-demo.onrender.com/api/pushtotalk/commands/
VOICE_GATEWAY_KMS_API_TOKEN=
VOICE_GATEWAY_HTTP_TIMEOUT_SECONDS=10
```

`VOICE_GATEWAY_KMS_API_TOKEN` must equal `PUSHTOTALK_API_TOKEN` in KMS.

## Render

Create a new Web Service from this folder:

```text
Root Directory: services/voice-gateway
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Add the environment variables above in Render. Do not put tokens in GitHub.

## Tests

```powershell
cd services/voice-gateway
pip install -r requirements-dev.txt
pytest
```
