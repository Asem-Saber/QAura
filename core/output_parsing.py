from typing import Type, TypeVar
from pydantic import BaseModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage, SystemMessage

T = TypeVar("T", bound=BaseModel)


def robust_parse(raw_output: str, pydantic_class: Type[T], llm, max_retries: int = 2) -> T:
    """Parse LLM output into a Pydantic model with LLM-assisted retry on failure.

    1. Attempt direct parsing via PydanticOutputParser.
    2. On failure, send the raw output + error back to the LLM and ask it to fix
       the JSON.  Retry up to ``max_retries`` times.
    3. Raise the last error if all attempts fail.
    """
    parser = PydanticOutputParser(pydantic_object=pydantic_class)

    try:
        return parser.invoke(raw_output)
    except Exception as first_error:
        last_error = first_error

    for attempt in range(max_retries):
        fix_messages = [
            SystemMessage(content=(
                "The following text was supposed to be valid JSON matching this schema, "
                "but it failed to parse. Fix the JSON and return ONLY the corrected JSON "
                "object — no explanation, no markdown fences.\n\n"
                f"Schema:\n{parser.get_format_instructions()}"
            )),
            HumanMessage(content=(
                f"Raw output:\n{raw_output}\n\n"
                f"Parse error:\n{last_error}"
            )),
        ]
        try:
            fix_response = llm.invoke(fix_messages)
            return parser.invoke(fix_response.content)
        except Exception as retry_error:
            last_error = retry_error

    raise last_error
