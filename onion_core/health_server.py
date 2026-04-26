"""
Onion Core - Health Check HTTP Server

提供轻量级 HTTP 服务器用于 Kubernetes 健康检查探针。
支持 liveness、readiness 和 startup 探针。

用法：
    from onion_core.health_server import start_health_server
    
    # 在应用启动时
    server = start_health_server(pipeline, port=8080)
    
    # 在应用关闭时
    server.stop()
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline import Pipeline

logger = logging.getLogger("onion_core.health_server")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP 健康检查请求处理器。"""
    
    pipeline: Pipeline | None = None
    
    def log_message(self, format: str, *args: object) -> None:
        """抑制默认日志输出。"""
        pass
    
    def do_GET(self) -> None:
        """处理 GET 请求。"""
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/health/live":
            self._handle_liveness()
        elif self.path == "/health/ready":
            self._handle_readiness()
        elif self.path == "/health/startup":
            self._handle_startup()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())
    
    def _handle_health(self) -> None:
        """综合健康检查（liveness + readiness）。"""
        if not self.pipeline:
            self._send_error(503, "Pipeline not configured")
            return
        
        health = self.pipeline.health_check()
        
        if health["status"] == "healthy":
            self._send_success(200, health)
        elif health["status"] == "not_started":
            self._send_error(503, "Pipeline not started", health)
        else:  # degraded
            self._send_error(503, "Pipeline degraded", health)
    
    def _handle_liveness(self) -> None:
        """
        Liveness 探针：检查进程是否存活。
        
        Kubernetes 会在失败时重启容器。
        """
        self._send_success(200, {"status": "alive"})
    
    def _handle_readiness(self) -> None:
        """
        Readiness 探针：检查是否准备好接收流量。
        
        Kubernetes 会在失败时将 Pod 从 Service 中移除。
        """
        if not self.pipeline:
            self._send_error(503, "Pipeline not configured")
            return
        
        health = self.pipeline.health_check()
        
        if health["status"] in ("healthy", "degraded"):
            # Degraded 状态仍可以接收流量，只是性能可能下降
            self._send_success(200, health)
        else:
            self._send_error(503, "Not ready", health)
    
    def _handle_startup(self) -> None:
        """
        Startup 探针：检查应用是否完成启动。
        
        Kubernetes 会在失败时重启容器（仅在启动阶段使用）。
        """
        if not self.pipeline:
            self._send_error(503, "Pipeline not configured")
            return
        
        health = self.pipeline.health_check()
        
        if health.get("started", False):
            self._send_success(200, health)
        else:
            self._send_error(503, "Still starting up", health)
    
    def _send_success(self, status_code: int, data: dict[str, object]) -> None:
        """发送成功响应。"""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def _send_error(self, status_code: int, message: str, details: dict[str, object] | None = None) -> None:
        """发送错误响应。"""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response: dict[str, object] = {"error": message}
        if details:
            response["details"] = details
        self.wfile.write(json.dumps(response).encode())


class HealthServer:
    """健康检查 HTTP 服务器。"""
    
    def __init__(self, pipeline: Pipeline, host: str = "0.0.0.0", port: int = 8080) -> None:
        """
        Args:
            pipeline: Onion Core Pipeline 实例
            host: 监听地址，默认 0.0.0.0
            port: 监听端口，默认 8080
        """
        self.pipeline = pipeline
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
    
    def start(self) -> None:
        """启动健康检查服务器（后台线程）。"""
        HealthCheckHandler.pipeline = self.pipeline
        
        self._server = HTTPServer((self.host, self.port), HealthCheckHandler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        
        logger.info(
            "Health check server started on http://%s:%d",
            self.host, self.port
        )
        logger.info("Endpoints: /health, /health/live, /health/ready, /health/startup")
    
    def stop(self) -> None:
        """停止健康检查服务器。"""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            logger.info("Health check server stopped.")
            self._server = None
            self._thread = None


def start_health_server(
    pipeline: Pipeline,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> HealthServer:
    """
    便捷函数：创建并启动健康检查服务器。
    
    Args:
        pipeline: Onion Core Pipeline 实例
        host: 监听地址
        port: 监听端口
        
    Returns:
        HealthServer 实例（可用于后续停止）
        
    Example:
        >>> from onion_core import Pipeline, EchoProvider
        >>> from onion_core.health_server import start_health_server
        >>> 
        >>> pipeline = Pipeline(provider=EchoProvider())
        >>> server = start_health_server(pipeline, port=8080)
        >>> # ... application logic ...
        >>> server.stop()
    """
    server = HealthServer(pipeline, host, port)
    server.start()
    return server
