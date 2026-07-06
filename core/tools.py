import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent

@tool
def read_requirements_file(file_path: str) -> str:
    """Read the project requirements markdown file to understand the scope of testing.

    Args:
        file_path: The path to the requirements file (e.g., 'project_requirements.md')
    """
    try:
        resolved = ROOT / file_path if not os.path.isabs(file_path) else Path(file_path)
        with open(resolved, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


PLANNING_TOOLS = [read_requirements_file]