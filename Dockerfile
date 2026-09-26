FROM python:3.14-slim
WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
VOLUME ["/srv/app/data"]
CMD ["python", "-m", "app.main"]
