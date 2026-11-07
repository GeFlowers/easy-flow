'''在 Windows 本机安全地启动和停止 DeerFlow 前后端进程。'''

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
FRONTEND = ROOT / 'frontend'
LOGS = ROOT / 'logs'
STATE = LOGS / 'processes.json'
PYTHON = BACKEND / '.venv' / 'Scripts' / 'python.exe'
NEXT = FRONTEND / 'node_modules' / 'next' / 'dist' / 'bin' / 'next'

_QUERY = 0x1000
_SYNCHRONIZE = 0x100000
_TERMINATE = 0x0001
_EVENT_MODIFY = 0x0002
_WAIT_OBJECT_0 = 0
_CREATE_NO_WINDOW = 0x08000000


def _kernel():
    '''配置 Windows 进程和事件接口，保证句柄在 64 位系统中不被截断。'''
    if sys.platform != 'win32':
        raise RuntimeError('本机部署需要 Windows 和 Git Bash。')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.SetEvent.restype = wintypes.BOOL
    return kernel


def _identity(kernel, handle) -> tuple[int, str] | None:
    '''读取进程创建时间与可执行文件，识别已退出或被复用的编号。'''
    exit_code = wintypes.DWORD()
    if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
        raise ctypes.WinError(ctypes.get_last_error())
    if exit_code.value != 259:
        return None
    created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    size = wintypes.DWORD(32768)
    image = ctypes.create_unicode_buffer(size.value)
    if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
    return ticks, os.path.normcase(os.path.abspath(image.value))


def _open_process(kernel, pid: int, *, terminate: bool = False):
    '''打开进程句柄；权限不足时明确报错，不把未知进程当成已退出。'''
    handle = kernel.OpenProcess(_QUERY | _SYNCHRONIZE | (_TERMINATE if terminate else 0), False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return None
        raise ctypes.WinError(error)
    return handle


def _load_state() -> list[dict]:
    '''读取受管进程记录；拒绝损坏或旧格式，防止误停其他程序。'''
    if not STATE.exists():
        return []
    try:
        records = json.loads(STATE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise RuntimeError('进程记录无法读取，请检查 logs/processes.json。') from exc
    if not isinstance(records, list):
        raise RuntimeError('进程记录格式错误，请检查 logs/processes.json。')
    seen = set()
    for record in records:
        if not isinstance(record, dict) or record.get('name') not in {'gateway', 'frontend'}:
            raise RuntimeError('发现旧版或无效进程记录，请先停止旧版本项目。')
        if record['name'] in seen or not isinstance(record.get('pid'), int) or record['pid'] <= 0:
            raise RuntimeError('进程记录存在重复或无效编号，未执行操作。')
        if not isinstance(record.get('created'), int) or not isinstance(record.get('executable'), str):
            raise RuntimeError('进程身份记录不完整，未执行操作。')
        seen.add(record['name'])
    return records


def _save_state(records: list[dict]) -> None:
    '''原子更新进程记录，避免中途退出时留下半个文件。'''
    LOGS.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=LOGS, prefix='.processes-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(records, stream, ensure_ascii=False, indent=2)
        temporary.replace(STATE)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _expected_executable(name: str) -> str:
    '''计算允许管理的程序路径，不根据进程名称批量结束程序。'''
    if name == 'gateway':
        executable = PYTHON
    elif name == 'frontend':
        node = shutil.which('node.exe')
        if node is None:
            raise RuntimeError('找不到 Node.js，请先安装并加入 PATH。')
        executable = Path(node)
    else:
        raise ValueError('未知服务')
    return os.path.normcase(os.path.abspath(executable))


def _open_verified(kernel, record: dict, *, terminate: bool = False):
    '''校验编号、创建时间及程序路径；成功时返回仍持有的进程句柄。'''
    expected = _expected_executable(record['name'])
    if os.path.normcase(os.path.abspath(record['executable'])) != expected:
        raise RuntimeError(f"{record['name']} 的进程记录路径不匹配，未执行操作。")
    handle = _open_process(kernel, record['pid'], terminate=terminate)
    if handle is None:
        return None
    try:
        actual = _identity(kernel, handle)
        if actual is None:
            kernel.CloseHandle(handle)
            return None
        if actual != (record['created'], expected):
            raise RuntimeError(f"{record['name']} 的进程身份不匹配，未操作该进程。")
        return handle
    except Exception:
        kernel.CloseHandle(handle)
        raise


def _assert_port_free(port: int) -> None:
    '''端口被占用时立即退出，不结束占用端口的其他程序。'''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'端口 {port} 已被占用；未停止其他进程。') from exc


def _wait_ready(url: str, *, timeout: float = 90) -> None:
    '''等待本机服务健康，不通过系统代理访问本地地址。'''
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=3) as response:
                if 200 <= response.status < 400:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError(f'服务未就绪：{url}；请检查 logs 目录。')


def _start_process(name: str, command: list[str], directory: Path, environment: dict[str, str], records: list[dict]) -> None:
    '''隐藏窗口启动程序，并持久化可验证的进程身份。'''
    kernel = _kernel()
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / f'{name}.out.log').open('ab') as out, (LOGS / f'{name}.err.log').open('ab') as err:
        process = subprocess.Popen(command, cwd=directory, env=environment, stdout=out, stderr=err, creationflags=_CREATE_NO_WINDOW)
    try:
        time.sleep(0.8)
        if process.poll() is not None:
            raise RuntimeError(f'{name} 启动后退出，请查看 logs。')
        handle = _open_process(kernel, process.pid)
        if handle is None:
            raise RuntimeError(f'{name} 启动后退出，请查看 logs。')
        try:
            identity = _identity(kernel, handle)
        finally:
            kernel.CloseHandle(handle)
        if identity is None or identity[1] != _expected_executable(name):
            raise RuntimeError(f'{name} 的启动进程身份不匹配。')
        record = {'name': name, 'pid': process.pid, 'created': identity[0], 'executable': identity[1]}
        _save_state(records + [record])
        records.append(record)
    except Exception:
        # 只终止刚由本函数创建、尚未成功登记的进程。
        if not any(record.get('pid') == process.pid for record in records) and process.poll() is None:
            process.terminate()
        raise


def _nginx_home() -> Path:
    '''从环境或私有配置解析本机代理安装目录。'''
    value = os.environ.get('NGINX_HOME') or dotenv_values(ROOT / '.env').get('NGINX_HOME')
    if not value:
        raise RuntimeError('请在根目录 .env 中设置 NGINX_HOME。')
    directory = Path(value).expanduser().resolve()
    if not (directory / 'nginx.exe').is_file():
        raise RuntimeError('NGINX_HOME 必须指向包含 nginx.exe 的目录。')
    return directory


def _nginx_listener_matches(kernel, executable: Path) -> bool:
    '''确认 2026 端口由配置的 Nginx 程序监听。'''
    result = subprocess.run(['netstat', '-ano', '-p', 'tcp'], capture_output=True, text=True, errors='replace', check=True, creationflags=_CREATE_NO_WINDOW)
    expected = os.path.normcase(os.path.abspath(executable))
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != 'TCP' or fields[3].upper() != 'LISTENING':
            continue
        if fields[1].rsplit(':', 1)[-1] != '2026' or not fields[4].isdigit():
            continue
        handle = _open_process(kernel, int(fields[4]))
        if handle is None:
            continue
        try:
            identity = _identity(kernel, handle)
            if identity and identity[1] == expected:
                return True
        finally:
            kernel.CloseHandle(handle)
    return False


def _start_nginx(kernel) -> None:
    '''复用已运行的本机代理；未运行时校验配置并隐藏窗口启动。'''
    directory = _nginx_home()
    executable = directory / 'nginx.exe'
    prefix = directory.as_posix() + '/'
    subprocess.run([str(executable), '-t', '-p', prefix, '-c', 'conf/nginx.conf'], cwd=directory, check=True, creationflags=_CREATE_NO_WINDOW)
    if _nginx_listener_matches(kernel, executable):
        return
    _assert_port_free(2026)
    subprocess.Popen([str(executable), '-p', prefix, '-c', 'conf/nginx.conf'], cwd=directory, creationflags=_CREATE_NO_WINDOW)


def start() -> None:
    '''按后端、前端和本机代理顺序启动，重复执行不会创建重复进程。'''
    kernel = _kernel()
    if not PYTHON.is_file() or not NEXT.is_file():
        raise RuntimeError('缺少后端虚拟环境或前端依赖，请先按文档安装。')
    if not (FRONTEND / '.next' / 'BUILD_ID').is_file():
        raise RuntimeError('缺少前端构建产物，请先按文档构建。')
    records = _load_state()
    active = {}
    for record in records[:]:
        handle = _open_verified(kernel, record)
        if handle is None:
            records.remove(record)
            _save_state(records)
        else:
            active[record['name']] = True
            kernel.CloseHandle(handle)
    for name, port in (('gateway', 8001), ('frontend', 3001)):
        if name not in active:
            _assert_port_free(port)
    if 'gateway' not in active:
        _start_process('gateway', [str(PYTHON), '-X', 'utf8', '-m', 'server.gateway'], BACKEND, os.environ.copy(), records)
    _wait_ready('http://127.0.0.1:8001/health')
    if 'frontend' not in active:
        environment = os.environ.copy()
        environment.update({'DEER_FLOW_INTERNAL_GATEWAY_BASE_URL': 'http://127.0.0.1:8001', 'DEER_FLOW_TRUSTED_ORIGINS': 'http://localhost:2026,http://127.0.0.1:2026', 'NODE_ENV': 'production'})
        _start_process('frontend', [_expected_executable('frontend'), str(NEXT), 'start', '--hostname', '127.0.0.1', '--port', '3001'], FRONTEND, environment, records)
    _wait_ready('http://127.0.0.1:3001/login')
    _start_nginx(kernel)
    _wait_ready('http://localhost:2026/health')
    print('项目已启动：http://localhost:2026')


def _request_gateway_shutdown(kernel) -> None:
    '''通过项目专属系统事件请求后端正常退出。'''
    digest = hashlib.sha256(str(ROOT.resolve()).lower().encode('utf-8')).hexdigest()[:16]
    event = kernel.OpenEventW(_EVENT_MODIFY, False, f'Local\\DeerFlow-Gateway-{digest}')
    if not event:
        raise RuntimeError('无法发送后端正常退出信号；未强制终止。')
    try:
        if not kernel.SetEvent(event):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(event)


def stop() -> None:
    '''只停止身份匹配的本项目前后端，保留他人的进程。'''
    kernel = _kernel()
    records = _load_state()
    for name in ('frontend', 'gateway'):
        record = next((item for item in records if item['name'] == name), None)
        if record is None:
            continue
        handle = _open_verified(kernel, record, terminate=(name == 'frontend'))
        if handle is not None:
            try:
                if name == 'gateway':
                    _request_gateway_shutdown(kernel)
                elif not kernel.TerminateProcess(handle, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
                if kernel.WaitForSingleObject(handle, 30000) != _WAIT_OBJECT_0:
                    raise RuntimeError(f'{name} 未在 30 秒内退出，未进一步强制处理。')
            finally:
                kernel.CloseHandle(handle)
        records.remove(record)
        _save_state(records)
    print('本机前后端已停止；Nginx 和共享 Redis 保持运行。')


def main() -> None:
    '''仅提供启动和关闭两项操作，供 Git Bash 脚本调用。'''
    parser = argparse.ArgumentParser(description='管理本机 DeerFlow 前后端。')
    parser.add_argument('action', choices=('start', 'stop'))
    args = parser.parse_args()
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / '.services.lock').open('a+b') as lock:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('另一个启停操作正在进行，请稍后重试。') from exc
            try:
                start() if args.action == 'start' else stop()
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f'操作失败：{exc}', file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
