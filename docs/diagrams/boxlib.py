"""Tiny text-canvas helpers for box diagrams (shared by gen_diagrams.py and gen_dashboard_v3.py)."""

class C:
    def __init__(s, w, h):
        s.w, s.h = w, h
        s.g = [[' '] * w for _ in range(h)]

    def put(s, x, y, t):
        for i, ch in enumerate(t):
            assert 0 <= x + i < s.w and 0 <= y < s.h, (x, y, t)
            s.g[y][x + i] = ch

    def hl(s, x1, x2, y, ch='─'):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            s.g[y][x] = ch

    def vl(s, x, y1, y2, ch='│'):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            s.g[y][x] = ch

    def box(s, x, y, w, lines, h=None, align='c', style='single', header=0):
        sep = 1 if header else 0
        h = h or len(lines) + 2 + sep
        tl, tr, bl, br, hz, vt = {
            'single': '┌┐└┘─│', 'double': '╔╗╚╝═║', 'dashed': '┌┐└┘╌╎'}[style]
        s.put(x, y, tl + hz * (w - 2) + tr)
        s.put(x, y + h - 1, bl + hz * (w - 2) + br)
        for yy in range(y + 1, y + h - 1):
            s.put(x, yy, vt + ' ' * (w - 2) + vt)
        row = y + 1
        for i, l in enumerate(lines):
            if header and i == header:
                s.put(x, row, '├' + '─' * (w - 2) + '┤')
                row += 1
            assert len(l) <= w - 4, (l, w)
            if align == 'c' or (header and i < header):
                t = l.center(w - 2)
            else:
                t = ' ' + l.ljust(w - 3)
            s.put(x + 1, row, t)
            row += 1
        return h

    def out(s):
        return '\n'.join(''.join(r).rstrip() for r in s.g).rstrip('\n')


def seq(parts, w, msgs, start=4, gap=3, H=None):
    n = len(parts)
    centers = [p[1] for p in parts]
    H = H or start + gap * len(msgs) + 1
    W = max(centers) + w // 2 + 2
    c = C(W, H)
    for name, cx in parts:
        c.box(cx - w // 2, 0, w, [name])
    for cx in centers:
        c.vl(cx, 3, H - 1)
        c.put(cx, 2, '┬')
    y = start
    for m in msgs:
        if m[0] == 'self':
            cx = centers[m[1]]
            c.put(cx, y, '├──┐'); c.put(cx + 3, y + 1, '│ ' + m[2]); c.put(cx, y + 2, '│◄─┘')
            y += gap + 1
            continue
        a, b, label = centers[m[0]], centers[m[1]], m[2]
        dashed = len(m) > 3 and m[3]
        ch = '╌' if dashed else '─'
        lo, hi = min(a, b), max(a, b)
        assert len(label) <= hi - lo - 3, label
        c.put(lo + 2, y, label)
        c.hl(lo + 1, hi - 1, y + 1, ch)
        if b > a:
            c.put(hi - 1, y + 1, '►')
        else:
            c.put(lo + 1, y + 1, '◄')
        y += gap
    return c.out()
