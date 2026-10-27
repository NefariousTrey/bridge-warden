"""v6: the AG Studio key from env may hold spaces (real trial keys do: '{11 December 2026}'); control chars refused."""
from bridge_warden import ag_studio as STUDIO

FAKE = "[TRIAL]_this_{X}_key_{AG-0}_will_deactivate_on_{1 January 2030}____[v3]_[0102]_abcDEF=="


def test_key_with_spaces_kept_whole():
    assert STUDIO.license_key({STUDIO.LICENSE_ENV: FAKE}) == FAKE
    assert STUDIO.license_key({STUDIO.LICENSE_ENV: "  " + FAKE + "\n"}) == FAKE


def test_bad_keys_refused():
    for bad in ("", "short", FAKE.replace(" ", "\t"), FAKE + "\nx", FAKE + "\x00"):
        assert STUDIO.license_key({STUDIO.LICENSE_ENV: bad}) == ""
