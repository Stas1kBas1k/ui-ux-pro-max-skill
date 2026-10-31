"""MiguRod counterattack: press the key shown on screen (Shift by default) when the white line is on
the orange diamond. Real screenshot: tests/fixtures/real/migu_counter.webp."""
from __future__ import annotations



def update(s, obs: Observation, now: float) -> None:
    """Counterattack bar: read which key it asks for (in the background), press it once when the line
    will be on the diamond, then check the bar goes away. If it is still there a second later the press
    was not taken, and one more press is allowed."""
    t = obs.timing
    if not t.present:
        if s.migu_seen_at is not None:
            s._note(now, "migu bar gone" + (" after press" if s.migu_fired else " (not pressed)"))
        s.migu_seen_at, s.migu_fired, s.migu_retries = None, None, 0
        s.pointer_hist.clear()
        return
    if s.migu_seen_at is None:
        s.migu_seen_at = now
        s.prompts.reset()
        s.prompts.request(obs.prompt_image)  # which key? (result arrives a little later)
        s._note(now, "migu timing bar")
    elif obs.prompt_image is not None and s.prompts.result is None and now - s.migu_seen_at < 1.5:
        s.prompts.request(obs.prompt_image)
    s.pointer_hist.append((now, t.pointer))
    if s.migu_fired is not None:
        if now - s.migu_fired < 1.0 or s.migu_retries >= 1:
            return
        s.migu_retries += 1  # still on screen a second after the press: it did not register
        s._note(now, "migu press not taken - one more try")
        s.migu_fired = None
    if len(s.pointer_hist) < 3:
        return
    centre = 0.5
    if t.segments:  # the orange diamond, if found near the middle
        a, b = min(t.segments, key=lambda seg: abs((seg[0] + seg[1]) / 2 - 0.5))
        if abs((a + b) / 2 - 0.5) < 0.15:
            centre = (a + b) / 2
    ahead = s._predict(t.pointer, now, s.latency)
    if abs(ahead - centre) <= s.cfg.migu_window * 0.6:
        p = s.prompts.result
        key = p.key if p is not None else (s.cfg.migu_key or "shift")
        s.migu_fired = now
        s.fsm.input.press_key(key)
        s.actions += 1
        s._note(now, f"migu press {key}{' (read on screen)' if p is not None else ''} at {t.pointer:.3f} "
                     f"(aimed {ahead:.3f})")
