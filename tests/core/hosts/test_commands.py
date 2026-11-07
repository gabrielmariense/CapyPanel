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
    # Your scripts come from the scripts folder, not this list.
    assert all(commands.in_group(group) for group in Group if group is not Group.OWN)
    assert not commands.in_group(Group.OWN)


def test_the_quick_row_names_existing_commands() -> None:
    assert all(commands.command(i) for i in QUICK)


def test_risky_commands_ask_first() -> None:
    for c in COMMANDS:
        if c.risky:
            assert c.name.endswith("…") and c.need in (Need.ASK_WINDOWS, Need.RUN), c.id


def test_only_scripts_run_a_program_on_the_pc() -> None:
    running = {c.id for c in COMMANDS if c.need is Need.RUN}
    assert running == {c.id for c in commands.in_group(Group.SCRIPTS)}
