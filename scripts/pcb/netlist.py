"""Parse a KiCad (kicadsexpr) netlist."""
from sexp import parse, find, findall


def load(path):
    t = parse(open(path, encoding="utf-8").read())
    comps = {}
    for c in findall(find(t, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        fields = {}
        fs = find(c, "fields")
        if fs:
            for f in findall(fs, "field"):
                nm = str(find(f, "name")[1])
                fields[nm] = str(f[2]) if len(f) > 2 else ""
        props = {str(find(p, "name")[1]): (str(find(p, "value")[1]) if find(p, "value") else "")
                 for p in findall(c, "property")}
        sp = find(c, "sheetpath")
        comps[ref] = dict(ref=ref, value=str(find(c, "value")[1]), footprint=str(find(c, "footprint")[1]),
                          fields=fields, props=props, sheet=str(find(sp, "names")[1]),
                          sheet_ts=str(find(sp, "tstamps")[1]), ts=str(find(c, "tstamps")[1]),
                          dnp="dnp" in props)
    nets = {}
    for n in findall(find(t, "nets"), "net"):
        name = str(find(n, "name")[1])
        nets[name] = [(str(find(x, "ref")[1]), str(find(x, "pin")[1])) for x in findall(n, "node")]
    return comps, nets
