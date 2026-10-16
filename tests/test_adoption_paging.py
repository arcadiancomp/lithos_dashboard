"""Network-adoption paging regression tests for the single-file Lithos Dashboard."""
import json
import runpy
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

DASHBOARD = Path(__file__).resolve().parents[1] / "lithos_dashboard"
module = runpy.run_path(str(DASHBOARD))
fetch = module["fetch_chain_headers"]
api_get = module["api_get"]
CAP = module["MAX_RESPONSE_BYTES"]
BATCH = module["CHAIN_SLICE_BATCH"]


class FakeNode(BaseHTTPRequestHandler):
    calls = []
    start_height = 1894000

    @classmethod
    def make_header(cls, height):
        return {"height": height, "id": f"{height:064x}", "padding": "X" * 2500}

    def do_GET(self):
        target = urlsplit(self.path)
        query = parse_qs(target.query)
        if target.path == "/blocks/chainSlice":
            first = int(query["fromHeight"][0])
            end = int(query["toHeight"][0])
            FakeNode.calls.append((first, end))
            # Ergo v6.0.6 BlocksApiRoute.getChainSlice uses
            # headerChainBack(... _.height <= fromHeight + 1).
            # Thus the response is (fromHeight, toHeight] on this node.
            payload = [self.make_header(i) for i in range(first + 1, end + 1)]
        elif target.path == "/blocks/lastHeaders/1000":
            payload = [self.make_header(i) for i in range(
                self.start_height, self.start_height + 1000)]
        else:
            self.send_error(404)
            return
        content = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class PagingTests(unittest.TestCase):
    """Regression against actual Ergo v6.0.6 Scala chainSlice semantics."""
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeNode)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        FakeNode.calls.clear()

    def test_1000_headers_paginated_under_original_size_limit(self):
        # An unpaged query is demonstrably > 2 MiB.
        self.assertGreater(
            len(json.dumps([FakeNode.make_header(i) for i in range(1000)]).encode()),
            CAP
        )
        with self.assertRaisesRegex(ValueError, "API response exceeds.*lastHeaders/1000"):
            api_get(self.base, "/blocks/lastHeaders/1000", timeout=5)

        first = FakeNode.start_height
        headers = fetch(self.base, first, first + 999)
        self.assertEqual([h["height"] for h in headers], list(range(first, first + 1000)))
        self.assertEqual(len(FakeNode.calls), (1000 + BATCH - 1) // BATCH)
        self.assertEqual(FakeNode.calls[0], (first - 1, first + BATCH - 1))
        self.assertEqual(FakeNode.calls[-1], (first + 7 * BATCH - 1, first + 999))

    def test_small_partial_window_and_empty_window(self):
        self.assertEqual(fetch(self.base, 100, 102)[0]["height"], 100)
        self.assertEqual(FakeNode.calls, [(99, 102)])
        self.assertEqual(fetch(self.base, 200, 199), [])

    def test_missing_or_duplicate_height_is_rejected(self):
        def missing(*_args, **kw):
            start, end = kw["params"]["fromHeight"], kw["params"]["toHeight"]
            return [{"height": n} for n in range(start + 1, end + 1) if n != start + 4]
        with patch.dict(fetch.__globals__, {"api_get": missing}):
            with self.assertRaisesRegex(ValueError, "missing or duplicate"):
                fetch(self.base, 100, 110)

        def duplicate(*_args, **kw):
            start, end = kw["params"]["fromHeight"], kw["params"]["toHeight"]
            return [{"height": n} for n in range(start + 1, end)] + [{"height": start + 1}]
        with patch.dict(fetch.__globals__, {"api_get": duplicate}):
            with self.assertRaisesRegex(ValueError, "missing or duplicate"):
                fetch(self.base, 100, 110)

    def test_non_list_response_is_rejected(self):
        with patch.dict(fetch.__globals__, {"api_get": lambda *_a, **_kw: {"error": "bad"}}):
            with self.assertRaisesRegex(ValueError, "non-list"):
                fetch(self.base, 100, 110)


if __name__ == "__main__":
    unittest.main()
