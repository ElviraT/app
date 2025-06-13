# Cluster Rebalancer for AKS

Aplicación para optimización de costos en AKS mediante:
- Movimiento estratégico a nodos Spot
- Rebalanceo inteligente de cargas de trabajo

## Requisitos
- Python 3.9+
- Kubernetes CLI configurado
- Acceso a cluster AKS

## Instalación
```bash
pip install -r requirements.txt
```

## Uso
```bash
python main.py
```

## Configuración
Crear archivo `.env` con:
```
KUBECONFIG=path/to/kubeconfig
```
