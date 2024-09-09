from autogpt_server.app import run_processes
from autogpt_server.executor import ExecutionManager, ExecutionScheduler
from autogpt_server.server import AgentServer


def main():
    """
    Run all the processes required for the AutoGPT-server REST API.
    """
    run_processes(
        ExecutionManager(),
        ExecutionScheduler(),
        AgentServer(),
    )


if __name__ == "__main__":
    main()