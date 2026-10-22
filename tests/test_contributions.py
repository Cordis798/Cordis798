import importlib.util
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

SPEC = importlib.util.spec_from_file_location(
    "contributions", Path(__file__).resolve().parents[1] / "scripts" / "update_contributions.py"
)
cards = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cards)


def node(number, private=False, title="Fix a bug"):
    return {
        "number": number, "title": title,
        "url": f"https://github.com/example/project/pull/{number}",
        "mergedAt": "2026-10-22T08:05:44Z",
        "repository": {"nameWithOwner": "example/project", "isPrivate": private},
    }


def page(nodes, more=False, cursor=None):
    return {"data": {"user": {"pullRequests": {
        "nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor}
    }}}}


class ContributionsTest(unittest.TestCase):
    def test_all_pages_private_filter_and_deduplication(self):
        calls = []

        def request(variables):
            calls.append(variables.copy())
            if variables["cursor"] is None:
                return page([node(1), node(2, private=True)], True, "next-page")
            return page([node(1), node(3)])

        prs = cards.fetch_prs("Cordis798", request)
        self.assertEqual([pr["number"] for pr in prs], [3, 1])
        self.assertEqual([call["cursor"] for call in calls], [None, "next-page"])

    def test_repeated_pagination_cursor_fails(self):
        with self.assertRaisesRegex(RuntimeError, "cursor"):
            cards.fetch_prs("Cordis798", lambda _: page([node(1)], True, "loop"))

    def test_partial_api_error_preserves_previous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme = root / "README.md"
            readme.write_text(f"Intro\n{cards.START}\nExisting cards\n{cards.END}\n", encoding="utf-8")
            original = readme.read_bytes()

            def request(variables):
                if variables["cursor"] is None:
                    return page([node(1)], True, "next")
                return {"errors": [{"message": "Rate limit exceeded"}]}

            with self.assertRaises(RuntimeError):
                cards.generate(root, "Cordis798", cards.fetch_prs("Cordis798", request))
            self.assertEqual(readme.read_bytes(), original)
            self.assertFalse((root / "data").exists())

    def test_unexpected_url_is_rejected(self):
        unsafe = node(1)
        unsafe["url"] = "https://example.com/not-a-pr"
        with self.assertRaisesRegex(ValueError, "URL"):
            cards.fetch_prs("Cordis798", lambda _: page([unsafe]))

    def test_cards_escape_markup_and_link_directly_to_pr(self):
        title = 'Fix [request] <script>alert("x")</script> & headers'
        prs = cards.fetch_prs("Cordis798", lambda _: page([node(1, title=title)]))
        svg = cards.render_card(prs[0])
        parsed = ElementTree.fromstring(svg)
        self.assertNotIn("<script>", svg)
        self.assertEqual(parsed.find("{http://www.w3.org/2000/svg}title").text,
                         f"example/project #1: {title}")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(f"Intro\n{cards.START}\n{cards.END}\nFooter\n", encoding="utf-8")
            cards.generate(root, "Cordis798", prs)
            readme = (root / "README.md").read_text(encoding="utf-8")
            self.assertIn(r"Fix \[request\]", readme)
            self.assertIn(")](https://github.com/example/project/pull/1)", readme)
            self.assertTrue(readme.startswith("Intro\n"))
            self.assertTrue(readme.endswith("Footer\n"))
            snapshot = {file.relative_to(root): file.read_bytes() for file in root.rglob("*") if file.is_file()}
            cards.generate(root, "Cordis798", prs)
            self.assertEqual(snapshot, {file.relative_to(root): file.read_bytes() for file in root.rglob("*") if file.is_file()})

    def test_invalid_markers_leave_outputs_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("My profile without markers", encoding="utf-8")
            with self.assertRaises(ValueError):
                cards.generate(root, "Cordis798", [])
            self.assertFalse((root / "assets").exists())


if __name__ == "__main__":
    unittest.main()
