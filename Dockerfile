FROM python:3.11-slim

ADD --checksum=sha256:842c05600b70cb04639958269426e5ffe83ef390a069df7936286c6081ac0f1b \
    https://github.com/STAIxBWLB/hwp-cli/releases/download/v0.17.0/hwp-v0.17.0-x86_64-unknown-linux-gnu.tar.gz \
    /tmp/hwp-cli.tar.gz
RUN tar -xzf /tmp/hwp-cli.tar.gz -C /usr/local/bin hwp \
    && chmod +x /usr/local/bin/hwp \
    && rm /tmp/hwp-cli.tar.gz

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

CMD ["python", "-m", "app.healthcheck"]
