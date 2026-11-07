'''验证根目录统一管理忽略规则与构建命令，且不扩大源码忽略范围。'''

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RootProjectFilesTests(unittest.TestCase):
    '''检查迁移后的文件位置、忽略范围和命令可解析性。'''

    def test_no_duplicate_project_control_files(self):
        '''前后端不再保留重复的控制文件。'''
        for relative in ('backend/.gitignore', 'frontend/.gitignore', 'backend/Makefile', 'frontend/Makefile'):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    @unittest.skipUnless(shutil.which('git'), '未安装 Git')
    def test_ignore_scope_preserved(self):
        '''依赖、私有数据和产物仍被忽略，源码及示例文件不被误忽略。'''
        ignored = (
            '.env', 'frontend/.env', 'config/config.yaml', 'config/extensions_config.json',
            'backend/.venv/check.txt', 'backend/.deer-flow/check.txt', 'logs/check.log',
            'backend/dist/check.txt', 'backend/build/check.txt', 'backend/wheels/check.txt',
            'backend/.coverage', 'backend/example.egg-info/check.txt', 'backend/.langgraph_api/check.txt',
            'backend/sandbox/check.txt', 'frontend/node_modules/check.txt', 'frontend/.next/check.txt',
            'frontend/out/check.txt', 'frontend/build/check.txt', 'frontend/next-env.d.ts',
            'frontend/cache.tsbuildinfo', 'frontend/cert.pem', 'frontend/.vercel/check.txt',
            'frontend/prisma/db.sqlite', 'frontend/prisma/db.sqlite-journal', 'frontend/npm-debug.log.1',
        )
        visible = (
            '.env.example', 'frontend/.env.example', 'config/config.example.yaml',
            'config/extensions_config.example.json', 'backend/deerflow/sandbox/sandbox.py',
            'backend/server/gateway/app.py', 'frontend/src/app/layout.tsx',
            'skills/public/skill-creator/SKILL.md', 'Makefile',
        )
        for path, expected in [(path, 0) for path in ignored] + [(path, 1) for path in visible]:
            with self.subTest(path=path):
                result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', path], cwd=ROOT, capture_output=True)
                self.assertEqual(result.returncode, expected, path)

    @unittest.skipUnless(shutil.which('make'), '未安装 Make')
    def test_root_commands_parse_without_running(self):
        '''试运行只展示命令，不安装依赖、不改代码、不重启服务。'''
        result = subprocess.run(
            ['make', '-n', 'start', 'stop'],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('scripts/start.sh', result.stdout)
        self.assertIn('scripts/stop.sh', result.stdout)


if __name__ == '__main__':
    unittest.main()
