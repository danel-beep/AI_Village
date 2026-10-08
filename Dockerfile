# The public website (docs/site.md): aivillage/web.py behind one password, a game server per browser.
# Built and run by Railway from the `site-live` branch (.github/workflows/site-deploy.yml moves it to main).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY . .
# editable: the game reads viewer/, presets/, scenarios/ next to the package
RUN pip install -e ".[live]"
ENV AIVILLAGE_DATA=/data
CMD ["python", "-m", "aivillage.web"]
