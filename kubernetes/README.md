# Calibre Web Automated — Kubernetes Deployment

This directory contains a working, opinionated example for deploying Calibre Web Automated (CWA) to Kubernetes. It includes:

- A `Deployment` and `Service`
- Two `PersistentVolumeClaim`s for configuration and the Calibre library
- An ingest directory (hostPath by default) for automatic imports
- Optional Istio Gateway API manifests (HTTPS + redirect)

Adjust storage classes, hostnames, and paths to match your cluster.

---

## Prerequisites

- Kubernetes cluster with `kubectl` access
- Namespace (defaults to `media` in several manifests)
- Storage provisioners for RWX volumes (e.g., Longhorn, NFS)
  - Example uses `longhorn-retain` and `nfs-client` storage classes
- Optional: Istio (Gateway API) and cert-manager if using `gateway-istio.yaml`
  - GatewayClass `istio` available
  - A `ClusterIssuer` named `letsencrypt` (or update the annotation)
  - cert-manager installed with Gateway API support to auto-provision certs. See: [cert-manager documentation](https://cert-manager.io/docs/usage/gateway/)
- Optional: DIUN if you want automated image update notifications (annotation is included in the Deployment)

---

## What’s in this folder

- `deployment.yaml`: Runs `crocodilestick/calibre-web-automated:latest` on port `8083` with a single replica and `Recreate` strategy. Mounts:
  - `/config` from PVC `calibre-web-automated-config`
  - `/calibre-library` from PVC `calibre-library-pvc`
  - `/cwa-book-ingest` from a hostPath (edit this to your NAS or use a PVC)
  - Sets `PUID`, `PGID`, and `TZ`. Add any other CWA envs you need.
- `service.yaml`: ClusterIP service exposing port `8083` with selector `app.service=calibre-web-automated`.
- `pvc-config.yaml`: RWX claim for CWA config data. Uses `longhorn-retain` (100Gi) in namespace `media`.
- `pvc-library.yml`: RWX claim for the Calibre library. Uses `nfs-client` (100Gi) in namespace `media`.
- `gateway-istio.yaml` (optional): Gateway + HTTPRoutes using Gateway API. Redirects HTTP→HTTPS and terminates TLS for your hostname via cert-manager.

---

## Quick Start

1) Configure variables and paths
- Edit `deployment.yaml`:
  - Set `TZ` to your timezone and adjust `PUID`/`PGID` to match file ownership on your volumes.
  - Update the ingest `hostPath` (`/nas/path/to/import-ebooks`) to an existing path on cluster nodes (or convert to PVC — see below).
  - Optionally add more environment variables (e.g., `HARDCOVER_TOKEN`, `NETWORK_SHARE_MODE`). See “Environment variables” below.
- Edit storage classes in `pvc-*` files to match your cluster.

2) Create the namespace

```bash
kubectl create namespace media
```

3) Create PersistentVolumeClaims

```bash
kubectl apply -n media -f pvc-config.yaml -f pvc-library.yml
```

4) Deploy the app and service

```bash
kubectl apply -n media -f deployment.yaml -f service.yaml
```

5) (Optional) Expose via Istio Gateway
- Edit `kubernetes/gateway-istio.yaml`:
  - Set your hostname (e.g., `books.example.com`).
  - Ensure the `cert-manager.io/cluster-issuer` annotation references an issuer that exists (e.g., `letsencrypt`).
  - Set `certificateRefs.name` to the name of a TLS secret that cert-manager will create.
- Apply it:

```bash
kubectl apply -f kubernetes/gateway-istio.yaml
```

6) Access the UI
- Port-forward:

```bash
kubectl -n media port-forward svc/calibre-web-automated 8083:8083
```

  Then open http://localhost:8083

- Or via your Gateway/hostname once DNS and TLS are ready.

---

## Storage and Data

- `/config` (PVC: `calibre-web-automated-config`) holds application configuration and state.
- `/calibre-library` (PVC: `calibre-library-pvc`) holds the Calibre library data.
- `/cwa-book-ingest` is an ingest folder. Files dropped here are imported and then removed after processing. By default this is a `hostPath` you must edit; consider switching to a PVC if you prefer.

Note: If you use the Calibre Web Automated Book Downloader, you can mount the same ingest volume into that downloader so finished downloads are written directly into `/cwa-book-ingest` for automatic import by CWA. Make sure the PVC is Reads Write Many (`RWX`) so it can be mounted by more than one deployment. See the project: [Calibre Web Automated Book Downloader](https://github.com/calibrain/calibre-web-automated-book-downloader).

Example: switch ingest from hostPath to a PVC

```yaml
# Replace the hostPath volume in deployment.yaml with:
volumes:
  - name: calibre-web-automated-ingest
    persistentVolumeClaim:
      claimName: calibre-web-automated-ingest

# And create a matching PVC (adjust storageClassName as needed):
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: calibre-web-automated-ingest
  namespace: media
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: nfs-client
  resources:
    requests:
      storage: 50Gi
```

Note on RWX: Both example PVCs request `ReadWriteMany`. Ensure your storage supports RWX (e.g., Longhorn with share manager, or NFS). If not, use `ReadWriteOnce` or change provisioners accordingly.

---

## Networking

- `service.yaml` creates a ClusterIP on port `8083`.
- For external access you can either:
  - Use `port-forward` for local access/testing,
  - Configure an Ingress/Gateway (example uses Gateway API with Istio), or
  - Change the Service to `NodePort` or `LoadBalancer` if that suits your environment.

### Using the provided Istio Gateway (optional)
- `gateway-istio.yaml` creates:
  - A `Gateway` with HTTP (80) and HTTPS (443) listeners
  - An `HTTPRoute` that redirects HTTP→HTTPS
  - An `HTTPRoute` that routes HTTPS traffic to the `calibre-web-automated` service on port `8083`
- TLS termination: The Gateway references a secret via `certificateRefs`. You typically manage this secret using cert-manager. A minimal Certificate example:

Note: cert-manager must be deployed with Gateway API support enabled so it can watch Gateway/HTTPRoute resources and provision certificates automatically. Docs: https://cert-manager.io/docs/usage/gateway-api/

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: calibre-web-automated-cert
  namespace: media
spec:
  secretName: calibre-web-automated-tls  # must match certificateRefs.name
  dnsNames:
    - books.example.com
  issuerRef:
    kind: ClusterIssuer
    name: letsencrypt
```

Apply this after cert-manager is installed and your issuer exists.

---

## Environment variables

The example `deployment.yaml` sets:
- `PUID`, `PGID`: Run as a user/group that owns your mounted files (prevents permission errors).
- `TZ`: Your timezone.

Additional useful variables (see `docker-compose.yml` for examples):
- `HARDCOVER_TOKEN`: API key for Hardcover metadata provider.
- `NETWORK_SHARE_MODE`: `true`/`false` — optimize for network shares (disables WAL/chown, uses polling watcher).
- `CWA_WATCH_MODE`: Force `poll` or use default inotify.
- `DISABLE_LIBRARY_AUTOMOUNT`: `true/yes/1` to skip the auto-mount service at startup.

Add them under `spec.template.spec.containers[0].env` in `deployment.yaml`, e.g.:

```yaml
- name: HARDCOVER_TOKEN
  valueFrom:
    secretKeyRef:
      name: cwa-secrets
      key: hardcover_token
```

Consider using `Secret`s for sensitive values.

---

## Scaling and Updates

- The Deployment uses `strategy: Recreate` and `replicas: 1`.
  - Calibre libraries are file-based; concurrent writers risk corruption. Single replica is recommended.
- Image updates:
  - `imagePullPolicy: Always` ensures new tags are pulled on rollout.
  - DIUN annotation (`diun.enable: "true"`) is present if you run DIUN to monitor for updates.

---

## Troubleshooting

- PVC Pending:
  - Confirm your `storageClassName` exists and supports `ReadWriteMany`.
  - Change to an available class or adjust access modes.
- Permission denied / read-only:
  - Ensure `PUID`/`PGID` match ownership of files on the backing storage.
  - For NFS, verify export permissions (e.g., `no_root_squash` if needed).
- Pod CrashLoopBackOff:
  - `kubectl -n media logs deploy/calibre-web-automated` to inspect errors.
- Gateway returns 404:
  - Verify hostname matches the request and `HTTPRoute` `parentRefs` section names.
  - Check the `GatewayClass` exists and is `Accepted` by Istio.
- TLS not provisioning:
  - Ensure cert-manager is installed, issuer/ClusterIssuer exists, and a `Certificate` resource was created pointing to your DNS name.
- Ingest not working / files not removed:
  - Confirm the ingest volume path is correct and writable; check CWA settings in the UI.

---

## Uninstall

Delete resources (PVCs may retain data depending on your storage policy):

```bash
kubectl delete -n media -f service.yaml -f deployment.yaml
kubectl delete -n media -f pvc-config.yaml -f pvc-library.yml
# If used:
kubectl delete -f gateway-istio.yaml
```

If your storage class uses a Retain policy, delete PVs or underlying data as appropriate.

---

## Notes and Recommendations

- Replace `hostPath` for ingest with a PVC or CSI-backed volume when possible; `hostPath` ties you to a node path.
- Keep replicas at 1 unless you fully understand the implications for Calibre’s file-based library.
- Consider resource requests/limits in `deployment.yaml` for more predictable scheduling.
- Back up `/config` and your library regularly.
