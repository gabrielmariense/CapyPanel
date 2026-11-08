from capypanel.core.hosts.accounts import (
    Link,
    Place,
    Scope,
    credential_name,
    dump,
    load,
    pick,
    users,
    with_link,
)

LIST = r"D:\Lists\clinic.capylist"
OTHER = r"D:\Lists\lab.capylist"
PLACE = Place("desk-02.example.test", LIST, ("front", "floor-1"), ("VPN",))


def test_no_link_is_the_windows_account() -> None:
    assert pick([], PLACE) is None
    assert pick([Link("EXAMPLE\\b", Scope.PC, "desk-09")], PLACE) is None


def test_a_pc_beats_its_group_which_beats_a_tag_which_beats_every_pc() -> None:
    every = Link("EXAMPLE\\all", Scope.ALL)
    tag = Link("EXAMPLE\\tag", Scope.TAG, "vpn", LIST)
    group = Link("EXAMPLE\\group", Scope.GROUP, "floor-1", LIST)
    pc = Link("EXAMPLE\\pc", Scope.PC, "DESK-02.example.test")
    assert pick([every, tag, group, pc], PLACE) == pc
    assert pick([every, tag, group], PLACE) == group
    assert pick([every, tag], PLACE) == tag  # tags match whatever their case
    assert pick([every], PLACE) == every


def test_the_nearest_group_wins() -> None:
    parent = Link("EXAMPLE\\parent", Scope.GROUP, "floor-1", LIST)
    own = Link("EXAMPLE\\own", Scope.GROUP, "front", LIST)
    assert pick([parent, own], PLACE) == own


def test_groups_and_tags_only_count_in_their_own_list() -> None:
    group = Link("EXAMPLE\\g", Scope.GROUP, "front", OTHER)
    tag = Link("EXAMPLE\\t", Scope.TAG, "VPN", OTHER)
    assert pick([group, tag], PLACE) is None
    typed = Place("desk-02.example.test")  # an address typed in the Commands window
    assert pick([Link("EXAMPLE\\g", Scope.GROUP, "front", LIST)], typed) is None
    assert pick([Link("EXAMPLE\\p", Scope.PC, "desk-02.example.test")], typed) is not None


def test_the_same_list_file_matches_whatever_its_spelling() -> None:
    link = Link("EXAMPLE\\g", Scope.GROUP, "front", r"d:\lists\.\CLINIC.capylist")
    assert pick([link], PLACE) == link


def test_a_new_link_replaces_the_one_for_the_same_pcs() -> None:
    old = Link("EXAMPLE\\old", Scope.PC, "DESK-02")
    keep = Link("EXAMPLE\\old", Scope.ALL)
    new = Link("EXAMPLE\\new", Scope.PC, "desk-02")
    assert with_link([old, keep], new) == [keep, new]


def test_each_account_once() -> None:
    links = [Link("EXAMPLE\\a", Scope.ALL), Link("example\\A", Scope.PC, "x"),
             Link("EXAMPLE\\b", Scope.PC, "y")]  # fmt: skip
    assert users(links) == ["EXAMPLE\\a", "EXAMPLE\\b"]
    assert credential_name("EXAMPLE\\Admin") == "account/example\\admin"


def test_settings_round_trip_and_bad_entries_skipped() -> None:
    links = [
        Link("EXAMPLE\\a", Scope.ALL),
        Link("EXAMPLE\\b", Scope.GROUP, "front", LIST, "Clinic / Front desk"),
        Link("EXAMPLE\\c", Scope.PC, "192.0.2.15", name="DESK-02"),
    ]
    assert load(dump(links)) == links
    bad = [
        "nope",
        {"user": "x", "scope": "all", "value": 3},
        {"user": "x", "scope": "planet"},
        {"user": "x", "scope": "pc"},  # which PC?
        {"user": "x", "scope": "tag", "value": "VPN"},  # which list?
        {"user": 3, "scope": "all"},
    ]
    assert load(bad) == []
    assert load(None) == []


def test_a_row_with_no_user_is_the_windows_account() -> None:
    from capypanel.core.hosts.accounts import WINDOWS

    pc = Link(WINDOWS, Scope.PC, "desk-02.example.test")
    group = Link("EXAMPLE\\g", Scope.GROUP, "front", LIST)
    assert pick([group, pc], PLACE) == pc  # kept on Windows' even though its group has another
    assert load(dump([pc])) == [pc]
    assert users([pc, group]) == ["EXAMPLE\\g"]  # no password to keep for it
