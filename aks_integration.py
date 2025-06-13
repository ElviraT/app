from azure.identity import DefaultAzureCredential
from azure.mgmt.containerservice import ContainerServiceClient
from config import Config
import logging
from scaling_metrics import ScalingMetrics
import os

class AKSManager:
    def __init__(self):
        self.config = Config()
        self.credential = DefaultAzureCredential()
        self.client = ContainerServiceClient(
            credential=self.credential,
            subscription_id=self.config.AZURE_SUBSCRIPTION_ID
        )
        self.scaling_metrics = ScalingMetrics()
        
        # Configurar cliente Kubernetes
        self.k8s_client = self._configure_k8s_client()
        
    def _configure_k8s_client(self):
        """
        Configura el cliente de Kubernetes con RBAC
        En local, retorna un mock sin conexión real
        """
        if os.getenv('ENVIRONMENT') == 'local':
            # Modo local - no requiere Kubernetes
            from unittest.mock import MagicMock
            return {
                'core': MagicMock(),
                'apps': MagicMock(),
                'custom': MagicMock()
            }
            
        try:
            from kubernetes.config import load_incluster_config
            from kubernetes.client import CoreV1Api, AppsV1Api, CustomObjectsApi
            load_incluster_config()
            
            return {
                'core': CoreV1Api(),
                'apps': AppsV1Api(),
                'custom': CustomObjectsApi()
            }
            
        except Exception as e:
            logging.error(f"Error configurando cliente Kubernetes: {str(e)}")
            raise
    
    def check_rbac_permissions(self) -> bool:
        """Verifica que tenemos los permisos RBAC necesarios"""
        required_permissions = [
            ('pods', 'list'),
            ('deployments', 'patch'),
            ('horizontalpodautoscalers', 'create'),
            ('scaledobjects.keda.sh', 'update')
        ]
        
        try:
            auth_api = self.k8s_client['custom'].list_cluster_custom_object(
                group="authorization.k8s.io",
                version="v1",
                plural="selfsubjectaccessreviews",
                body={"spec": {"resourceAttributes": {"namespace": "default"}}}
            )
            
            for resource, verb in required_permissions:
                if not auth_api['status']['allowed']:
                    logging.error(f"Faltan permisos RBAC: {verb} en {resource}")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error verificando permisos RBAC: {str(e)}")
            return False
    
    def get_aks_cluster(self):
        """Obtiene información del cluster AKS"""
        try:
            return self.client.managed_clusters.get(
                resource_group_name=f"MC_{self.config.AKS_CLUSTER_NAME}",
                resource_name=self.config.AKS_CLUSTER_NAME
            )
        except Exception as e:
            logging.error(f"Error al obtener cluster AKS: {e}")
            return None
    
    def scale_node_pool(self, pool_name: str, node_count: int):
        """Escala un nodo pool en AKS"""
        try:
            self.client.agent_pools.begin_create_or_update(
                resource_group_name=f"MC_{self.config.AKS_CLUSTER_NAME}",
                resource_name=self.config.AKS_CLUSTER_NAME,
                agent_pool_name=pool_name,
                parameters={
                    "count": node_count
                }
            )
            return True
        except Exception as e:
            logging.error(f"Error al escalar nodo pool {pool_name}: {e}")
            return False

    def auto_scale_node_pool(self, pool_name: str) -> bool:
        """
        Escala automáticamente el nodo pool basado en métricas de Prometheus
        """
        try:
            # Obtener métricas actuales
            cpu_usage = self.scaling_metrics.get_prometheus_metrics(
                f'avg(rate(container_cpu_usage_seconds_total{{namespace=\"{self.config.KEDA_NAMESPACE}\"}}[1m])) * 100'
            )
            memory_usage = self.scaling_metrics.get_prometheus_metrics(
                f'avg(container_memory_working_set_bytes{{namespace=\"{self.config.KEDA_NAMESPACE}\"}}) / avg(container_spec_memory_limit_bytes{{namespace=\"{self.config.KEDA_NAMESPACE}\"}}) * 100'
            )
            
            # Obtener número actual de pods
            current_pods = int(self.scaling_metrics.get_prometheus_metrics(
                f'count(kube_pod_info{{namespace=\"{self.config.KEDA_NAMESPACE}\"}})'
            ))
            
            self.scaling_metrics.update_metrics(cpu_usage, memory_usage, current_pods)
            
            # Lógica de escalado
            if self.scaling_metrics.should_scale_up() and current_pods < self.config.MAX_REPLICAS:
                new_count = min(current_pods + 1, self.config.MAX_REPLICAS)
                logging.info(f"Escalando {pool_name} de {current_pods} a {new_count} pods")
                return self.scale_node_pool(pool_name, new_count)
            elif current_pods > self.config.MIN_REPLICAS and \
                 cpu_usage < self.config.CPU_SCALING_THRESHOLD * 0.7 and \
                 memory_usage < self.config.MEMORY_SCALING_THRESHOLD * 0.7:
                new_count = max(current_pods - 1, self.config.MIN_REPLICAS)
                logging.info(f"Reduciendo {pool_name} de {current_pods} a {new_count} pods")
                return self.scale_node_pool(pool_name, new_count)
            
            return False
        except Exception as e:
            logging.error(f"Error en auto_scale_node_pool: {e}")
            return False

    def start_hpa_scheduler(self, namespace: str, hpa_name: str):
        """
        Inicia el scheduler de ajustes horarios para HPA
        Ejemplo de uso:
        manager.start_hpa_scheduler(namespace='default', hpa_name='my-app-hpa')
        """
        from hpa_scheduler import HPAScheduler
        import threading
        
        scheduler = HPAScheduler(self.k8s_client)
        
        # Ejecutar en segundo plano
        thread = threading.Thread(
            target=scheduler.run_scheduled_adjustment,
            args=(namespace, hpa_name),
            daemon=True
        )
        thread.start()
        
        logging.info(f"Iniciado scheduler de ajustes horarios para HPA {hpa_name}")
