import re
import json
from typing import Dict, Any, Optional, List
from app.llm import chat
from app.config import MAX_STEPS
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tool_specs import TOOLS
from app.agent import tools as T
from app.data_sources.companies import resolve_ticker, company_info, find_companies_in_text

REGISTRY = {
    "get_price_history": T.get_price_history,
    "compute_indicators": T.compute_indicators,
    "search_filings": T.search_filings,
    "search_news": T.search_news,
}

def sanitize_response_text(text: str) -> str:
    """
    Strips accidental internal tool names or 'via the X tool' phrases from LLM output
    so end users never see developer implementation details.
    """
    if not text:
        return text
    # Remove phrases like "(via the get_price_history tool)", "(via get_price_history)", etc.
    text = re.sub(r"\s*\(\s*via\s+[^)]+\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\bvia\s+(?:the\s+)?[`\w]+(?:\s+tool)?\b", "", text, flags=re.IGNORECASE)
    for tool_name in ["get_price_history", "compute_indicators", "search_filings", "search_news"]:
        text = re.sub(rf"`?{tool_name}`?\s+tool", "official market data", text, flags=re.IGNORECASE)
        text = re.sub(rf"`?{tool_name}`?", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def run_agent(user_message: str, ticker_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes the autonomous equity research agent loop with tool-calling.
    """
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    detected = find_companies_in_text(user_message)
    resolved_hint = resolve_ticker(ticker_hint) if ticker_hint else None

    # Proactively ensure multi-quarter filings are indexed for all detected companies
    for comp in detected:
        try:
            from app.data_sources.filings import ensure_latest_filings
            ensure_latest_filings(comp["nse_symbol"], doc_type="results")
        except Exception:
            pass

    if resolved_hint and not any(c["nse_symbol"] == resolved_hint for c in detected):
        hint_info = company_info(resolved_hint)
        if hint_info:
            detected.append(hint_info)

    if len(detected) == 1:
        c = detected[0]
        msgs.append({
            "role": "system",
            "content": f"The user is specifically inquiring about company: {c['name']} (NSE: {c['nse_symbol']})."
        })
    elif len(detected) > 1:
        comp_desc = ", ".join([f"{c['name']} (NSE: {c['nse_symbol']})" for c in detected])
        msgs.append({
            "role": "system",
            "content": (
                f"The user is asking a COMPARATIVE research question across multiple companies: {comp_desc}.\n"
                "PEER COMPARISON DIRECTIVES:\n"
                "1. You MUST call tools separately for EACH company mentioned (e.g., search_filings with ticker='RELIANCE', and search_filings with ticker='BHARTIARTL') so you have verified official data for all companies.\n"
                "2. When presenting the answer, format the comparison as a clean Markdown table with columns: Company | Quarter | Revenue (₹ crore) | Net Profit (₹ crore) | Operating Profit/Margin | Source.\n"
                "3. Note on Subsidiaries: 'Reliance Jio' is an unlisted digital services segment under Reliance Industries Limited (RELIANCE). Report Jio's segment results where available in disclosures and state Reliance Industries' official consolidated figures clearly."
            )
        })

    msgs.append({"role": "user", "content": user_message})

    sources: List[Dict[str, Any]] = []
    tool_log: List[Dict[str, Any]] = []

    for step in range(MAX_STEPS):
        # Force the model to synthesize an answer if it has gathered ample evidence or is on the last step
        is_last_step = (step >= MAX_STEPS - 1)
        has_ample_evidence = (step >= 2 and len(sources) >= 9)
        active_tools = None if (is_last_step or has_ample_evidence) else TOOLS

        try:
            resp = chat(msgs, active_tools)
        except Exception as e:
            return {
                "answer": f"LLM provider error: {str(e)}",
                "sources": sources,
                "tool_log": tool_log
            }

        m = resp.choices[0].message
        if not m.tool_calls:
            return {
                "answer": sanitize_response_text(m.content or "No response generated."),
                "sources": sources,
                "tool_log": tool_log
            }

        # Record assistant tool call intention
        tool_call_dicts = []
        for tc in m.tool_calls:
            if hasattr(tc, "model_dump"):
                tool_call_dicts.append(tc.model_dump())
            elif isinstance(tc, dict):
                tool_call_dicts.append(tc)
            else:
                tool_call_dicts.append({
                    "id": getattr(tc, "id", f"call_{step}"),
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                })

        msgs.append({
            "role": "assistant",
            "content": m.content or "",
            "tool_calls": tool_call_dicts
        })

        # Execute each tool call
        for tc in m.tool_calls:
            fn_name = tc.function.name if hasattr(tc, "function") else tc.get("function", {}).get("name")
            args_str = tc.function.arguments if hasattr(tc, "function") else tc.get("function", {}).get("arguments", "{}")
            tc_id = getattr(tc, "id", "tool_call_0")
            
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except Exception:
                args = {}

            if fn_name in REGISTRY:
                try:
                    result = REGISTRY[fn_name](**args)
                except Exception as ex:
                    result = {"error": f"Tool execution failed: {str(ex)}"}
            else:
                result = {"error": f"Tool '{fn_name}' not found."}

            tool_log.append({
                "step": step + 1,
                "tool": fn_name,
                "args": args,
                "result": result
            })

            # Harvest citations
            if isinstance(result, dict):
                # RAG filing results
                if "results" in result and isinstance(result["results"], list):
                    for hit in result["results"]:
                        sources.append({
                            "type": hit.get("kind", "filing"),
                            "source": hit.get("source") or hit.get("headline"),
                            "page": hit.get("page"),
                            "symbol": hit.get("symbol"),
                            "fiscal_year": hit.get("fiscal_year"),
                            "url": hit.get("url") or (hit.get("sources", [{}])[0].get("url") if hit.get("sources") else "")
                        })
                # Price / Indicator source
                elif "source" in result:
                    sources.append({
                        "type": "market_data",
                        "source": result["source"],
                        "as_of": result.get("as_of"),
                        "symbol": result.get("symbol")
                    })

            # Truncate structured fields safely before serialization to preserve valid JSON
            if isinstance(result, dict) and "results" in result and isinstance(result["results"], list):
                trimmed = []
                for h in result["results"][:6]:
                    h_copy = dict(h)
                    if "text" in h_copy and len(str(h_copy["text"])) > 1500:
                        h_copy["text"] = str(h_copy["text"])[:1500] + "..."
                    if "summary" in h_copy and len(str(h_copy["summary"])) > 800:
                        h_copy["summary"] = str(h_copy["summary"])[:800] + "..."
                    trimmed.append(h_copy)
                result_to_dump = {**result, "results": trimmed}
            else:
                result_to_dump = result

            content_str = json.dumps(result_to_dump)

            msgs.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": content_str
            })

    # If the loop ended without generating a text answer, force a final synthesis using gathered evidence
    try:
        final_msgs = msgs + [{
            "role": "user",
            "content": "Please synthesize all the gathered evidence above into a direct, well-structured factual response with exact figures and source citations."
        }]
        final_resp = chat(final_msgs, tools=None)
        final_answer = final_resp.choices[0].message.content or "No response generated."
    except Exception:
        final_answer = "I reached the maximum step limit without concluding. Here is the data collected so far."

    return {
        "answer": sanitize_response_text(final_answer),
        "sources": sources,
        "tool_log": tool_log
    }
