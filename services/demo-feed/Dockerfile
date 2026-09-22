FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY feed.py selfcheck.py build_profile.py profile.json ./

# Состояние - какие дни уже заведены, какие события ещё ждут своего часа.
# Переживает пересоздание контейнера, иначе после каждого рестарта журнал
# получал бы дыру в сутки, а дыра - первое, что выдаёт синтетику.
VOLUME ["/srv/demo-feed"]

CMD ["python", "feed.py"]
