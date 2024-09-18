
FROM nvidia/cuda:12.2.0-devel-ubuntu22.04  
# 최신 CUDA 이미지로 변경
# FROM nvidia/cuda:12.1.0-devel-ubuntu22.04

RUN apt-get update && apt-get install -y python3 python3-pip
RUN mkdir -p /data  # 이 줄을 추가했습니다.

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY gpu_monitor.py .

CMD ["python3", "gpu_monitor.py"]