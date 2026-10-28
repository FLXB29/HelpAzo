import ipaddress
import json
import socket
import ssl
import threading
import urllib.request

_PRIMARY_DNS = '8.8.8.8'
_SECONDARY_DNS = '1.1.1.1'
_RESOLVE_TIMEOUT = 1.0
_RESOLVE_LIFETIME = 2.0
_DOH_ENDPOINTS = [
    {'ip': '8.8.8.8', 'host': 'dns.google'},
    {'ip': '8.8.4.4', 'host': 'dns.google'},
    {'ip': '1.1.1.1', 'host': 'cloudflare-dns.com'},
    {'ip': '1.0.0.1', 'host': 'cloudflare-dns.com'},
    {'ip': '9.9.9.9', 'host': 'dns.quad9.net'},
    {'ip': '149.112.112.112', 'host': 'dns.quad9.net'},
]

_original_getaddrinfo = socket.getaddrinfo
_cache = {}
_cache_lock = threading.Lock()
_init_lock = threading.Lock()
_resolver = None
_resolver_available = False
_doh_ssl_ctx = None
_doh_ssl_lock = threading.Lock()
_local = threading.local()

_LOCAL_PREFIXES = (
    'localhost', '127.', '::1', '0.', '10.',
    '172.16.', '172.17.', '172.18.', '172.19.', '172.20.', '172.21.', '172.22.', '172.23.', '172.24.',
    '172.25.', '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.',
    '192.168.', '169.254.'
)

def _is_local(host: str) -> bool:
    if not isinstance(host, str):
        return True
    lowered = host.lower()
    if lowered in ('localhost', 'localhost.localdomain') or lowered.endswith('.local'):
        return True
    for prefix in _LOCAL_PREFIXES:
        if lowered.startswith(prefix):
            return True
    return False

def _get_doh_ssl_ctx():
    global _doh_ssl_ctx
    if _doh_ssl_ctx is not None:
        return _doh_ssl_ctx
    with _doh_ssl_lock:
        if _doh_ssl_ctx is not None:
            return _doh_ssl_ctx
        try:
            ctx = ssl._create_unverified_context()
            ctx.check_hostname = False
            _doh_ssl_ctx = ctx
        except Exception:
            _doh_ssl_ctx = False
        return _doh_ssl_ctx

def _init_resolver():
    global _resolver, _resolver_available
    if _resolver_available:
        return
    with _init_lock:
        if _resolver_available:
            return
        try:
            import dns.resolver
            r = dns.resolver.Resolver()
            r.nameservers = [_PRIMARY_DNS, _SECONDARY_DNS]
            r.timeout = _RESOLVE_TIMEOUT
            r.lifetime = _RESOLVE_LIFETIME
            _resolver = r
            _resolver_available = True
        except ImportError:
            _resolver = None
            _resolver_available = False

def _resolve_host_via_doh(host: str):
    ctx = _get_doh_ssl_ctx()
    if not ctx:
        return None
    if getattr(_local, 'in_doh', False):
        return None
    _local.in_doh = True
    try:
        for rtype, _label in ((1, 'A'), (28, 'AAAA')):
            for ep in _DOH_ENDPOINTS:
                try:
                    url = f"https://{ep['ip']}/dns-query?name={host}&type={rtype}"
                    req = urllib.request.Request(
                        url,
                        headers={'Accept': 'application/dns-json', 'Host': ep['host']}
                    )
                    with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                        data = json.loads(resp.read())
                        for answer in data.get('Answer', []):
                            if answer.get('type') == rtype and answer.get('data'):
                                return answer['data']
                except Exception:
                    continue
    finally:
        _local.in_doh = False
    return None

def _resolve_host(host: str):
    if _resolver_available and _resolver is not None:
        try:
            answers = _resolver.resolve(host)
            for answer in answers:
                return str(answer)
        except Exception:
            pass
    return _resolve_host_via_doh(host)

def _make_cache_key(host, family):
    return (host, family)

def _custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if not isinstance(host, str) or _is_local(host):
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    try:
        ipaddress.ip_address(host)
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    except ValueError:
        pass

    key = _make_cache_key(host, family)
    with _cache_lock:
        cached = _cache.get(key)
    if cached:
        return cached

    try:
        ip = _resolve_host(host)
        if not ip:
            return _original_getaddrinfo(host, port, family, type, proto, flags)
        result = _original_getaddrinfo(ip, port, family, type, proto, flags)
        with _cache_lock:
            _cache[key] = result
        return result
    except Exception:
        return _original_getaddrinfo(host, port, family, type, proto, flags)

def install():
    _init_resolver()
    if _resolver_available or _get_doh_ssl_ctx():
        socket.getaddrinfo = _custom_getaddrinfo
