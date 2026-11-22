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
        "Endereço;Nome;Grupo;Tags;Sala\n"
        "PC-0142.corp.example.net;Reception 01;Headquarters/Front desk;kiosk, 2nd floor;12\n"
    )
    assert parsed.rows == (
        ImportRow(
            "Reception 01", "PC-0142.corp.example.net", "Headquarters/Front desk",
            ("kiosk", "2nd floor"),
        ),
    )  # fmt: skip
    assert parsed.ignored == ("Sala",)


def test_lines_without_a_header_are_name_and_address() -> None:
    pasted = "Lab 07\t10.20.30.47\n\nLab 08,10.20.30.48\nLAB-09\n"  # Excel copies with tabs
    rows = parse(pasted).rows
    assert [(r.name, r.address) for r in rows] == [
        ("Lab 07", "10.20.30.47"), ("Lab 08,10.20.30.48", ""), ("LAB-09", ""),
    ]  # fmt: skip
    assert parse("Lab 08,10.20.30.48").rows[0].address == "10.20.30.48"


def test_headers_match_however_the_words_are_joined() -> None:
    parsed = parse("Hostname\tIP_Address\tGroupName\nLab 07\t192.0.2.47\tWard A\n")
    assert parsed.rows == (ImportRow("Lab 07", "192.0.2.47", "Ward A"),)
    assert parse("Nome;Nome do grupo\nLab 07;Ala B\n").rows[0].group == "Ala B"


def test_a_table_lined_up_with_spaces_imports_by_its_columns() -> None:
    pasted = (
        "Hostname        Address         Group Name\n"
        "Lab 07          192.0.2.47      Ward A / 2nd floor\n"
        "LAB-08                          Ward B\n"
        "Reception-workstation-01  192.0.2.49  Ward C\n"
    )
    parsed = parse(pasted)
    assert [(r.name, r.address, r.group) for r in parsed.rows] == [
        ("Lab 07", "192.0.2.47", "Ward A / 2nd floor"),
        ("LAB-08", "", "Ward B"),
        ("Reception-workstation-01", "192.0.2.49", "Ward C"),
    ]
    assert parse("Lab 07    192.0.2.47\n").rows[0].name == "Lab 07    192.0.2.47"


def test_quoted_cells_keep_their_delimiters() -> None:
    rows = parse('name,address,tags\n"Lab, 2nd floor",10.0.0.9,"a;b"\n').rows
    assert rows[0].name == "Lab, 2nd floor" and rows[0].tags == ("a", "b")


def test_the_plan_adds_skips_and_flags_without_changing_the_list() -> None:
    hl, branch = _office()
    rows = [
        ImportRow("Reception 01", "PC-0142", "Headquarters/Front desk", ("kiosk",)),
        ImportRow("Finance 01", "PC-0201", "Headquarters/Finance"),
        ImportRow("Finance 01", "PC-0201", "Headquarters/Finance"),
        ImportRow("Old HQ", "10.0.0.1"),
        ImportRow("hq-01"),
        ImportRow("", "10.20.30.48"),
        ImportRow("Lab 07", "not an address!"),
        ImportRow("Lab 08"),
        ImportRow("LAB-09"),
    ]
    p = plan(hl, rows, branch)
    assert [i.verdict for i in p.items] == [
        Verdict.ADD, Verdict.ADD, Verdict.SKIP, Verdict.SKIP, Verdict.SKIP,
        Verdict.BAD, Verdict.BAD, Verdict.BAD, Verdict.ADD,
    ]  # fmt: skip
    assert p.items[2].reason == "Same as row 2"
    assert p.items[3].reason == "“HQ-01” has this address, in “Headquarters”"
    assert p.items[4].reason == "A host with this name is already in the list, in “Headquarters”"
    assert p.items[5].reason == "No name"
    assert p.adding == 3
    assert p.new_groups == (("Headquarters", "Finance"),)
    assert p.items[8].group == ("Branch office",)
    assert len(hl.hosts) == 1
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
    hl = hl.rename_group(slash, "Front desk / lobby")
    hl, _ = hl.add_host("FD-01", slash, address="10.0.0.2", tags=["kiosk", "2nd floor"])
    text = export(hl, hl.hosts)
    assert text.splitlines()[0] == "name,address,group,tags,notes"
    assert "FD-01,10.0.0.2,Headquarters/Front desk / lobby,kiosk;2nd floor," in text
    emptied = hl.remove_hosts(h.id for h in hl.hosts)
    back = plan(emptied, parse(text).rows, branch)
    assert back.adding == 2 and back.new_groups == ()
    fd01 = next(h for h in back.result.hosts if h.name == "FD-01")
    assert fd01.group == slash and fd01.tags == ("kiosk", "2nd floor")


def test_a_report_never_hands_a_spreadsheet_a_formula() -> None:
    hl, branch = _office()
    link = '=HYPERLINK("http://198.51.100.9")'
    hl, _ = hl.add_host(link, branch, address="192.0.2.5", notes="-2 floors")
    hl, _ = hl.add_host("@SUM", branch, address="192.0.2.6", tags=["+kiosk"])
    text = export(hl, hl.hosts)
    assert "'=HYPERLINK" in text and "'-2 floors" in text and "'@SUM" in text
    assert "'+kiosk" in text and "HQ-01,10.0.0.1," in text
    emptied = hl.remove_hosts(h.id for h in hl.hosts)
    back = plan(emptied, parse(text).rows, branch).result.hosts
    assert {(h.name, h.notes, h.tags) for h in back} >= {
        ('=HYPERLINK("http://198.51.100.9")', "-2 floors", ()),
        ("@SUM", "", ("+kiosk",)),
    }


def test_table_edits_are_written_back_as_csv() -> None:
    rows = [ImportRow("Lab 07", "10.20.30.47", "Branch office", ("a", "b"), "USB printer")]
    assert to_csv(rows) == (
        "name,address,group,tags,notes\nLab 07,10.20.30.47,Branch office,a;b,USB printer\n"
    )
    assert parse(to_csv(rows)).rows == tuple(rows)


def test_a_list_that_cant_be_read_says_why_instead_of_guessing() -> None:
    assert parse("PC-1,10.0.0.1,Lab,kiosk").needs_header
    assert parse("PC-1,10.0.0.1", file=True).needs_header
    assert not parse("PC-1,10.0.0.1").needs_header
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


MORE = {"brand": {"brand", "marca"}, "asset_tag": {"asset tag", "patrimônio"}}


def test_a_callers_own_columns_come_in_and_are_not_ignored() -> None:
    text = "Name;Marca;Patrimônio;Sala\nLab;RICOH;PAT-1;12\nDesk;;PAT-2;\n"
    parsed = parse(text, more=MORE)
    assert [r.more for r in parsed.rows] == [
        (("brand", "RICOH"), ("asset_tag", "PAT-1")),
        (("asset_tag", "PAT-2"),),
    ]
    assert parsed.ignored == ("Sala",)
    plain = parse(text)
    assert all(r.more == () for r in plain.rows)
    assert plain.ignored == ("Marca", "Patrimônio", "Sala")


def test_a_callers_own_columns_in_a_table_lined_up_with_spaces() -> None:
    text = "Name    Brand    Asset tag\nLab     RICOH    PAT-1\n"
    [row] = parse(text, more=MORE).rows
    assert (row.name, row.more) == ("Lab", (("brand", "RICOH"), ("asset_tag", "PAT-1")))


def test_a_callers_own_columns_read_back_from_the_tables_csv() -> None:
    rows = (ImportRow("Lab", "192.0.2.11", more=(("brand", "RICOH"), ("asset_tag", "PAT-1"))),)
    text = to_csv(rows, more=list(MORE))
    assert text.splitlines()[0] == "name,address,group,tags,notes,brand,asset_tag"
    assert parse(text, more=MORE).rows == rows


def test_a_callers_own_check_takes_the_place_of_the_hosts_one() -> None:
    rows = (
        ImportRow("Web", "https://192.0.2.10"),
        ImportRow("USB-01"),
        ImportRow("Lab 07"),
    )

    def check(row: ImportRow) -> str | None:
        return {"Web": "", "USB-01": "Its port is USB001"}.get(row.name)

    items = plan(HostList(), rows, NO_GROUP, problem=check).items
    assert [(i.verdict, i.reason) for i in items] == [
        (Verdict.ADD, ""),
        (Verdict.BAD, "Its port is USB001"),
        (Verdict.BAD, "No address: the name must then be the computer's name on the network"),
    ]
    assert plan(HostList(), rows, NO_GROUP).items[0].verdict is Verdict.BAD
