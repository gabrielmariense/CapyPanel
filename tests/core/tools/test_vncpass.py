from capypanel.core.tools import vncpass


def test_des_matches_the_textbook_example() -> None:
    key, plain = bytes.fromhex("133457799BBCDFF1"), bytes.fromhex("0123456789ABCDEF")
    assert vncpass.des_ecb(key, plain).hex() == "85e813540f0ab405"


def test_the_well_known_scrambled_form_of_password() -> None:
    # What VNC servers and viewers store for "password" (e.g. TightVNC's registry value).
    assert vncpass.obfuscate("password").hex() == "dbd83cfd727a1458"


def test_short_passwords_fill_one_block_and_long_ones_more() -> None:
    assert len(vncpass.obfuscate("pi")) == 8
    assert len(vncpass.obfuscate("12345678")) == 8
    assert len(vncpass.obfuscate("123456789")) == 16
    assert vncpass.obfuscate("123456789")[:8] == vncpass.obfuscate("12345678")
