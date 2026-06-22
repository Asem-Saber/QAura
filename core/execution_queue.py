from typing import List, Dict, Optional
from core.state import GeneratedTest, TestPlan

class DynamicExecutionQueue:
    """
    Manages the stateful, dynamically ranked test queue for the Execution Agent.
    Prioritizes based on risk levels and test layers, and reprioritizes dynamically.
    """
    def __init__(self, test_plan: TestPlan, compiled_tests: List[GeneratedTest]):
        self.test_plan = test_plan
        self.queue: List[Dict] = []
        self._initialize_queue(compiled_tests)
        
    def _initialize_queue(self, tests: List[GeneratedTest]):
        # Map component risk to priority weight
        risk_weights = {'High': 3, 'Medium': 2, 'Low': 1}
        
        for test in tests:
            # Find the component in the test plan to get its risk level
            component = next((c for c in self.test_plan.components if c.name == test.target_component), None)
            risk_level = component.risk_level if component else 'Medium'
            priority = risk_weights.get(risk_level, 1)
            
            # Unit tests generally run before E2E tests, add a small weight based on layer
            layer_weight = {'unit': 3, 'integration': 2, 'e2e': 1}.get(test.test_type, 1)
            
            total_priority = (priority * 10) + layer_weight
            
            self.queue.append({
                'test': test,
                'priority': total_priority,
                'status': 'pending'
            })
            
        self._sort_queue()
        
    def _sort_queue(self):
        # Sort descending by priority
        self.queue.sort(key=lambda x: x['priority'], reverse=True)
        
    def get_next_test(self) -> Optional[GeneratedTest]:
        """Pops the highest priority pending test."""
        for item in self.queue:
            if item['status'] == 'pending':
                item['status'] = 'running'
                return item['test']
        return None
        
    def mark_completed(self, test: GeneratedTest, success: bool):
        for item in self.queue:
            if item['test'] == test:
                item['status'] = 'passed' if success else 'failed'
                break
        if not success:
            self.reprioritize_on_failure(test.target_component)
        
    def reprioritize_on_failure(self, failed_component: str):
        """
        Deprioritize tests dependent on the failed component.
        For example, deprioritize e2e tests for the same component if unit fails.
        """
        for item in self.queue:
            if item['status'] == 'pending':
                if item['test'].target_component == failed_component and item['test'].test_type in ['integration', 'e2e']:
                    # Halve the priority to delay its execution, simulating dependency awareness
                    item['priority'] = max(0, item['priority'] - 20)
        self._sort_queue()
