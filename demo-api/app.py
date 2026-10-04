# -*- coding: utf-8 -*-
"""
演示 Python 应用：
- 提供 RESTful API (/api/process)，该方法内部调用两个 Python 方法 method_a 和 method_b
- 使用 OpenTelemetry 进行链路追踪，通过 OTLP/HTTP 上报到 Tempo
- 输出 JSON 结构化日志到 stdout，由 OpenTelemetry Collector (filelog) 采集并发送到 Loki
"""
import os
import time
import json
import logging
import random

from flask import Flask, jsonify, request
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor


# ---------- 日志配置：单行 JSON 输出到 stdout ----------
class JsonFormatter(logging.Formatter):
    """将日志记录格式化为单行 JSON，便于 OpenTelemetry Collector 解析与 Loki 查询"""

    # logging 内部使用的标准属性名，排除后剩余的即为 extra 自定义字段
    _STANDARD_FIELDS = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message",
    }

    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 通过 extra={"key": value} 传入的自定义字段一并输出
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(service: str) -> logging.Logger:
    """初始化 JSON 日志格式，返回应用专用 logger"""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    return logging.getLogger(service)


# ---------- OpenTelemetry 链路追踪配置 ----------
# 初始化 TracerProvider，服务名会显示在 Tempo 中
service_name = os.environ.get("OTEL_SERVICE_NAME", "demo-api")
resource = Resource.create({"service.name": service_name})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            # Tempo 的 OTLP/HTTP 接口地址，由环境变量注入
            endpoint=os.environ.get(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "http://tempo.monitoring.svc.cluster.local:4318/v1/traces",
            ),
        )
    )
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app, tracer_provider=provider)

# 应用日志器：打印的日志会随容器 stdout 落到 /var/log/pods/，
# 由 OpenTelemetry Collector (filelog receiver) 采集并发送到 Loki
logger = setup_logging(service_name)


def method_a(n: int) -> int:
    """方法A：计算斐波那契数列第 n 项（迭代实现）"""
    with tracer.start_as_current_span("method_a") as span:
        span.set_attribute("method.name", "method_a")
        span.set_attribute("method.param.n", n)
        logger.info("method_a 开始计算斐波那契", extra={"method": "method_a", "n": n})
        start = time.time()
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
            time.sleep(0.02)  # 模拟处理耗时，便于在链路中观察
        span.set_attribute("method.result", a)
        logger.info(
            "method_a 计算完成",
            extra={"method": "method_a", "n": n, "result": a,
                   "duration_ms": round((time.time() - start) * 1000, 2)},
        )
        return a


def method_b(text: str) -> dict:
    """方法B：文本处理，返回反转文本、字符数与随机评分"""
    with tracer.start_as_current_span("method_b") as span:
        span.set_attribute("method.name", "method_b")
        span.set_attribute("method.param.length", len(text))
        logger.info(
            "method_b 开始处理文本",
            extra={"method": "method_b", "text": text, "length": len(text)},
        )
        time.sleep(0.05)  # 模拟处理耗时，便于在链路中观察
        result = {
            "reversed": text[::-1],
            "length": len(text),
            "score": random.randint(1, 100),
        }
        span.set_attribute("method.result.length", result["length"])
        logger.info(
            "method_b 处理完成",
            extra={"method": "method_b", "result": result},
        )
        return result


@app.route("/")
def index():
    """首页：接口使用说明"""
    return jsonify(
        {
            "app": service_name,
            "api": "GET /api/process?n=10&text=hello",
            "health": "GET /healthz",
        }
    )


@app.route("/healthz")
def healthz():
    """健康检查接口"""
    return jsonify({"status": "ok"})


@app.route("/api/process")
def process():
    """RESTful API：依次调用两个 Python 方法 method_a 与 method_b 并返回结果"""
    n = request.args.get("n", default=10, type=int)
    text = request.args.get("text", default="kubernetes", type=str)
    n = max(1, min(n, 30))  # 限制参数范围，防止计算过大
    logger.info(
        "收到 /api/process 请求",
        extra={"path": "/api/process", "n": n, "text": text},
    )
    start = time.time()
    result_a = method_a(n)
    result_b = method_b(text)
    logger.info(
        "/api/process 处理完成",
        extra={"path": "/api/process",
               "duration_ms": round((time.time() - start) * 1000, 2)},
    )
    return jsonify(
        {
            "input": {"n": n, "text": text},
            "method_a": {"fibonacci": result_a},
            "method_b": result_b,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
