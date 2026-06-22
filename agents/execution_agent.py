import os
import uuid
import time
import concurrent.futures
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from core.state import QAuraState, ExecutionSummary, CoverageConfidence, AnomalyReport, CoverageComponentScore
from core.execution_queue import DynamicExecutionQueue
from core.tools import run_pytest_subprocess, check_environment_health, save_execution_memory, capture_execution_evidence

load_dotenv()
API_KEY = os.environ.get('GITHUB_API_KEY', '')
API_ENDPOINT = os.environ.get('GITHUB_ENDPOINT', '')
API_MODEL = os.environ.get('GITHUB_MODEL_ID', '')

llm = ChatOpenAI(
    base_url=API_ENDPOINT, 
    api_key=API_KEY, 
    model=API_MODEL, 
    temperature=0 
)

DIAGNOSTIC_PROMPT = """You are the QAura Execution Analyzer.
A test just failed. Analyze the provided test output, error message, and stack trace to classify the failure.
Classification must be exactly one of:
- INFRASTRUCTURE (e.g. timeout, connection refused, 503)
- APPLICATION_DEFECT (e.g. assertion error, logic bug, 500 error from app)
- TEST_SCRIPT_DECAY (e.g. element not found, locator drift)

Test Output:
{output}
"""

def classify_failure(output: str) -> str:
    prompt = ChatPromptTemplate.from_template(DIAGNOSTIC_PROMPT)
    chain = prompt | llm
    try:
        result = chain.invoke({"output": output})
        content = result.content.upper()
        if "INFRASTRUCTURE" in content: return "INFRASTRUCTURE"
        if "TEST_SCRIPT_DECAY" in content: return "TEST_SCRIPT_DECAY"
        return "APPLICATION_DEFECT"
    except Exception as e:
        print(f"LLM Classification Exception: {e}")
        return "AGENT_ERROR"

def process_test(test):
    """Executes a test with an intelligent retry loop for infra/decay errors."""
    retries = 2
    for attempt in range(retries + 1):
        success, output = run_pytest_subprocess(test.file_name, test.test_code)
        if success:
            return test, True, output, attempt > 0, "PASSED"
        
        classification = classify_failure(output)
        if classification not in ["INFRASTRUCTURE", "TEST_SCRIPT_DECAY"] or attempt == retries:
            return test, False, output, attempt > 0, classification

def execution_agent_node(state: QAuraState) -> dict:
    """LangGraph node for Phase 3: Execution."""
    print("--- Running Execution Agent (Phase 3) ---")
    
    if not check_environment_health("mock://database"):
        print("ENVIRONMENT HEALTH CHECK FAILED. Aborting.")
        return {
            "messages": ["Execution aborted: Environment health check failed."],
            "anomalies": [AnomalyReport(
                anomaly_id=str(uuid.uuid4()), test_id="ENV_CHECK", affected_component="all", 
                classification="INFRASTRUCTURE", root_cause_hypothesis="Environment is unreachable.", stack_trace="Pre-flight check failed."
            )]
        }
    
    test_plan = state.get("test_plan")
    
    all_tests = []
    all_tests.extend(state.get("unit_tests", []))
    all_tests.extend(state.get("integration_tests", []))
    all_tests.extend(state.get("e2e_tests", []))
    
    if not test_plan or not all_tests:
        return {"messages": ["Execution skipped: No test plan or compiled tests found."]}
        
    queue = DynamicExecutionQueue(test_plan, all_tests)
    summary = ExecutionSummary(total_tests=len(all_tests))
    anomalies = []
    
    start_time = time.time()
    
    active_futures = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        while True:
            while len(active_futures) < 3:
                test = queue.get_next_test()
                if not test:
                    break
                print(f"Executing: {test.file_name} (Parallel Worker)")
                future = executor.submit(process_test, test)
                active_futures.add(future)
                
            if not active_futures:
                break
                
            done, active_futures = concurrent.futures.wait(active_futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                test, success, output, is_flaky, classification = future.result()
                queue.mark_completed(test, success)
                
                save_execution_memory(test.file_name, 1.0, is_flaky, classification)
                
                if success:
                    summary.passed += 1
                    if is_flaky: summary.flaky_tests += 1
                else:
                    summary.failed += 1
                    evidence = capture_execution_evidence(test.file_name)
                    anomalies.append(AnomalyReport(
                        anomaly_id=str(uuid.uuid4()),
                        test_id=test.file_name,
                        affected_component=test.target_component,
                        classification=classification,
                        root_cause_hypothesis=f"Agent classified failure as {classification}.",
                        stack_trace=output[:1000],
                        evidence_urls=evidence
                    ))
            
    summary.execution_duration_ms = (time.time() - start_time) * 1000
    
    pass_rate = summary.passed / summary.total_tests if summary.total_tests > 0 else 0
    coverage = CoverageConfidence(
        overall_confidence=pass_rate,
        component_scores=[CoverageComponentScore(component="all", score=pass_rate)]
    )
    
    return {
        "execution_summary": summary,
        "coverage_confidence": coverage,
        "anomalies": anomalies,
        "messages": [f"Phase 3 complete. {summary.passed}/{summary.total_tests} passed. {summary.failed} failed."]
    }
