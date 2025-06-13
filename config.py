import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    KUBECONFIG = os.getenv('KUBECONFIG')
    AKS_CLUSTER_NAME = os.getenv('AKS_CLUSTER_NAME')
    AZURE_SUBSCRIPTION_ID = os.getenv('AZURE_SUBSCRIPTION_ID')
    SPOT_NODE_POOL = os.getenv('SPOT_NODE_POOL', 'spot')
    REGULAR_NODE_POOL = os.getenv('REGULAR_NODE_POOL', 'regular')
    
    # Umbrales para rebalanceo
    SPOT_UTILIZATION_THRESHOLD = float(os.getenv('SPOT_UTILIZATION_THRESHOLD', '0.7'))
    REGULAR_UTILIZATION_THRESHOLD = float(os.getenv('REGULAR_UTILIZATION_THRESHOLD', '0.8'))
    MAX_SPOT_INTERRUPTION_RISK = float(os.getenv('MAX_SPOT_INTERRUPTION_RISK', '0.3'))

    # Configuraciones para KEDA/Prometheus
    KEDA_NAMESPACE = os.getenv('KEDA_NAMESPACE', 'keda')
    PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus-kube-prometheus-prometheus.monitoring:9090')
    SCALING_COOLDOWN = int(os.getenv('SCALING_COOLDOWN', '300'))  # 5 minutos
    MIN_REPLICAS = int(os.getenv('MIN_REPLICAS', '1'))
    MAX_REPLICAS = int(os.getenv('MAX_REPLICAS', '10'))
    CPU_SCALING_THRESHOLD = int(os.getenv('CPU_SCALING_THRESHOLD', '70'))  # 70% de uso
    MEMORY_SCALING_THRESHOLD = int(os.getenv('MEMORY_SCALING_THRESHOLD', '80'))  # 80% de uso

    # Configuración de entorno
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'local')  # local|production

    # Configuración de rendimiento
    RESPONSE_TIME_THRESHOLD = float(os.getenv('RESPONSE_TIME_THRESHOLD', '1.0'))  # 1 segundo
    MAX_RESPONSE_TIME = float(os.getenv('MAX_RESPONSE_TIME', '2.0'))  # 2 segundos

    # Configuración de estabilización
    COOLDOWN_PERIOD = int(os.getenv('COOLDOWN_PERIOD', '300'))  # 5 minutos entre escalados
    STABILIZATION_WINDOW = int(os.getenv('STABILIZATION_WINDOW', '60'))  # Segundos para considerar métricas estables
    MIN_CHANGE_PERIOD = int(os.getenv('MIN_CHANGE_PERIOD', '120'))  # Mínimo tiempo entre cambios de pods

    # Configuración de ventanas horarias
    TIME_WINDOWS = {
        'night': {'start': '00:00', 'end': '06:00', 'min_replicas': 1, 'max_replicas': 3},
        'morning': {'start': '06:00', 'end': '12:00', 'min_replicas': 2, 'max_replicas': 5},
        'afternoon': {'start': '12:00', 'end': '18:00', 'min_replicas': 3, 'max_replicas': 8},
        'evening': {'start': '18:00', 'end': '00:00', 'min_replicas': 2, 'max_replicas': 6}
    }
    
    # Configuración de rollback automático
    ROLLBACK_ENABLED = bool(os.getenv('ROLLBACK_ENABLED', True))
    ROLLBACK_THRESHOLD_CPU = int(os.getenv('ROLLBACK_THRESHOLD_CPU', 85))  # %
    ROLLBACK_CHECK_INTERVAL = int(os.getenv('ROLLBACK_CHECK_INTERVAL', 300))  # segundos
