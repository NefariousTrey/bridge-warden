# Made by @Nefarious_Trey, with Grok.  Copyright 2026 Douglas Gibbons III.  Apache-2.0.
"""Oct 27 2026 audit fix: the hosted /login page used to keep the local footer "Runs only on this computer."
(false on Render). Every hosted HTML page, /login included, now says the hosted wording. Fake keys only."""
import threading

import pytest

from bridge_warden import hosted as Ho
from bridge_warden import web
import test_v5_render_hosted as HT
import test_v6_site_lock as SL


def _serve(env):
    s, app = Ho.serve_hosted(0, env=env, bind="127.0.0.1", sender=lambda *a, **k: (201, {}, b"{}"))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


@pytest.mark.parametrize("locked", [False, True])
def test_hosted_login_footer_says_render_not_this_computer(tmp_path, locked):
    more = {"BW_SITE_LOCK_PASSWORD": SL.PW} if locked else {}
    s = _serve(HT.env_for(tmp_path, **more))
    try:
        st, _, body = HT.req(s, "GET", "/login", headers=SL.basic() if locked else None)
        assert st == 200 and "<h1>Log in</h1>" in body
        assert Ho.LOCAL_FOOTER not in body
        assert Ho.HOSTED_FOOTER in body
    finally:
        s.shutdown()
        s.server_close()


def test_local_footer_text_still_matches_web_page():
    """If web.page() ever changes its footer, the hosted swap must change with it (or it would silently miss)."""
    out = web.page("x", "<p>x</p>", "", None)
    assert Ho.LOCAL_FOOTER in out


def test_hosted_footer_uses_the_same_words_as_the_judge_guide_footer():
    """hosted.py's footer and web.py's hosted Judge Guide footer say the same thing (Oct 27 regrade)."""
    import inspect
    assert Ho.HOSTED_FOOTER == "Runs on its own Render service."
    assert '"' + Ho.HOSTED_FOOTER + '"' in inspect.getsource(web)
