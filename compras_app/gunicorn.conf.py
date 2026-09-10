"""Safe defaults for Render's existing ``gunicorn app:app`` command."""

worker_class = "gthread"
workers = 1
threads = 2
timeout = 120
graceful_timeout = 120
max_requests = 50
max_requests_jitter = 10
keepalive = 5
accesslog = "-"
errorlog = "-"
