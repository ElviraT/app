#!/bin/bash
# Script seguro para despliegue en producción
# No modifica ningún archivo existente

# 1. Variables de configuración
APP_NAME="python-app"
TARGET_DIR="./prod_deploy_$(date +%Y%m%d_%H%M%S)"
K8S_DIR="k8s"

# 2. Crear directorio temporal para el despliegue
mkdir -p "$TARGET_DIR"

# 3. Copiar archivos esenciales (solo lectura)
echo "Copiando archivos para producción..."
cp -r main.py aks_integration.py config.py hpa_scheduler.py scaling_metrics.py simulador_escalado.py utils.py requirements.txt "$TARGET_DIR"

# 4. Copiar configuración Kubernetes
mkdir -p "$TARGET_DIR/$K8S_DIR"
cp -r "$K8S_DIR"/*.yaml "$TARGET_DIR/$K8S_DIR"

# 5. Instalar dependencias (en entorno virtual)
echo "\nInstalando dependencias..."
python -m venv "$TARGET_DIR/venv"
source "$TARGET_DIR/venv/bin/activate"
pip install -r "$TARGET_DIR/requirements.txt"

echo "\nDespliegue preparado en: $TARGET_DIR"
echo "Para completar el despliegue:"
echo "1. cd $TARGET_DIR"
echo "2. Revisar y ajustar configuraciones"
echo "3. Aplicar configuración Kubernetes: kubectl apply -f $K8S_DIR/"

exit 0
