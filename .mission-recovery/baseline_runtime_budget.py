def pytest_configure(config):
    from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
    from execution_subsystem.adapter_repository import ExecutionAdapterRepository
    ExecutionRuntimeRepository._network_reservation_cost = ExecutionAdapterRepository._network_reservation_cost
