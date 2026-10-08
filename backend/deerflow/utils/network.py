'''线程安全地分配并释放端口，为本地服务或开发子进程选择监听端口。'''

import socket
import threading
from contextlib import contextmanager


class PortAllocator:
    '''维护已预留端口集合，避免同一进程中的调用重复分配。'''

    def __init__(self):
        '''初始化端口锁和当前进程内的预留记录。'''
        self._lock = threading.Lock()
        self._reserved_ports: set[int] = set()

    def _is_port_available(self, port: int) -> bool:
        '''尝试绑定通配地址判断端口是否空闲，并排除本分配器已预留端口。'''
        if port in self._reserved_ports:
            return False

        # 检查通配地址而非仅检查 localhost，使探测结果覆盖监听所有网卡的服务；
        # 只绑定回环地址可能误把已被通配监听占用的端口判断为空闲。
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    def allocate(self, start_port: int = 8080, max_range: int = 100) -> int:
        '''在给定范围内选择并预留第一个可绑定端口，找不到时抛出错误。'''
        with self._lock:
            for port in range(start_port, start_port + max_range):
                if self._is_port_available(port):
                    self._reserved_ports.add(port)
                    return port

            raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_range}")

    def release(self, port: int) -> None:
        '''释放进程内的端口预留标记，使后续调用可以再次分配该端口。'''
        with self._lock:
            self._reserved_ports.discard(port)

    @contextmanager
    def allocate_context(self, start_port: int = 8080, max_range: int = 100):
        '''以上下文管理方式分配端口，并确保退出时释放预留。'''
        port = self.allocate(start_port, max_range)
        try:
            yield port
        finally:
            self.release(port)


# 全进程共享的分配器，确保各处端口探测遵守同一预留记录。
_global_port_allocator = PortAllocator()


def get_free_port(start_port: int = 8080, max_range: int = 100) -> int:
    '''通过全局分配器寻找并预留一个可用端口。'''
    return _global_port_allocator.allocate(start_port, max_range)


def release_port(port: int) -> None:
    '''释放由全局分配器登记的端口。'''
    _global_port_allocator.release(port)
