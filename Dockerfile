# Runs the bot on any Docker host (Railway, Fly, a VPS, a Pi).
# Default command is the Discord bot; override with
# `python -m argumentwinner --telegram` to run Telegram instead.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[telegram]"

# Deployed bots want sessions to survive restarts, so sqlite is the image
# default. Mount a persistent volume at /data (on Railway: attach a Volume
# with mount path /data) or sessions only last until the next redeploy.
ENV AW_SESSION_STORE=sqlite \
    AW_SQLITE_PATH=/data/argumentwinner.db
RUN mkdir -p /data

CMD ["python", "-m", "argumentwinner"]
