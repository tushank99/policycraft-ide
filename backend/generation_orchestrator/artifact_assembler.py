"""Artifact assembler: parses LLM output into individual files and creates a ZIP archive.

Expected LLM output format:
    ### FILE: relative/path/to/file
    ```
    file content here
    ```
    ### FILE: another/file.py
    ```python
    more content
    ```
"""

import ast
import hashlib
import io
import re
import zipfile
from typing import Any, Optional

from shared.logger import get_logger

logger = get_logger("artifact-assembler")

# ### FILE: path  |  ## FILE: path  |  FILE: path  (optional backticks)
_FILE_HEADER = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+)?(?:FILE|File)[ \t]*:[ \t]*[`*\"']*"
    r"([A-Za-z0-9_./\\-]+(?:\.[A-Za-z0-9]+)?|Dockerfile|Makefile|\.gitignore|\.env)"
    r"[`*\"']*[^\n]*$",
    re.MULTILINE,
)

_XML_FILE = re.compile(
    r"<file\s+(?:path|name)=[\"']([^\"']+)[\"']\s*>(.*?)</file>",
    re.DOTALL | re.IGNORECASE,
)

_NAMED_FENCE = re.compile(
    r"```(?:[\w+-]+)[ \t]*(?::|[ \t]+(?:title|filename|file|path)\s*=)?[ \t]*"
    r"[\"']?([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)[\"']?[^\n]*\n"
    r"(.*?)"
    r"\n?```",
    re.DOTALL,
)

_UNNAMED_FENCE = re.compile(
    r"(.{0,120}?)\n?\s*```[a-zA-Z]*[ \t]*\n(.*?)\n?\s*```",
    re.DOTALL,
)

_PLACEHOLDER_NAMES = {
    "filename",
    "filename.ext",
    "file.ext",
    "path",
    "example",
    "your_file",
}

_GENERIC_NAME = re.compile(r"^generated_file_\d+\.[A-Za-z0-9]+$", re.IGNORECASE)

# Break smushed Python so `import x from y` / `()def` / `try:` become real lines.
_BREAK_BEFORE_STMT = re.compile(
    r"(?:(?<=[^\s])[ \t]+|(?<=[)\]]))"
    r"(?="
    r"from\s+\S+\s+import\b"
    r"|import\s+\w"
    r"|def\s+"
    r"|class\s+"
    r"|async\s+def\s+"
    r"|try:"
    r"|except\b"
    r"|finally:"
    r"|else:"
    r"|elif\b"
    r"|if\s+"
    r"|for\s+"
    r"|while\s+"
    r"|with\s+"
    r"|return\b"
    r"|raise\b"
    r"|pass\b"
    r"|@"
    r")"
)

_BREAK_BEFORE_ASSIGN = re.compile(r"(?<=[)\]\w])[ \t]*(?=[A-Za-z_]\w*\s*=)")


def parse_llm_output(raw_output: str) -> dict[str, str]:
    """Parse the LLM's output into a dict of filepath -> content.

    Args:
        raw_output: The raw text output from the LLM.

    Returns:
        Dict mapping relative file paths to their content.

    Raises:
        ValueError: If no files could be parsed from the output.
    """
    raw_output = (raw_output or "").replace("\r\n", "\n").replace("\r", "\n")
    files: dict[str, str] = {}

    header_matches = list(_FILE_HEADER.finditer(raw_output))
    if header_matches:
        for i, match in enumerate(header_matches):
            start = match.end()
            end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(raw_output)
            path = _clean_path(match.group(1))
            content = _strip_fence(raw_output[start:end])
            _add_file(files, path, content)
    else:
        xml_matches = list(_XML_FILE.finditer(raw_output))
        if xml_matches:
            for match in xml_matches:
                _add_file(files, _clean_path(match.group(1)), _strip_fence(match.group(2)))
        else:
            named = list(_NAMED_FENCE.finditer(raw_output))
            consumed_spans = []
            for match in named:
                _add_file(files, _clean_path(match.group(1)), match.group(2).strip("\n"))
                consumed_spans.append((match.start(), match.end()))

            leftover = raw_output
            if consumed_spans:
                leftover = _remove_spans(raw_output, consumed_spans)

            if not files or leftover.strip():
                for i, (preceding_text, content) in enumerate(_UNNAMED_FENCE.findall("\n" + leftover)):
                    filename = _filename_from_context(preceding_text, content, i)
                    _add_file(files, filename, content.strip("\n"))

    if not files:
        raise ValueError("Could not parse any files from LLM output")

    files = {
        path: _normalize_content(path, content)
        for path, content in files.items()
        if content and content.strip()
    }
    files = _resolve_generic_names(files)
    files = _dedupe_identical_content(files)

    if not files:
        raise ValueError("LLM produced no valid files — output may be planning prose only")

    logger.info(f"Parsed {len(files)} files from LLM output: {list(files.keys())}")
    return files


def _add_file(files: dict[str, str], path: str, content: str) -> None:
    content = (content or "").strip("\n")
    if not content.strip():
        return
    if not _is_valid_filename(path):
        path = _infer_filename(content, files)
    if not _is_valid_filename(path):
        logger.warning(f"Skipping invalid/placeholder filename: '{path}'")
        return
    if path in files and files[path] != content:
        if len(content) > len(files[path]):
            files[path] = content
        return
    files[path] = content


def _filename_from_context(preceding_text: str, content: str, index: int) -> str:
    file_match = re.search(
        r"[*`'\"]?([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)[*`'\"]?",
        preceding_text,
    )
    if file_match:
        return _clean_path(file_match.group(1))

    first_line = content.lstrip().split("\n")[0]
    if first_line.startswith(("#", "//", "/*")):
        inline_match = re.search(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)", first_line)
        if inline_match:
            return _clean_path(inline_match.group(1))

    return _infer_filename(content, {}, fallback_index=index)


def _clean_path(path: str) -> str:
    clean = path.strip().strip("`\"'*").replace("\\", "/")
    clean = clean.lstrip("./")
    return clean.lstrip("/")


def _strip_fence(block: str) -> str:
    block = block.strip("\n")
    block = re.sub(r"^```[a-zA-Z0-9_+-]*[^\n]*\n", "", block)
    block = re.sub(r"\n```[ \t]*$", "", block)
    return block.strip("\n")


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    pieces = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _normalize_content(path: str, content: str) -> str:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if content.count("\n") < 2 and "\\n" in content:
        content = content.replace("\\n", "\n").replace("\\t", "\t")
    if path.endswith(".py") or _looks_like_python(content):
        content = _reflow_python(content)
    return content.strip("\n") + "\n"


def _looks_like_python(content: str) -> bool:
    head = content.lstrip()[:400]
    return bool(
        re.search(r"^(from |import |def |class |async def )", head, re.MULTILINE)
        or "FastAPI" in content
        or "BaseSettings" in content
    )


def _looks_smushed_python(content: str) -> bool:
    if len(content) < 80:
        return False
    newline_count = content.count("\n")
    if newline_count <= 2 and len(content) > 120:
        return True
    try:
        ast.parse(content)
        return False
    except SyntaxError:
        compact = newline_count < max(6, len(content) // 180)
        has_stmts = bool(re.search(r"\b(def|class|from|import|try)\b", content))
        return compact and has_stmts


def _reflow_python(content: str) -> str:
    """Restore newlines/indentation when the model emitted minified Python."""
    try:
        ast.parse(content)
        return content
    except SyntaxError:
        pass

    if not _looks_smushed_python(content):
        return content

    text = content.replace("\n", " ")
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = _BREAK_BEFORE_STMT.sub("\n", text)
    text = re.sub(r"\)(?=[A-Za-z_]\w*\s*=)", ")\n", text)
    text = re.sub(r":[ \t]+(?=try:|def |class |if |return |raise |pass\b|for |with |async )", ":\n", text)
    text = _BREAK_BEFORE_ASSIGN.sub("\n", text)

    lines: list[str] = []
    indent = 0
    for raw in text.split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue
        if re.match(r"^(except\b|else:|elif\b|finally:)", stripped):
            indent = max(0, indent - 1)
        lines.append(("    " * indent) + stripped)
        if stripped.endswith(":") and not stripped.startswith("#"):
            indent += 1
        elif re.match(r"^(return|raise|pass|break|continue)\b", stripped):
            indent = max(0, indent - 1)

    restored = "\n".join(lines) + "\n"
    try:
        ast.parse(restored)
        logger.info("Restored newlines/indentation for smushed Python file")
        return restored
    except SyntaxError as err:
        logger.warning(f"Python reflow still has syntax error: {err}")
        return restored


def _infer_filename(content: str, used: dict[str, str], fallback_index: int = 0) -> str:
    head = content.lstrip()
    lower = content.lower()

    if re.search(r"^[a-zA-Z0-9_.-]+(?:==|>=|~=)", content, re.MULTILINE) and "def " not in content:
        return _unique_name("requirements.txt", used)
    if re.match(r"FROM\s+", head, re.IGNORECASE):
        return _unique_name("Dockerfile", used)
    if "kind:" in lower and ("deployment" in lower or "service" in lower):
        kind = "deployment.yaml" if "kind: deployment" in lower else "service.yaml"
        return _unique_name(kind, used)
    if re.search(r"^#\s+", head) and ("setup" in lower or "api" in lower) and len(content) > 200:
        if "readme" not in "".join(used.keys()).lower():
            return _unique_name("README.md", used)
    if "jobs:" in content and ("on:" in content or "runs-on:" in content):
        return _unique_name(".github/workflows/ci.yml", used)

    if "HTTPBearer" in content or "decode_token" in content or "require_role" in content:
        return _unique_name("auth.py", used)
    if "BaseSettings" in content or "class Settings" in content:
        return _unique_name("config.py", used)
    if re.search(r"class\s+\w*Repository\b", content):
        repo = re.search(r"class\s+(\w+)", content)
        name = _to_snake(repo.group(1)) + ".py" if repo else "repository.py"
        return _unique_name(name, used)
    if re.search(r"class\s+\w*Service\b", content) and "FastAPI" not in content:
        svc = re.search(r"class\s+(\w+)", content)
        name = _to_snake(svc.group(1)) + ".py" if svc else "service.py"
        return _unique_name(name, used)
    if "FastAPI(" in content or re.search(r"@app\.(get|post|put|delete)", content):
        return _unique_name("main.py", used)
    if "APIRouter" in content:
        return _unique_name("routes.py", used)
    if "def setup_telemetry" in content or "TracerProvider" in content:
        return _unique_name("telemetry.py", used)

    if _looks_like_python(content):
        return _unique_name(f"module_{fallback_index + 1}.py", used)
    return _unique_name(f"file_{fallback_index + 1}.txt", used)


def _to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _unique_name(name: str, used: dict[str, str]) -> str:
    if name not in used:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, "txt"
    i = 2
    candidate = f"{stem}_{i}.{ext}"
    while candidate in used:
        i += 1
        candidate = f"{stem}_{i}.{ext}"
    return candidate


def _resolve_generic_names(files: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for path, content in files.items():
        basename = path.split("/")[-1]
        if _GENERIC_NAME.match(basename) or basename.startswith("file_"):
            path = _infer_filename(content, resolved)
        _add_file(resolved, path, content)
    return resolved


def _dedupe_identical_content(files: dict[str, str]) -> dict[str, str]:
    by_hash: dict[str, str] = {}
    out: dict[str, str] = {}
    for path, content in sorted(files.items(), key=lambda kv: _name_quality(kv[0]), reverse=True):
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest in by_hash:
            logger.info(f"Dropping duplicate of {by_hash[digest]}: {path}")
            continue
        by_hash[digest] = path
        out[path] = content
    return out


def _name_quality(path: str) -> int:
    score = 0
    base = path.split("/")[-1].lower()
    if _GENERIC_NAME.match(base) or base.startswith("file_"):
        score -= 20
    if "." in base:
        score += 2
    if "/" in path:
        score += 1
    if base in {"main.py", "requirements.txt", "dockerfile", "readme.md"}:
        score += 5
    return score


def _is_valid_filename(path: str) -> bool:
    """Return True only if path looks like a real file, not a template placeholder."""
    if not path:
        return False
    basename = path.split("/")[-1].lower()
    if _GENERIC_NAME.match(basename):
        return False
    known_extensionless = {"dockerfile", "makefile", ".gitignore", ".env"}
    has_extension = "." in basename
    if not has_extension and basename not in known_extensionless:
        return False
    if basename in _PLACEHOLDER_NAMES:
        return False
    if has_extension:
        ext = basename.rsplit(".", 1)[-1]
        if len(ext) < 1 or ext in {"ext", "extension", "type"}:
            return False
    return True


def create_zip(files: dict[str, str], service_name: Optional[str] = None) -> bytes:
    """Create a ZIP archive from parsed files.

    Args:
        files: Dict mapping relative file paths to their content.
        service_name: Optional service name to use as the root directory in the ZIP.

    Returns:
        ZIP archive as bytes.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        root = service_name or "generated-service"
        for filepath, content in files.items():
            full_path = f"{root}/{filepath}"
            zf.writestr(full_path, content)
            logger.info(f"Added to ZIP: {full_path} ({len(content)} bytes)")

    zip_bytes = buffer.getvalue()
    logger.info(f"ZIP created: {len(zip_bytes)} bytes, {len(files)} files")
    return zip_bytes


def get_file_list(files: dict[str, str]) -> list[dict[str, Any]]:
    """Get a summary list of files for the results dashboard.

    Args:
        files: Dict mapping relative file paths to their content.

    Returns:
        List of dicts with file metadata.
    """
    file_list = []
    for filepath, content in files.items():
        file_list.append({
            "path": filepath,
            "size": len(content),
            "lines": content.count("\n") + 1,
            "type": _detect_file_type(filepath),
        })
    return file_list


def _detect_file_type(filepath: str) -> str:
    """Detect file type from extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".json": "json",
        ".toml": "toml",
        ".md": "markdown",
        ".txt": "text",
        ".sh": "shell",
        ".bash": "shell",
    }
    for ext, file_type in ext_map.items():
        if filepath.lower().endswith(ext):
            return file_type

    basename = filepath.split("/")[-1].lower()
    if basename == "dockerfile":
        return "dockerfile"
    if basename == "makefile":
        return "makefile"
    if basename == ".gitignore":
        return "gitignore"

    return "text"
