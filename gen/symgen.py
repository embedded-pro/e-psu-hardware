"""Generate the project symbol library (rectangular IC symbols from pin lists)."""
from sexp import Q, dump

PIN_LEN = 2.54
PITCH = 2.54


def _pin(num, name, ptype, x, y, ang, hide=False):
    """hide=True: stacked duplicate (KLC S4.3: invisible, passive, so no implicit power net)."""
    p = ["pin", "passive" if hide else ptype, "line", ["at", x, y, ang], ["length", PIN_LEN]]
    if hide:
        p.append("hide")
    return p + [["name", Q(name), ["effects", ["font", ["size", 1.27, 1.27]]]],
                ["number", Q(str(num)), ["effects", ["font", ["size", 1.27, 1.27]]]]]


def ic_symbol(name, ref, left=(), right=(), top=(), bottom=(), width=None, value=None, fp="", ds="", desc="",
              keywords=""):
    """Each side is a list of (number(s), name, type) or None for a gap.
    number(s) may be a list -> stacked pins at the same spot."""
    lname = max([len(p[1]) for p in left if p] + [0])
    rname = max([len(p[1]) for p in right if p] + [0])
    w = width or (lname + rname) * 1.27 + 7.62
    n_lr = max(len(left), len(right), 1)
    tb_names = max([len(p[1]) for side in (top, bottom) for p in side if p] + [0])
    top_rows = (int(tb_names * 1.27 / PITCH) + 1) if top else 0
    bot_rows = (int(tb_names * 1.27 / PITCH) + 1) if bottom else 0
    h = (n_lr + 1 + top_rows + bot_rows) * PITCH
    n_tb = max(len(top), len(bottom), 0)
    w = max(w, (n_tb + 1) * PITCH * 2)
    w = round(w / 5.08 + 0.49) * 5.08
    x0, x1 = -w / 2, w / 2
    y0 = round((h / 2) / 2.54) * 2.54
    y1 = y0 - h
    pins = []

    def nums(n):
        return n if isinstance(n, (list, tuple)) else [n]

    for i, p in enumerate(left):
        if p:
            for k, n in enumerate(nums(p[0])):
                pins.append(_pin(n, p[1], p[2], round(x0 - PIN_LEN, 3), round(y0 - (i + 1 + top_rows) * PITCH, 3), 0, hide=k > 0))
    for i, p in enumerate(right):
        if p:
            for k, n in enumerate(nums(p[0])):
                pins.append(_pin(n, p[1], p[2], round(x1 + PIN_LEN, 3), round(y0 - (i + 1 + top_rows) * PITCH, 3), 180, hide=k > 0))
    for i, p in enumerate(top):
        if p:
            xs = x0 + (i + 1) * (w / (len(top) + 1))
            xs = round(round(xs / 2.54) * 2.54, 3)
            for k, n in enumerate(nums(p[0])):
                pins.append(_pin(n, p[1], p[2], xs, round(y0 + PIN_LEN, 3), 270, hide=k > 0))
    for i, p in enumerate(bottom):
        if p:
            xs = x0 + (i + 1) * (w / (len(bottom) + 1))
            xs = round(round(xs / 2.54) * 2.54, 3)
            for k, n in enumerate(nums(p[0])):
                pins.append(_pin(n, p[1], p[2], xs, round(y1 - PIN_LEN, 3), 90, hide=k > 0))
    eff = ["effects", ["font", ["size", 1.27, 1.27]]]
    effl = ["effects", ["font", ["size", 1.27, 1.27]], ["justify", "left"]]
    hid = ["effects", ["font", ["size", 1.27, 1.27]], "hide"]
    sym = ["symbol", Q(name), ["in_bom", "yes"], ["on_board", "yes"],
           ["property", Q("Reference"), Q(ref), ["at", round(x0, 3), round(y0 + 1.27, 3), 0], effl],
           ["property", Q("Value"), Q(value or name), ["at", round(x0, 3), round(y1 - 1.27, 3), 0], effl],
           ["property", Q("Footprint"), Q(fp), ["at", 0, 0, 0], hid],
           ["property", Q("Datasheet"), Q(ds), ["at", 0, 0, 0], hid],
           ["property", Q("ki_description"), Q(desc), ["at", 0, 0, 0], hid],
           ["property", Q("ki_keywords"), Q(keywords), ["at", 0, 0, 0], hid],
           ["symbol", Q(name + "_0_1"),
            ["rectangle", ["start", round(x0, 3), round(y0, 3)], ["end", round(x1, 3), round(y1, 3)],
             ["stroke", ["width", 0.254], ["type", "default"]], ["fill", ["type", "background"]]]],
           ["symbol", Q(name + "_1_1")] + pins]
    return sym


def two_pin_symbol(name, ref, n1, n2, t="passive"):
    """Simple vertical box with pins 1 (top) and 2 (bottom)."""
    return ic_symbol(name, ref, top=[(n1[0], n1[1], t)], bottom=[(n2[0], n2[1], t)], width=5.08)


def write_lib(path, symbols):
    lib = ["kicad_symbol_lib", ["version", "20220914"], ["generator", "kicad_symbol_editor"]] + symbols
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump(lib) + "\n")
