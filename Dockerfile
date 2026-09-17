FROM python:3.11-slim

WORKDIR /app

# پوشه داده برای Volume (Railway: mount path = /app/data)
RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# مسیر پایدار دیتابیس روی Volume
ENV DB_PATH=/app/data/bot.db
ENV PORT=8080

# Volume در Railway باید روی /app/data مانت شود تا داده بعد از ری‌استارت نپرد
CMD ["python", "bot.py"]
