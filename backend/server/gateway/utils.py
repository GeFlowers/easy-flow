'''网关通用的轻量字符串处理工具。'''


def sanitize_log_param(value: str) -> str:
    '''移除日志参数中的换行和空字节，避免伪造多行日志。'''
    return value.replace("\n", "").replace("\r", "").replace("\x00", "")
