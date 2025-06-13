import os
import time
from datetime import datetime, time as dt_time
import logging
from kubernetes.client import CustomObjectsApi
from config import Config

class HPAScheduler:
    """
    Controlador para ajustar automáticamente los parámetros de HPA según horarios configurados
    """
    def __init__(self, k8s_client):
        self.config = Config()
        self.k8s_client = k8s_client
        self.current_window = None
        self.last_rollback_check = 0
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def get_current_time_window(self) -> dict:
        """Determina la ventana horaria actual"""
        now = datetime.now().time()
        
        for window_name, window in self.config.TIME_WINDOWS.items():
            start = datetime.strptime(window['start'], '%H:%M').time()
            end = datetime.strptime(window['end'], '%H:%M').time()
            
            if start <= now < end or \
               (window['start'] > window['end'] and (now >= start or now < end)):
                return window_name, window
        
        return None, None
    
    def adjust_hpa(self, namespace: str, hpa_name: str):
        """Ajusta el HPA según la ventana horaria actual"""
        window_name, window = self.get_current_time_window()
        
        if not window_name:
            self.logger.error("No se pudo determinar la ventana horaria actual")
            return False
            
        if window_name == self.current_window:
            return False  # No hay cambios necesarios
            
        try:
            if os.getenv('ENVIRONMENT') == 'local':
                # Modo simulación - solo logging
                self.logger.info(
                    f"[SIMULACIÓN] Ajuste HPA {hpa_name} para {window_name}: "
                    f"min={window['min_replicas']}, max={window['max_replicas']}"
                )
            else:
                # Modo producción - ajuste real
                body = {
                    "spec": {
                        "minReplicas": window['min_replicas'],
                        "maxReplicas": window['max_replicas']
                    }
                }
                
                self.k8s_client['custom'].patch_namespaced_custom_object(
                    group="autoscaling",
                    version="v2",
                    namespace=namespace,
                    plural="horizontalpodautoscalers",
                    name=hpa_name,
                    body=body
                )
            
            self.current_window = window_name
            return True
            
        except Exception as e:
            self.logger.error(f"Error ajustando HPA: {str(e)}")
            return False
    
    def check_rollback_conditions(self, namespace: str, hpa_name: str) -> bool:
        """Verifica si se deben revertir los cambios por alta carga"""
        if not self.config.ROLLBACK_ENABLED:
            return False
            
        now = time.time()
        if now - self.last_rollback_check < self.config.ROLLBACK_CHECK_INTERVAL:
            return False
            
        self.last_rollback_check = now
        
        try:
            # Obtener métricas de CPU
            cpu_usage = self.k8s_client['custom'].list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods"
            )
            
            total_cpu = 0
            count = 0
            
            for pod in cpu_usage.get('items', []):
                for container in pod.get('containers', []):
                    cpu = container.get('usage', {}).get('cpu', '0m')
                    total_cpu += int(cpu.rstrip('m'))
                    count += 1
            
            avg_cpu = total_cpu / max(1, count)
            
            if avg_cpu > self.config.ROLLBACK_THRESHOLD_CPU:
                self.logger.warning(
                    f"CPU promedio {avg_cpu:.1f}m supera umbral de rollback. "
                    f"Restaurando configuración máxima"
                )
                
                # Restaurar límites máximos
                body = {
                    "spec": {"maxReplicas": max(w['max_replicas'] for w in self.config.TIME_WINDOWS.values())}
                }
                
                self.k8s_client['custom'].patch_namespaced_custom_object(
                    group="autoscaling",
                    version="v2",
                    namespace=namespace,
                    plural="horizontalpodautoscalers",
                    name=hpa_name,
                    body=body
                )
                return True
                
        except Exception as e:
            self.logger.error(f"Error verificando rollback: {str(e)}")
            
        return False
    
    def run_scheduled_adjustment(self, namespace: str, hpa_name: str, interval: int = 60):
        """Ejecuta ajustes continuos cada intervalo especificado"""
        self.logger.info("Iniciando scheduler de ajustes horarios para HPA")
        
        while True:
            try:
                self.adjust_hpa(namespace, hpa_name)
                self.check_rollback_conditions(namespace, hpa_name)
                time.sleep(interval)
                
            except KeyboardInterrupt:
                self.logger.info("Deteniendo scheduler de ajustes horarios")
                break
            except Exception as e:
                self.logger.error(f"Error en scheduler: {str(e)}")
                time.sleep(interval)


if __name__ == "__main__":
    from aks_integration import AKSManager
    
    manager = AKSManager()
    scheduler = HPAScheduler(manager.k8s_client)
    
    # Ejemplo: Ajustar HPA 'my-app-hpa' en namespace 'default'
    scheduler.run_scheduled_adjustment(
        namespace="default",
        hpa_name="my-app-hpa",
        interval=300  # 5 minutos
    )
