FROM python:3.11-slim

WORKDIR /app

# پوشه داده برای Volume (Railway: mount path = /app/data)
RUN mkdir -p /app/data /app/bin

# وابستگی‌های سیستم + هسته Xray برای تست واقعی اتصال
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip \
    && XRAY_VER=$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest | grep -oP '"tag_name":\s*"\K[^"]+' | head -1) \
    && XRAY_VER=${XRAY_VER:-v25.9.11} \
    && curl -fsSL -o /tmp/xray.zip \
        "https://github.com/XTLS/Xray-core/releases/download/${XRAY_VER}/Xray-linux-64.zip" \
    && unzip -o /tmp/xray.zip xray -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && rm -f /tmp/xray.zip \
    && xray version || true \
    && apt-get purge -y unzip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# مسیر پایدار دیتابیس روی Volume
ENV DB_PATH=/app/data/bot.db
ENV PORT=8080
# همزمانی تست واقعی (هر کدام یک پروسه xray)
ENV PROBE_CONCURRENCY=3
ENV PROBE_TIMEOUT=18

# Volume در Railway باید روی /app/data مانت شود تا داده بعد از ری‌استارت نپرد
CMD ["python", "bot.py"]
