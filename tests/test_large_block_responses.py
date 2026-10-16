"""Regression tests for large Ergo block transactions and unchanged small API cap."""
import json
import runpy
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

core = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'lithos_dashboard'))
api_get = core['api_get']
classify_ergo_block = core['classify_ergo_block']
DEFAULT_LIMIT = core['MAX_RESPONSE_BYTES']
BLOCK_LIMIT = core['MAX_BLOCK_TX_RESPONSE_BYTES']
BLOCK_ID = 'a' * 64
TREE = 'holding-contract-ergo-tree'

# The first transaction is a real-form genesis candidate; unrelated JSON in
# subsequent transactions puts the block response well above the 2 MiB limit.
GENESIS = {
    'inputs': [{'boxId': 'minting-input-box'}],
    'outputs': [{
        'ergoTree': TREE,
        'assets': [{'tokenId': 'minting-input-box'}]
    }],
}
BIG_REPLY = json.dumps({
    'transactions': [GENESIS, {'inputs': [], 'outputs': [],
                                'additionalRegisters': 'x' * (DEFAULT_LIMIT + 100_000)}]
}).encode('utf-8')


class FakeNode(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in (f'/blocks/{BLOCK_ID}/transactions', '/info'):
            data = BIG_REPLY
            advertised_length = len(data)
        elif path == '/too-large':
            # A content-length guard must reject before reading anything.
            data = b'{}'
            advertised_length = BLOCK_LIMIT + 1
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(advertised_length))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class BlockSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = ThreadingHTTPServer(('127.0.0.1', 0), FakeNode)
        cls.thread = threading.Thread(target=cls.node.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.node.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.node.shutdown()
        cls.node.server_close()
        cls.thread.join(timeout=3)

    def test_original_two_megabyte_guard_remains(self):
        self.assertEqual(DEFAULT_LIMIT, 2 * 1024 * 1024)
        self.assertGreater(len(BIG_REPLY), DEFAULT_LIMIT)
        with self.assertRaisesRegex(ValueError, r'API response exceeds 2097152 bytes.*info'):
            api_get(self.base, '/info')

    def test_large_block_transactions_classify_correctly(self):
        self.assertEqual(BLOCK_LIMIT, 16 * 1024 * 1024)
        result = classify_ergo_block(
            self.base, {'id': BLOCK_ID, 'powSolutions': {'pk': 'lender-key'}}, TREE
        )
        self.assertEqual(result, {
            'blockId': BLOCK_ID, 'lithos': True, 'lenderPk': 'lender-key'
        })

    def test_block_override_still_rejects_over_16mib(self):
        with self.assertRaisesRegex(ValueError, r'API response exceeds 16777216 bytes.*too-large'):
            api_get(self.base, '/too-large', max_response_bytes=BLOCK_LIMIT)

    def test_non_block_api_cannot_inherit_override(self):
        with self.assertRaisesRegex(ValueError, r'API response exceeds 2097152 bytes.*info'):
            api_get(self.base, '/info')


if __name__ == '__main__':
    unittest.main()
