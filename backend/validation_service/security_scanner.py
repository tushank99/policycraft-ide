import re
from typing import List, Dict, Any

class SecurityScanner:
    AWS_KEY_PATTERN = re.compile(r"(AKIA[0-9A-Z]{16})")
    PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN .*PRIVATE KEY-----")
    
    WILDCARD_CORS_PATTERN = re.compile(r"allow_origins\s*=\s*\[\s*['\"]*['\"]\s*\]|AllowOrigins:\s*\[\]string\{['\"]\*{1}['\"]\}")
    
    # 3. Insecure Protocols (Flags http:// unless it's pointing to localhost)
    INSECURE_HTTP_PATTERN = re.compile(r"http://(?!(localhost|127\.0\.0\.1))")

    @staticmethod
    def scan_file(file_content: str, filename: str) -> List[Dict[str, Any]]:
        """Scans any text-based file for security vulnerabilities."""
        results = []
        lines = file_content.split('\n')

        for line_number, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            
            # Skip comments to prevent false positives from documentation/examples
            if stripped_line.startswith(("#", "//", "/*", "*")):
                continue

            # Check: AWS Credentials
            if SecurityScanner.AWS_KEY_PATTERN.search(line):
                results.append(SecurityScanner._build_finding(
                    rule="Hardcoded AWS Credentials",
                    status="FAIL",
                    severity="mandatory",
                    message=f"AWS Access Key found in {filename} at line {line_number}.",
                    remediation="Remove the hardcoded key and use secure environment variables (e.g., os.getenv)."
                ))

            # Check: Private Keys
            if SecurityScanner.PRIVATE_KEY_PATTERN.search(line):
                results.append(SecurityScanner._build_finding(
                    rule="Hardcoded Private Key",
                    status="FAIL",
                    severity="mandatory",
                    message=f"Private key block found in {filename} at line {line_number}.",
                    remediation="Store private keys in a secure vault or AWS Secrets Manager, never in source code."
                ))

            # Check: Wildcard CORS
            if SecurityScanner.WILDCARD_CORS_PATTERN.search(line):
                results.append(SecurityScanner._build_finding(
                    rule="Insecure CORS Policy",
                    status="FAIL",
                    severity="mandatory",
                    message=f"Wildcard CORS origin ('*') detected in {filename} at line {line_number}.",
                    remediation="Restrict CORS allow_origins to specific, trusted front-end domains."
                ))

            # Check: Insecure HTTP
            if SecurityScanner.INSECURE_HTTP_PATTERN.search(line):
                results.append(SecurityScanner._build_finding(
                    rule="Insecure HTTP Protocol",
                    status="WARNING",
                    severity="warning",
                    message=f"Plaintext HTTP URL detected in {filename} at line {line_number}.",
                    remediation="Use HTTPS for all external network communication to prevent man-in-the-middle attacks."
                ))

        # If the file passed all security checks, append a passing record
        if not results:
            results.append(SecurityScanner._build_finding(
                rule=f"Static Security Scan: {filename}",
                status="PASS",
                severity="mandatory",
                message=f"No hardcoded secrets or glaring vulnerabilities found."
            ))

        return results

    @staticmethod
    def _build_finding(rule: str, status: str, severity: str, message: str, remediation: str = "") -> Dict[str, Any]:
        """Helper to format validation results consistently."""
        finding = {
            "rule": rule,
            "status": status,
            "severity": severity,
            "message": message,
            "engine": "security_scanner"
        }
        if status in ["FAIL", "WARNING"] and remediation:
            finding["remediation"] = remediation
        return finding