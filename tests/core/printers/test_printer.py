import json
from dataclasses import replace
from pathlib import Path

from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.printers.printer import DOC360, SNMP, PrinterInfo, info_of, with_info


def _list_with(info: PrinterInfo) -> HostList:
    printers, host = HostList().add_host("RECEPTION", NO_GROUP, address="192.0.2.10")
    return printers.update_host(with_info(host, info))


def test_details_round_trip_through_the_list_file(tmp_path: Path) -> None:
    info = PrinterInfo(brand="SAMSUNG", model="M4070", serial="SAMPLE1", counter_source=DOC360)
    path = tmp_path / "printers.json"
    listfile.save(path, _list_with(info), expected=None)
    [host] = listfile.load(path).hosts.hosts
    assert info_of(host) == info


def test_the_file_is_a_plain_host_list_with_one_extra_key(tmp_path: Path) -> None:
    # Keys the app doesn't know are kept, so other tools can open, edit and save the list.
    path = tmp_path / "printers.json"
    listfile.save(path, _list_with(PrinterInfo(brand="RICOH", serial="X1")), expected=None)
    [entry] = json.loads(path.read_text(encoding="utf-8"))["hosts"]
    assert entry["address"] == "192.0.2.10"
    assert entry["printer"] == {"brand": "RICOH", "serial": "X1"}  # empty fields and SNMP left out


def test_a_host_without_details_is_an_snmp_printer() -> None:
    [host] = HostList().add_host("PC", NO_GROUP)[0].hosts
    assert info_of(host) == PrinterInfo()
    assert info_of(host).counter_source == SNMP
    assert "printer" not in with_info(host, PrinterInfo()).extra


def test_odd_values_are_kept_as_found() -> None:
    _printers, host = HostList().add_host("P", NO_GROUP)
    odd = {"brand": 7, "counter_source": "papercut", "toner_alert": 15}
    host = replace(host, extra={"printer": odd})
    info = info_of(host)
    assert info.brand == "" and info.counter_source == "papercut" and not info.known_source
    assert with_info(host, info).extra["printer"] == odd  # saved back untouched


def test_a_new_value_replaces_an_odd_one() -> None:
    _printers, host = HostList().add_host("P", NO_GROUP)
    host = with_info(host, PrinterInfo(extra={"brand": 7}))
    info = info_of(host)
    edited = with_info(host, PrinterInfo(brand="BROTHER", extra=info.extra))
    assert edited.extra["printer"]["brand"] == "BROTHER"
