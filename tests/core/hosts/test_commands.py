from capypanel.core.hosts import commands
from capypanel.core.hosts.commands import COMMANDS, GROUP_NAMES, QUICK, Group, Need


def test_every_command_has_its_own_id_and_is_found_by_it() -> None:
    ids = [c.id for c in COMMANDS]
    assert len(set(ids)) == len(ids)
    assert all(commands.command(i).id == i for i in ids)


def test_every_group_is_named_and_has_commands_in_list_order() -> None:
    assert list(GROUP_NAMES) == list(Group)
    order = [list(Group).index(c.group) for c in COMMANDS]
    assert order == sorted(order)  # the list reads group by group, as the menu shows it
    assert all(commands.in_group(group) for group in Group)


def test_the_quick_row_names_existing_commands() -> None:
    assert all(commands.command(i) for i in QUICK)


def test_risky_commands_ask_first() -> None:
    for c in COMMANDS:
        if c.risky:
            assert c.name.endswith("…") and c.need is Need.ASK_WINDOWS, c.id


def test_nothing_runs_a_program_on_the_pc() -> None:
    assert {c.need for c in COMMANDS} <= {Need.READ, Need.OPEN_HERE, Need.ASK_WINDOWS}


def test_quick_commands_are_the_admin_s_pick_in_the_commands_window_s_order() -> None:
    assert commands.quick_from(None) == QUICK  # nothing ever chosen: the starting four
    assert commands.quick_from([]) == ()  # none is a choice too
    kept = ["services", "restart", "c-share", "services", "no-such", 7]
    # Only what can be quick, once, and in one order whatever order it was kept in (a list
    # saved by 0.25, when the order was the admin's, reads the same way).
    assert commands.quick_from(kept) == ("c-share", "services")
    assert commands.quick_from(list(QUICK)) == QUICK  # the starting four are in that order


def test_a_quick_command_never_cuts_a_person_off() -> None:
    assert set(QUICK) <= set(commands.CAN_BE_QUICK)
    for command_id in commands.CAN_BE_QUICK:
        command = commands.command(command_id)  # each one exists
        assert not command.per_person and command.group is not Group.POWER, command_id
    assert "all-checks" not in commands.CAN_BE_QUICK  # it's the fixed Refresh host
