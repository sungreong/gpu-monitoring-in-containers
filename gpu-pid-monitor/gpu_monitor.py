import subprocess
import docker
import time
import logging
from prometheus_client import start_http_server, Gauge

# 로그 설정
logging.basicConfig(
    filename='/data/gpu_monitor.log',  # 로그 파일 경로
    level=logging.INFO,                # 로그 레벨 설정
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Prometheus 메트릭 정의
GPU_MEMORY_USAGE = Gauge('gpu_memory_usage_mb', 'GPU Memory Usage in MB', ['container_name', 'gpu_id', 'gpu_name'])

client = docker.from_env()

# 활성화된 메트릭 라벨 조합을 추적하기 위한 딕셔너리
active_metrics = {}
# 사라진 메트릭 라벨 조합을 추적하기 위한 딕셔너리
disappeared_metrics = {}

def get_busid_to_index_mapping():
    result = subprocess.run(
        ['nvidia-smi', '--query-gpu=index,gpu_bus_id', '--format=csv,noheader,nounits'],
        stdout=subprocess.PIPE, text=True
    )
    lines = [line.strip().split(',') for line in result.stdout.strip().split('\n') if line.strip()]
    busid_to_index = {bus_id.strip(): index.strip() for index, bus_id in lines}
    logging.debug(f"Bus ID to Index Mapping: {busid_to_index}")
    return busid_to_index

def get_gpu_info():
    result = subprocess.run(
        ['nvidia-smi', '--query-compute-apps=pid,gpu_name,gpu_bus_id,used_memory', '--format=csv,noheader,nounits'],
        stdout=subprocess.PIPE, text=True
    )
    lines = [line.strip().split(', ') for line in result.stdout.strip().split('\n') if line.strip()]
    gpu_info = [line for line in lines if len(line) == 4]
    logging.debug(f"GPU Info: {gpu_info}")
    return gpu_info

def get_container_name(pid):
    for container in client.containers.list():
        try:
            top = container.top()
            if str(pid) in [process[1] for process in top['Processes']]:
                return container.name
        except Exception as e:
            logging.error(f"Error accessing container {container.name}: {e}")
    return 'Unknown'

def collect_metrics():
    global active_metrics, disappeared_metrics
    gpu_info = get_gpu_info()
    busid_to_index = get_busid_to_index_mapping()

    current_metrics = set()
    if gpu_info:
        for pid, gpu_name, gpu_bus_id, used_memory in gpu_info:
            pid = pid.strip()
            gpu_name = gpu_name.strip()
            gpu_bus_id = gpu_bus_id.strip()
            used_memory = used_memory.strip()
            gpu_index = busid_to_index.get(gpu_bus_id, 'Unknown')
            container_name = get_container_name(pid)

            # Unknown GPU 또는 Container 이름이면 무시
            if gpu_index == 'Unknown' or container_name == 'Unknown':
                logging.warning(f"Skipping metric for PID {pid} due to Unknown GPU Index or Container Name.")
                continue

            # 라벨 조합 생성
            label_tuple = (container_name, gpu_index, gpu_name)

            # 활성화된 메트릭 정보 업데이트
            active_metrics[label_tuple] = True

            # GPU 사용량 업데이트
            GPU_MEMORY_USAGE.labels(
                container_name=container_name,
                gpu_id=gpu_index,
                gpu_name=gpu_name
            ).set(float(used_memory))

            # 로그 기록
            logging.info(f"Active: Container={container_name}, GPU Index={gpu_index}, GPU Name={gpu_name}, Used Memory={used_memory} MB")

            # 현재 메트릭 집합에 추가
            current_metrics.add(label_tuple)

    # 사라진 메트릭 감지
    disappeared = set(active_metrics.keys()) - current_metrics
    for label_tuple in disappeared:
        # GPU 사용량을 0으로 설정
        GPU_MEMORY_USAGE.labels(
            *label_tuple
        ).set(0.0)

        # 로그 기록
        logging.info(f"Disappeared: Container={label_tuple[0]}, GPU Index={label_tuple[1]}, GPU Name={label_tuple[2]}. Setting GPU usage to 0.")

        # 사라진 메트릭 딕셔너리에 추가 (타임스탬프 포함)
        disappeared_metrics[label_tuple] = {
            'timestamp': time.time()
        }

        # 활성화된 메트릭 딕셔너리에서 제거
        del active_metrics[label_tuple]

    # 일정 시간 후에 메트릭 제거
    current_time = time.time()
    for label_tuple in list(disappeared_metrics.keys()):
        elapsed_time = current_time - disappeared_metrics[label_tuple]['timestamp']
        if elapsed_time > 30:  # 스크레이프 주기에 맞게 시간 설정 (예: 30초)
            # 메트릭 제거
            GPU_MEMORY_USAGE.remove(
                *label_tuple  # 라벨 값을 인수로 전달
            )
            # 로그 기록
            logging.info(f"Removed metrics for Container={label_tuple[0]}, GPU Index={label_tuple[1]}, GPU Name={label_tuple[2]} after {elapsed_time} seconds.")
            # 사라진 메트릭 딕셔너리에서 제거
            del disappeared_metrics[label_tuple]

def initialize_metrics():
    # 기존에 존재하는 모든 메트릭 라벨 조합을 가져와서 GPU 사용량을 0으로 설정
    metrics = list(GPU_MEMORY_USAGE._metrics.keys())
    for label_values in metrics:
        GPU_MEMORY_USAGE.labels(*label_values).set(0.0)
        logging.info(f"Initialized metric: Container={label_values[0]}, GPU Index={label_values[1]}, GPU Name={label_values[2]} to 0.")

if __name__ == '__main__':
    try:
        logging.info("Starting GPU PID Monitor...")
        start_http_server(8000)

        # 메트릭 초기화
        initialize_metrics()

        while True:
            logging.debug("Collecting metrics...")
            collect_metrics()
            time.sleep(5)
    except Exception as e:
        logging.error(f"Error occurred: {e}")
