from task2pr.tools.filesystem import (
    RepoSandbox,
    ToolError,
    edit_file,
    grep,
    list_directory,
    read_file,
    write_file,
)

READ_ONLY_TOOL_SCHEMAS = [
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

EDIT_TOOL_SCHEMAS = READ_ONLY_TOOL_SCHEMAS + [
    {
        "name": "write_file",
        "description": (
            "Create a new file, or overwrite an existing one entirely, "
            "inside the target repo. Prefer edit_file for changes to an "
            "existing file so you don't discard unrelated content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repo root."},
                "content": {"type": "string", "description": "Full file content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace an exact snippet of text in an existing file inside the "
            "target repo. old_string must match the file's current content "
            "exactly (read the file first) and must be unique unless "
            "replace_all is set."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repo root."},
                "old_string": {"type": "string", "description": "Exact text to replace."},
                "new_string": {"type": "string", "description": "Text to replace it with."},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace every occurrence instead of requiring a unique match. Default false.",
                },
            },
            "required": ["path", "old_string", "new_string"],
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
        if name == "write_file":
            return write_file(sandbox, tool_input["path"], tool_input["content"])
        if name == "edit_file":
            return edit_file(
                sandbox,
                tool_input["path"],
                tool_input["old_string"],
                tool_input["new_string"],
                replace_all=tool_input.get("replace_all", False),
            )
        return f"Error: unknown tool {name!r}"
    except ToolError as exc:
        return f"Error: {exc}"


__all__ = [
    "RepoSandbox",
    "ToolError",
    "READ_ONLY_TOOL_SCHEMAS",
    "EDIT_TOOL_SCHEMAS",
    "run_tool",
]
