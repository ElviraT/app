"""
Módulo de utilidades para el Cluster Rebalancer.

Contiene funciones auxiliares para:
- Cálculo de scores de nodos
- Evicción segura de pods
- Operaciones comunes
"""

import logging
from typing import Dict, Any
from kubernetes.client import CoreV1Api
from kubernetes.client.rest import ApiException
import time
import random
from config import Config  # Importar Config para acceder a TEST_MODE


def safe_evict_pod(pod_name: str, namespace: str, max_retries: int = 3) -> bool:
    """
    Evicta un pod de manera segura con:
    - Verificación de existencia del pod
    - Chequeo de pods críticos
    - Reintentos con backoff exponencial
    - Manejo de rate limits
    
    Args:
        pod_name: Nombre del pod a evictar
        namespace: Namespace del pod
        max_retries: Intentos máximos antes de fallar
        
    Returns:
        bool: True si la evicción fue exitosa
    """
    if Config().TEST_MODE:
        logging.info(f"[SIMULACIÓN] Evictando pod {pod_name} (no se realizan cambios reales)")
        return True
    
    api = CoreV1Api()
    
    for attempt in range(max_retries):
        try:
            # 1. Verificar si el pod existe y obtener sus metadatos
            pod = api.read_namespaced_pod(pod_name, namespace)
            
            # 2. Verificar si es un pod crítico (ej. nodo master)
            if pod.metadata.labels.get('critical', 'false') == 'true':
                logging.warning(f"Pod {pod_name} es crítico, no se puede evictar")
                return False
            
            # 3. Crear objeto de evicción con política v1
            body = {
                "apiVersion": "policy/v1",
                "kind": "Eviction",
                "metadata": {
                    "name": pod_name,
                    "namespace": namespace
                }
            }
            
            # 4. Ejecutar la evicción
            api.create_namespaced_pod_eviction(
                name=pod_name,
                namespace=namespace,
                body=body
            )
            
            logging.info(f"Pod {pod_name} evictado exitosamente")
            return True
            
        except ApiException as e:
            if e.status == 429:  # Too Many Requests
                # Backoff exponencial con jitter para evitar thundering herd
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logging.warning(f"Rate limit alcanzado, reintentando en {wait_time:.1f}s")
                time.sleep(wait_time)
                continue
            
            logging.error(f"Error evictando pod {pod_name}: {e}")
            return False
    
    return False


def calculate_node_score(node_info: Dict[str, Any]) -> float:
    """
    Calcula un score para el nodo basado en:
    - Tipo de nodo (Spot/Regular)
    - Utilización de recursos
    - Disponibilidad
    
    Args:
        node_info: Diccionario con información del nodo
        
    Returns:
        float: Score entre 0.1 y 1.5 (mayor es mejor)
    """
    try:
        is_spot = node_info.get('is_spot', False)
        
        # Convertir recursos asignables a valores numéricos
        cpu_alloc = float(node_info['allocatable']['cpu'])
        mem_alloc = float(node_info['allocatable']['memory'].rstrip('Gi'))
        
        # Score base + bonus por ser spot + penalización por utilización
        score = 1.0  # Puntuación base para nodos regulares
        
        # Bonus del 50% para nodos Spot
        if is_spot:
            score += 0.5
        
        # Penalizar nodos muy utilizados (30% del score por utilización)
        utilization = (cpu_alloc + mem_alloc) / 2
        score -= utilization * 0.3
        
        # Asegurar un mínimo de 0.1 para nodos muy utilizados
        return max(0.1, score)
    except Exception as e:
        logging.error(f"Error calculando score de nodo: {e}")
        return 0.0  # Score mínimo en caso de error
