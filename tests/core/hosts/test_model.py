from dataclasses import replace

import pytest

from capypanel.core.hosts.model import HostList, HostListRuleError, clean_tags


def _office() -> tuple[HostList, str, str]:
    hl, hq = HostList().add_group("Headquarters")
    hl, finance = hl.add_group("Finance", parent=hq.id)
    return hl, hq.id, finance.id


def test_add_host_cleans_what_was_typed() -> None:
    hl, _, finance = _office()
    hl, host = hl.add_host(
        "  FIN-PC04 ", finance, address=" 10.0.12.24 ", tags=["floor-3", " ", "floor-3"]
    )
    assert (host.name, host.address, host.tags) == ("FIN-PC04", "10.0.12.24", ("floor-3",))
    assert hl.host(host.id) == host


def test_edits_return_a_new_list_and_keep_the_old_one() -> None:
    before, _, finance = _office()
    after, _ = before.add_host("PC1", finance)
    assert len(before.hosts) == 0 and len(after.hosts) == 1


def test_ids_are_unique_and_prefixed() -> None:
    hl, _, finance = _office()
    ids = set()
    for n in range(50):
        hl, host = hl.add_host(f"PC{n}", finance)
        ids.add(host.id)
    assert len(ids) == 50 and all(i.startswith("h") for i in ids)


def test_host_needs_an_existing_group_and_a_name() -> None:
    hl, _, finance = _office()
    with pytest.raises(HostListRuleError):
        hl.add_host("PC1", "g-missing")
    with pytest.raises(HostListRuleError):
        hl.add_host("   ", finance)


def test_target_falls_back_to_the_name() -> None:
    hl, _, finance = _office()
    hl, by_name = hl.add_host("PC1", finance)
    hl, by_ip = hl.add_host("PC2", finance, address="10.0.0.2")
    assert by_name.target == "PC1" and by_ip.target == "10.0.0.2"


def test_nested_groups_count_their_subgroups_hosts() -> None:
    hl, hq, finance = _office()
    hl, _ = hl.add_host("HQ-1", hq)
    hl, _ = hl.add_host("FIN-1", finance)
    assert {h.name for h in hl.hosts_in(hq)} == {"HQ-1", "FIN-1"}
    assert {h.name for h in hl.hosts_in(hq, nested=False)} == {"HQ-1"}


def test_removing_a_group_removes_its_subgroups_and_hosts() -> None:
    hl, hq, finance = _office()
    hl, other = hl.add_group("Branch")
    hl, _ = hl.add_host("FIN-1", finance)
    hl, keep = hl.add_host("BR-1", other.id)
    hl = hl.remove_group(hq)
    assert [g.id for g in hl.groups] == [other.id]
    assert [h.id for h in hl.hosts] == [keep.id]


def test_update_host_moves_it_and_keeps_its_id() -> None:
    hl, hq, finance = _office()
    hl, host = hl.add_host("PC1", finance)
    hl = hl.update_host(replace(host, group=hq, name=" PC-01 "))
    moved = hl.host(host.id)
    assert moved is not None and (moved.group, moved.name) == (hq, "PC-01")


def test_tag_counts() -> None:
    hl, _, finance = _office()
    hl, _ = hl.add_host("A", finance, tags=["kiosk", "floor-3"])
    hl, _ = hl.add_host("B", finance, tags=["kiosk"])
    assert hl.all_tags() == {"kiosk": 2, "floor-3": 1}


def test_clean_tags_keeps_typed_order() -> None:
    assert clean_tags(["b", "a", " b ", ""]) == ("b", "a")


def test_a_host_follows_the_nearest_group_with_a_profile() -> None:
    hl, hq, finance = _office()
    hl, pc = hl.add_host("PC1", finance)
    assert hl.profile_of(pc) == ("", None)  # nothing set anywhere: the app's default
    hl = hl.set_group_profile(hq, "ultravnc-account")
    profile, source = hl.profile_of(pc)
    assert profile == "ultravnc-account" and source is not None and source.id == hq
    hl = hl.set_group_profile(finance, "realvnc-account")
    assert hl.profile_of(pc)[0] == "realvnc-account"  # the nearer group wins
    hl = hl.set_hosts_profile([pc.id], "ultravnc-password")
    pc = hl.host(pc.id)
    assert pc is not None and hl.profile_of(pc) == ("ultravnc-password", None)
    hl = hl.set_hosts_profile([pc.id], "")  # back to following its group
    assert hl.profile_of(hl.host(pc.id) or pc)[0] == "realvnc-account"


def test_a_name_stands_in_for_the_address_only_when_it_is_a_computer_name() -> None:
    hl, _, finance = _office()
    hl, by_name = hl.add_host("FIN-PC04", finance)
    hl, label = hl.add_host("Ward 2A - Desk", finance)
    hl, with_ip = hl.add_host("Ward 2A - Desk", finance, address="10.0.0.9")
    assert by_name.connect_address == "FIN-PC04"
    assert label.connect_address == ""
    assert with_ip.connect_address == "10.0.0.9"
