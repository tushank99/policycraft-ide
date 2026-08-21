import ast
from typing import List, Dict, Any

class ComplianceVisitor(ast.NodeVisitor):
    def __init__(self):
        self.found_routes = []
        self.has_middleware = False
        self.envelope_violations = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Scans function decorators to detect route definitions."""
        for decorator in node.decorator_list:
            
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr in ['get', 'post', 'put', 'delete', 'patch']:
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        route_path = decorator.args[0].value
                        self.found_routes.append(route_path)

        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Return):
                if isinstance(stmt.value, ast.Dict):
                    keys = [k.value for k in stmt.value.keys if isinstance(k, ast.Constant)]
                    if not all(required_key in keys for required_key in ['data', 'status', 'error']):
                        self.envelope_violations.append(node.lineno)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Scans for middleware attachments."""
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'add_middleware':
                self.has_middleware = True
        self.generic_visit(node)


class ASTComplianceEngine:
    @staticmethod
    def validate_python_project(files: Dict[str, str]) -> List[Dict[str, Any]]:
        """Parses all Python code into an AST and evaluates structural compliance holistically."""
        results = []
        all_found_routes = []
        all_envelope_violations = []

        parsed_any = False
        for filename, file_content in files.items():
            try:
                tree = ast.parse(file_content)
            except SyntaxError as e:
                results.append({
                    "rule": "Python Syntax Compilation",
                    "status": "FAIL",
                    "severity": "mandatory",
                    "message": f"Syntax Error in {filename} at line {e.lineno}: {e.msg}",
                    "engine": "ast_python"
                })
                continue

            parsed_any = True
            visitor = ComplianceVisitor()
            visitor.visit(tree)
            
            all_found_routes.extend(visitor.found_routes)
            if visitor.envelope_violations:
                all_envelope_violations.append((filename, visitor.envelope_violations))

        # Skip route checks when nothing compiled — syntax failures already cover it.
        if not parsed_any:
            return results

        # 3. Health Probe Route Validation
        required_routes = ["/healthz", "/readyz"]
        for route in required_routes:
            if route in all_found_routes:
                results.append({
                    "rule": f"AST Route Verification: {route}",
                    "status": "PASS",
                    "severity": "mandatory",
                    "message": f"Required {route} endpoint successfully detected in AST.",
                    "engine": "ast_python"
                })
            else:
                results.append({
                    "rule": f"AST Route Verification: {route}",
                    "status": "FAIL",
                    "severity": "mandatory",
                    "message": f"Missing required endpoint: {route}. Ensure it is decorated with @app.get('{route}').",
                    "engine": "ast_python",
                    "remediation": f"Add a GET route for {route} returning a 200 status."
                })

        # 4. Response Envelope Validation
        if all_envelope_violations:
            violation_msgs = [f"{fname} (lines: {', '.join(map(str, lines))})" for fname, lines in all_envelope_violations]
            results.append({
                "rule": "AST Response Envelope Format",
                "status": "WARNING",
                "severity": "warning",
                "message": f"Found direct returns without standard envelope in: {'; '.join(violation_msgs)}",
                "engine": "ast_python",
                "remediation": "Wrap dictionary returns in {'data': ..., 'status': 'success', 'error': null}."
            })

        return results