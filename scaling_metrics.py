from prometheus_client import start_http_server, Gauge, REGISTRY
from config import Config
import logging
import random
import time
import os
import requests

class ScalingMetrics:
    """
    Clase mejorada con:
    - Cooldown entre escalados
    - Ventana de estabilización
    - Protección contra métricas erráticas
    """
    
    def __init__(self):
        self.config = Config()
        self.last_scale_time = 0
        self.metric_history = []
        
        # Limpiar métricas existentes
        for metric in ['service_cpu_usage', 'service_memory_usage', 'service_pod_count', 'service_response_time']:
            if metric in REGISTRY._names_to_collectors:
                REGISTRY.unregister(REGISTRY._names_to_collectors[metric])
        
        # Métricas Prometheus
        self.cpu_usage = Gauge('service_cpu_usage', 'Uso de CPU del servicio en porcentaje', registry=REGISTRY)
        self.memory_usage = Gauge('service_memory_usage', 'Uso de memoria del servicio en porcentaje', registry=REGISTRY)
        self.pod_count = Gauge('service_pod_count', 'Número de pods en ejecución', registry=REGISTRY)
        self.response_time = Gauge('service_response_time', 'Tiempo medio de respuesta en segundos', registry=REGISTRY)
        
        start_http_server(8000)
    
    def update_metrics(self, cpu_usage: float, memory_usage: float, current_pods: int, response_time: float = None):
        """Registra métricas incluyendo tiempo de respuesta"""
        now = time.time()
        
        # Si no se provee response_time, calcular uno basado en carga
        if response_time is None:
            response_time = self._calculate_simulated_response_time(cpu_usage, memory_usage, current_pods)
            
        self.metric_history.append({
            'timestamp': now,
            'cpu': cpu_usage,
            'memory': memory_usage,
            'response_time': response_time
        })
        
        # Mantener solo métricas recientes
        self.metric_history = [m for m in self.metric_history 
                             if m['timestamp'] > now - self.config.STABILIZATION_WINDOW]
        
        self.cpu_usage.set(cpu_usage)
        self.memory_usage.set(memory_usage)
        self.pod_count.set(current_pods)
        self.response_time.set(response_time)
    
    def _calculate_simulated_response_time(self, cpu: float, memory: float, pods: int) -> float:
        """Simula el tiempo de respuesta basado en carga y pods"""
        base_time = 0.2  # Tiempo base en segundos
        
        # Impacto de la carga de CPU (cuadrático para simular degradación)
        cpu_factor = (cpu / 100) ** 2 
        
        # Impacto de la carga de memoria (lineal)
        mem_factor = (memory / 100)
        
        # Factor de escalado (mejora con más pods)
        scaling_factor = 1.0 / max(1, pods ** 0.7)
        
        return base_time + (cpu_factor * mem_factor * scaling_factor * 3.0)
    
    def _metrics_are_stable(self) -> bool:
        """Determina si las métricas son estables en la ventana de tiempo"""
        if len(self.metric_history) < 3:
            return False
            
        avg_cpu = sum(m['cpu'] for m in self.metric_history) / len(self.metric_history)
        avg_memory = sum(m['memory'] for m in self.metric_history) / len(self.metric_history)
        
        # Verificar que no haya fluctuaciones mayores al 15%
        for m in self.metric_history:
            if (abs(m['cpu'] - avg_cpu) > 15 or 
                abs(m['memory'] - avg_memory) > 15):
                return False
        return True
    
    def should_scale_up(self) -> bool:
        """
        Determina si se debe escalar considerando tiempo de respuesta
        Prioriza escalar si el tiempo de respuesta supera el máximo permitido
        """
        now = time.time()
        
        # Verificar cooldown
        if now - self.last_scale_time < self.config.MIN_CHANGE_PERIOD:
            logging.info("[COOLDOWN] En periodo de enfriamiento. No escalar")
            return False
            
        if not self.metric_history:
            return False
            
        # Calcular promedios
        avg_cpu = sum(m['cpu'] for m in self.metric_history) / len(self.metric_history)
        avg_memory = sum(m['memory'] for m in self.metric_history) / len(self.metric_history)
        avg_response = sum(m['response_time'] for m in self.metric_history) / len(self.metric_history)
        
        logging.info(f"[CRITERIO] Tiempo Respuesta: {avg_response:.3f}s (Umbral: {self.config.RESPONSE_TIME_THRESHOLD}s)")
        
        # Prioridad 1: Tiempo de respuesta crítico
        if avg_response > self.config.MAX_RESPONSE_TIME:
            self.last_scale_time = now
            logging.info("[ESCALADO URGENTE] Tiempo de respuesta supera máximo permitido")
            return True
            
        # Prioridad 2: Tiempo de respuesta cercano al umbral
        if avg_response > self.config.RESPONSE_TIME_THRESHOLD:
            self.last_scale_time = now
            logging.info("[ESCALADO] Tiempo de respuesta supera umbral óptimo")
            return True
            
        # Prioridad 3: Umbrales tradicionales de recursos
        cpu_ok = avg_cpu > self.config.CPU_SCALING_THRESHOLD
        mem_ok = avg_memory > self.config.MEMORY_SCALING_THRESHOLD
        
        if cpu_ok or mem_ok:
            self.last_scale_time = now
            logging.info("[ESCALADO] Umbral de recursos superado")
            return True
            
        logging.info("[NO ESCALAR] Todas las métricas dentro de rangos aceptables")
        return False
    
    def get_prometheus_metrics(self, query: str) -> float:
        """
        Obtiene métricas reales desde Prometheus en producción
        Ejemplo queries:
        - 'sum(rate(container_cpu_usage_seconds_total{namespace="default"}[1m])) * 100'
        - 'sum(container_memory_working_set_bytes{namespace="default"}) / sum(kube_pod_container_resource_limits{resource="memory",namespace="default"}) * 100'
        - 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))'
        """
        if os.getenv('ENVIRONMENT') == 'local':
            # En local usamos métricas simuladas
            return self._get_simulated_metric(query)
            
        try:
            prometheus_url = f"{self.config.PROMETHEUS_URL}/api/v1/query"
            params = {'query': query}
            
            # Autenticación con bearer token
            headers = {}
            if 'PROMETHEUS_TOKEN' in os.environ:
                headers['Authorization'] = f'Bearer {os.getenv("PROMETHEUS_TOKEN")}'
            
            response = requests.get(
                prometheus_url,
                params=params,
                headers=headers,
                verify=False  # Solo para desarrollo, en producción usar certificados
            )
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'success' and data['data']['result']:
                return float(data['data']['result'][0]['value'][1])
            
            return 0.0
            
        except Exception as e:
            logging.error(f"Error obteniendo métricas de Prometheus: {str(e)}")
            return 0.0
    
    def _get_simulated_metric(self, query: str) -> float:
        """Simula métricas Prometheus para entorno local"""
        if 'cpu' in query.lower():
            return self.cpu_usage._value.get()
        elif 'memory' in query.lower():
            return self.memory_usage._value.get()
        elif 'response_time' in query.lower():
            return self.response_time._value.get()
        return 0.0
