'''为服务端网页工具提供统一的网址和目标地址安全校验。'''

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def resolve_host_addresses(hostname: str) -> list[ipaddress._BaseAddress]:
    '''解析主机名对应的所有地址，供后续检查是否指向受限网络。'''
    addresses: list[ipaddress._BaseAddress] = []
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return addresses
    for info in infos:
        sockaddr = info[4]
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return addresses


def is_blocked_address(address: ipaddress._BaseAddress) -> bool:
    '''判断地址是否属于默认禁止访问的私有、环回、保留或特殊用途范围。'''
    return address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified


def validate_public_http_url(
    url: str,
    *,
    allow_private_addresses: bool = False,
    action: str = "fetch",
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> str | None:
    '''在服务端抓取前检查协议、主机名解析和地址范围，拦截访问内网的请求。

    返回拒绝原因字符串表示网址不允许访问；返回 ``None`` 表示可以继续请求。
    自托管抓取服务运行在部署网络内，因此此检查默认阻止云元数据和私有地址。
    '''
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Error: Only http:// and https:// URLs are supported"

    if allow_private_addresses:
        return None

    hostname = parsed.hostname
    if not hostname:
        return "Error: URL host could not be parsed"

    normalized_host = hostname.strip().rstrip(".").lower()
    if normalized_host in _BLOCKED_HOSTNAMES:
        return f"Error: Refusing to {action} a private or loopback address"

    try:
        literal_ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        candidates = [literal_ip]
    else:
        resolve = resolver or resolve_host_addresses
        candidates = resolve(hostname)
        if not candidates:
            return "Error: URL host could not be resolved"

    if any(is_blocked_address(addr) for addr in candidates):
        return f"Error: Refusing to {action} a private, loopback, or metadata address"
    return None
