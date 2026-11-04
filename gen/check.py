"""Run ERC, export netlist and compare to the generator's intended connectivity."""
import json
import subprocess
import sys
import os
from sexp import parse, find, findall


def netlist_nodes(netfile):
    t = parse(open(netfile, encoding="utf-8").read())
    nets = {}
    for n in findall(find(t, "nets"), "net"):
        name = str(find(n, "name")[1])
        nodes = {(str(find(x, "ref")[1]), str(find(x, "pin")[1])) for x in findall(n, "node")}
        nets[name] = nodes
    return nets


def compare(expected, nets, verbose=True):
    # map each node to its kicad net
    node2net = {}
    for name, nodes in nets.items():
        for nd in nodes:
            node2net[nd] = name
    problems = []
    for exp_name, exp_nodes in sorted(expected.items()):
        got = {node2net.get(nd) for nd in exp_nodes}
        if None in got:
            missing = [nd for nd in exp_nodes if nd not in node2net]
            problems.append(f"{exp_name}: nodes missing from netlist {missing}")
            got.discard(None)
        if len(got) > 1:
            split = {g: sorted(nd for nd in exp_nodes if node2net.get(nd) == g) for g in got}
            problems.append(f"{exp_name}: split across {split}")
        for g in got:
            extra = nets[g] - exp_nodes
            extra = {e for e in extra if not e[0].startswith("#")}
            if extra:
                problems.append(f"{exp_name}: kicad net {g} has unexpected nodes {sorted(extra)}")
    return problems


if __name__ == "__main__":
    root, expfile = sys.argv[1], sys.argv[2]
    d = os.path.dirname(root)
    net = os.path.join(d, "check.net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, root], check=True,
                   capture_output=True)
    expected = {k: set(map(tuple, v)) for k, v in json.load(open(expfile)).items()}
    probs = compare(expected, netlist_nodes(net))
    print("\n".join(probs) if probs else "netlist matches intent")
