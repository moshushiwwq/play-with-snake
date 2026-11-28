"""客户端启动决策的单元测试：地址拼接、上次服务器优先与自动打开的条件。"""
from __future__ import annotations

import unittest

from client.launcher import (
    auto_open_target, collapse_servers, match_last, server_detail, server_page_url,
    server_title,
)


def srv(host='192.168.1.5', port=8080, name='贪吃蛇大冒险服务器', ver='3.2.0',
        rooms=0, players=0):
    """构造一条服务器信息。"""
    return {'host': host, 'httpPort': port, 'wsPort': port + 1, 'name': name,
            'version': ver, 'rooms': rooms, 'players': players}


class TestPageUrl(unittest.TestCase):
    """浏览器地址拼接。"""

    def test_builds_http_url_with_http_port(self):
        """用 HTTP 端口拼地址，而不是 WS 端口。"""
        self.assertEqual(server_page_url(srv('10.0.0.9', 8080)), 'http://10.0.0.9:8080/')

    def test_custom_http_port(self):
        """非默认 HTTP 端口同样保留。"""
        self.assertEqual(server_page_url(srv('10.0.0.9', 18080)), 'http://10.0.0.9:18080/')

    def test_strips_scheme_and_path_from_host(self):
        """主机字段里混入协议或路径时只取主机名。"""
        self.assertEqual(server_page_url({'host': 'http://10.0.0.9:8080/x'}), 'http://10.0.0.9:8080/')

    def test_missing_host_returns_empty(self):
        """缺少主机时不拼出无效地址。"""
        self.assertEqual(server_page_url({}), '')
        self.assertEqual(server_page_url(None), '')

    def test_bad_port_falls_back(self):
        """端口异常时回退到默认 HTTP 端口。"""
        self.assertEqual(server_page_url({'host': '10.0.0.9', 'httpPort': 'x'}),
                         'http://10.0.0.9:8080/')


class TestAutoOpen(unittest.TestCase):
    """自动打开的条件：只有无歧义时才自动打开。"""

    def test_single_server_opens_automatically(self):
        """局域网里只有一台服务器时自动打开。"""
        target = auto_open_target([srv('10.0.0.7')], '')
        self.assertEqual((target or {}).get('host'), '10.0.0.7')

    def test_multiple_servers_without_history_waits_for_user(self):
        """多台服务器且没有历史记录时不替用户做选择。"""
        self.assertIsNone(auto_open_target([srv('10.0.0.7'), srv('10.0.0.8')], ''))

    def test_last_server_wins_even_with_multiple(self):
        """上次用过的服务器仍在时优先它，避免每次都要重新选。"""
        target = auto_open_target([srv('10.0.0.7'), srv('10.0.0.8')], '10.0.0.8:8081')
        self.assertEqual((target or {}).get('host'), '10.0.0.8')

    def test_last_server_ignores_scheme_and_port(self):
        """历史地址带协议或端口也能匹配。"""
        self.assertIsNotNone(match_last([srv('10.0.0.8')], 'http://10.0.0.8:8080/'))

    def test_empty_scan(self):
        """没扫到服务器时不自动打开。"""
        self.assertIsNone(auto_open_target([], '10.0.0.8'))
        self.assertIsNone(auto_open_target(None, '10.0.0.8'))


class TestCollapse(unittest.TestCase):
    """本机服务器的回环地址与局域网地址要合并成一条。"""

    def test_same_machine_two_addresses_collapse_to_one(self):
        """回环 + 本机局域网地址归并为一条，自动打开因此生效。"""
        servers = [srv('127.0.0.1'), srv('192.168.10.52')]
        own = {'127.0.0.1', '192.168.10.52'}
        self.assertEqual(len(collapse_servers(servers, '', own)), 1)
        self.assertEqual(auto_open_target(servers, '', own)['host'], '127.0.0.1')

    def test_last_address_wins_inside_group(self):
        """上次用的是局域网地址时，合并后保留该地址。"""
        servers = [srv('127.0.0.1'), srv('192.168.10.52')]
        own = {'127.0.0.1', '192.168.10.52'}
        merged = collapse_servers(servers, '192.168.10.52:8081', own)
        self.assertEqual(merged[0]['host'], '192.168.10.52')

    def test_remote_servers_never_merge(self):
        """别人的服务器即使端口版本相同也各自独立，不会被误合并。"""
        servers = [srv('10.0.0.7'), srv('10.0.0.8', name='另一台'), srv('10.0.0.9')]
        self.assertEqual(len(collapse_servers(servers, '', {'127.0.0.1'})), 3)
        self.assertIsNone(auto_open_target(servers, '', {'127.0.0.1'}))

    def test_different_ports_are_kept_apart(self):
        """本机上两个不同端口的服务器算两台，不自动打开。"""
        servers = [srv('127.0.0.1'), srv('127.0.0.1', port=18080)]
        self.assertEqual(len(collapse_servers(servers, '', {'127.0.0.1'})), 2)
        self.assertIsNone(auto_open_target(servers, ''))

    def test_skips_unusable_entries(self):
        """没有可用地址的条目直接丢弃。"""
        self.assertEqual(collapse_servers([{'host': ''}, srv('10.0.0.9')]),
                         [srv('10.0.0.9')])


class TestRowText(unittest.TestCase):
    """列表文案：纯文本、无表情符号。"""

    def test_title_and_detail_contain_key_info(self):
        """标题含名称与地址，副标题含版本与人数。"""
        s = srv('10.0.0.9', rooms=2, players=3)
        self.assertIn('贪吃蛇大冒险服务器', server_title(s))
        self.assertIn('http://10.0.0.9:8080/', server_title(s))
        detail = server_detail(s)
        self.assertIn('版本 3.2.0', detail)
        self.assertIn('房间 2', detail)
        self.assertIn('在线 3', detail)

    def test_no_symbol_or_emoji_characters(self):
        """文案里不出现表情符号、箭头、几何装饰等字符。"""
        def is_decor(ch: str) -> bool:
            """判断字符是否属于表情/装饰符号区段。"""
            o = ord(ch)
            return (0x2190 <= o <= 0x2BFF) or (0xFE00 <= o <= 0xFE0F) or (0x1F000 <= o <= 0x1FAFF)

        s = srv()
        for text in (server_title(s), server_detail(s)):
            for ch in text:
                self.assertFalse(is_decor(ch), '出现装饰性字符：%r' % ch)


if __name__ == '__main__':
    unittest.main()
