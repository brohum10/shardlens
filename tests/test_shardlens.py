import contextlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

from shardlens import Node, Placement, main, plan


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [Node(str(i)) for i in range(5)]

    def test_order_independent(self):
        a = Placement(self.nodes, 3)
        b = Placement(list(reversed(self.nodes)), 3)
        for i in range(100):
            self.assertEqual(a.owners(str(i)), b.owners(str(i)))

    def test_distinct_replicas(self):
        for i in range(100):
            owners = Placement(self.nodes, 5).owners(str(i))
            self.assertEqual(len(set(owners)), 5)

    def test_add_only_moves_to_new_node(self):
        a, b = Placement(self.nodes), Placement(self.nodes + [Node('new')])
        for i in range(1000):
            old, new = a.owners(str(i)), b.owners(str(i))
            self.assertTrue(old == new or new == ['new'])

    def test_remove_only_moves_departing_primary(self):
        a, b = Placement(self.nodes), Placement(self.nodes[:-1])
        for i in range(1000):
            old, new = a.owners(str(i)), b.owners(str(i))
            if old != ['4']:
                self.assertEqual(old, new)

    def test_replica_add_preserves_survivor_order(self):
        a, b = Placement(self.nodes, 3), Placement(self.nodes + [Node('new')], 3)
        for i in range(300):
            old, new = a.owners(str(i)), b.owners(str(i))
            self.assertEqual([x for x in new if x != 'new'], old[:2] if 'new' in new else old)

    def test_weight_distribution(self):
        p = Placement([Node('a', 1), Node('b', 3)])
        count = sum(p.owners(str(i)) == ['b'] for i in range(10000))
        self.assertTrue(7200 < count < 7800, count)

    def test_weight_increase_only_gains(self):
        a = Placement([Node('a'), Node('b')])
        b = Placement([Node('a', 3), Node('b')])
        for i in range(1000):
            if a.owners(str(i)) == ['a']:
                self.assertEqual(b.owners(str(i)), ['a'])

    def test_invalid_cluster(self):
        for nodes, replicas in [([], 1), (self.nodes, 0), (self.nodes, True),
                                (self.nodes, 6), ([Node('a'), Node('a')], 1),
                                ([Node(' ')], 1)]:
            with self.assertRaises(ValueError):
                Placement(nodes, replicas)
        for weight in [0, -1, float('nan'), float('inf'), True, '3', 1e-14]:
            with self.assertRaises(ValueError):
                Placement([Node('a', weight)])

    def test_unicode_and_framing(self):
        p = Placement([Node('ab'), Node('b'), Node('🌍')], 2)
        self.assertEqual(p.owners('你好'), p.owners('你好'))
        with self.assertRaises(ValueError):
            p.owners('')

    def test_repeatable_seeded_topology_properties(self):
        rng = random.Random(17)
        for _ in range(30):
            nodes = [Node(str(i), rng.uniform(.1, 9)) for i in range(8)]
            p = Placement(nodes, 4)
            rng.shuffle(nodes)
            self.assertEqual(p.owners('key'), Placement(nodes, 4).owners('key'))


class PlanTests(unittest.TestCase):
    def test_identity(self):
        nodes = [Node('a'), Node('b')]
        result = plan(nodes, nodes, [{'key':'x','bytes':10}], 2)
        self.assertEqual(result['changes'], [])
        self.assertEqual(result['estimated_copy_bytes'], 0)
        self.assertEqual(sum(n['bytes'] for n in result['after_load'].values()), 20)

    def test_complete_replacement(self):
        r = plan([Node('a'), Node('b')], [Node('c'), Node('d')], [{'key':'x','bytes':10}], 2)
        self.assertEqual(r['estimated_copy_bytes'], 20)
        self.assertEqual(r['replica_copies'], 2)
        self.assertEqual(r['primary_changes'], 1)

    def test_primary_swap_does_not_copy_existing_replica(self):
        before = [Node('a'), Node('b')]
        after = [Node('a', 100), Node('b')]
        items = [{'key':str(i), 'bytes':10} for i in range(100)]
        r = plan(before, after, items, 2)
        self.assertGreater(r['primary_changes'], 0)
        self.assertEqual(r['estimated_copy_bytes'], 0)

    def test_input_order_determinism(self):
        items = [{'key':str(i),'bytes':i} for i in range(10)]
        self.assertEqual(plan([Node('a')], [Node('b')], items),
                         plan([Node('a')], [Node('b')], list(reversed(items))))

    def test_bad_objects(self):
        for items in [[{'key':'a','bytes':True}], [{'key':'a','bytes':-1}],
                      [{'key':'a','bytes':1},{'key':'a','bytes':2}], [{}]]:
            with self.assertRaises(ValueError):
                plan([Node('a')], [Node('b')], items)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'input.json'
            path.write_text(json.dumps({'before':[{'id':'a'}], 'after':[{'id':'b'}],
                                       'objects':[{'key':'x','bytes':15}]}))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue())['estimated_copy_bytes'], 15)
            for invalid in ['{"before":[],"before":[]}', '{}', '{',
                            '{"before":[],"after":[],"objects":null}']:
                path.write_text(invalid)
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as out:
                    with self.assertRaises(SystemExit) as error:
                        main([str(path)])
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(out.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
