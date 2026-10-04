# -*- coding: utf-8 -*-
"""
演示 Python 应用：
- 提供 RESTful API (/api/process)，该方法内部调用两个 Python 方法 method_a 和 method_b
- 使用 OpenTelemetry 进行链路追踪，通过 OTLP/HTTP 上报到 Tempo
"""
import os
import time
import random

from flask import Flask, jsonify, request
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor

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


def method_a(n: int) -> int:
    """方法A：计算斐波那契数列第 n 项（迭代实现）"""
    with tracer.start_as_current_span("method_a") as span:
        span.set_attribute("method.name", "method_a")
        span.set_attribute("method.param.n", n)
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
            time.sleep(0.02)  # 模拟处理耗时，便于在链路中观察
        span.set_attribute("method.result", a)
        return a


def method_b(text: str) -> dict:
    """方法B：文本处理，返回反转文本、字符数与随机评分"""
    with tracer.start_as_current_span("method_b") as span:
        span.set_attribute("method.name", "method_b")
        span.set_attribute("method.param.length", len(text))
        time.sleep(0.05)  # 模拟处理耗时，便于在链路中观察
        result = {
            "reversed": text[::-1],
            "length": len(text),
            "score": random.randint(1, 100),
        }
        span.set_attribute("method.result.length", result["length"])
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
    result_a = method_a(n)
    result_b = method_b(text)
    return jsonify(
        {
            "input": {"n": n, "text": text},
            "method_a": {"fibonacci": result_a},
            "method_b": result_b,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
