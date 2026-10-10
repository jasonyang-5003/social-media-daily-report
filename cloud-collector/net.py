"""Use authenticated public DNS for workers.dev; retain hostname TLS checks."""
from contextlib import contextmanager
import socket
from urllib.parse import urlparse
import requests


@contextmanager
def worker_dns(url):
    host=urlparse(url).hostname
    if not host or not host.endswith(".workers.dev"):
        yield
        return
    answer=requests.get("https://cloudflare-dns.com/dns-query",params={"name":host,"type":"A"},headers={"Accept":"application/dns-json"},timeout=20)
    answer.raise_for_status()
    addresses=[row["data"] for row in answer.json().get("Answer",[]) if row["type"]==1]
    if not addresses:raise RuntimeError("Worker public DNS lookup failed")
    original=socket.getaddrinfo
    def resolve(name,*args,**kwargs):
        return original(addresses[0] if name==host else name,*args,**kwargs)
    socket.getaddrinfo=resolve
    try:yield
    finally:socket.getaddrinfo=original
