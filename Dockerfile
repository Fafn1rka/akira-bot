FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаём папки для данных и кэша
RUN mkdir -p data assets/audio_cache logs

# Открываем порты для веб-аватара и телефона
EXPOSE 8765 8766

# По умолчанию запускаем в текстовом режиме без графического GUI
CMD ["python", "akira_app.py", "--text"]
