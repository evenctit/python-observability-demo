# Python 演示应用镜像
FROM python:3.12-slim

WORKDIR /app

# 使用阿里云 pypi 镜像安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY app.py .

EXPOSE 5000
CMD ["python", "app.py"]
