# HANDOFF — Complete AC-01-04 (Fargate/Playwright locality smoke test)

**From:** P1 (Vanshika) **To:** P4 **Date:** 2026-09-20
**WP:** WP-01 (cloud viability checkpoint) · **Branch:** `feat/wp-01-cloud-viability-checkpoint-p4`
**Blocking:** AC-01-10 (final checkpoint decision) — currently a *conditional* pass, blocked only on this AC.

Read this fully before running anything. It tells you exactly what is already
deployed, what is broken, and the exact command sequence to finish AC-01-04 —
plus the mandatory teardown so we don't leave a billed resource running.

## 1. What AC-01-04 actually requires

Per `docs/specs/WP-01-cloud-viability-checkpoint.md`: run P2's Playwright/agent
container as a one-off ECS Fargate task, hit it for two different pincodes in
different localities, and confirm the response differs in a way that proves
the browser really re-resolved locality server-side (not a cached/fixture
result) — specifically, Blinkit's `merchant_zone_id` (a different dark-store
ID per pincode) and `address_hint` (a different resolved address string), plus
actually-different served content. Record everything in
`docs/evidence/checkpoint.md`.

## 2. What's already deployed (do NOT redeploy from scratch)

Stack `proofpath-checkpoint`, region `ap-south-1`, account `780891108112`,
deployed via `sam deploy` from `infra/template.yaml` this session. Relevant
outputs (`aws cloudformation describe-stacks --stack-name proofpath-checkpoint
--region ap-south-1 --query "Stacks[0].Outputs"` reproduces this):

| Resource | Value |
| --- | --- |
| ECR repo (push the built image here) | `780891108112.dkr.ecr.ap-south-1.amazonaws.com/proofpath-checkpoint-agent` |
| ECS cluster | `proofpath-checkpoint-agent` |
| ECS task definition ARN | `arn:aws:ecs:ap-south-1:780891108112:task-definition/proofpath-checkpoint-agent:1` |
| Security group (no baked-in ingress — see step 5) | `sg-07d498dbcbed27b09` |
| S3 evidence bucket | `proofpath-checkpoint-evidence-780891108112` |
| Public subnets used for `awsvpcConfiguration` | `subnet-0bb0ca4526dbcd8c2`, `subnet-0c07d318c76306d9a`, `subnet-0c12e5942b25c866b` |
| VPC | `vpc-09ea2b33ec846aaa9` (account default VPC) |

Task execution role and task role are least-privilege (ECR pull + log write
only; S3 `PutObject` to the evidence bucket only, respectively) — see
`infra/template.yaml`'s `CheckpointAgentTaskExecutionRole` /
`CheckpointAgentTaskRole` if you need to check scopes.

**Before you do anything else**, these files are modified locally on P1's
machine and were never committed/pushed (needed for the infra to be
reproducible / for anyone else to `sam deploy` this stack again):

- `infra/template.yaml` (the AC-01-04 resources above)
- `infra/samconfig.toml` (deploy parameters: `CAPABILITY_NAMED_IAM`, the VPC/subnet overrides)
- `services/merchants/evidence.py` (new `S3EvidenceSink` / `build_evidence_sink()`)
- `services/merchants/registry.py` (wires `build_evidence_sink()` into the live registry)
- `tests/unit/test_evidence_sink.py` (new, untracked — 4 passing tests for the above)
- `docs/STATUS.md` (the blocker note from step 3, below)

Ask P1 to commit/push these (or pull her branch) before you start, so your
work and hers don't diverge.

## 3. The actual blocker — two separate, unrelated failures

We got as far as deploying the infra above, then tried to build P2's
container and could not get an image into ECR. Two distinct problems hit in
the same `docker build --platform linux/amd64 -f services/agent/Dockerfile .`
attempt:

### 3a. Real dependency bug in `services/agent/requirements.txt` (P2-owned file)

`websockets==17.1` requires Python ≥3.11. Pip could not resolve it against
the pinned base image `mcr.microsoft.com/playwright/python:v1.49.0-jammy`,
meaning that image's Python is older than 3.11:

```
ERROR: Ignored the following versions that require a different python version: ... 17.1 Requires-Python >=3.11
ERROR: Could not find a version that satisfies the requirement websockets==17.1
ERROR: No matching distribution found for websockets==17.1
```

This is outside P1's/P4's ownership area (`services/agent/**` is P2's) — **loop
in P2** to either bump the base image to one with Python ≥3.11, or relax the
`websockets` pin to a version compatible with the current base image's
Python. Confirm the image's actual Python version first:

```bash
docker run --rm --platform linux/amd64 mcr.microsoft.com/playwright/python:v1.49.0-jammy python3 --version
```

### 3b. Local Docker Desktop failure (P1's machine only, not a repo defect)

Independently, on top of 3a, the same build attempt hit:

```
ERROR: error committing ...: write /var/lib/docker/buildkit/containerd-overlayfs/metadata_v2.db: read-only file system
```

Traced to P1's Mac disk being at 99% capacity (288MB free of 228GB) — Docker's
build cache couldn't write. This is a local-environment issue, not something
in code. If you hit the same error on your own machine, check `df -h /` and
free space or prune Docker's own reclaimable cache (`docker system prune`)
before retrying.

## 4. Once P2's fix lands — build and push the image

From the repo root, after pulling P2's fix:

```bash
docker build --platform linux/amd64 -f services/agent/Dockerfile -t proofpath-checkpoint-agent:latest .

aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin 780891108112.dkr.ecr.ap-south-1.amazonaws.com

docker tag proofpath-checkpoint-agent:latest \
  780891108112.dkr.ecr.ap-south-1.amazonaws.com/proofpath-checkpoint-agent:latest

docker push 780891108112.dkr.ecr.ap-south-1.amazonaws.com/proofpath-checkpoint-agent:latest
```

## 5. Open a temporary ingress rule for your own IP (and only yours)

The security group has egress-only by default, deliberately, so it's not
sitting open between tests. Add a rule scoped to your current public IP only:

```bash
MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress \
  --group-id sg-07d498dbcbed27b09 \
  --protocol tcp --port 8080 \
  --cidr "${MY_IP}/32" \
  --region ap-south-1
```

Remember the exact rule you added — you'll revoke it in step 9.

## 6. Run the one-off Fargate task

```bash
aws ecs run-task \
  --cluster proofpath-checkpoint-agent \
  --task-definition arn:aws:ecs:ap-south-1:780891108112:task-definition/proofpath-checkpoint-agent:1 \
  --launch-type FARGATE \
  --network-configuration '{
    "awsvpcConfiguration": {
      "subnets": ["subnet-0bb0ca4526dbcd8c2","subnet-0c07d318c76306d9a","subnet-0c12e5942b25c866b"],
      "securityGroups": ["sg-07d498dbcbed27b09"],
      "assignPublicIp": "ENABLED"
    }
  }' \
  --region ap-south-1
```

Poll until `RUNNING`, then get the task's public IP:

```bash
TASK_ARN=<taskArn from run-task output>

aws ecs wait tasks-running --cluster proofpath-checkpoint-agent --tasks "$TASK_ARN" --region ap-south-1

ENI_ID=$(aws ecs describe-tasks --cluster proofpath-checkpoint-agent --tasks "$TASK_ARN" \
  --region ap-south-1 --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text)

PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI_ID" \
  --region ap-south-1 --query "NetworkInterfaces[0].Association.PublicIp" --output text)

echo "$PUBLIC_IP"
```

## 7. Run the differential locality smoke test

Confirm health first:

```bash
curl -s "http://${PUBLIC_IP}:8080/health"
```

Then hit `/tasks/search` for two different localities with the same real,
Blinkit-searchable item (`milk` confirmed working earlier this session):

```bash
# Delhi
curl -s -X POST "http://${PUBLIC_IP}:8080/tasks/search" \
  -H "Content-Type: application/json" \
  -d '{"location":{"locality":"Connaught Place","pincode":"110001"},"item":{"name":"milk","quantity":1,"unit":"l"},"mode":"live"}'

# Mumbai
curl -s -X POST "http://${PUBLIC_IP}:8080/tasks/search" \
  -H "Content-Type: application/json" \
  -d '{"location":{"locality":"Fort","pincode":"400001"},"item":{"name":"milk","quantity":1,"unit":"l"},"mode":"live"}'
```

(If `PROOFPATH_AGENT_TOKEN` is set on the task, add
`-H "Authorization: Bearer <token>"` — check the task definition's env if the
request is rejected.)

**Compare and record in `docs/evidence/checkpoint.md`:**

- `merchant_zone_id` must differ between the two responses (earlier live
  testing this session confirmed real values: `34748` for `110001` vs.
  `49585` for `400001` — expect similar, not necessarily identical, since
  Blinkit's zone mapping can change).
- `address_hint` must show a real, different resolved address per pincode.
- Actual served content (price/availability) should differ.
- If Blinkit blocks the request (CAPTCHA, Cloudflare 403, etc.), **record that
  honestly as the AC-01-04 result** — do not retry around it or substitute
  fixture data. That's a legitimate documented outcome per the spec's
  block/CAPTCHA/error honesty rule.

Evidence (screenshots) should land in the S3 bucket
`proofpath-checkpoint-evidence-780891108112` — check
`aws s3 ls s3://proofpath-checkpoint-evidence-780891108112/ --recursive` after
each request and reference the keys in `checkpoint.md`.

## 8. Stop the task immediately after capturing evidence — non-negotiable

AC-01-09 requires no hourly-billed resource left standing past its
verification window. As soon as you have both responses and the evidence
bucket keys:

```bash
aws ecs stop-task --cluster proofpath-checkpoint-agent --task "$TASK_ARN" --region ap-south-1
```

## 9. Revoke the temporary ingress rule

```bash
aws ec2 revoke-security-group-ingress \
  --group-id sg-07d498dbcbed27b09 \
  --protocol tcp --port 8080 \
  --cidr "${MY_IP}/32" \
  --region ap-south-1
```

## 10. Write up and close out

- Fill in AC-01-04's section of `docs/evidence/checkpoint.md` with the real
  commands run, their exact output, and the S3 evidence keys — matching the
  rigor of the other AC sections already in that file. Never write an
  unearned "PASS."
- Once AC-01-04 is genuinely done (pass or an honestly-documented block),
  update AC-01-10's checkpoint decision from "conditional pass, blocked on
  AC-01-04" to either a full unconditional pass, or the honest blocker if it
  didn't succeed.
- Commit your changes, but confirm with P1 before pushing/merging (per the
  session's standing rule — self-merge exception from `docs/STATUS.md` still
  requires a green required-checks run first).

## Known non-blockers, don't re-investigate these

- The two `W3660` cfn-lint warnings on `GatewayResponse` resources in
  `sam validate --lint` are pre-existing, documented, accepted (see
  `docs/STATUS.md`'s WP-01 row).
- `build`/`web-smoke` CI jobs' AWS OIDC path is fixed and green (PR #13,
  merged) — unrelated to this task.
