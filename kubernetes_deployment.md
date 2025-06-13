# Requisitos para despliegue en Minikube y AKS

## 1. Configuración de Kubernetes

### Para Minikube:
- Instalar Minikube y kubectl
- Configurar contextos de kubectl
- Crear namespaces necesarios

### Para AKS:
- Configurar autenticación con Azure CLI (`az login`)
- Configurar kubectl para conectarse al cluster AKS

## 2. Cambios en el código

### Archivos a modificar:

1. `config.py`:
   - Añadir configuración para:
     - Nombres de servicios Kubernetes
     - Configuración de conexión al cluster
     - Variables específicas de Minikube/AKS

2. `aks_integration.py`:
   - Implementar lógica específica para AKS:
     - Autenticación con Azure
     - Manejo de recursos específicos de AKS

3. `requirements.txt`:
   - Añadir dependencias:
     - `azure-identity`
     - `azure-mgmt-containerservice`
     - `kubernetes`

## 3. Despliegue

### Archivos YAML necesarios:
- `deployment.yaml` (plantilla base)
- `service.yaml`
- `hpa.yaml` (para autoescalado)
- `ingress.yaml` (solo para AKS)

## 4. Pasos adicionales

- Configurar secrets para variables sensibles
- Configurar RBAC adecuado
- Implementar health checks
- Configurar logging y monitoring

## 5. Comandos útiles

```bash
# Minikube
minikube start
kubectl apply -f deployment.yaml

# AKS
az aks get-credentials --name NOMBRE_CLUSTER --resource-group GRUPO_RECURSOS
kubectl apply -f deployment.yaml
```
