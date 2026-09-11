# GitHub Copilot Instructions

- **Architecture & Routing**: Always refer to [AGENTS.md](../AGENTS.md) to locate the exact module and file before reading or generating code. Avoid scanning the entire repository.
- **Noise Prevention**: Never suggest modifying or scanning `.venv/`, `data/`, audio files (`*.wav`), or database files.
- **Configuration**: Always use `my_openai_robot/config.py` (Pydantic model) for environment configurations.
- **Type Hints**: Use standard Python 3.10+ typing annotations for all new/modified functions.
