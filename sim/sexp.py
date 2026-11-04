"""Minimal S-expression reader/writer for KiCad files."""
import re


class Q(str):
    """A quoted string token."""


_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def parse(text):
    pos, stack, cur = 0, [], []
    n = len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError("bad token at %d: %r" % (pos, text[pos:pos + 40]))
        pos = m.end()
        if m.group(1):
            stack.append(cur)
            cur = []
        elif m.group(2):
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif m.group(3) is not None:
            s = m.group(3).replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
            cur.append(Q(s))
        else:
            cur.append(m.group(4))
    assert not stack, "unbalanced"
    return cur[0] if len(cur) == 1 else cur


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def dump(node, indent=0):
    """Serialize; short lists on one line, long ones broken."""
    if isinstance(node, Q):
        return q(node)
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return fmtnum(node)
    parts = [dump(x, indent + 1) for x in node]
    one = "(" + " ".join(parts) + ")"
    if len(one) + indent * 2 < 110 and "\n" not in one:
        return one
    head = []
    rest = []
    for i, x in enumerate(node):
        if not rest and not isinstance(x, list):
            head.append(parts[i])
        else:
            rest.append(parts[i])
    pad = "\n" + "  " * (indent + 1)
    return "(" + " ".join(head) + pad + pad.join(rest) + "\n" + "  " * indent + ")"


def fmtnum(v):
    if isinstance(v, int):
        return str(v)
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def find(node, key):
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def findall(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]
