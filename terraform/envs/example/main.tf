# Consumes the tfvars the playbook renders (out/terraform/*.auto.tfvars.json)
# and fans each tenant out to the module matching its CURRENT tier.
#
#   mnat onboard deals/globex-bank.json   # renders tfvars
#   cd terraform/envs/example && terraform init && terraform plan
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.40" }
  }
}

provider "aws" { region = "us-east-1" }

variable "tfvars_dir" { default = "../../../out/terraform" }
variable "mna_ou_id" { default = "ou-xxxx-acquisitions" }
variable "account_email_domain" { default = "example.com" }
variable "transit_gateway_id" { default = "tgw-00000000000000000" }
variable "inspection_attachment_id" { default = "tgw-attach-00000000000000000" }
variable "tenant_registry_table" { default = "mna-tenant-registry" }

locals {
  tenants = {
    for f in fileset(var.tfvars_dir, "*.auto.tfvars.json") :
    trimsuffix(f, ".auto.tfvars.json") => jsondecode(file("${var.tfvars_dir}/${f}"))
  }
  silo   = { for k, v in local.tenants : k => v if v.module == "tenant-silo" }
  bridge = { for k, v in local.tenants : k => v if v.module == "tenant-bridge" }
  pool   = { for k, v in local.tenants : k => v if v.module == "tenant-pool" }
}

module "silo" {
  source               = "../../modules/tenant-silo"
  for_each             = local.silo
  tenant               = each.value
  mna_ou_id            = var.mna_ou_id
  account_email_domain = var.account_email_domain
}

module "bridge" {
  source                   = "../../modules/tenant-bridge"
  for_each                 = local.bridge
  tenant                   = each.value
  transit_gateway_id       = var.transit_gateway_id
  inspection_attachment_id = var.inspection_attachment_id
}

module "pool" {
  source                = "../../modules/tenant-pool"
  for_each              = local.pool
  tenant                = each.value
  tenant_registry_table = var.tenant_registry_table
}

output "tenants_by_tier" {
  value = { silo = keys(local.silo), bridge = keys(local.bridge), pool = keys(local.pool) }
}
