'''检查应用配置与示例只声明当前支持的渠道，并准确描述部署方式。'''

from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))


class ConfigConsistencyTests(unittest.TestCase):
    '''只检查字段名称和部署说明，不输出私有配置值。'''

    def test_channel_sections_only_use_supported_fields(self):
        '''渠道配置不得包含解析器已经不支持的提供商。'''
        from deerflow.config.channel_connections_config import ChannelConnectionsConfig

        supported = set(ChannelConnectionsConfig.model_fields)
        for name in ('config.yaml', 'config.example.yaml'):
            path = ROOT / 'config' / name
            if not path.exists():
                continue
            raw = yaml.safe_load(path.read_text(encoding='utf-8'))
            unknown = set(raw.get('channel_connections', {})) - supported
            with self.subTest(file=name):
                self.assertFalse(unknown, '不支持的渠道字段：' + ', '.join(sorted(unknown)))

    def test_local_sandbox_not_described_as_backend_container(self):
        '''当前默认沙箱运行于本机后端，不是已移除的容器部署。'''
        for name in ('config.yaml', 'config.example.yaml'):
            path = ROOT / 'config' / name
            if path.exists():
                with self.subTest(file=name):
                    self.assertFalse('后端容器' in path.read_text(encoding='utf-8'), '本地沙箱部署说明已过时')


if __name__ == '__main__':
    unittest.main()
