"""LAN address discovery (plan §12.2). Pure helpers, no Django imports."""

import ipaddress

import ifaddr

_VIRTUAL_MARKERS = (
    "vethernet",
    "wsl",
    "virtualbox",
    "vmware",
    "docker",
    "loopback",
    "vbox",
    "hyper-v",
)


def lan_ipv4_addresses() -> list[str]:
    """Private IPv4 addresses of real network adapters, best candidates first."""
    found: list[tuple[int, str]] = []
    for adapter in ifaddr.get_adapters():
        label = f"{adapter.nice_name} {adapter.name}".lower()
        virtual = any(marker in label for marker in _VIRTUAL_MARKERS)
        for ip in adapter.ips:
            if not ip.is_IPv4:
                continue
            addr = ipaddress.ip_address(ip.ip)
            if addr.is_loopback or addr.is_link_local or not addr.is_private:
                continue
            found.append((1 if virtual else 0, str(addr)))
    found.sort(key=lambda item: item[0])
    return [addr for _, addr in found]


def base_url(request=None, port: int | None = None) -> str:
    """http://<lan-ip>:<port> for building links students can open on their phones."""
    if port is None:
        port = int(request.get_port()) if request is not None else 8000
    addresses = lan_ipv4_addresses()
    host = (
        addresses[0]
        if addresses
        else (request.get_host().split(":")[0] if request else "127.0.0.1")
    )
    return f"http://{host}:{port}"
