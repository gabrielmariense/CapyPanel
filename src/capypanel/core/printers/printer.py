"""A printer's own details: brand, model, serial, asset tag and where its page counters come from.

They live in the host entry under one key, "printer", so a printer list is a normal host
list. Odd values are read as empty and the original is kept as typed, so opening and saving a
list never loses anything."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from capypanel.core.hosts.model import Host

KEY = "printer"

# Where a printer's page counters are read from. A source this version doesn't know is kept
# as written and shown as unknown.
SNMP = "snmp"  # asked straight from the printer on the network
DOC360 = "doc360"  # Doc360 MPS, the managed-print portal: reaches printers on other networks
COUNTER_SOURCES = (SNMP, DOC360)

_FIELDS = ("brand", "model", "serial", "asset_tag", "counter_source")


@dataclass(frozen=True)
class PrinterInfo:
    brand: str = ""
    model: str = ""
    serial: str = ""
    asset_tag: str = ""  # the organization's own inventory number
    counter_source: str = SNMP
    extra: Mapping[str, Any] = field(default_factory=dict)  # keys this version doesn't know

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
    """The host with these details. Empty fields aren't written, so entries stay short."""
    data: dict[str, Any] = dict(info.extra)  # an odd value kept as found, unless replaced now
    for name in _FIELDS:
        value = getattr(info, name)
        if value and not (name == "counter_source" and value == SNMP):
            data[name] = value
    extra = {k: v for k, v in host.extra.items() if k != KEY}
    if data:
        extra[KEY] = data
    return replace(host, extra=extra)
