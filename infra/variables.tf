variable "groq_api_key" {
  description = "Groq API key (get one free at console.groq.com)"
  type        = string
  sensitive   = true
}
variable "github_token" {
  description = "GitHub Personal Access Token (PAT) for provisioning repositories"
  type        = string
  sensitive   = true
}
