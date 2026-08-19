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
    def validate_python_code(file_content: str, filename: str) -> List[Dict[str, Any]]:
        """Parses Python code into an AST and evaluates structural compliance."""
        results = []

        # 1. Syntax & Parseability Check
        try:
            tree = ast.parse(file_content)
        except SyntaxError as e:
            return [{
                "rule": "Python Syntax Compilation",
                "status": "FAIL",
                "severity": "mandatory",
                "message": f"Syntax Error in {filename} at line {e.lineno}: {e.msg}",
                "engine": "ast_python"
            }]

        # 2. Traverse AST Node Tree
        visitor = ComplianceVisitor()
        visitor.visit(tree)

        # 3. Health Probe Route Validation
        required_routes = ["/healthz", "/readyz"]
        for route in required_routes:
            if route in visitor.found_routes:
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
        if visitor.envelope_violations:
            results.append({
                "rule": "AST Response Envelope Format",
                "status": "WARNING",
                "severity": "warning",
                "message": f"Found direct returns without standard envelope at lines: {', '.join(map(str, visitor.envelope_violations))}",
                "engine": "ast_python",
                "remediation": "Wrap dictionary returns in {'data': ..., 'status': 'success', 'error': null}."
            })

        return results