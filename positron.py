#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "boto3>=1.35,<2",
# ]
# ///

"""Reconcile the complete Positron-on-SageMaker workshop environment.

This script intentionally does not accept a Posit license key. Positron on
SageMaker validates a Posit Workbench Advanced entitlement through AWS License
Manager using the SageMaker execution role.

The script is designed for a preconfigured Linux terminal:
  * uv creates an isolated environment and installs boto3 from the inline metadata.
  * The Positron image is read from the pre-mirrored private ECR repository.
  * All AWS calls target us-east-1 unless explicitly rejected.

The script takes no command-line options. It can create a SageMaker domain in
the default VPC, including its execution role, participant user profile, Space,
JupyterLab application, and browser URL. Rerunning it resumes from whatever
resources an earlier attempt already created.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, ProfileNotFound
except ImportError as exc:  # pragma: no cover - depends on the runtime environment.
    raise SystemExit(
        "boto3 is required. Run this file with uv: "
        "uv run setup_positron_sagemaker_from_private_ecr.py"
    ) from exc


REGION = "us-east-1"
POSITRON_IMAGE_ACCOUNT_ID = "834525417363"
POSITRON_IMAGE_REPOSITORY = "positron-sagemaker"
POSITRON_IMAGE_TAG = "2026-10-23-aws-hackathon"
DEFAULT_APP_IMAGE_CONFIG = "positron-sagemaker-config"
DEFAULT_DOMAIN_NAME = "positron-workshop"
DEFAULT_EXECUTION_ROLE_NAME = "SageMakerPositronExecutionRole"
LICENSE_POLICY_NAME = "PositronLicenseManager"
ECR_PULL_POLICY_NAME = "PositronPrivateEcrPull"
MANAGED_POLICY_ARNS = (
    # Intentionally broad for this exploratory hackathon environment.
    "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess",
    "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
    "arn:aws:iam::aws:policy/AmazonS3FullAccess",
    "arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess",
)
USER_AGENT = "AWSSkill-SageMaker"
DOMAIN_POLL_INTERVAL_SECONDS = 15
DOMAIN_MAX_POLL_ATTEMPTS = 60

LICENSE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "license-manager:ListReceivedLicenses",
                "license-manager:GetLicense",
                "license-manager:CheckoutLicense",
                "license-manager:ExtendLicenseConsumption",
                "license-manager:CheckInLicense",
            ],
            "Resource": "*",
        }
    ],
}

ECR_PULL_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AuthenticateToEcr",
            "Effect": "Allow",
            "Action": "ecr:GetAuthorizationToken",
            "Resource": "*",
        },
        {
            "Sid": "PullPremirroredPositronImage",
            "Effect": "Allow",
            "Action": [
                "ecr:BatchCheckLayerAvailability",
                "ecr:BatchGetImage",
                "ecr:GetDownloadUrlForLayer",
            ],
            "Resource": (
                f"arn:aws:ecr:{REGION}:{POSITRON_IMAGE_ACCOUNT_ID}:"
                f"repository/{POSITRON_IMAGE_REPOSITORY}"
            ),
        },
    ],
}


@dataclass(frozen=True)
class WorkshopSettings:
    """Fixed settings for this workshop's one-command reconciler."""

    profile: str | None
    domain_name: str = DEFAULT_DOMAIN_NAME
    execution_role_name: str = DEFAULT_EXECUTION_ROLE_NAME
    app_network_access_type: str = "PublicInternetOnly"
    user_profile_name: str = "participant"
    url_expires_in_seconds: int = 300
    space_name: str = "positron-test"
    space_instance_type: str = "ml.t3.xlarge"
    app_image_config: str = DEFAULT_APP_IMAGE_CONFIG
    dry_run: bool = False


def workshop_settings() -> WorkshopSettings:
    if len(sys.argv) > 1:
        raise RuntimeError(
            "This workshop script takes no command-line options. "
            "Set AWS_PROFILE when running locally; then rerun the command."
        )
    return WorkshopSettings(profile=os.environ.get("AWS_PROFILE"))


def session_for(settings: WorkshopSettings) -> boto3.Session:
    try:
        if settings.profile:
            return boto3.Session(profile_name=settings.profile, region_name=REGION)
        return boto3.Session(region_name=REGION)
    except ProfileNotFound as exc:
        raise RuntimeError(
            f"AWS profile {settings.profile!r} was not found. "
            "In CloudShell or on the workshop EC2 instance, unset AWS_PROFILE "
            "and use the pre-authenticated session."
        ) from exc


def clients(session: boto3.Session) -> dict[str, Any]:
    config = Config(user_agent_extra=USER_AGENT, retries={"max_attempts": 8, "mode": "standard"})
    return {
        "sts": session.client("sts", config=config),
        "ec2": session.client("ec2", config=config),
        "iam": session.client("iam", config=config),
        "sagemaker": session.client("sagemaker", config=config),
    }


def aws_error(operation: str, exc: ClientError) -> RuntimeError:
    detail = exc.response.get("Error", {})
    return RuntimeError(
        f"{operation} failed: {detail.get('Code', 'AWS error')}: "
        f"{detail.get('Message', str(exc))}"
    )


def account_id(sts: Any) -> str:
    try:
        return sts.get_caller_identity()["Account"]
    except ClientError as exc:
        raise aws_error("sts:GetCallerIdentity", exc) from exc


def default_network(ec2: Any) -> tuple[str, list[str]]:
    try:
        vpcs = ec2.describe_vpcs(
            Filters=[{"Name": "isDefault", "Values": ["true"]}]
        )["Vpcs"]
        if not vpcs:
            raise RuntimeError("No default VPC exists in this workshop account.")
        vpc_id = vpcs[0]["VpcId"]
        subnets = ec2.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["Subnets"]
        subnet_ids = [
            item["SubnetId"]
            for item in sorted(subnets, key=lambda item: item.get("AvailabilityZone", ""))
        ]
        if not subnet_ids:
            raise RuntimeError(f"Default VPC {vpc_id} has no subnets.")
        return vpc_id, subnet_ids
    except ClientError as exc:
        raise aws_error("ec2:DescribeVpcs/DescribeSubnets", exc) from exc


def ensure_execution_role(
    iam: Any,
    account: str,
    role_name: str,
    dry_run: bool,
) -> tuple[str, str]:
    role_arn = f"arn:aws:iam::{account}:role/{role_name}"
    try:
        iam.get_role(RoleName=role_name)
        exists = True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise aws_error(f"iam:GetRole {role_name}", exc) from exc
        exists = False

    if not exists:
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "sagemaker.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        if dry_run:
            print(f"[dry-run] create IAM role {role_name}")
        else:
            try:
                iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="SageMaker execution role for the Positron workshop",
                )
            except ClientError as exc:
                raise aws_error("iam:CreateRole", exc) from exc

    return role_arn, role_name


def ensure_managed_policies(iam: Any, role_name: str, dry_run: bool) -> None:
    for policy_arn in MANAGED_POLICY_ARNS:
        if dry_run:
            print(f"[dry-run] attach {policy_arn} to {role_name}")
            continue
        try:
            iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_arn,
            )
        except ClientError as exc:
            policy_name = policy_arn.rsplit("/", 1)[-1]
            raise aws_error(f"iam:AttachRolePolicy {policy_name}", exc) from exc


def create_domain(
    sagemaker: Any,
    domain_name: str,
    role_arn: str,
    vpc_id: str,
    subnet_ids: list[str],
    app_network_access_type: str,
    dry_run: bool,
) -> str:
    if dry_run:
        print(
            "[dry-run] create SageMaker domain "
            f"{domain_name} in {vpc_id} using {len(subnet_ids)} subnet(s)"
        )
        return "d-dry-run"
    try:
        response = sagemaker.create_domain(
            DomainName=domain_name,
            AuthMode="IAM",
            DefaultUserSettings={"ExecutionRole": role_arn},
            VpcId=vpc_id,
            SubnetIds=subnet_ids,
            AppNetworkAccessType=app_network_access_type,
        )
    except ClientError as exc:
        raise aws_error("sagemaker:CreateDomain", exc) from exc
    return response["DomainId"]


def wait_for_domain(sagemaker: Any, domain_id: str, dry_run: bool) -> None:
    if dry_run:
        return

    print(
        f"Waiting for SageMaker domain {domain_id} to become InService "
        f"(polling every {DOMAIN_POLL_INTERVAL_SECONDS}s)...",
        flush=True,
    )
    started_at = time.monotonic()
    for attempt in range(DOMAIN_MAX_POLL_ATTEMPTS):
        domain = describe_domain(sagemaker, domain_id)
        status = domain.get("Status")
        elapsed = int(time.monotonic() - started_at)
        elapsed_minutes, elapsed_seconds = divmod(elapsed, 60)
        print(
            f"SageMaker domain {domain_id}: "
            f"status={status or 'Unknown'}; "
            f"elapsed={elapsed_minutes}m {elapsed_seconds:02d}s; "
            f"poll {attempt + 1}/{DOMAIN_MAX_POLL_ATTEMPTS}",
            flush=True,
        )
        if status == "InService":
            return
        if status in {"Failed", "Deleted", "Update_Failed"}:
            raise RuntimeError(
                f"SageMaker domain {domain_id} entered terminal status {status}: "
                f"{domain.get('FailureReason', '')}"
            )
        time.sleep(DOMAIN_POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"SageMaker domain {domain_id} did not become InService in time.")


def ensure_user_profile(
    sagemaker: Any,
    domain_id: str,
    profile_name: str | None,
    dry_run: bool,
) -> None:
    if not profile_name:
        return
    if dry_run and domain_id == "d-dry-run":
        print(f"[dry-run] create Studio user profile {profile_name}")
        return
    try:
        sagemaker.describe_user_profile(
            DomainId=domain_id, UserProfileName=profile_name
        )
        print(f"Studio user profile already exists: {profile_name}")
        wait_for_user_profile(sagemaker, domain_id, profile_name, dry_run)
        return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {
            "ValidationException",
            "ResourceNotFound",
        }:
            raise aws_error(f"sagemaker:DescribeUserProfile {profile_name}", exc) from exc
    if dry_run:
        print(f"[dry-run] create Studio user profile {profile_name}")
        return
    try:
        sagemaker.create_user_profile(
            DomainId=domain_id,
            UserProfileName=profile_name,
        )
    except ClientError as exc:
        raise aws_error("sagemaker:CreateUserProfile", exc) from exc
    wait_for_user_profile(sagemaker, domain_id, profile_name, dry_run)


def wait_for_user_profile(
    sagemaker: Any,
    domain_id: str,
    profile_name: str,
    dry_run: bool,
) -> None:
    if dry_run and domain_id == "d-dry-run":
        return
    for _ in range(60):
        try:
            profile = sagemaker.describe_user_profile(
                DomainId=domain_id,
                UserProfileName=profile_name,
            )
        except ClientError as exc:
            raise aws_error(f"sagemaker:DescribeUserProfile {profile_name}", exc) from exc
        status = profile.get("Status")
        if status == "InService":
            return
        if status in {"Failed", "Delete_Failed", "Deleted"}:
            raise RuntimeError(
                f"Studio user profile {profile_name} entered status {status}: "
                f"{profile.get('FailureReason', '')}"
            )
        time.sleep(5)
    raise RuntimeError(f"Studio user profile {profile_name} did not become InService in time.")


def describe_space(sagemaker: Any, domain_id: str, space_name: str) -> dict[str, Any] | None:
    try:
        return sagemaker.describe_space(DomainId=domain_id, SpaceName=space_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {
            "ValidationException",
            "ResourceNotFound",
        }:
            return None
        raise aws_error(f"sagemaker:DescribeSpace {space_name}", exc) from exc


def wait_for_space(
    sagemaker: Any,
    domain_id: str,
    space_name: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run and domain_id == "d-dry-run":
        return {"Status": "InService"}
    for attempt in range(90):
        space = describe_space(sagemaker, domain_id, space_name)
        if space is None:
            if attempt == 0:
                print(
                    f"SageMaker Space {space_name} is being created; "
                    "waiting for it to become visible."
                )
            time.sleep(10)
            continue
        status = space.get("Status")
        if status == "InService":
            return space
        if status in {"Failed", "Delete_Failed", "Deleted"}:
            raise RuntimeError(
                f"SageMaker Space {space_name} entered status {status}: "
                f"{space.get('FailureReason', '')}"
            )
        time.sleep(10)
    raise RuntimeError(
        f"SageMaker Space {space_name} did not become visible and InService in time."
    )


def ensure_space(
    sagemaker: Any,
    domain_id: str,
    profile_name: str,
    space_name: str,
    image_arn: str,
    image_version_arn: str,
    instance_type: str,
    dry_run: bool,
) -> None:
    existing = describe_space(sagemaker, domain_id, space_name)
    if existing:
        print(f"SageMaker Space already exists: {space_name}")
        wait_for_space(sagemaker, domain_id, space_name, dry_run)
        return

    if dry_run:
        print(f"[dry-run] create private JupyterLab Space {space_name}")
        return

    try:
        sagemaker.create_space(
            DomainId=domain_id,
            SpaceName=space_name,
            OwnershipSettings={"OwnerUserProfileName": profile_name},
            SpaceSharingSettings={"SharingType": "Private"},
            SpaceSettings={
                "AppType": "JupyterLab",
                "JupyterLabAppSettings": {
                    "DefaultResourceSpec": {
                        "InstanceType": instance_type,
                        "SageMakerImageArn": image_arn,
                        "SageMakerImageVersionArn": image_version_arn,
                    }
                }
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceInUse":
            raise aws_error("sagemaker:CreateSpace", exc) from exc
    wait_for_space(sagemaker, domain_id, space_name, dry_run)


def ensure_jupyterlab_app(
    sagemaker: Any,
    domain_id: str,
    space_name: str,
    image_arn: str,
    image_version_arn: str,
    instance_type: str,
    dry_run: bool,
) -> None:
    if dry_run and domain_id == "d-dry-run":
        print(f"[dry-run] start JupyterLab application in Space {space_name}")
        return

    try:
        apps = sagemaker.list_apps(
            DomainIdEquals=domain_id,
            SpaceNameEquals=space_name,
        ).get("Apps", [])
    except ClientError as exc:
        raise aws_error(f"sagemaker:ListApps {space_name}", exc) from exc

    existing = next(
        (
            app
            for app in apps
            if app.get("AppType") == "JupyterLab"
            and app.get("AppName") == "default"
        ),
        None,
    )
    if existing:
        status = existing.get("Status", "Unknown")
        print(f"JupyterLab application already exists: {space_name} ({status})")
        if status == "Failed":
            print(
                "WARNING: JupyterLab application is Failed. "
                "A Posit License Manager grant may be required."
            )
        return

    if dry_run:
        print(f"[dry-run] start JupyterLab application in Space {space_name}")
        return

    try:
        sagemaker.create_app(
            DomainId=domain_id,
            SpaceName=space_name,
            AppType="JupyterLab",
            AppName="default",
            ResourceSpec={
                "InstanceType": instance_type,
                "SageMakerImageArn": image_arn,
                "SageMakerImageVersionArn": image_version_arn,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceInUse":
            raise aws_error("sagemaker:CreateApp", exc) from exc
    print(f"JupyterLab application requested in Space: {space_name}")


def describe_domain(sagemaker: Any, domain_id: str) -> dict[str, Any]:
    try:
        return sagemaker.describe_domain(DomainId=domain_id)
    except ClientError as exc:
        raise aws_error(f"sagemaker:DescribeDomain {domain_id}", exc) from exc


def role_name_from_domain(domain: dict[str, Any]) -> str:
    role_arn = domain.get("DefaultUserSettings", {}).get("ExecutionRole")
    if not role_arn or ":role/" not in role_arn:
        raise RuntimeError(
            "The SageMaker domain has no usable DefaultUserSettings.ExecutionRole."
        )
    return role_arn.rsplit("/", 1)[-1]


def role_arn_from_domain(domain: dict[str, Any]) -> str:
    role_arn = domain.get("DefaultUserSettings", {}).get("ExecutionRole")
    if not role_arn:
        raise RuntimeError(
            "The SageMaker domain has no DefaultUserSettings.ExecutionRole."
        )
    return role_arn


def resolve_domain(
    sagemaker: Any,
    ec2: Any,
    iam: Any,
    account: str,
    args: WorkshopSettings,
) -> tuple[str, str, str]:
    try:
        domains = sagemaker.list_domains()["Domains"]
    except ClientError as exc:
        raise aws_error("sagemaker:ListDomains", exc) from exc

    if domains:
        if len(domains) > 1:
            ids = ", ".join(item["DomainId"] for item in domains)
            raise RuntimeError(
                f"Multiple SageMaker domains found ({ids}); workshop expects one."
            )
        domain_id = domains[0]["DomainId"]
        domain = describe_domain(sagemaker, domain_id)
        role_arn = role_arn_from_domain(domain)
        return domain_id, role_arn, role_name_from_domain(domain)

    role_arn, role_name = ensure_execution_role(
        iam, account, args.execution_role_name, args.dry_run
    )

    vpc_id, subnet_ids = default_network(ec2)

    domain_id = create_domain(
        sagemaker,
        args.domain_name,
        role_arn,
        vpc_id,
        subnet_ids,
        args.app_network_access_type,
        args.dry_run,
    )
    wait_for_domain(sagemaker, domain_id, args.dry_run)
    return domain_id, role_arn, role_name


def premirrored_image() -> tuple[str, str]:
    registry = f"{POSITRON_IMAGE_ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com"
    image_uri = f"{registry}/{POSITRON_IMAGE_REPOSITORY}:{POSITRON_IMAGE_TAG}"
    return POSITRON_IMAGE_TAG, image_uri


def image_registration(
    sagemaker: Any,
    role_arn: str,
    image_name: str,
    display_name: str,
    image_uri: str,
    app_image_config: str,
    dry_run: bool,
) -> int:
    if dry_run:
        print(f"[dry-run] create SageMaker image {image_name}")
        print(f"[dry-run] create image version from {image_uri}")
        print(f"[dry-run] create app image config {app_image_config}")
        return 1

    try:
        sagemaker.describe_image(ImageName=image_name)
        image_exists = True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {
            "ValidationException",
            "ResourceNotFound",
        }:
            raise aws_error(f"sagemaker:DescribeImage {image_name}", exc) from exc
        image_exists = False

    if not image_exists:
        try:
            sagemaker.create_image(
                ImageName=image_name,
                DisplayName=display_name,
                RoleArn=role_arn,
            )
        except ClientError as exc:
            raise aws_error("sagemaker:CreateImage", exc) from exc

    for _ in range(60):
        try:
            image_status = sagemaker.describe_image(ImageName=image_name)
        except ClientError as exc:
            raise aws_error(f"sagemaker:DescribeImage {image_name}", exc) from exc
        status = image_status.get("ImageStatus")
        if status == "CREATED":
            break
        if status in {"CREATE_FAILED", "DELETE_FAILED"}:
            raise RuntimeError(
                f"SageMaker image {image_name} entered status {status}: "
                f"{image_status.get('FailureReason', '')}"
            )
        time.sleep(5)
    else:
        raise RuntimeError(f"SageMaker image {image_name} did not become CREATED in time.")

    version = None
    try:
        versions = sagemaker.list_image_versions(ImageName=image_name).get(
            "ImageVersions", []
        )
    except ClientError as exc:
        raise aws_error("sagemaker:ListImageVersions", exc) from exc

    for item in versions:
        version_number = int(item["Version"])
        try:
            version_details = sagemaker.describe_image_version(
                ImageName=image_name,
                Version=version_number,
            )
        except ClientError as exc:
            raise aws_error(
                f"sagemaker:DescribeImageVersion {image_name}:{version_number}",
                exc,
            ) from exc
        if (
            version_details.get("BaseImage") == image_uri
            and version_details.get("ImageVersionStatus") == "CREATED"
        ):
            version = version_number
            break

    if version is None:
        try:
            result = sagemaker.create_image_version(
                ImageName=image_name, BaseImage=image_uri
            )
        except ClientError as exc:
            raise aws_error("sagemaker:CreateImageVersion", exc) from exc
        version = int(result["ImageVersionArn"].rsplit("/", 1)[-1])

    try:
        sagemaker.describe_app_image_config(AppImageConfigName=app_image_config)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {
            "ValidationException",
            "ResourceNotFound",
        }:
            raise aws_error("sagemaker:DescribeAppImageConfig", exc) from exc
        try:
            sagemaker.create_app_image_config(
                AppImageConfigName=app_image_config,
                JupyterLabAppImageConfig={},
            )
        except ClientError as create_exc:
            raise aws_error("sagemaker:CreateAppImageConfig", create_exc) from create_exc

    return version


def attach_image(
    sagemaker: Any,
    domain_id: str,
    image_name: str,
    version: int,
    app_image_config: str,
    keep_older: bool,
    dry_run: bool,
) -> None:
    if dry_run and domain_id == "d-dry-run":
        print(
            "[dry-run] attach the Positron image to the newly created domain "
            f"using app image config {app_image_config}"
        )
        return
    domain = describe_domain(sagemaker, domain_id)
    default_settings = domain.get("DefaultUserSettings") or {}
    lab_settings = default_settings.get("JupyterLabAppSettings") or {}
    existing = lab_settings.get("CustomImages") or []
    if keep_older:
        retained = [
            item
            for item in existing
            if item.get("ImageName") != image_name
        ]
    else:
        retained = [
            item
            for item in existing
            if not item.get("ImageName", "").startswith("positron-sagemaker-")
        ]
    updated = dict(default_settings)
    updated_lab = dict(lab_settings)
    updated_lab["CustomImages"] = retained + [
        {
            "ImageName": image_name,
            "ImageVersionNumber": version,
            "AppImageConfigName": app_image_config,
        }
    ]
    updated["JupyterLabAppSettings"] = updated_lab
    if dry_run:
        print(
            "[dry-run] update domain custom images:\n"
            + json.dumps(updated_lab["CustomImages"], indent=2)
        )
        return
    try:
        sagemaker.update_domain(
            DomainId=domain_id,
            DefaultUserSettings=updated,
        )
    except ClientError as exc:
        raise aws_error("sagemaker:UpdateDomain", exc) from exc


def put_license_policy(iam: Any, role_name: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] put inline policy {LICENSE_POLICY_NAME} on {role_name}")
        return
    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=LICENSE_POLICY_NAME,
            PolicyDocument=json.dumps(LICENSE_POLICY),
        )
    except ClientError as exc:
        raise aws_error("iam:PutRolePolicy", exc) from exc


def put_ecr_pull_policy(iam: Any, role_name: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] put inline policy {ECR_PULL_POLICY_NAME} on {role_name}")
        return
    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=ECR_PULL_POLICY_NAME,
            PolicyDocument=json.dumps(ECR_PULL_POLICY),
        )
    except ClientError as exc:
        raise aws_error("iam:PutRolePolicy", exc) from exc


def print_presigned_url(
    sagemaker: Any,
    domain_id: str,
    profile_name: str,
    expires_in_seconds: int,
    space_name: str | None,
    dry_run: bool,
) -> None:
    if dry_run:
        print(
            "[dry-run] print a SageMaker Studio presigned URL for "
            f"{profile_name} ({expires_in_seconds}s)"
        )
        return
    request = {
        "DomainId": domain_id,
        "UserProfileName": profile_name,
        "ExpiresInSeconds": expires_in_seconds,
    }
    if space_name:
        request["SpaceName"] = space_name
    try:
        response = sagemaker.create_presigned_domain_url(**request)
    except ClientError as exc:
        raise aws_error("sagemaker:CreatePresignedDomainUrl", exc) from exc

    url = response.get("AuthorizedUrl")
    if not url:
        raise RuntimeError(
            "SageMaker did not return an AuthorizedUrl for the Studio domain."
        )
    print()
    print("SageMaker Studio URL (open this in a browser before it expires):")
    print(url)
    print(
        "This URL is a bearer token; do not share it. "
        f"It expires in {expires_in_seconds} seconds."
    )


def sage_maker_image_name(tag: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9-]+", "-", tag).strip("-")
    name = f"positron-sagemaker-{sanitized}"
    if len(name) > 63:
        name = name[:63].rstrip("-")
    if not name:
        raise RuntimeError(f"Image tag {tag!r} produced an invalid SageMaker image name.")
    return name


def main() -> int:
    args = workshop_settings()
    session = session_for(args)
    aws = clients(session)

    account = account_id(aws["sts"])
    print(f"Account: {account}")
    print(f"Region: {REGION}")

    domain_id, role_arn, role_name = resolve_domain(
        aws["sagemaker"],
        aws["ec2"],
        aws["iam"],
        account,
        args,
    )
    print(f"Domain: {domain_id}")
    print(f"Execution role: {role_name}")

    ensure_managed_policies(aws["iam"], role_name, args.dry_run)

    tag, image_uri = premirrored_image()

    image_name = sage_maker_image_name(tag)
    display_name = f"Positron {tag}"
    print(f"Image: {image_name}")
    print(f"Image URI: {image_uri}")

    put_license_policy(aws["iam"], role_name, args.dry_run)
    put_ecr_pull_policy(aws["iam"], role_name, args.dry_run)

    version = image_registration(
        aws["sagemaker"],
        role_arn,
        image_name,
        display_name,
        image_uri,
        args.app_image_config,
        args.dry_run,
    )
    print(f"SageMaker image version: {version}")

    attach_image(
        aws["sagemaker"],
        domain_id,
        image_name,
        version,
        args.app_image_config,
        True,
        args.dry_run,
    )
    wait_for_domain(aws["sagemaker"], domain_id, args.dry_run)
    ensure_user_profile(
        aws["sagemaker"],
        domain_id,
        args.user_profile_name,
        args.dry_run,
    )
    image_arn = f"arn:aws:sagemaker:{REGION}:{account}:image/{image_name}"
    image_version_arn = (
        f"arn:aws:sagemaker:{REGION}:{account}:image-version/"
        f"{image_name}/{version}"
    )
    ensure_space(
        aws["sagemaker"],
        domain_id,
        args.user_profile_name,
        args.space_name,
        image_arn,
        image_version_arn,
        args.space_instance_type,
        args.dry_run,
    )
    ensure_jupyterlab_app(
        aws["sagemaker"],
        domain_id,
        args.space_name,
        image_arn,
        image_version_arn,
        args.space_instance_type,
        args.dry_run,
    )
    print("Positron custom image attached to the SageMaker domain.")
    print(f"Space configured: {args.space_name}")
    print_presigned_url(
        aws["sagemaker"],
        domain_id,
        args.user_profile_name,
        args.url_expires_in_seconds,
        args.space_name,
        args.dry_run,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except (RuntimeError, ClientError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
