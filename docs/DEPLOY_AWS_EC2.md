# Deploying to AWS EC2 (Docker Compose, single instance)

Design: **one EC2 instance** running Docker Compose: Caddy (automatic HTTPS) → the Flask app (gunicorn) → PostgreSQL
on the instance's EBS disk, plus a reminder loop. This is the cheapest setup that comfortably meets a **99% availability**
target (about 7 hours of downtime a month allowed) for unplanned failures, and **zero downtime for deployments**. Approximate cost: **~$20–30/month** (`t3.small`, 20–30 GiB gp3, public IPv4,
S3 pennies; prices vary by region, check the AWS Pricing Calculator).

> Status: the Compose file is validated (`docker compose config`) and CI builds the images and smoke-tests the app, but the
> AWS steps below have **not** been run end to end. Expect to adjust small things on the first deploy.

How the 99% is protected (all three are required, see section 7):
1. **EC2 auto-recovery** alarm: the instance is restarted on healthy hardware if AWS detects a failure (keeps its Elastic IP and disk).
2. **Backups:** nightly verified `pg_dump` to S3, plus daily EBS snapshots.
3. **Uptime monitor** on `/readyz` that emails you when the site is down.

**Zero-downtime deploys:** two app replicas run behind Caddy; `deploy/deploy.sh` drains and replaces them one at a time, so users
never see an error during an update. CI proves this on every push by sending continuous traffic during a deploy.

What is **not** covered: one instance means an instance failure, an OS reboot (e.g. a kernel update) or a PostgreSQL restart still
causes a short outage (a few minutes; it is recovered, not failed over). For that you need a second Availability Zone (RDS Multi-AZ,
two app nodes, a load balancer), roughly $90-120/month.

## 1. Launch the instance
- AMI Ubuntu 24.04 LTS, **`t3.small`** (2 vCPU / 2 GiB), 20–30 GiB **gp3** root volume.
- IAM **instance profile** (role) for the backups (section 5). Tag everything `Project=booking-portal`.
- Security group inbound: **22** from your IP only, **80** and **443** from anywhere. Nothing else (never 5432).
- Allocate an **Elastic IP** and point a DNS `A` record (e.g. `booking.yourdomain.com`) at it (needed for HTTPS and for auto-recovery to keep the address).
- Let containers use the instance role (metadata hop limit 2) and require IMDSv2:
  ```bash
  aws ec2 modify-instance-metadata-options --instance-id i-XXXXXXXX --http-tokens required --http-put-response-hop-limit 2
  ```

## 2. Prepare the server
```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker          # Docker (and the stack) must come back after a reboot/recovery
# Keep containers running even while the Docker daemon itself is restarted (e.g. by an automatic package upgrade)
echo '{"live-restore": true}' | sudo tee /etc/docker/daemon.json && sudo systemctl restart docker
sudo usermod -aG docker "$USER"             # log out and back in afterwards
# 1 GiB swap so a memory spike doesn't kill a container on a 2 GiB machine
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 3. Get the code and configure
```bash
sudo mkdir -p /opt/booking && sudo chown "$USER" /opt/booking
git clone https://github.com/Ryan-wong123/booking-service-telegram-bot /opt/booking && cd /opt/booking
cp .env.example .env && chmod 600 .env
```
Edit `.env` (never commit it). Generate secrets on the server:
```bash
echo "SECRET_KEY=$(openssl rand -hex 32)"; echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
```
Set at least: `APP_ENV=production`, `SECRET_KEY`, `POSTGRES_PASSWORD`, `DOMAIN`, `ACME_EMAIL`,
`APP_BASE_URL=https://your.domain`, `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` (12+ chars), `MAIL_FROM`,
`SMTP_*`, `S3_BUCKET`, `AWS_DEFAULT_REGION`, `APP_TIMEZONE`. Use **new** Zoom credentials if you enable Zoom:
the ones in the old repository history are compromised and must be revoked.

### Email with Amazon SES
1. SES console → *Verified identities* → verify your domain (best) or the `MAIL_FROM` address.
2. SES → *SMTP settings* → *Create SMTP credentials* (creates an IAM user and a **separate SMTP password**; the IAM
   secret key will not work). Put them in `SMTP_USERNAME` / `SMTP_PASSWORD`; `SMTP_HOST` is `email-smtp.<region>.amazonaws.com`.
3. New SES accounts are in the **sandbox** (verified recipients only): request *production access* before real customers use the portal.

## 4. Start it
```bash
cd /opt/booking
docker compose -f docker-compose.prod.yml up -d --build      # first start only; later updates use ./deploy/deploy.sh
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs init      # "Created super admin ..." and "Database ready."
docker compose -f docker-compose.prod.yml logs -f caddy   # certificate obtained for your domain
curl -fsS https://booking.yourdomain.com/readyz           # {"status":"ready"}
```
Log in as the super admin, create a staff user and a service, publish slots, and book as a customer to test email.
HTTPS is required: production session cookies are `Secure`, so login will not work over plain HTTP.

## 5. S3 backups
```bash
BUCKET=your-booking-backups; REGION=ap-southeast-1
aws s3api create-bucket --bucket $BUCKET --region $REGION --create-bucket-configuration LocationConstraint=$REGION
aws s3api put-public-access-block --bucket $BUCKET --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
cat > lifecycle.json <<'JSON'
{"Rules":[{"ID":"expire-old-backups","Status":"Enabled","Filter":{"Prefix":"booking/"},"Expiration":{"Days":30}}]}
JSON
aws s3api put-bucket-lifecycle-configuration --bucket $BUCKET --lifecycle-configuration file://lifecycle.json
```
Attach this policy to the **instance role** (no AWS keys are stored on the server):
```json
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:PutObject","s3:GetObject"],"Resource":"arn:aws:s3:::your-booking-backups/booking/*"},
  {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::your-booking-backups"}]}
```
Test once, then schedule it nightly at 02:30 Singapore time (18:30 UTC):
```bash
cd /opt/booking && docker compose -f docker-compose.prod.yml run --rm backup      # ends with "Backup complete: booking-....dump"
aws s3 ls s3://your-booking-backups/booking/
( crontab -l 2>/dev/null; echo '30 18 * * * cd /opt/booking && docker compose -f docker-compose.prod.yml run --rm backup >> /var/log/booking-backup.log 2>&1' ) | crontab -
```
(Create the log file first with `sudo touch /var/log/booking-backup.log && sudo chown "$USER" /var/log/booking-backup.log`.)

**Restore** is destructive (replaces current data). Rehearse it once on a scratch instance:
```bash
docker compose -f docker-compose.prod.yml run --rm --entrypoint /usr/local/bin/restore.sh backup                    # lists backups
docker compose -f docker-compose.prod.yml run --rm --entrypoint /usr/local/bin/restore.sh backup booking-20261108T183000Z.dump
```

## 6. Reminders
The `reminders` service runs `flask send-reminders` every 5 minutes and sends each reminder once (retries if SMTP fails).
Check it with `docker compose -f docker-compose.prod.yml logs --tail=20 reminders`.

## 7. Availability protections (do all three)
**a) EC2 auto-recovery** (replace the instance ID, region and, optionally, an SNS topic that emails you):
```bash
aws cloudwatch put-metric-alarm --alarm-name booking-auto-recover --namespace AWS/EC2 \
  --metric-name StatusCheckFailed_System --dimensions Name=InstanceId,Value=i-XXXXXXXX \
  --statistic Maximum --period 60 --evaluation-periods 2 --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:automate:ap-southeast-1:ec2:recover
```
Also consider an alarm on `StatusCheckFailed_Instance` with action `arn:aws:automate:ap-southeast-1:ec2:reboot`
(it recovers from a hung OS). Recovery keeps the Elastic IP and EBS data; containers restart by themselves
(`restart: unless-stopped` + Docker enabled at boot).

**b) Daily EBS snapshots** (Data Lifecycle Manager; keeps 7). Snapshots are crash-consistent: fine for disaster recovery, but the S3
dump is your clean, verified copy.
```bash
aws dlm create-default-role     # once per account, if not done before
aws dlm create-lifecycle-policy --description "booking daily" --state ENABLED \
  --execution-role-arn arn:aws:iam::ACCOUNT_ID:role/AWSDataLifecycleManagerDefaultRole \
  --policy-details '{"ResourceTypes":["VOLUME"],"TargetTags":[{"Key":"Project","Value":"booking-portal"}],
    "Schedules":[{"Name":"daily","CreateRule":{"Interval":24,"IntervalUnit":"HOURS","Times":["19:00"]},
    "RetainRule":{"Count":7},"CopyTags":true}]}'
```
(The volume must carry the `Project=booking-portal` tag.)

**c) Uptime monitor** on `https://booking.yourdomain.com/readyz` (it checks the database too), alerting your email.
UptimeRobot's free tier (5-minute checks) is enough. Route 53 health checks also work but are billed (small amount per check).
Without this you will find out about outages from your users.

## 8. Updating (zero downtime)
```bash
cd /opt/booking && git pull
./deploy/deploy.sh
```
The script builds the image while the site keeps running, applies migrations, then for each app replica in turn **drains** it
(its `/healthz` returns 503 so Caddy stops sending traffic), replaces it, waits until it is healthy and lets Caddy put it back
before touching the other. It takes about a minute and a half. Users see no errors.

Rules that keep it zero-downtime:
- **Migrations must be backward compatible** with the previous release, because old and new code run side by side while it applies.
  Add columns/tables in one release, stop using the old ones in the next, and drop them in a later one. Never rename or drop in the same release.
- Changing the Caddyfile or the Compose file is picked up by the script (`caddy reload` is graceful); recreating Caddy itself can drop
  connections for a moment, which only happens if `docker-compose.prod.yml` changed Caddy's own definition.
- To roll back: `git checkout <previous commit>` and run the script again (migrations are forward-only, which is why they must be compatible).
- Take a manual backup first for risky changes.

CI (`.github/workflows/ci.yml`) tests every push/PR, builds the images and runs the zero-downtime test, but it does not deploy to AWS;
deploying is the two commands above.

## 9. Operations
```bash
docker compose -f docker-compose.prod.yml logs -f web1 web2            # app logs (rotated: 3 x 10 MB)
docker compose -f docker-compose.prod.yml restart web1                 # restart one replica at a time to stay up
docker compose -f docker-compose.prod.yml exec web1 flask create-user EMAIL "Name" staff
docker compose -f docker-compose.prod.yml exec db psql -U booking -d booking
df -h /; docker system df                                              # watch disk; prune old images occasionally
```
- **Security updates:** `sudo apt-get update && sudo apt-get upgrade`, then reboot in a quiet period (the stack restarts itself; a reboot is the one routine action that still causes a short outage, so schedule it. Ubuntu Pro's free personal tier offers kernel Livepatch to avoid most kernel reboots). Consider `unattended-upgrades`.
- **Hardening:** keep SSH limited to your IP (or use AWS Systems Manager Session Manager instead), never expose 5432, keep `.env` at `chmod 600`.
- **Costs:** the instance, its EBS volume, snapshots, the Elastic IP (public IPv4 is billed) and S3 are charged while they exist.
- **Growing later:** move PostgreSQL to RDS (change `DATABASE_URL`, remove the `db` service), run two app nodes behind a load balancer across two AZs.
