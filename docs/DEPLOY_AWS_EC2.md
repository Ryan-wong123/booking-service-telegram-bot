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
```
(Alternative: push to Amazon ECR and add an image pull secret; then set `newName` in `k8s/kustomization.yaml`.)

## 4. Set your domain
Edit `k8s/ingress.yaml` and replace `booking.example.com`.

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
# Optional Zoom: add --from-literal=ZOOM_ACCOUNT_ID=... ZOOM_CLIENT_ID=... ZOOM_CLIENT_SECRET=...
```
Use **new** Zoom credentials: the ones in the old repo history are compromised and must be revoked.

## 6. Deploy
```bash
sudo k3s kubectl apply -k k8s/
sudo k3s kubectl -n booking rollout status statefulset/postgres
sudo k3s kubectl apply -f k8s/init-job.yaml          # creates tables + the first super admin
sudo k3s kubectl -n booking logs job/booking-init-db
sudo k3s kubectl -n booking get pods
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
sudo k3s kubectl apply -k k8s/                 # rolling update, zero downtime (2 replicas)
sudo k3s kubectl -n booking rollout status deploy/booking-web
```
If a release adds **tables**, re-run the init job (`kubectl -n booking delete job booking-init-db --ignore-not-found` then
`apply -f k8s/init-job.yaml`). If it changes **existing columns**, you need a real migration tool first (see README).

## 9. Operations
```bash
sudo k3s kubectl -n booking logs deploy/booking-web --tail=100 -f
sudo k3s kubectl -n booking scale deploy/booking-web --replicas=3   # the HPA also scales 2-4 on CPU
sudo k3s kubectl -n booking rollout restart deploy/booking-web
sudo k3s kubectl -n booking exec -it deploy/booking-web -- flask --app wsgi create-user EMAIL "Name" staff
```
- **Backups:** `k8s/backup-cronjob.yaml` writes nightly `pg_dump` files to a PVC *on the same disk*. That does not survive losing the
  instance: copy dumps to S3, take EBS snapshots, or use RDS. Test a restore.
- **Hardening:** keep SSH to your IP, enable automatic security updates, and consider AWS Systems Manager Session Manager instead of open SSH.
- **Costs:** the instance, its EBS volume and the Elastic IP are billed while they exist.
