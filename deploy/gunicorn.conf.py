"""Own-machine public runtime; only a local proxy/tunnel reaches this listener."""
import os

bind = os.environ.get('SIGNAL_BIND', '127.0.0.1:8001')
workers = 2
worker_class = 'gthread'
threads = 4
timeout = 30
graceful_timeout = 30
# The browser bounds saved-list queries to 7,500 characters, including filters.
limit_request_line = 8190
accesslog = '-'
errorlog = '-'
# Avoid logging query strings, which may contain candidate search terms.
access_log_format = '%(t)s "%(m)s %(U)s" %(s)s %(L)s'
