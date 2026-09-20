from task2pr.tools.filesystem import RepoSandbox, ToolError, grep, list_directory, read_file

TOOL_SCHEMAS = [
    {
        "name": "list_directory",
        "description": (
            "List the immediate contents of a directory inside the target repo "
            "(one level deep - subdirectories are shown but not expanded). "
            "Directory entries are suffixed with '/'. Use this to orient "
            "yourself before reading files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the repo root. Defaults to the repo root itself.",
                }
            },
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file inside the target repo, with 1-indexed line numbers. "
            "Large files are windowed - if the response is truncated, call "
            "again with a higher offset to keep reading."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repo root."},
                "offset": {
                    "type": "integer",
                    "description": "0-indexed line number to start from. Default 0.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of lines to return. Default 500.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search for a regex pattern across files under a path inside the "
            "target repo. Returns matching lines formatted as "
            "'relative/path:line_number:content'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regex pattern to search for."},
                "path": {
                    "type": "string",
                    "description": "Path relative to the repo root to search under. Defaults to the whole repo.",
                },
            },
            "required": ["pattern"],
        },
    },
]


def run_tool(sandbox: RepoSandbox, name: str, tool_input: dict) -> str:
    """Dispatch a tool call and return its result as a string.

    ToolError is caught here (not raised) so Claude sees "Error: ..." as the
    tool result and can adjust its next call, instead of the whole agent
    loop crashing on a bad path or pattern.
    """
    try:
        if name == "list_directory":
            return list_directory(sandbox, tool_input.get("path", "."))
        if name == "read_file":
            return read_file(
                sandbox,
                tool_input["path"],
                offset=tool_input.get("offset", 0),
                limit=tool_input.get("limit", 500),
            )
        if name == "grep":
            return grep(sandbox, tool_input["pattern"], tool_input.get("path", "."))
        return f"Error: unknown tool {name!r}"
    except ToolError as exc:
        return f"Error: {exc}"


__all__ = ["RepoSandbox", "ToolError", "TOOL_SCHEMAS", "run_tool"]
