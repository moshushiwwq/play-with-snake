"""签名算法测试：必须与客户端 JS snakeSig() 完全一致（向量取自 Node 端实算）。"""
from __future__ import annotations

import unittest

from shared.protocol import snake_sig, verify_record

VECTORS = [
    ({'mode': 'single', 'diff': 'normal', 'players': ['魔术师', ''], 'scores': [321, 0],
      'levels': [2, 1], 'lens': [18, 0], 'duration': 95, 'mapId': 'classic'}, 'bbe2d74c'),
    ({'mode': 'duel', 'diff': 'hard', 'players': ['甲', '乙'], 'scores': [120, 80],
      'levels': [1, 1], 'lens': [9, 7], 'duration': 60, 'mapId': 'pillars'}, '7a7fee68'),
    ({'mode': 'single', 'diff': 'easy', 'players': ['Player'], 'scores': [0],
      'levels': [1], 'lens': [4], 'duration': None, 'mapId': ''}, 'f2b619c8'),
]


class TestSignature(unittest.TestCase):
    """校验签名与篡改识别。"""

    def test_vectors_match_js(self):
        """三组向量与 Node 实现一致。"""
        for rec, expect in VECTORS:
            with self.subTest(rec=rec):
                self.assertEqual(snake_sig(rec), expect)

    def test_verify_accepts_original(self):
        """原始记录可通过校验。"""
        rec, _ = VECTORS[0]
        rec = dict(rec, sig=snake_sig(rec))
        self.assertTrue(verify_record(rec))

    def test_verify_rejects_tampered(self):
        """修改分数后校验失败。"""
        rec, _ = VECTORS[0]
        rec = dict(rec, sig=snake_sig(rec))
        rec['scores'] = [999999, 0]
        self.assertFalse(verify_record(rec))

    def test_missing_sig_rejected(self):
        """缺少签名一律拒绝。"""
        rec, _ = VECTORS[0]
        self.assertFalse(verify_record(rec))


if __name__ == '__main__':
    unittest.main()
