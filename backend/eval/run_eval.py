import json
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.agent.agent import run_agent
from eval.checks import find_banned_advice, check_unsupported_numbers

def run_evaluation():
    golden_path = Path(__file__).parent / "golden_set.json"
    with open(golden_path, "r", encoding="utf-8") as f:
        tests = json.load(f)

    print("=" * 60)
    print(f"RUNNING INDIA STOCK AGENT EVALUATION ({len(tests)} test cases)")
    print("=" * 60)

    passed = 0
    failed = 0

    for t in tests:
        q_id = t["id"]
        question = t["question"]
        ticker = t.get("ticker")
        print(f"\n[TEST {q_id}] {question}")

        result = run_agent(question, ticker_hint=ticker)
        answer = result.get("answer", "")
        tool_log = result.get("tool_log", [])

        # Check 1: Banned advice phrases
        banned = find_banned_advice(answer)
        # Check 2: Unsupported numbers
        unsupported = check_unsupported_numbers(answer, tool_log)
        
        # Check 3: Must include
        missing_required = [req for req in t.get("must_include", []) if req.lower() not in answer.lower()]

        test_passed = True
        reasons = []

        if banned:
            test_passed = False
            reasons.append(f"Used banned advisory words: {banned}")
        if unsupported and len(unsupported) > 2:
            test_passed = False
            reasons.append(f"Found unsupported hallucinated numbers: {unsupported}")
        if missing_required:
            test_passed = False
            reasons.append(f"Missing required concepts: {missing_required}")

        if test_passed:
            passed += 1
            print(f"  -> ✅ PASS")
        else:
            failed += 1
            print(f"  -> ❌ FAIL: {', '.join(reasons)}")

    print("\n" + "=" * 60)
    print(f"EVALUATION SUMMARY: {passed} PASSED, {failed} FAILED (Pass Rate: {round(passed / len(tests) * 100, 1)}%)")
    print("=" * 60)

if __name__ == "__main__":
    run_evaluation()
