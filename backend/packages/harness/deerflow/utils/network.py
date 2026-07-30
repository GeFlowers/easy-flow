"""处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""

import socket
import threading
from contextlib import contextmanager


class PortAllocator:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""

    def __init__(self):
        """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
        self._lock = threading.Lock()
        self._reserved_ports: set[int] = set()

    def _is_port_available(self, port: int) -> bool:
        """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
        if port in self._reserved_ports:
            return False

        # Bind to 0.0.0.0 (wildcard) rather than localhost so that the check
        # mirrors exactly what Docker does.  Docker binds to 0.0.0.0:PORT;
        # checking only 127.0.0.1 can falsely report a port as available even
        # when Docker already occupies it on the wildcard address.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    def allocate(self, start_port: int = 8080, max_range: int = 100) -> int:
        """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
        with self._lock:
            for port in range(start_port, start_port + max_range):
                if self._is_port_available(port):
                    self._reserved_ports.add(port)
                    return port

            raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_range}")

    def release(self, port: int) -> None:
        """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
        with self._lock:
            self._reserved_ports.discard(port)

    @contextmanager
    def allocate_context(self, start_port: int = 8080, max_range: int = 100):
        """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
        port = self.allocate(start_port, max_range)
        try:
            yield port
        finally:
            self.release(port)


# Global port allocator instance for shared use across the application
_global_port_allocator = PortAllocator()


def get_free_port(start_port: int = 8080, max_range: int = 100) -> int:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    return _global_port_allocator.allocate(start_port, max_range)


def release_port(port: int) -> None:
    """处理本模块相关逻辑，并保持既有的安全、隔离和运行语义。"""
    _global_port_allocator.release(port)
