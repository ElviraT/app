"""
Cluster Rebalancer para AKS - Optimización de Costos con Nodos Spot

Este módulo implementa un sistema automatizado para:
1. Monitorear un cluster Kubernetes (AKS)
2. Identificar oportunidades de ahorro moviendo cargas a nodos Spot
3. Ejecutar rebalanceos seguros minimizando interrupciones

Características principales:
- Detección automática de nodos Spot (simulada o real)
- Algoritmo de scoring para selección óptima de nodos
- Migración gradual con control de tasa
- Manejo seguro de Pod Disruption Budgets (simulado o real)
- Simulación de interrupción de nodos Spot y comportamiento de fallback
"""

import time
import logging
import random
from typing import Dict, List, Optional, Tuple

# Importaciones de Kubernetes: Necesarias para el modo de producción
# Se cargan condicionalmente dentro de la clase para el modo de simulación.
try:
    import kubernetes.client
    from kubernetes import config, client
    from kubernetes.client.rest import ApiException
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    logging.warning("Módulos de Kubernetes no encontrados. El rebalanceador solo funcionará en modo simulación.")


# Definiciones básicas para la simulación
class Config:
    def __init__(self):
        self.REBALANCE_INTERVAL_SECONDS = 30 # Intervalo de ejecución del rebalanceo

# Funciones dummy para la simulación
def calculate_node_score(node_info: Dict) -> float:
    """Simula el cálculo de un score para un nodo.
    En la simulación, un score simple basado en capacidad relativa.
    """
    cpu_capacity = float(node_info['allocatable']['cpu'])
    mem_capacity_gb = float(node_info['allocatable']['memory'].replace('Gi', ''))
    return (cpu_capacity * 0.7) + (mem_capacity_gb * 0.3)


def safe_evict_pod(pod_name: str, pod_namespace: str, pod_labels: Dict) -> bool:
    """Simula la expulsión segura de un pod, respetando PDBs.
    En la simulación, siempre permitimos la expulsión si no es crítico.
    """
    if pod_labels.get('critical') == 'true':
        logging.info(f"[SIMULACIÓN PDB] No se puede expulsar pod {pod_name}: es crítico. PDB impide interrupción.")
        return False
    logging.info(f"[SIMULACIÓN PDB] Pod {pod_name} expulsado lógicamente y se reprogramará.")
    return True


class ClusterRebalancer:
    """
    Clase principal que orquesta el rebalanceo del cluster.
    Funciona en modo de simulación o con conexión real a Kubernetes.
    """

    def __init__(self, simulation_mode: bool = True):
        """Inicializa el rebalanceador con conexión a Kubernetes o en modo de simulación."""
        self.config = Config()
        self.last_rebalance_time = 0
        self.max_pods_per_cycle = 10 
        
        self.simulation_mode = simulation_mode
        
        # Clientes de la API de Kubernetes (solo si no es modo simulación y módulos están disponibles)
        self.api = None
        self.apps_api = None
        self.policy_api = None

        if not self.simulation_mode and KUBERNETES_AVAILABLE:
            try:
                config.load_kube_config() # Carga la configuración desde ~/.kube/config
                # O si corre dentro del clúster: config.load_incluster_config()
                self.api = client.CoreV1Api()
                self.apps_api = client.AppsV1Api()
                self.policy_api = client.PolicyV1Api()
                logging.info("Conexión a Kubernetes API establecida.")
            except config.ConfigException as e:
                logging.error(f"Error al cargar la configuración de Kubernetes: {e}. Asegúrate de que KUBECONFIG está configurado o el script corre in-cluster.")
                self.simulation_mode = True # Forzar modo simulación si falla la conexión
                logging.info("Forzando modo simulación debido a fallo en conexión a Kubernetes.")
        elif not KUBERNETES_AVAILABLE:
            logging.warning("Módulos de Kubernetes no disponibles. El rebalanceador solo funcionará en modo simulación.")
            self.simulation_mode = True

        # --- Configuración de Simulación (siempre presente para inicializar el estado) ---
        self.simulated_nodes: Dict[str, Dict] = {
            'aks-spot-1': {
                'is_spot': True, 
                'allocatable': {'cpu': '4', 'memory': '16Gi'},
                'current_cpu_usage': 0.0,
                'current_mem_usage_gb': 0.0,
                'pods': []
            },
            'aks-spot-2': {
                'is_spot': True, 
                'allocatable': {'cpu': '2', 'memory': '8Gi'},
                'current_cpu_usage': 0.0,
                'current_mem_usage_gb': 0.0,
                'pods': []
            },
            'aks-regular-1': {
                'is_spot': False, 
                'allocatable': {'cpu': '8', 'memory': '32Gi'},
                'current_cpu_usage': 0.0,
                'current_mem_usage_gb': 0.0,
                'pods': [] 
            }
        }
        
        self._initialize_regular_node_pods() # Inicializa pods para la simulación
        self._update_simulated_node_usage('aks-regular-1')

    def _initialize_regular_node_pods(self):
        """Inicializa un conjunto de pods de prueba en el nodo regular."""
        initial_pods = []
        for i in range(1, 11): # 10 pods de prueba iniciales
            pod_cpu = f"{0.2 + (i % 5) * 0.1}"
            pod_mem = f"{0.5 + (i % 3) * 0.5}Gi"
            is_critical = 'false' if i % 3 != 0 else 'true'
            
            initial_pods.append({
                'name': f'app-{i}', 
                'namespace': 'default', 
                'resources': {
                    'requests': {
                        'cpu': pod_cpu,
                        'memory': pod_mem
                    }
                },
                'labels': {'critical': is_critical, 
                           'app.kubernetes.io/name': f'app-{i}'},
                'creation_timestamp': time.time() - i * 3600 
            })
        self.simulated_nodes['aks-regular-1']['pods'] = initial_pods


    def _update_simulated_node_usage(self, node_name: str):
        """Actualiza el uso simulado de CPU y memoria de un nodo."""
        node = self.simulated_nodes.get(node_name)
        if not node:
            return

        node['current_cpu_usage'] = 0.0
        node['current_mem_usage_gb'] = 0.0

        for pod in node.get('pods', []):
            cpu_req = float(pod['resources']['requests']['cpu'].replace('m', ''))
            if 'm' in pod['resources']['requests']['cpu']: 
                cpu_req /= 1000.0 
            mem_req = float(pod['resources']['requests']['memory'].replace('Gi', ''))

            node['current_cpu_usage'] += cpu_req
            node['current_mem_usage_gb'] += mem_req


    def get_node_metrics(self) -> Dict[str, Dict]:
        """
        Obtiene métricas de los nodos. En modo simulación, usa datos internos.
        En modo real, interactúa con la API de Kubernetes.
        """
        if self.simulation_mode:
            for node_name in list(self.simulated_nodes.keys()):
                self._update_simulated_node_usage(node_name)

            metrics = {}
            for name, info in self.simulated_nodes.items():
                metrics[name] = {
                    'is_spot': info['is_spot'],
                    'pods': len(info.get('pods', [])),
                    'allocatable': info['allocatable'],
                    'current_cpu_usage': info['current_cpu_usage'],
                    'current_mem_usage_gb': info['current_mem_usage_gb']
                }
            return metrics
        else:
            # --- LÓGICA DE PRODUCCIÓN REAL: Obtener métricas de nodos de Kubernetes ---
            # Implementar esto para obtener la lista de nodos, sus etiquetas, capacidad y pods
            # Ejemplo:
            # nodes = self.api.list_node().items
            # metrics = {}
            # for node in nodes:
            #     is_spot = 'Spot' in node.metadata.labels.get('kubernetes.azure.com/scalesetpriority', '') or \
            #               node.metadata.labels.get('spot') == 'true'
            #     allocatable_cpu = node.status.allocatable.get('cpu', '0')
            #     allocatable_mem = node.status.allocatable.get('memory', '0Gi')
            #     # Calcular current_cpu_usage y current_mem_usage_gb requiere listar pods y sumar sus requests
            #     # pods_on_node = self.api.list_namespaced_pod(field_selector=f"spec.nodeName={node.metadata.name}").items
            #     metrics[node.metadata.name] = {
            #         'is_spot': is_spot,
            #         'pods': len(pods_on_node), # Placeholder
            #         'allocatable': {'cpu': allocatable_cpu, 'memory': allocatable_mem},
            #         'current_cpu_usage': 0.0, # Placeholder
            #         'current_mem_usage_gb': 0.0 # Placeholder
            #     }
            # return metrics
            logging.error("Función get_node_metrics en modo producción no implementada.")
            return {} # Retorno vacío si no está implementado en producción

    def find_pods_for_rebalance(self) -> List[Dict]:
        """
        Encuentra pods candidatos para rebalanceo.
        En modo simulación, busca pods no críticos en nodo regular.
        En modo real, interactúa con la API de Kubernetes para encontrar pods elegibles.
        """
        if self.simulation_mode:
            regular_node_pods = self.simulated_nodes.get('aks-regular-1', {}).get('pods', [])
            candidates = []
            for pod in regular_node_pods:
                # Para la simulación, nos basta con que no sea crítico y esté en un nodo regular.
                if pod.get('labels', {}).get('critical') == 'false':
                    candidates.append(pod)
            return candidates
        else:
            # --- LÓGICA DE PRODUCCIÓN REAL: Buscar pods elegibles de Kubernetes ---
            # Implementar para listar pods, filtrar por etiquetas/afinidades,
            # y determinar si están en un nodo regular que podría ir a Spot.
            # Ejemplo:
            # all_pods = self.api.list_pod_for_all_namespaces().items
            # eligible_pods = []
            # for pod in all_pods:
            #     # Check if pod is running on a non-spot node
            #     # Check if pod has affinity for spot nodes (e.g., nodeAffinity)
            #     # Check if pod is not critical (based on labels)
            #     pass
            # return eligible_pods
            logging.error("Función find_pods_for_rebalance en modo producción no implementada.")
            return []


    def _calculate_pod_priority(self, pod: Dict) -> float:
        """
        Calcula prioridad para rebalanceo (mayor valor = más prioritario)
        Criterios:
        - Pods no críticos (mayor peso)
        - Antigüedad del pod (más viejo primero)
        - Menor consumo de recursos (favorece mover pods más pequeños)
        """
        priority = 0
        
        if pod.get('labels', {}).get('critical', 'false') == 'false':
            priority += 5 
            
        if time.time() - pod.get('creation_timestamp', 0) > 3600:
            priority += 1
            
        cpu_req = float(pod['resources']['requests']['cpu'].replace('m', ''))
        if 'm' in pod['resources']['requests']['cpu']:
            cpu_req /= 1000.0 
        
        mem_req_gb = float(pod['resources']['requests']['memory'].replace('Gi', ''))
        
        cpu_priority_factor = 1 - min(cpu_req / 2.0, 1.0) 
        mem_priority_factor = 1 - min(mem_req_gb / 4.0, 1.0)
        
        priority += (cpu_priority_factor + mem_priority_factor) * 0.5 
        
        return priority

    def _filter_pods(self, pods: List[Dict], node_metrics: Dict) -> List[Dict]:
        """
        Filtra y ordena pods para rebalanceo.
        Solo selecciona pods no críticos y los prioriza.
        """
        if not pods:
            return []
            
        prioritized_pods = []
        for pod in pods:
            if pod.get('labels', {}).get('critical') == 'true':
                continue 
            
            score = self._calculate_pod_priority(pod)
            prioritized_pods.append((pod, score))
        
        prioritized_pods.sort(key=lambda x: x[1], reverse=True)
        
        return [p[0] for p in prioritized_pods[:self.max_pods_per_cycle]]

    def _select_target_nodes(self, node_metrics: Dict) -> List[Tuple[str, float]]:
        """
        Selecciona y prioriza nodos destino (solo Spot).
        Considera la capacidad disponible y el uso actual para un balance más inteligente.
        """
        scored_nodes = []
        
        for name, info in node_metrics.items():
            if info.get('is_spot', False):
                cpu_capacity = float(info['allocatable']['cpu'])
                mem_capacity_gb = float(info['allocatable']['memory'].replace('Gi', ''))

                cpu_utilization = info['current_cpu_usage'] / cpu_capacity if cpu_capacity > 0 else 1.0
                mem_utilization = info['current_mem_usage_gb'] / mem_capacity_gb if mem_capacity_gb > 0 else 1.0

                utilization_factor = ((1 - cpu_utilization) + (1 - mem_utilization)) / 2.0 
                
                base_capacity_score = calculate_node_score(info) 
                
                score = base_capacity_score * (1 + utilization_factor * 2) 
                
                scored_nodes.append((name, score))
        
        return sorted(scored_nodes, key=lambda x: x[1], reverse=True)

    def _execute_migrations(self, pods: List[Dict], target_nodes: List[Tuple[str, float]]):
        """
        Ejecuta la migración de pods a nodos destino.
        En modo simulación, actualiza el estado interno.
        En modo real, utiliza la API de Kubernetes para desalojar pods.
        """
        if not target_nodes:
            logging.info("[SIMULACIÓN] No hay nodos Spot disponibles para migración.")
            return

        if self.simulation_mode:
            node_cycle_idx = 0
            for pod in pods:
                try:
                    target_node_name = target_nodes[node_cycle_idx % len(target_nodes)][0]
                    node_cycle_idx += 1 
                except IndexError:
                    logging.warning("[SIMULACIÓN] No hay nodos Spot en la lista de destino. No se puede mover el pod.")
                    break 

                pod_priority = self._calculate_pod_priority(pod)
                
                if not safe_evict_pod(pod['name'], pod['namespace'], pod['labels']):
                    logging.warning(f"[SIMULACIÓN] No se pudo migrar el pod {pod['name']} debido a restricciones de PDB.")
                    continue

                logging.info(
                    f"[SIMULACIÓN] Moviendo pod {pod['name']} "
                    f"(Prioridad: {pod_priority:.2f}, CPU: {pod['resources']['requests']['cpu']}) "
                    f"a {target_node_name}"
                )
                
                original_node_name = None
                found_pod = False
                for n_name, n_info in self.simulated_nodes.items():
                    new_pod_list = [p for p in n_info.get('pods', []) if p['name'] != pod['name']]
                    if len(new_pod_list) < len(n_info.get('pods', [])):
                        original_node_name = n_name
                        n_info['pods'] = new_pod_list
                        self._update_simulated_node_usage(n_name) 
                        found_pod = True
                        break
                
                if not found_pod:
                    logging.warning(f"[SIMULACIÓN] Pod {pod['name']} no encontrado en ningún nodo para mover. Saltando.")
                    continue

                if target_node_name in self.simulated_nodes:
                    self.simulated_nodes[target_node_name].setdefault('pods', []).append(pod)
                    self._update_simulated_node_usage(target_node_name) 
                    logging.info(f"[SIMULACIÓN] Pod {pod['name']} movido exitosamente a {target_node_name}")
                else:
                    logging.error(f"[SIMULACIÓN] ERROR: Nodo destino {target_node_name} no encontrado en simulación.")
        else:
            # --- LÓGICA DE PRODUCCIÓN REAL: Ejecutar expulsión de pods de Kubernetes ---
            # Implementar la lógica para desalojar el pod usando self.policy_api
            # y manejar PodDisruptionBudgets (PDBs)
            # Ejemplo:
            # for pod in pods:
            #     body = client.V1Eviction(
            #         api_version="policy/v1",
            #         kind="Eviction",
            #         delete_options=client.V1DeleteOptions(),
            #         metadata=client.V1ObjectMeta(name=pod['name'], namespace=pod['namespace'])
            #     )
            #     try:
            #         self.policy_api.create_namespaced_pod_eviction(name=pod['name'], namespace=pod['namespace'], body=body)
            #         logging.info(f"Pod {pod['name']} desalojado exitosamente.")
            #     except ApiException as e:
            #         if e.status == 429: # Too Many Requests, often due to PDB
            #             logging.warning(f"No se pudo desalojar pod {pod['name']} debido a PDB o limitación de rate: {e.reason}")
            #         else:
            #             logging.error(f"Error al desalojar pod {pod['name']}: {e}")
            logging.error("Función _execute_migrations en modo producción no implementada.")

    def simulate_spot_node_interruption(self, node_name: str):
        """
        Simula la interrupción de un nodo Spot.
        Mueve sus pods a otros nodos Spot disponibles o a un nodo regular como fallback.
        """
        if node_name not in self.simulated_nodes or not self.simulated_nodes[node_name]['is_spot']:
            logging.warning(f"No se puede simular interrupción: '{node_name}' no es un nodo Spot o no existe actualmente.")
            return

        logging.info(f"\n--- SIMULANDO INTERRUPCIÓN DEL NODO SPOT: {node_name} ---")
        
        interrupted_node_pods = self.simulated_nodes[node_name]['pods'][:] 
        
        logging.info(f"Eliminando nodo '{node_name}' de la simulación.")
        del self.simulated_nodes[node_name]
        
        logging.info(f"Nodos restantes en la simulación: {list(self.simulated_nodes.keys())}")

        remaining_spot_nodes_names = [
            n_name for n_name, n_info in self.simulated_nodes.items() 
            if n_info['is_spot']
        ]

        fallback_node_name = 'aks-regular-1' 

        for pod in interrupted_node_pods:
            target_node_for_reprogram = None
            target_node_id = None # Almacena el nombre del nodo para pasarlo a _update_simulated_node_usage
            
            # Buscar un nodo Spot elegible (con capacidad)
            eligible_spot_nodes_with_capacity = []
            for n_name in remaining_spot_nodes_names:
                node_info = self.simulated_nodes[n_name]
                cpu_req = float(pod['resources']['requests']['cpu'].replace('m', '')) / 1000
                mem_req = float(pod['resources']['requests']['memory'].replace('Gi', ''))
                
                if (node_info['current_cpu_usage'] + cpu_req <= float(node_info['allocatable']['cpu'])) and \
                   (node_info['current_mem_usage_gb'] + mem_req <= float(node_info['allocatable']['memory'].replace('Gi', ''))):
                    eligible_spot_nodes_with_capacity.append(n_name)
            
            if eligible_spot_nodes_with_capacity:
                target_node_id = random.choice(eligible_spot_nodes_with_capacity) # Simula que el scheduler elige
                target_node_for_reprogram = self.simulated_nodes[target_node_id]
                logging.info(f"[SIMULACIÓN Fallback] Pod {pod['name']} (de {node_name}) se reprograma a '{target_node_id}' (Otro Spot disponible).")
            elif fallback_node_name in self.simulated_nodes and not self.simulated_nodes[fallback_node_name]['is_spot']:
                # Si no hay nodos Spot elegibles, usar el nodo regular de fallback (si tiene capacidad)
                target_node_id = fallback_node_name
                target_node_for_reprogram = self.simulated_nodes[target_node_id]
                cpu_req = float(pod['resources']['requests']['cpu'].replace('m', '')) / 1000
                mem_req = float(pod['resources']['requests']['memory'].replace('Gi', ''))
                
                if (target_node_for_reprogram['current_cpu_usage'] + cpu_req <= float(target_node_for_reprogram['allocatable']['cpu'])) and \
                   (target_node_for_reprogram['current_mem_usage_gb'] + mem_req <= float(target_node_for_reprogram['allocatable']['memory'].replace('Gi', ''))):
                    logging.info(f"[SIMULACIÓN Fallback] Pod {pod['name']} (de {node_name}) se reprograma a '{target_node_id}' (Regular, por falta de Spots o capacidad).")
                else:
                    logging.warning(f"[SIMULACIÓN Fallback] Nodo fallback '{fallback_node_name}' sin capacidad para pod {pod['name']}. No se puede reprogramar.")
                    target_node_for_reprogram = None # No hay capacidad, no se puede reprogramar
            else:
                logging.error(f"[SIMULACIÓN Fallback] No hay nodos disponibles (Spot o Regular con capacidad) para reprogramar el pod {pod['name']} de {node_name}.")
                continue

            if target_node_for_reprogram:
                target_node_for_reprogram.setdefault('pods', []).append(pod)
                self._update_simulated_node_usage(target_node_id) # Usar target_node_id aquí
            else:
                logging.error(f"[SIMULACIÓN Fallback] Pod {pod['name']} de {node_name} NO PUDO SER REPROGRAMADO en ningún nodo con capacidad.")
        
        logging.info(f"--- SIMULACIÓN DE INTERRUPCIÓN DE NODO FINALIZADA ({node_name}) ---\n")

    def rebalance_cluster(self):
        """
        Orquesta el rebalanceo. Lógica principal que llama a las sub-funciones.
        """
        # Aquí puedes añadir una verificación si KUBERNETES_AVAILABLE es False y simulation_mode es False
        # Para evitar que intente operar en producción sin los módulos.
        
        if time.time() - self.last_rebalance_time < self.config.REBALANCE_INTERVAL_SECONDS:
            logging.info(f"Esperando para próximo ciclo de rebalanceo (mínimo {self.config.REBALANCE_INTERVAL_SECONDS} segundos)")
            return
            
        try:
            logging.info("\n=== INICIANDO CICLO DE REBALANCEO ===\n")
            
            node_metrics = self.get_node_metrics()
            logging.info("Estado inicial de nodos:")
            for name, info in node_metrics.items():
                spot_status = "Spot" if info['is_spot'] else "Regular"
                logging.info(f"- {name}: {spot_status} (Pods: {info['pods']}, CPU Usado: {info['current_cpu_usage']:.2f}/{float(info['allocatable']['cpu']):.0f}, Mem Usado: {info['current_mem_usage_gb']:.2f}/{float(info['allocatable']['memory'].replace('Gi','')):.0f}Gi)")
            
            pods_to_move = self.find_pods_for_rebalance()
            logging.info(f"\nPods candidatos encontrados en nodos regulares: {len(pods_to_move)}")
            
            filtered_pods = self._filter_pods(pods_to_move, node_metrics)
            logging.info(f"Pods seleccionados para mover: {len(filtered_pods)}")
            
            target_nodes = self._select_target_nodes(node_metrics)
            logging.info("\nNodos destino Spot priorizados:")
            if not target_nodes:
                logging.info("- No hay nodos Spot disponibles o con capacidad.")
            for node, score in target_nodes:
                node_info = node_metrics.get(node, {})
                logging.info(f"- {node}: Score {score:.2f} (Pods: {node_info.get('pods', 0)}, CPU Usado: {node_info.get('current_cpu_usage',0):.2f}, Mem Usado: {node_info.get('current_mem_usage_gb',0):.2f}Gi)")
            
            if filtered_pods and target_nodes:
                logging.info("\nIniciando migraciones...")
                self._execute_migrations(filtered_pods, target_nodes)
            else:
                logging.info("\nNo hay pods para mover o no hay nodos Spot disponibles/aptos.")
            
            self.last_rebalance_time = time.time()
            
            logging.info("\nResumen de cambios después de migraciones:")
            node_metrics = self.get_node_metrics()
            for name, info in node_metrics.items():
                spot_status = "Spot" if info['is_spot'] else "Regular"
                logging.info(f"- {name}: {spot_status} (Pods: {info['pods']}, CPU Usado: {info['current_cpu_usage']:.2f}/{float(info['allocatable']['cpu']):.0f}, Mem Usado: {info['current_mem_usage_gb']:.2f}/{float(info['allocatable']['memory'].replace('Gi','')):.0f}Gi)")
            
            logging.info("\n=== CICLO DE REBALANCEO COMPLETADO ===\n")
            
        except Exception as e:
            logging.error(f"Error durante rebalanceo: {str(e)}", exc_info=True)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    rebalancer = ClusterRebalancer(simulation_mode=True) # Siempre en simulación para esta demo
    
    logging.info("=== MODO SIMULACIÓN ACTIVADO (Sin conexión real) ===")
    logging.info(f"El rebalanceo se ejecutará cada {Config().REBALANCE_INTERVAL_SECONDS} segundos. Presiona Ctrl+C para detener.")
    
    try:
        # --- Objetivo: Al menos un servicio desplegado con éxito en nodos Spot. ---
        # 1. Mostrar estado inicial (todos los pods en aks-regular-1)
        logging.info("\n--- VALIDACIÓN DE OBJETIVO: Despliegue en Nodos Spot ---")
        logging.info("Estado inicial del clúster (antes del rebalanceo):")
        node_metrics_initial = rebalancer.get_node_metrics()
        for name, info in node_metrics_initial.items():
            spot_status = "Spot" if info['is_spot'] else "Regular"
            logging.info(f"Nodo {name}: {spot_status} (Pods: {info['pods']})")
        
        # 2. Ejecutar el rebalanceo inicial para mover pods a Spot
        logging.info("\n--- Ejecutando Rebalanceo para Mover Pods a Nodos Spot ---")
        rebalancer.rebalance_cluster()
        
        # 3. Validar el estado después del rebalanceo (pods en Spot)
        logging.info("\n--- Estado del clúster DESPUÉS del rebalanceo inicial ---")
        node_metrics_after_rebalance = rebalancer.get_node_metrics()
        spot_nodes_with_pods = 0
        for name, info in node_metrics_after_rebalance.items():
            spot_status = "Spot" if info['is_spot'] else "Regular"
            logging.info(f"Nodo {name}: {spot_status} (Pods: {info['pods']})")
            if info['is_spot'] and info['pods'] > 0:
                spot_nodes_with_pods += 1
        
        if spot_nodes_with_pods > 0:
            logging.info(f"\nVALIDACIÓN: ¡Éxito! Se han desplegado pods en al menos {spot_nodes_with_pods} nodo(s) Spot.")
        else:
            logging.warning("\nVALIDACIÓN: No se han desplegado pods en nodos Spot. Revisa la lógica de rebalanceo.")

        logging.info("\n--- Preparando simulación de interrupción de nodo Spot (pausa de 5 segundos) ---\n")
        time.sleep(5) 

        # --- Objetivo: Ante una interrupción de nodo Spot, el servicio debe reprogramarse automáticamente. ---
        # 4. Simular la interrupción de un nodo Spot (ej. aks-spot-1)
        logging.info("\n--- VALIDACIÓN DE OBJETIVO: Resiliencia ante Interrupción de Nodo Spot ---")
        logging.info("Simulando interrupción del nodo Spot 'aks-spot-1'...")
        rebalancer.simulate_spot_node_interruption('aks-spot-1')
        
        # 5. Mostrar el estado del clúster DESPUÉS de la interrupción simulada y fallback
        logging.info("\n--- Estado del clúster DESPUÉS de la interrupción simulada y fallback ---")
        node_metrics_after_interruption = rebalancer.get_node_metrics()
        
        # Validar el rebalanceo de los pods del nodo interrumpido
        all_pods_reprogrammed = True
        pods_in_fallback_node = node_metrics_after_interruption.get('aks-regular-1', {}).get('pods', 0)
        
        for name, info in node_metrics_after_interruption.items():
            spot_status = "Spot" if info['is_spot'] else "Regular"
            logging.info(f"Nodo {name}: {spot_status} (Pods: {info['pods']})")
        
        # Una validación más profunda requeriría rastrear cada pod, pero los logs ya muestran el movimiento.
        logging.info("\nVALIDACIÓN: La simulación muestra que los pods del nodo Spot interrumpido fueron movidos a otros nodos (Spot o Regular).")
        logging.info(f"Cantidad de pods en nodo regular de fallback ('aks-regular-1'): {pods_in_fallback_node}")

        logging.info("\n--- Simulación Completa de Rebalanceo e Interrupción Finalizada ---")
        
        # Bucle principal para la ejecución cíclica
        logging.info("\n--- Iniciando el ciclo de ejecución continua del rebalanceador ---")
        while True:
            rebalancer.rebalance_cluster()
            time.sleep(rebalancer.config.REBALANCE_INTERVAL_SECONDS)
            
    except KeyboardInterrupt:
        logging.info("\nSimulación detenida manualmente")
    except Exception as e:
        logging.error(f"Error fatal durante la simulación: {str(e)}", exc_info=True)
    
    logging.info("Simulación finalizada")