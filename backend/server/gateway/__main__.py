'''从项目私有配置启动本机网关，并选择数据库驱动兼容的异步事件循环。'''

import os
import sys
import ctypes
import hashlib
import threading
import urllib.request
from ctypes import wintypes
from pathlib import Path

from dotenv import load_dotenv
import uvicorn


def create_server_config() -> uvicorn.Config:
    '''限定网关监听范围，并为 Windows 的数据库连接选择兼容的循环工厂。'''
    loop = 'asyncio:SelectorEventLoop' if sys.platform == 'win32' else 'asyncio'
    return uvicorn.Config('server.gateway.app:app', host='127.0.0.1', port=8001, loop=loop)


def shutdown_event_name(root: Path) -> str:
    '''由项目绝对路径生成退出事件名称，避免其他项目的停止请求影响本进程。'''
    digest = hashlib.sha256(str(root.resolve()).lower().encode('utf-8')).hexdigest()[:16]
    return f'Local\\DeerFlow-Gateway-{digest}'


def create_shutdown_signal(server: uvicorn.Server, root: Path):
    '''监听本项目的系统事件，将停止请求交给服务器执行正常关闭和记忆刷新。'''
    if sys.platform != 'win32':
        return None
    kernel = ctypes.windll.kernel32
    kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateEventW(None, True, False, shutdown_event_name(root))
    if not handle:
        raise ctypes.WinError()

    def request_shutdown() -> None:
        '''收到退出事件后停止接收新请求，并让网关完成自身关闭钩子。'''
        if kernel.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
            server.should_exit = True

    listener = threading.Thread(target=request_shutdown, name='gateway-shutdown', daemon=True)
    listener.start()
    return handle, listener


def close_shutdown_signal(signal) -> None:
    '''唤醒并回收退出监听器，避免进程退出时遗留系统事件句柄。'''
    if signal is not None:
        handle, listener = signal
        kernel = ctypes.windll.kernel32
        kernel.SetEvent(handle)
        listener.join(timeout=2)
        kernel.CloseHandle(handle)


def main() -> None:
    '''固定项目与数据路径，加载私有环境变量，并只在本机回环地址提供网关。'''
    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / '.env', override=True)
    # Windows 下仅设置 NO_PROXY 会遮蔽系统代理；先保留外部请求的代理路由。
    proxies = urllib.request.getproxies()
    if sys.platform == 'win32' and not any(name in proxies for name in ('http', 'https', 'all')):
        proxies = {**urllib.request.getproxies_registry(), **proxies}
    for protocol in ('http', 'https', 'all'):
        if proxy := proxies.get(protocol):
            os.environ.setdefault(f'{protocol.upper()}_PROXY', proxy)
    os.environ['DEER_FLOW_PROJECT_ROOT'] = str(root)
    os.environ['DEER_FLOW_HOME'] = str(root / 'backend' / '.deer-flow')
    os.environ['DEER_FLOW_CONFIG_PATH'] = str(root / 'config' / 'config.yaml')
    os.environ['DEER_FLOW_EXTENSIONS_CONFIG_PATH'] = str(root / 'config' / 'extensions_config.json')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['NO_PROXY'] = ','.join(filter(None, [os.environ.get('NO_PROXY', ''), 'localhost', '127.0.0.1', '::1']))
    os.environ['no_proxy'] = os.environ['NO_PROXY']
    sys.path.insert(0, str(root / 'backend'))
    os.chdir(root / 'backend')
    server = uvicorn.Server(create_server_config())
    signal = create_shutdown_signal(server, root)
    try:
        server.run()
    finally:
        close_shutdown_signal(signal)


if __name__ == '__main__':
    main()
