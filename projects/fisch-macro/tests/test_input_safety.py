import threading

from fischmacro.input.controller import InputController, RecordingBackend


def make():
    b = RecordingBackend()
    return InputController(b, click_hold_ms=0, key_hold_ms=0), b


def test_release_all_releases_buttons_and_keys():
    c, b = make()
    c.mouse_down()
    c.key_down("w")
    c.key_down("shift")
    c.release_all()
    assert c.held() == (set(), set())
    ups = {e for e in b.events if e[0] in ("up", "key_up")}
    assert ("up", "left") in ups and ("key_up", "w") in ups and ("key_up", "shift") in ups


def test_kill_switch_blocks_further_input():
    c, b = make()
    c.mouse_down()
    c.disable()
    assert not c.is_held()
    n = len(b.events)
    assert c.mouse_down() is False
    assert c.click(10, 10) is False
    assert c.press_key("e") is False
    assert len(b.events) == n
    c.enable()
    assert c.mouse_down() is True


def test_duplicate_down_is_not_resent():
    c, b = make()
    c.mouse_down(); c.mouse_down()
    assert [e for e in b.events if e[0] == "down"] == [("down", "left")]


def test_release_continues_after_backend_error():
    class Flaky(RecordingBackend):
        def button(self, down, button="left"):
            if not down:
                raise OSError("boom")
            super().button(down, button)
    b = Flaky()
    c = InputController(b, click_hold_ms=0)
    c.mouse_down()
    c.key_down("w")
    c.release_all()  # must not raise, must still release the key
    assert ("key_up", "w") in b.events
    assert c.held() == (set(), set())


def test_concurrent_release_is_safe():
    c, _ = make()
    c.mouse_down()
    threads = [threading.Thread(target=c.release_all) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not c.is_held()
