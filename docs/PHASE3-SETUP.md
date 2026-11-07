# Phase 3 environment setup (Windows → WSL2 → Containerlab)

Phase 3 is the only part of this project that cannot run on Windows. Containerlab
creates veth pairs and network namespaces; that needs a real Linux kernel.

**The single most common failure**, and the reason this document exists:
Docker Desktop's WSL integration does **not** create `docker0` inside the distro,
so Containerlab fails with `Link not found`. Use a plain Ubuntu WSL distro with
docker-ce installed natively, and disable Docker Desktop integration for it.
Batfish can keep running under Docker Desktop on the Windows side — the two are
independent.

## 1. A dedicated distro

```powershell
wsl --install -d Ubuntu-22.04 --name clab
wsl -d clab
```

In **Docker Desktop → Settings → Resources → WSL Integration**, make sure the
`clab` distro is **OFF**. Verify inside the distro:

```bash
docker version    # must say "command not found" BEFORE step 2
```

If it prints a Docker Desktop client, integration is still on. Fix it first —
everything after this will fail in confusing ways otherwise.

## 2. docker-ce and Containerlab

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
sudo service docker start
docker run --rm hello-world

bash -c "$(curl -sL https://get.containerlab.dev)"
containerlab version
```

**The domain is `get.containerlab.dev`. Not `.net`.** And note the trap: with
`curl -sL`, a DNS failure produces an EMPTY string, so `bash -c ""` runs
nothing and exits 0. The install looks like it worked and `containerlab` is
simply absent. Use `curl -fsSL` if you want the failure to be loud.

If DNS or a GitHub rate limit gets in the way, install the package directly:

```bash
LATEST=$(curl -s https://api.github.com/repos/srl-labs/containerlab/releases/latest \
         | grep -oP '"tag_name": "v\K[^"]+')
curl -sL -o /tmp/clab.deb \
  "https://github.com/srl-labs/containerlab/releases/download/v${LATEST}/containerlab_${LATEST}_linux_amd64.deb"
sudo dpkg -i /tmp/clab.deb
```

`sudo service docker start` is needed after every WSL restart — systemd is often
not running.

## 3. Images (pull once, ~2 GB total)

```bash
docker pull frrouting/frr:v8.4.1
docker pull alpine:3.19
```

Note the `v` prefix and the registry: it is Docker Hub `frrouting/frr:v8.4.1`,
not `quay.io/frrouting/frr:8.4.4`. That earlier value was never verified against
a registry and does not exist. `frrouting/frr` has published nothing newer than
v8.4.1 (Dec 2022); the image line is dormant, which is fine for a lab and worth
one sentence in the paper's reproducibility notes.

Phase 3 preflight resolves and records the RepoDigest of both images into
`run_metadata.json`, so the exact bytes are captured even though the artifact
pins only a tag.

## 3b. Containerlab needs root — decide how

Containerlab creates veth pairs and network namespaces, so it requires sudo.
The orchestrator detects this: as root it calls `containerlab` directly,
otherwise it prefixes `sudo -n`. `-n` is non-interactive deliberately — a
password prompt in the middle of an unattended 61-lab run would hang forever
instead of failing.

**Simplest: run the whole thing as root.**

```bash
sudo -E python3 pipeline/run_phase3.py --workdir /root/nrl-run --preflight-only
```

**Or grant passwordless sudo for containerlab only:**

```bash
echo "$USER ALL=(ALL) NOPASSWD: $(which containerlab)" \
  | sudo tee /etc/sudoers.d/nrl-clab
```

Preflight tests whichever path applies and fails before anything is deployed.

## 3c. No virtualenv here

Phase 3 is pure standard library — no pandas, no pyyaml, no pybatfish. Use WSL's
system `python3`. The repo's `.venv` is a **Windows** venv (`.venv/Scripts/`)
and cannot be used from Linux; do not try to activate it here. Phases 1 and 2
still use it on the Windows side.

## 4. Memory

`.wslconfig` in `C:\Users\karth\`:

```ini
[wsl2]
memory=10GB
processors=4
```

Written for pilot-v1's six-router network. **The 20-topology design goes to 16
routers**: `t19_dualcore16` deploys 16 FRR containers plus three alpine, 19 in
total, at roughly 60–100 MB each — about 1.5 GB, still comfortable inside 10 GB.
`t16_pop14` is 14 routers and `t17_metro13` is 13. Only one lab runs at a time,
so the peak is one topology, not the sum. WSL2 otherwise claims about half of
system RAM by default.

## 5. Run from the repo, stage to native Linux

```bash
cd /mnt/c/Users/karth/network-research-lab
python3 pipeline/run_phase3.py --preflight-only
```

The orchestrator reads the artifacts from `/mnt/c/...` and **copies** each one
into `~/nrl-run/<run_id>/` before deploying. That copy is not a weakening of the
same-artifact guarantee: every staged file is re-hashed against
`pilot.lock.json` and a mismatch aborts the run before anything is deployed.

Bind-mounting straight off `/mnt/c` into containers is slow and has permission
quirks, which is why the copy exists at all. Keep `--workdir` on the native
filesystem.

## 6. If a run leaves containers behind

```bash
containerlab destroy --all --cleanup
docker ps -a | grep clab-nrl-
```

`verify_phase3.py` CHECK 11 fails if any `clab-nrl-*` container is still running,
because a leaked lab steals veths and interface names from the next one.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Link not found` on deploy | Docker Desktop WSL integration | disable it for this distro, install docker-ce |
| `Cannot connect to the Docker daemon` | dockerd not started | `sudo service docker start` |
| `permission denied` on the socket | user not in `docker` group | `sudo usermod -aG docker $USER && newgrp docker` |
| preflight: "running on Linux" fails | ran Windows Python | run inside `wsl -d clab` |
| every lab NO_CONVERGENCE | daemons file not applied, or images missing | check `docker logs clab-nrl-golden-corea` |
| staging hash mismatch | pilot rebuilt after the spike | re-run build → verify → spike, then Phase 3 |
