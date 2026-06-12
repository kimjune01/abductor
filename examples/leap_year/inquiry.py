"""Drive the leap-year repair as a hypothesis-graph inquiry.

This is what a debugging agent's loop looks like with the graph as its working
memory and the gate as its handed oracle:

    observe -> abduce a fix -> probe it against the gate ->
    the disagreement kills it and names the next fix -> repeat -> witness the rule

Run:  uv run python inquiry.py   (from this directory)
"""

from __future__ import annotations

from abductor.hygraph import HypothesisGraph
from property import Gate, no_centuries, patch_1900, the_rule


def main() -> None:
    gate = Gate(lo=1, hi=2400)
    g = HypothesisGraph(observation="find_dotenv-style bug report: year 1900 reported leap, but it is not")

    # An agent climbs from the narrow patch to the rule. Each kill hands it the
    # counterexamples; the next hypothesis answers the manner of death.
    node, ce = g.probe("special-case 1900", patch_1900, gate)
    print(f"#{node.id} {node.status.value}: {node.outcome}")

    if ce:  # the kill names the successor: still mishandling other centuries
        node, ce = g.probe(
            "centuries are never leap", no_centuries, gate, parent=node
        )
        print(f"#{node.id} {node.status.value}: {node.outcome}")

    if ce:  # killed again: now over-rejecting years divisible by 400
        node, ce = g.probe(
            "div by 4, skip centuries unless div by 400", the_rule, gate, parent=node
        )
        print(f"#{node.id} {node.status.value}: {node.outcome}")

    print("\n--- replay (distrust the author) ---")
    for n in g.nodes:
        matches, recorded, replayed = g.replay(n)
        verdict = "ok" if matches else "MISMATCH"
        print(f"#{n.id}: replay {verdict} ({len(replayed)} mishandled)")

    print("\n--- the hypothesis graph (smem) ---")
    print(g.to_markdown())


if __name__ == "__main__":
    main()
