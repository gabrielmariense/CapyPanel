from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from capypanel.core.hosts.model import Host

KEY = "printer"

SNMP = "snmp"
DOC360 = "doc360"
COUNTER_SOURCES = (SNMP, DOC360)

_FIELDS = ("brand", "model", "serial", "asset_tag", "counter_source")


@dataclass(frozen=True)
class PrinterInfo:
    brand: str = ""
    model: str = ""
    serial: str = ""
    asset_tag: str = ""
    counter_source: str = SNMP
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def known_source(self) -> bool:
        return self.counter_source in COUNTER_SOURCES


def info_of(host: Host) -> PrinterInfo:
    data = host.extra.get(KEY)
    if not isinstance(data, Mapping):
        return PrinterInfo()
    texts = {name: data[name] for name in _FIELDS if isinstance(data.get(name), str)}
    return PrinterInfo(
        **{name: value.strip() for name, value in texts.items() if name != "counter_source"},
        counter_source=texts.get("counter_source") or SNMP,
        extra={k: v for k, v in data.items() if k not in texts},
    )


def with_info(host: Host, info: PrinterInfo) -> Host:
    data: dict[str, Any] = dict(info.extra)
    for name in _FIELDS:
        value = getattr(info, name)
        if value and not (name == "counter_source" and value == SNMP):
            data[name] = value
    extra = {k: v for k, v in host.extra.items() if k != KEY}
    if data:
        extra[KEY] = data
    return replace(host, extra=extra)
