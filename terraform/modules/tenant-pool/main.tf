# POOL: fully absorbed. Shared data plane; isolation = Postgres RLS + ABAC session tags.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.40" }
  }
}

variable "tenant" { type = any }
variable "tenant_registry_table" { type = string }   # DynamoDB table read by the API gateway authorizer

resource "aws_dynamodb_table_item" "registry" {
  table_name = var.tenant_registry_table
  hash_key   = "tenant_id"
  item = jsonencode({
    tenant_id   = { S = var.tenant.tenant_id }
    tier        = { S = "pool" }
    parent      = { S = var.tenant.parent_tenant }
    regions     = { SS = var.tenant.regions }
    rls_setting = { S = "app.tenant_id" }
  })
}

output "tenant_id" { value = var.tenant.tenant_id }
