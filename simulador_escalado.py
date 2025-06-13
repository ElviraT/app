from aks_integration import AKSManager
import logging
import random
import time
import os

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimuladorEscalado:
    """
    Simulador mejorado con:
    - Fases de carga bien definidas
    - Variación más realista de métricas
    - Visualización de criterios de escalado
    """
    def __init__(self):
        # Forzar modo local para simulaciones
        os.environ['ENVIRONMENT'] = 'local'
        self.aks_manager = AKSManager()
        self.current_pods = 2  # Valor inicial
        
        # Iniciar scheduler de HPA en modo simulación
        self.aks_manager.start_hpa_scheduler(
            namespace='default', 
            hpa_name='simulated-hpa'
        )
        
    def simular_carga(self, duracion_minutos=10):
        """Simula 3 fases de carga con monitoreo de tiempo de respuesta"""
        logger.info(f"=== INICIANDO SIMULACIÓN ===\n"
                   f"Configuración:\n"
                   f"- CPU Threshold: {self.aks_manager.scaling_metrics.config.CPU_SCALING_THRESHOLD}%\n"
                   f"- Mem Threshold: {self.aks_manager.scaling_metrics.config.MEMORY_SCALING_THRESHOLD}%\n"
                   f"- Respuesta Max: {self.aks_manager.scaling_metrics.config.MAX_RESPONSE_TIME}s\n"
                   f"- Respuesta Óptima: {self.aks_manager.scaling_metrics.config.RESPONSE_TIME_THRESHOLD}s")
        
        for i in range(duracion_minutos * 6):  # Iteraciones cada 10 segundos
            # Determinar fase actual
            if i < 10:  # Fase 1: Carga baja
                cpu = random.uniform(25, 45)
                mem = random.uniform(30, 50)
                fase = "BAJA"
            elif 10 <= i < 20:  # Fase 2: Carga media
                cpu = random.uniform(50, 85)
                mem = random.uniform(60, 90)
                fase = "MEDIA"
            else:  # Fase 3: Carga alta
                cpu = random.uniform(70, 95)
                mem = random.uniform(75, 95)
                fase = "ALTA"
            
            # Actualizar métricas (el response_time se calcula automáticamente)
            self.aks_manager.scaling_metrics.update_metrics(cpu, mem, self.current_pods)
            
            # Obtener métricas actuales para logging
            current_metrics = self.aks_manager.scaling_metrics.metric_history[-1]
            
            logger.info(f"\n=== Fase {fase} - Iteración {i+1} ===\n"
                       f"- CPU: {cpu:.1f}%\n"
                       f"- Memoria: {mem:.1f}%\n"
                       f"- Pods: {self.current_pods}\n"
                       f"- Tiempo Respuesta: {current_metrics['response_time']:.3f}s")
            
            # Tomar decisión de escalado
            if self.aks_manager.scaling_metrics.should_scale_up() and self.current_pods < 10:
                self.current_pods += 1
                logger.info(f"== DECISIÓN: Escalar a {self.current_pods} pods ==")
            elif cpu < 50 and mem < 60 and self.current_pods > 1:
                self.current_pods -= 1
                logger.info(f"== DECISIÓN: Reducir a {self.current_pods} pods ==")
            
            time.sleep(3)
        
        logger.info("=== SIMULACIÓN COMPLETADA ===")

if __name__ == "__main__":
    simulador = SimuladorEscalado()
    simulador.simular_carga(duracion_minutos=5)
