# SILO: dedicated AWS account under an M&A OU, region-locked by SCP, own KMS key,
# immutable log archive. No network path to the parent (network_peering = none).
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.40" }
  }
}

variable "tenant" { type = any }            # decoded *.auto.tfvars.json from the playbook
variable "mna_ou_id" { type = string }      # e.g. ou-xxxx-acquisitions
variable "account_email_domain" { type = string }

locals {
  name = "mna-${var.tenant.tenant_id}"
  tags = merge(var.tenant.tags, { tenant_id = var.tenant.tenant_id, tier = "silo" })
}

resource "aws_organizations_account" "this" {
  name                       = local.name
  email                      = "aws+${var.tenant.tenant_id}@${var.account_email_domain}"
  parent_id                  = var.mna_ou_id
  role_name                  = "OrganizationAccountAccessRole"
  iam_user_access_to_billing = "DENY"
  close_on_deletion          = false
  tags                       = local.tags
}

# Region lock: data may only live where residency allows.
resource "aws_organizations_policy" "region_lock" {
  name = "${local.name}-region-lock"
  type = "SERVICE_CONTROL_POLICY"
  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyOutsideResidency"
        Effect    = "Deny"
        NotAction = ["iam:*", "organizations:*", "sts:*", "support:*", "cloudfront:*", "route53:*"]
        Resource  = "*"
        Condition = { StringNotEquals = { "aws:RequestedRegion" = var.tenant.regions } }
      },
      {
        Sid      = "DenyLeaveOrgAndLogTamper"
        Effect   = "Deny"
        Action   = ["organizations:LeaveOrganization", "cloudtrail:StopLogging", "cloudtrail:DeleteTrail"]
        Resource = "*"
      }
    ]
  })
  tags = local.tags
}

resource "aws_organizations_policy_attachment" "region_lock" {
  policy_id = aws_organizations_policy.region_lock.id
  target_id = aws_organizations_account.this.id
}

resource "aws_kms_key" "tenant" {
  description             = "${local.name} tenant data key (SILO)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}

resource "aws_s3_bucket" "log_archive" {
  bucket              = "${local.name}-log-archive"
  object_lock_enabled = true
  tags                = local.tags
}

resource "aws_s3_bucket_object_lock_configuration" "log_archive" {
  bucket = aws_s3_bucket.log_archive.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.tenant.log_archive_retention_days
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "log_archive" {
  bucket = aws_s3_bucket.log_archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.tenant.arn
    }
  }
}

output "account_id" { value = aws_organizations_account.this.id }
output "kms_key_arn" { value = aws_kms_key.tenant.arn }
