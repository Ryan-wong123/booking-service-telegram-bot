# Deploying to AWS EC2 with Docker and Kubernetes

Design: **one EC2 instance running k3s** (a lightweight, certified Kubernetes distribution). Docker builds the image,
k3s runs it. Two web replicas, PostgreSQL in the cluster, Traefik ingress (bundled with k3s).

> Status: the manifests are syntactically validated and the app/container command was exercised locally, but the Docker
> image build and the AWS deployment have **not** been run for you. Expect to adjust things on first deploy.

For a multi-node or production-grade setup consider Amazon EKS + RDS + ALB instead; the same image and most manifests
carry over (drop `postgres.yaml`, point `DATABASE_URL` at RDS).

## 1. Launch the instance
- AMI Ubuntu 24.04 LTS, `t3.medium` (2 vCPU / 4 GiB) or larger, 30 GiB gp3 disk.
- Security group inbound: **22** from your IP only, **80** and **443** from anywhere. Nothing else (not 5432, not 6443).
- Allocate an **Elastic IP** and point a DNS `A` record (e.g. `booking.yourdomain.com`) at it.

## 2. Install Docker and k3s
```bash
sudo apt-get update && sudo apt-get install -y docker.io git
curl -sfL https://get.k3s.io | sh -
sudo k3s kubectl get nodes        # should show Ready
```

## 3. Get the code and build the image
```bash
git clone <your repo URL> booking-portal && cd booking-portal
git checkout web-portal           # or main once merged
sudo docker build -t booking-portal:1.0.0 .
sudo docker save booking-portal:1.0.0 | sudo k3s ctr images import -
sudo docker build -t booking-backup:1.0.0 backup/       # image for the nightly S3 backup job
sudo docker save booking-backup:1.0.0 | sudo k3s ctr images import -
```
(Alternative: push to Amazon ECR and add an image pull secret; then set `newName` in `k8s/kustomization.yaml`.)

## 4. Configure your domain, email and backup bucket
- `k8s/ingress.yaml`: replace `booking.example.com`.
- `k8s/configmap.yaml`: set `APP_BASE_URL` (your https URL, used in email links), `MAIL_FROM`, `SMTP_HOST`
  (SES endpoint for your region), `S3_BUCKET` and `AWS_DEFAULT_REGION`.

### Email with Amazon SES
1. SES console → *Verified identities* → verify your domain (best) or the `MAIL_FROM` address.
2. SES → *SMTP settings* → *Create SMTP credentials* (this makes an IAM user and a **separate SMTP password**; the
   IAM secret key will not work). Put them in the secret below as `SMTP_USERNAME` / `SMTP_PASSWORD`.
3. New SES accounts are in the **sandbox**: you can only send to verified addresses. Request *production access*
   (SES → *Account dashboard*) before real customers use the portal.
4. Port 587 outbound is allowed from EC2 by default (port 25 is throttled, so we don't use it).

### S3 backups
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
Attach this policy to the **EC2 instance's IAM role** (the pods use it; no AWS keys are stored in the cluster):
```json
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:PutObject","s3:GetObject"],"Resource":"arn:aws:s3:::your-booking-backups/booking/*"},
  {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::your-booking-backups"}]}
```
Pods reach the instance role through the metadata service, which needs a hop limit of 2 for containers:
```bash
aws ec2 modify-instance-metadata-options --instance-id i-XXXXXXXX --http-tokens required --http-put-response-hop-limit 2
```

## 5. Create the namespace and secrets (never commit these)
```bash
sudo k3s kubectl apply -f k8s/namespace.yaml
read -rsp "Super admin password (12+ chars): " ADMINPW; echo
PGPW=$(openssl rand -hex 16)
sudo k3s kubectl -n booking create secret generic booking-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=POSTGRES_PASSWORD="$PGPW" \
  --from-literal=DATABASE_URL="postgresql://booking:$PGPW@postgres:5432/booking" \
  --from-literal=SUPERADMIN_EMAIL="you@yourdomain.com" \
  --from-literal=SUPERADMIN_PASSWORD="$ADMINPW"
  --from-literal=SMTP_USERNAME="..." --from-literal=SMTP_PASSWORD="..."
# Optional Zoom: add --from-literal=ZOOM_ACCOUNT_ID=... ZOOM_CLIENT_ID=... ZOOM_CLIENT_SECRET=...
```
Use **new** Zoom credentials: the ones in the old repo history are compromised and must be revoked.

## 6. Deploy
```bash
sudo k3s kubectl apply -k k8s/
sudo k3s kubectl -n booking rollout status statefulset/postgres
sudo k3s kubectl apply -f k8s/init-job.yaml          # applies migrations + creates the first super admin
sudo k3s kubectl -n booking logs job/booking-init-db
sudo k3s kubectl -n booking get pods
```
`kubectl apply -k` also creates two CronJobs: `booking-reminders` (every 10 min) and `pg-backup` (nightly).
Test them right away instead of waiting:
```bash
sudo k3s kubectl -n booking create job --from=cronjob/pg-backup backup-test
sudo k3s kubectl -n booking logs -f job/backup-test       # ends with "Backup complete: booking-....dump"
aws s3 ls s3://your-booking-backups/booking/
sudo k3s kubectl -n booking create job --from=cronjob/booking-reminders reminders-test
sudo k3s kubectl -n booking logs job/reminders-test       # "Sent N reminder(s)."
```
Visit `http://booking.yourdomain.com` once DNS resolves.

## 7. HTTPS (do this before real use)
The app sets `Secure` session cookies in production, so **login only works over HTTPS** (or set
`SESSION_COOKIE_SECURE: "false"` in `k8s/configmap.yaml` for a temporary HTTP test).

With cert-manager and Let's Encrypt:
```bash
sudo k3s kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.yaml
```
```yaml
# clusterissuer.yaml  (set your email)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata: { name: letsencrypt }
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: you@yourdomain.com
    privateKeySecretRef: { name: letsencrypt-key }
    solvers:
      - http01: { ingress: { ingressClassName: traefik } }
```
Then add to `k8s/ingress.yaml`:
```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  tls:
    - hosts: [booking.yourdomain.com]
      secretName: booking-tls
```
and `sudo k3s kubectl apply -f clusterissuer.yaml -f k8s/ingress.yaml`.

## 8. Updating
```bash
git pull
sudo docker build -t booking-portal:1.0.1 .
sudo docker save booking-portal:1.0.1 | sudo k3s ctr images import -
# bump newTag in k8s/kustomization.yaml to 1.0.1, then:
sudo k3s kubectl -n booking delete job booking-init-db --ignore-not-found
sudo k3s kubectl apply -f k8s/init-job.yaml            # applies any new migrations first
sudo k3s kubectl -n booking wait --for=condition=complete job/booking-init-db --timeout=120s
sudo k3s kubectl apply -k k8s/                         # rolling update, zero downtime (2 replicas)
sudo k3s kubectl -n booking rollout status deploy/booking-web
```
Migrations run **before** the new pods, so keep each migration backward compatible with the previous release
(add columns before using them; remove them a release later). Take a backup first for risky changes (see below).
CI (`.github/workflows/ci.yml`) runs the tests, builds the images and checks the migrations on every push/PR;
deploying is still the manual steps above. To publish images to ECR automatically, set the repository variables
`AWS_ROLE_ARN`, `AWS_REGION` and `ECR_REPOSITORY` (IAM role trusting GitHub OIDC).

## 9. Operations
```bash
sudo k3s kubectl -n booking logs deploy/booking-web --tail=100 -f
sudo k3s kubectl -n booking scale deploy/booking-web --replicas=3   # the HPA also scales 2-4 on CPU
sudo k3s kubectl -n booking rollout restart deploy/booking-web
sudo k3s kubectl -n booking exec -it deploy/booking-web -- flask --app wsgi create-user EMAIL "Name" staff
```
- **Backups / restore:** the nightly job uploads a verified dump to S3 (30-day lifecycle above). Restore is destructive,
  so do it deliberately, and rehearse it once on a scratch database:
  ```bash
  sudo k3s kubectl -n booking run restore --rm -it --restart=Never --image=booking-backup:1.0.0 \
    --image-pull-policy=IfNotPresent --command -- /usr/local/bin/restore.sh      # lists backups
  # then, with the chosen file (needs env: S3_BUCKET, PGHOST=postgres, PGPASSWORD from the secret):
  #   restore.sh booking-20261108T183000Z.dump
  ```
  For a fresh node: redeploy, then restore into the new database before opening it to users.
- **Reminders:** inspect with `kubectl -n booking get cronjob,jobs`; failures show in `kubectl -n booking logs job/<name>`.
  If SMTP is down, reminders are retried automatically on the next run until the appointment starts.
- **Hardening:** keep SSH to your IP, enable automatic security updates, and consider AWS Systems Manager Session Manager instead of open SSH.
- **Costs:** the instance, its EBS volume and the Elastic IP are billed while they exist.
