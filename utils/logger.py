"""
日志管理模块
提供统一的日志记录功能
"""

import os
import sys
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

try:
    from .app_meta import APP_LOGGER_NAME
except ImportError:
    APP_LOGGER_NAME = "WindowPilot"


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器（仅控制台）"""
    
    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # 获取原始消息
        message = super().format(record)
        
        # 添加颜色
        color = self.COLORS.get(record.levelname, '')
        if color:
            message = f"{color}{message}{self.RESET}"
        
        return message


class Logger:
    """日志记录器"""
    
    def __init__(self, name: str = APP_LOGGER_NAME, 
                 log_dir: str = None,
                 console_level: int = logging.INFO,
                 file_level: int = logging.DEBUG,
                 enable_file: bool = True):
        """
        初始化日志记录器
        
        Args:
            name: 日志记录器名称
            log_dir: 日志文件目录
            console_level: 控制台日志级别
            file_level: 文件日志级别
            enable_file: 是否启用文件日志
        """
        self.name = name
        self.log_dir = log_dir or "logs"
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        
        # 清除已有的处理器
        self._logger.handlers.clear()
        
        # 添加控制台处理器
        self._add_console_handler(console_level)
        
        # 添加文件处理器
        if enable_file:
            self._add_file_handler(file_level)
    
    def _add_console_handler(self, level: int):
        """添加控制台处理器"""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        
        # 检查是否支持颜色
        if sys.platform == 'win32':
            # Windows启用ANSI颜色支持
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                formatter = ColoredFormatter(
                    '%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%H:%M:%S'
                )
            except Exception:
                formatter = logging.Formatter(
                    '%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%H:%M:%S'
                )
        else:
            formatter = ColoredFormatter(
                '%(asctime)s [%(levelname)s] %(message)s',
                datefmt='%H:%M:%S'
            )
        
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)
    
    def _add_file_handler(self, level: int):
        """添加文件处理器"""
        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 生成日志文件名
        timestamp = datetime.now().strftime('%Y%m%d')
        log_file = os.path.join(self.log_dir, f'{self.name}_{timestamp}.log')
        
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setLevel(level)
        
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        self._logger.addHandler(handler)
    
    def debug(self, message: str, *args, **kwargs):
        """调试日志"""
        self._logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """信息日志"""
        self._logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """警告日志"""
        self._logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """错误日志"""
        self._logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """严重错误日志"""
        self._logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """异常日志（包含堆栈信息）"""
        self._logger.exception(message, *args, **kwargs)
    
    def set_level(self, level: int):
        """设置日志级别"""
        self._logger.setLevel(level)
    
    @staticmethod
    def clean_old_logs(log_dir: str, days: int = 7):
        """
        清理旧日志文件
        
        Args:
            log_dir: 日志目录
            days: 保留天数
        """
        if not os.path.exists(log_dir):
            return
        
        import time
        now = time.time()
        cutoff = now - (days * 24 * 60 * 60)
        
        for filename in os.listdir(log_dir):
            filepath = os.path.join(log_dir, filename)
            if os.path.isfile(filepath):
                if os.path.getmtime(filepath) < cutoff:
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass


# 全局日志实例
_global_logger: Optional[Logger] = None


def get_logger(name: str = None) -> Logger:
    """
    获取全局日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        Logger实例
    """
    global _global_logger
    
    if _global_logger is None:
        _global_logger = Logger(name or APP_LOGGER_NAME)
    
    return _global_logger


def setup_logger(name: str = APP_LOGGER_NAME,
                log_dir: str = None,
                console_level: int = logging.INFO,
                file_level: int = logging.DEBUG,
                enable_file: bool = True) -> Logger:
    """
    配置并返回全局日志记录器
    
    Args:
        name: 日志记录器名称
        log_dir: 日志文件目录
        console_level: 控制台日志级别
        file_level: 文件日志级别
        enable_file: 是否启用文件日志
        
    Returns:
        Logger实例
    """
    global _global_logger
    
    _global_logger = Logger(
        name=name,
        log_dir=log_dir,
        console_level=console_level,
        file_level=file_level,
        enable_file=enable_file
    )
    
    return _global_logger


# 测试代码
if __name__ == "__main__":
    logger = setup_logger(enable_file=False)
    
    logger.debug("这是调试信息")
    logger.info("这是普通信息")
    logger.warning("这是警告信息")
    logger.error("这是错误信息")
    logger.critical("这是严重错误")
    
    try:
        raise ValueError("测试异常")
    except Exception:
        logger.exception("捕获到异常")
