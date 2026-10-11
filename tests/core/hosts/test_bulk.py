from capypanel.core.hosts.bulk import (
    ImportRow,
    Verdict,
    export,
    list_separator,
    parse,
    plan,
    to_csv,
)
from capypanel.core.hosts.model import NO_GROUP, HostList


def _office() -> tuple[HostList, str]:
    hl, branch = HostList().add_group("Branch office")
    hl, hq = hl.add_group("Headquarters")
    hl, _ = hl.add_group("Front desk", parent=hq.id)
    hl, _ = hl.add_host("HQ-01", hq.id, address="10.0.0.1")
    return hl, branch.id


def test_a_csv_with_headers_in_any_order_and_language() -> None:
    parsed = parse(
        "Endereço;Nome;Grupo;Tags;Sala\n"  # Excel's CSV in pt-BR: semicolons
        "PC-0142.corp.example.net;Reception 01;Headquarters/Front desk;kiosk, 2nd floor;12\n"
    )
    assert parsed.rows == (
        ImportRow(
            "Reception 01", "PC-0142.corp.example.net", "Headquarters/Front desk",
            ("kiosk", "2nd floor"),
        ),
    )  # fmt: skip
    assert parsed.ignored == ("Sala",)  # said, not silently dropped


def test_lines_without_a_header_are_name_and_address() -> None:
    pasted = "Lab 07\t10.20.30.47\n\nLab 08,10.20.30.48\nLAB-09\n"  # Excel copies with tabs
    rows = parse(pasted).rows
    assert [(r.name, r.address) for r in rows] == [
        ("Lab 07", "10.20.30.47"), ("Lab 08,10.20.30.48", ""), ("LAB-09", ""),
    ]  # fmt: skip
    # One delimiter per list, from its first line: here a tab, so the comma line stays whole.
    assert parse("Lab 08,10.20.30.48").rows[0].address == "10.20.30.48"


def test_quoted_cells_keep_their_delimiters() -> None:
    rows = parse('name,address,tags\n"Lab, 2nd floor",10.0.0.9,"a;b"\n').rows
    assert rows[0].name == "Lab, 2nd floor" and rows[0].tags == ("a", "b")


def test_the_plan_adds_skips_and_flags_without_changing_the_list() -> None:
    hl, branch = _office()
    rows = [
        ImportRow("Reception 01", "PC-0142", "Headquarters/Front desk", ("kiosk",)),
        ImportRow("Finance 01", "PC-0201", "Headquarters/Finance"),
        ImportRow("Finance 01", "PC-0201", "Headquarters/Finance"),  # twice in the paste
        ImportRow("Old HQ", "10.0.0.1"),  # another name, but HQ-01's address
        ImportRow("hq-01"),  # HQ-01, in other case
        ImportRow("", "10.20.30.48"),
        ImportRow("Lab 07", "not an address!"),
        ImportRow("Lab 08"),  # no address, and spaces: it can't be connected to by name
        ImportRow("LAB-09"),
    ]
    p = plan(hl, rows, branch)
    assert [i.verdict for i in p.items] == [
        Verdict.ADD, Verdict.ADD, Verdict.SKIP, Verdict.SKIP, Verdict.SKIP,
        Verdict.BAD, Verdict.BAD, Verdict.BAD, Verdict.ADD,
    ]  # fmt: skip
    # A skipped row says which host or row it repeats, so the right one can be kept.
    assert p.items[2].reason == "Same as row 2"
    assert p.items[3].reason == "“HQ-01” has this address, in “Headquarters”"
    assert p.items[4].reason == "A host with this name is already in the list, in “Headquarters”"
    assert p.items[5].reason == "No name"
    assert p.adding == 3
    assert p.new_groups == (("Headquarters", "Finance"),)  # Front desk was there already
    assert p.items[8].group == ("Branch office",)  # no group: the one picked
    assert len(hl.hosts) == 1  # planning changes nothing
    assert {h.name for h in p.result.hosts} == {"HQ-01", "Reception 01", "Finance 01", "LAB-09"}


def test_rows_without_a_group_can_be_left_with_none() -> None:
    hl, _branch = _office()
    p = plan(hl, [ImportRow("PC-1")], NO_GROUP)
    assert p.items[0].group == () and p.result.hosts[-1].group == NO_GROUP
    assert p.new_groups == ()


def test_group_names_match_without_regard_to_case() -> None:
    hl, branch = _office()
    p = plan(hl, [ImportRow("FD-01", "", "headquarters/FRONT DESK")], branch)
    assert p.new_groups == () and p.items[0].group == ("Headquarters", "Front desk")


def test_an_export_imports_back_into_the_same_groups() -> None:
    hl, branch = _office()
    slash = next(g.id for g in hl.groups if g.name == "Front desk")
    hl = hl.rename_group(slash, "Front desk / lobby")  # a "/" in a group's own name
    hl, _ = hl.add_host("FD-01", slash, address="10.0.0.2", tags=["kiosk", "2nd floor"])
    text = export(hl, hl.hosts)
    assert text.splitlines()[0] == "name,address,group,tags,notes"
    assert "FD-01,10.0.0.2,Headquarters/Front desk / lobby,kiosk;2nd floor," in text
    # Into the list it came from, emptied: every host lands back in its own group.
    emptied = hl.remove_hosts(h.id for h in hl.hosts)
    back = plan(emptied, parse(text).rows, branch)
    assert back.adding == 2 and back.new_groups == ()
    fd01 = next(h for h in back.result.hosts if h.name == "FD-01")
    assert fd01.group == slash and fd01.tags == ("kiosk", "2nd floor")


def test_table_edits_are_written_back_as_csv() -> None:
    rows = [ImportRow("Lab 07", "10.20.30.47", "Branch office", ("a", "b"), "USB printer")]
    assert to_csv(rows) == (
        "name,address,group,tags,notes\nLab 07,10.20.30.47,Branch office,a;b,USB printer\n"
    )
    assert parse(to_csv(rows)).rows == tuple(rows)


def test_a_list_that_cant_be_read_says_why_instead_of_guessing() -> None:
    assert parse("PC-1,10.0.0.1,Lab,kiosk").needs_header  # 4 columns, no header: what are they?
    assert parse("PC-1,10.0.0.1", file=True).needs_header  # a CSV file needs its header row
    assert not parse("PC-1,10.0.0.1").needs_header  # pasted name and address: fine
    assert parse("PC-1,10.0.0.1,Lab").rows == ()


def test_notes_come_in_from_a_notes_column() -> None:
    rows = parse("Nome,Observações\nPC-1,USB printer\n").rows
    assert rows[0].notes == "USB printer"
    hl, branch = _office()
    added = plan(hl, rows, branch).result.hosts[-1]
    assert added.name == "PC-1" and added.notes == "USB printer"


def test_an_export_split_by_semicolons_imports_back_too() -> None:
    # Excel in Portuguese (and other languages) splits columns on ";": tags then use ",".
    rows = [ImportRow("Lab 07", "10.20.30.47", "Branch office", ("a", "b"), "USB; printer")]
    text = to_csv(rows, ";")
    assert text.splitlines()[1] == 'Lab 07;10.20.30.47;Branch office;a,b;"USB; printer"'
    assert parse(text).rows == tuple(rows)


def test_the_list_separator_is_one_excel_splits_on() -> None:
    assert list_separator() in (",", ";", "\t")
