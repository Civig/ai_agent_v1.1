import ipaddress
import os
import socket
from typing import Iterable

FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_LOOPBACK_ALLOWLIST = ("127.0.0.1", "::1")


def _sort_allowlist(values: Iterable[str]) -> list[str]:
    def sort_key(item: str) -> tuple[int, int, str, int]:
        network = ipaddress.ip_network(item, strict=False)
        max_prefix = network.max_prefixlen
        return (
            network.version,
            0 if network.prefixlen == max_prefix else 1,
            str(network.network_address),
            network.prefixlen,
        )

    unique_values = {value.strip() for value in values if value and value.strip()}
    return sorted(unique_values, key=sort_key)


def get_interface_addresses() -> dict[str, list[object]]:
    import psutil

    return psutil.net_if_addrs()


def build_default_forwarded_allow_ips() -> str:
    allowlist: list[str] = list(DEFAULT_LOOPBACK_ALLOWLIST)
    for addresses in get_interface_addresses().values():
        for address in addresses:
            if address.family not in (socket.AF_INET, socket.AF_INET6):
                continue

            ip_value = (address.address or "").split("%", 1)[0].strip()
            netmask_value = (address.netmask or "").split("%", 1)[0].strip()
            if not ip_value or not netmask_value:
                continue

            try:
                interface = ipaddress.ip_interface(f"{ip_value}/{netmask_value}")
            except ValueError:
                continue
            if interface.ip.is_loopback:
                allowlist.append(str(interface.ip))
                continue

            allowlist.append(str(interface.network))

    return ",".join(_sort_allowlist(allowlist))


def resolve_forwarded_allow_ips(env: dict[str, str] | None = None) -> str:
    environment = env if env is not None else os.environ
    configured_value = (environment.get(FORWARDED_ALLOW_IPS_ENV) or "").strip()
    if configured_value:
        return configured_value
    return build_default_forwarded_allow_ips()


def build_uvicorn_run_kwargs(env: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "app": "app:app",
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "proxy_headers": True,
        "forwarded_allow_ips": resolve_forwarded_allow_ips(env),
    }


def main() -> None:
    import uvicorn

    uvicorn.run(**build_uvicorn_run_kwargs())


if __name__ == "__main__":
    main()
