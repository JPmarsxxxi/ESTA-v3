"""LLM provider router.

Dispatches generation requests to the configured LLM provider. The
default provider is `claude`, meaning Claude generates in-conversation
(the calling SKILL.md instructs Claude directly — no Python API call).
Other providers (gemini, openai) would route through this function
with their respective API clients.

Today only the `claude` path is wired up (as a sentinel). Other
providers raise NotImplementedError — set llm_provider: claude in
config.yaml until support is added.
"""

from pathlib import Path
from typing import Any


CLAUDE_HARNESS_SENTINEL = "USE_CLAUDE_HARNESS"


def read_llm_provider(config_path: Path | None = None) -> str:
    """Read llm_provider from config.yaml. Defaults to 'claude'."""
    import yaml

    if config_path is None:
        # config.yaml at repo root, two levels up from tools/llm/router.py
        config_path = Path(__file__).resolve().parents[2] / "config.yaml"

    if not config_path.exists():
        return "claude"

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    return config.get("llm_provider", "claude")


def generate(
    task: str,
    prompt_vars: dict[str, Any],
    config_path: Path | None = None,
) -> str:
    """Dispatch a generation request to the configured LLM.

    Args:
        task: identifier like "talking_points", "script", "humanizer".
            Used by external-provider branches to pick the right prompt
            template from tools/scriptwriter/prompts.py.
        prompt_vars: substitution variables for the prompt template.
        config_path: override path to config.yaml (for tests).

    Returns:
        Raw text output from the LLM. For provider="claude", returns
        CLAUDE_HARNESS_SENTINEL — the calling SKILL.md should check for
        this and handle generation inline.

    Raises:
        NotImplementedError: when llm_provider is anything other than
            "claude". Those providers are not wired up yet.
    """
    provider = read_llm_provider(config_path)

    if provider == "claude":
        return CLAUDE_HARNESS_SENTINEL

    raise NotImplementedError(
        f"LLM provider '{provider}' is not implemented yet. "
        f"Set 'llm_provider: claude' in config.yaml until provider support is added."
    )
