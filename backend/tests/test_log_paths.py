'''检查本机启停脚本直接使用项目日志根目录。'''

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LogPathTests(unittest.TestCase):
    '''防止启动或错误提示重新引用多余的日志子目录。'''

    def test_startup_uses_log_root(self):
        '''启动配置与报错提示应统一指向根日志目录。'''
        text = (ROOT / 'backend' / 'server' / 'local_services.py').read_text(encoding='utf-8')
        self.assertIn("LOGS = ROOT / 'logs'", text)
        self.assertFalse('logs/local' in text or 'logs\\local' in text)


if __name__ == '__main__':
    unittest.main()
