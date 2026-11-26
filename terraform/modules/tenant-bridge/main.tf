# BRIDGE: shared control plane, dedicated data-plane boundary.
#   * dedicated KMS key (crypto-shredding on carve-out)
#   * dedicated DB schema + credentials (sql/postgres_rls.sql: bridge schema)
#   * ABAC role: sessions must carry PrincipalTag tenant_id == this tenant
#   * inspected Transit Gateway route table (no flat peering)
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.40" }
  }
}

variable "tenant" { type = any }
variable "transit_gateway_id" { type = string }
variable "inspection_attachment_id" { type = string }

locals {
  name = "mna-${var.tenant.tenant_id}"
  tags = merge(var.tenant.tags, { tenant_id = var.tenant.tenant_id, tier = "bridge" })
}

resource "aws_kms_key" "tenant" {
  description         = "${local.name} tenant data key (BRIDGE)"
  enable_key_rotation = true
  tags                = local.tags
}

resource "aws_kms_alias" "tenant" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.tenant.key_id
}

resource "aws_secretsmanager_secret" "db" {
  name       = "${local.name}/db/schema-owner"
  kms_key_id = aws_kms_key.tenant.arn
  tags       = local.tags
}

data "aws_iam_policy_document" "assume_abac" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:PrincipalTag/tenant_id"
      values   = [var.tenant.tenant_id]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "tenant_workload" {
  name               = "${local.name}-workload"
  assume_role_policy = data.aws_iam_policy_document.assume_abac.json
  tags               = local.tags
}

resource "aws_iam_role_policy" "tenant_data" {
  role = aws_iam_role.tenant_workload.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Decrypt", "kms:GenerateDataKey", "secretsmanager:GetSecretValue"]
      Resource = [aws_kms_key.tenant.arn, aws_secretsmanager_secret.db.arn]
    }]
  })
}

resource "aws_ec2_transit_gateway_route_table" "tenant" {
  transit_gateway_id = var.transit_gateway_id
  tags               = merge(local.tags, { Name = "${local.name}-rt" })
}

# Default route forces all tenant <-> parent traffic through the inspection VPC.
resource "aws_ec2_transit_gateway_route" "via_inspection" {
  destination_cidr_block         = "0.0.0.0/0"
  transit_gateway_attachment_id  = var.inspection_attachment_id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.tenant.id
}

output "kms_key_arn" { value = aws_kms_key.tenant.arn }
output "workload_role_arn" { value = aws_iam_role.tenant_workload.arn }
