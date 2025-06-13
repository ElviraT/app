import pytest
from unittest.mock import MagicMock
from main import ClusterRebalancer

@pytest.fixture
def mock_rebalancer():
    rebalancer = ClusterRebalancer()
    rebalancer.api = MagicMock()
    rebalancer.apps_api = MagicMock()
    return rebalancer

def test_get_node_metrics(mock_rebalancer):
    # Configurar mock
    mock_node = MagicMock()
    mock_node.metadata.name = "test-node"
    mock_node.status.allocatable = {"cpu": "2", "memory": "8Gi"}
    mock_node.status.capacity = {"cpu": "2", "memory": "8Gi"}
    mock_node.metadata.labels = {}
    mock_node.status.conditions = []
    
    mock_rebalancer.api.list_node.return_value.items = [mock_node]
    
    # Ejecutar prueba
    metrics = mock_rebalancer.get_node_metrics()
    
    # Verificar resultados
    assert "test-node" in metrics
    assert metrics["test-node"]["allocatable"]["cpu"] == "2"
