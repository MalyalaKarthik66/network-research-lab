# Phase 1 — Batfish Foundations and Formal Network Verification

**Lab manual. Read one module, run it, verify it, then move on.**

Everything in this manual has already been written to disk. You are not copying
code out of a document — the files exist. Your job is to run them, read the
output, and understand why the output is what it is.

---

## How to use this manual

Each module has the same thirteen sections. Two of them are not optional and
people skip them anyway:

- **Verification** — the module's script ends with `ALL CHECKS PASSED` or it
  lists exactly which check failed. Do not advance past a module with a failing
  check unless you can explain in `notes/surprises.md` why the manual is wrong.
- **Mini exercise** — you edit a config yourself and predict the result before
  running it. Prediction first, always. A prediction you got wrong teaches you
  something; an output you merely read teaches you nothing.

**Rule for the whole phase:** write the prediction down before you run the
command. In `notes/lab-notebook.md`. Every time.

---

## Repository layout

```
network-research-lab/
├── README.md
├── .gitignore
├── notes/
│   ├── lab-notebook.md          dated session log — write every session
│   └── surprises.md             every unpredicted result
└── batfish/
    ├── requirements.txt
    ├── docs/
    │   └── PHASE1-MANUAL.md     this file
    ├── scripts/
    │   ├── bf_common.py         shared plumbing: session, snapshot, sanity gate
    │   ├── m01_smoke_test.py
    │   ├── m03_snapshots.py
    │   ├── m04_basic_verification.py
    │   ├── m05_routing_analysis.py
    │   ├── m06_forwarding_analysis.py
    │   ├── m07_acl_verification.py
    │   ├── m08_config_validation.py
    │   ├── m09_corp_verify.py
    │   ├── m09_frr_spike.py
    │   ├── m10_limitations.py
    │   └── run_all.py           run every module, print one summary table
    └── snapshots/
        ├── m03-trio-static/         3 routers, static routes only
        ├── m05-trio-ospf/           same topology, OSPF
        ├── m05-trio-bgp/            same topology, three eBGP autonomous systems
        ├── m06-trio-ecmp/           OSPF + a second equal-cost link
        ├── m06-trio-blackhole/      OSPF + a static route into Null0
        ├── m07-acl-good/            the ACL policy that was intended
        ├── m07-acl-bad/             the ACL policy that was written
        ├── m08-broken-subnet/       an IP address typo
        ├── m08-broken-refs/         an undefined ACL and an orphaned ACL
        ├── m08-broken-bgp-as/       a wrong BGP remote-as
        ├── m09-corp-base/           our own 4-router network, healthy
        ├── m09-corp-acl-typo/       our network, one wildcard mask wrong
        ├── m09-corp-link-down/      our network, primary link shut
        ├── m10-acl-blocks-ospf/     an ACL that breaks OSPF in reality but not
        │                            in the model
        └── m10-frr-spike/           the same trio in FRRouting format
```

Every snapshot has the same shape:

```
<snapshot-name>/
├── configs/                     mandatory folder name, one file per device
│   ├── r1.cfg
│   ├── r2.cfg
│   └── r3.cfg
└── batfish/                     optional
    └── layer1_topology.json     explicit cabling (only the m09 snapshots)
```

---

# MODULE 1 — The Batfish environment

## 1. Learning objective

A running Batfish service, a Python environment that can talk to it, and a
correct mental model of which piece does what.

## 2. Why we are doing it

Every later module fails in confusing ways if the environment is subtly wrong.
Ten minutes here saves a day in Module 5. Specifically: if the ports are not
published, every question hangs; if `pybatfish` and the service are far apart in
version, some questions silently return different column names.

## 3. Theory — the architecture

Four pieces. Know which one you are talking to at any moment.

```
  YOU
   │  python m04_basic_verification.py
   ▼
 ┌──────────────────────────────────────────────────────────┐
 │ pybatfish (a Python library on your laptop)              │
 │   • builds JSON requests                                 │
 │   • turns JSON answers into pandas DataFrames            │
 │   • holds NO network knowledge whatsoever                │
 └──────────────────┬───────────────────────────────────────┘
                    │  HTTP, port 9996 (and 9997)
                    ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Batfish service (Java, inside the Docker container)      │
 │   • parses vendor configs                                │
 │   • builds the vendor-independent model                  │
 │   • simulates the control plane to convergence           │
 │   • derives the data plane                               │
 │   • answers questions with a constraint solver           │
 └──────────────────┬───────────────────────────────────────┘
                    │
                    ▼
 ┌──────────────────────────────────────────────────────────┐
 │ /data inside the container (the named volume)            │
 │   • every network and snapshot you have ever created     │
 │   • survives container restarts, dies with the volume    │
 └──────────────────────────────────────────────────────────┘

 Jupyter (port 8888, also inside the allinone container) is a fourth,
 independent thing: a browser front end with the official example notebooks.
 It is convenient for exploring. It is not where your work lives.
```

The vocabulary matters and people get it wrong constantly:

| Term | What it is |
|---|---|
| **network** | A namespace. Holds many snapshots. Differential questions only work between snapshots **in the same network**. We use one network, `phase1`, for all of Phase 1. |
| **snapshot** | A folder of configuration text, plus whatever Batfish derived from it. |
| **question** | A named query, e.g. `routes`, `reachability`. Always returns a pandas DataFrame. |
| **control plane** | The simulated routing protocols. Output: a RIB per VRF per node. |
| **data plane** | The forwarding tables derived from the RIBs. Needed by `traceroute`, `reachability`, `detectLoops`. Computed lazily or by `generate_dataplane()`. |

Two facts to internalise now:

- **Batfish never touches your network.** It reads text files. There is no
  device, no packet, no cable anywhere in Phase 1.
- **`batfish/allinone` bundles the service and Jupyter.** There is a leaner
  image, `batfish/batfish`, which is service-only. Use `allinone` now because
  the notebooks are worth exploring; you can switch later.

## 4. Folder structure

Already created. Nothing to do.

## 5. Files to create

None. `batfish/requirements.txt` and `batfish/scripts/*` already exist.

## 6. Commands to run

**Step 1 — verify Docker.** PowerShell:

```powershell
docker --version
docker info
docker run --rm hello-world
```

**Step 2 — pull and start Batfish.**

```powershell
docker pull batfish/allinone
docker run --name batfish -d -v batfish-data:/data -p 8888:8888 -p 9997:9997 -p 9996:9996 batfish/allinone
```

Flag by flag, because you should not run a command you cannot explain:

| Flag | Meaning |
|---|---|
| `--name batfish` | A stable name so you can `docker logs batfish` later. |
| `-d` | Detached. Drop `-d` the first time if you want to watch it boot. |
| `-v batfish-data:/data` | Named volume. Your snapshots survive `docker restart`. |
| `-p 9996:9996` | The API port pybatfish uses. **Omit this and nothing works.** |
| `-p 9997:9997` | The coordinator port. Publish it too. |
| `-p 8888:8888` | Jupyter. |

**Step 3 — record the exact image you are using.** Do this now, not later.

```powershell
docker images --digests batfish/allinone
```

Paste the digest into `notes/lab-notebook.md`. A future `docker pull` of
`latest` can change parser behaviour underneath you, and without the digest you
will have no way to tell whether your results moved because of your change or
because of theirs.

**Step 4 — Python environment.**

```powershell
cd C:\Users\karth\network-research-lab
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r batfish\requirements.txt
pip list | Select-String -Pattern "pybatfish|pandas"
```

Python 3.11 specifically: current pybatfish is tested against 3.8–3.12, and 3.11
is comfortably inside that range on Windows.

**Step 5 — the smoke test.**

```powershell
cd batfish\scripts
python m01_smoke_test.py
```

**Step 6 — the official notebooks.** Open <http://localhost:8888> in a browser.
Spend twenty minutes, no more. Read `Getting Started with Batfish.ipynb` and
`Introduction to Forwarding Analysis.ipynb`. You are looking at *style* — how
questions are chained, what the DataFrames look like — not learning content.
Do not build your work there; notebook state is invisible to Git.

## 7. Code

`batfish/scripts/m01_smoke_test.py` (already on disk). It proves four things in
order and stops at the first failure: pybatfish imports, the service answers, a
snapshot initialises, a question returns real rows.

`batfish/scripts/bf_common.py` (already on disk) holds the shared machinery:
`bf_session()`, `load()`, `sanity()`, and the `Checks` assertion collector.

## 8. Configuration files

None in this module.

## 9. Expected output

`docker ps` should show the container up with three published ports.

`python m01_smoke_test.py` should end with:

```
==============================================================================
MODULE 1 -- environment smoke test: 7/7 checks passed
==============================================================================
ALL CHECKS PASSED
```

Along the way you should see, in `fileParseStatus`, three rows with
`Status = PASSED`, and in `nodeProperties` a `Configuration_Format` containing
`CISCO_IOS` for each of r1, r2, r3.

The final step prints `data plane computed` after a second or two of silence.
That pause is Batfish simulating the routing protocols to convergence.

## 10. Verification

- [ ] `docker ps` lists a running container named `batfish`
- [ ] `m01_smoke_test.py` prints `ALL CHECKS PASSED`
- [ ] <http://localhost:8888> loads Jupyter
- [ ] `notes/lab-notebook.md` records the image digest and both versions

## 11. Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `ConnectionError` to localhost:9996 | Ports not published | Recreate the container with all three `-p` flags |
| Hangs forever on the first question | Service still starting | `docker logs batfish`; wait for the startup lines, then retry |
| `ModuleNotFoundError: pybatfish` | Virtualenv not activated | `.venv\Scripts\activate` — check for `(.venv)` in the prompt |
| Snapshots vanish after a restart | Ran without `-v batfish-data:/data` | Recreate with the volume |
| `docker: Error response: Conflict. The container name "/batfish" is already in use` | It already exists | `docker start batfish`, or `docker rm -f batfish` then re-run |
| Jupyter asks for a token | Normal | `docker logs batfish` and copy the token from the URL it prints |

## 12. Debugging steps

Work outward from the container, in this order. Do not skip a layer.

```powershell
docker ps -a                      # is it running, or exited?
docker logs batfish --tail 50     # did the Java service finish starting?
docker port batfish               # are 9996/9997/8888 actually mapped?
Test-NetConnection localhost -Port 9996    # can Windows reach the port?
python -c "from pybatfish.client.session import Session; print(Session(host='localhost').list_networks())"
```

The last line is the narrowest possible test of "can Python talk to Batfish".
If it returns a list — even an empty one — the environment is fine and the
problem is in your script.

## 13. Mini exercise

1. Stop and remove the container: `docker rm -f batfish`.
2. Start it again **without** `-p 9996:9996`.
3. Run `m01_smoke_test.py`. Read the error carefully.
4. Restore the correct command.

You want to have seen that failure once, deliberately, so you recognise it
instantly when it happens by accident at 1 a.m.

## 14. Completion checklist

- [ ] I can name the four components and say which one parses configuration
- [ ] I can explain why `-v batfish-data:/data` matters
- [ ] `m01_smoke_test.py` passes
- [ ] Image digest and versions are in the lab notebook
- [ ] I have deliberately broken and repaired the port mapping

---

# MODULE 2 — Reading router configurations

## 1. Learning objective

Read a Cisco IOS configuration line by line and say what each line does. No new
software, no scripts. This is the module that makes every other module possible.

## 2. Why we are doing it

Batfish's entire input is configuration text. If you cannot read it, every
answer Batfish gives you is a magic number. This module is short and you should
not rush it.

**Why Cisco IOS and not FRRouting?** IOS is Batfish's best-supported format, and
it is the syntax every textbook, RFC example and Stack Overflow answer uses.
Learning networking and debugging a partial parser at the same time is a bad
trade. Module 9 builds the same topology a second time in FRR format, which is
where the parser question gets answered properly.

## 3. Theory

### The topology used by Modules 3 through 8

```
  192.168.1.0/24         10.1.12.0/30           10.1.23.0/30        192.168.3.0/24
   PC LAN ─── Gi0/1 [r1] Gi0/0 ────── Gi0/0 [r2] Gi0/1 ────── Gi0/0 [r3] Gi0/1 ─── SERVER LAN
                 lo0 10.0.0.1           lo0 10.0.0.2            lo0 10.0.0.3
```

### The anatomy of a config file

Open `batfish/snapshots/m03-trio-static/configs/r1.cfg`. Every line, explained:

```
version 15.2
```
The IOS version. Batfish partly uses lines like this to guess the vendor format.
Programmatically generated configs often fail vendor detection precisely because
they lack this kind of header line.

```
hostname r1
```
The device name. **This, not the filename, becomes the node name in Batfish.**
A file called `router-one.cfg` containing `hostname r1` gives you a node called
`r1`. Get this wrong and half your queries return nothing.

```
interface Loopback0
 description router-id and management
 ip address 10.0.0.1 255.255.255.255
```
A loopback is a virtual interface that is always up. It is not attached to a
cable and cannot fail. That is exactly why routing protocols use it as a stable
router ID — a physical interface's address disappears when the link goes down,
and a router whose ID changes mid-session causes chaos.

`255.255.255.255` is a /32: exactly one address.

```
interface GigabitEthernet0/0
 description LINK TO r2 GigabitEthernet0/0
 ip address 10.1.12.1 255.255.255.252
 duplex auto
 speed auto
```
A physical interface. `255.255.255.252` is a /30 — four addresses, of which two
are usable. That is the conventional size for a point-to-point link between two
routers: exactly enough, and no waste.

The `description` is a comment for humans. Write them. In Module 9 they are the
only thing that will let you follow the topology without a diagram.

**Note what is absent:** there is no `no shutdown` line. On real IOS an enabled
interface simply does not print anything; a disabled one prints `shutdown`.
Batfish follows the same rule — an interface is active unless the config says
`shutdown`.

```
ip route 192.168.3.0 255.255.255.0 10.1.12.2
```
A static route. Read it as: "to reach network 192.168.3.0/24, send the packet to
the neighbour at 10.1.12.2." Note that the next hop is an *address*, not an
interface. The router must look that address up in its own table to find the
exit port. That second lookup is called **recursive next-hop resolution** and it
matters in Module 6.

### OSPF — `m05-trio-ospf/configs/r1.cfg`

```
router ospf 1
 router-id 10.0.0.1
 passive-interface GigabitEthernet0/1
 network 10.0.0.1 0.0.0.0 area 0
 network 10.1.12.0 0.0.0.3 area 0
 network 192.168.1.0 0.0.0.255 area 0
```

| Line | Meaning |
|---|---|
| `router ospf 1` | Start an OSPF process. The `1` is a local label, not an identity — two routers with different process numbers still talk to each other. |
| `router-id 10.0.0.1` | This router's identity inside OSPF. Pin it to the loopback so it never changes. |
| `network 10.1.12.0 0.0.0.3 area 0` | "Any interface whose address falls in 10.1.12.0/30 participates in OSPF, in area 0." |
| `passive-interface Gi0/1` | Advertise the LAN's subnet, but do not send hellos out of it. There are no routers on a user LAN; sending hellos there is noise and a security hole. |

**Wildcard masks.** `0.0.0.3` is not a subnet mask — it is inverted. A `0` bit
means "must match", a `1` bit means "don't care". So `0.0.0.3` matches a /30 and
`0.0.0.255` matches a /24. This inversion is the single most common source of
Cisco configuration bugs, and Module 9 breaks a network with exactly one wrong
wildcard mask.

**What OSPF actually does:** every router floods a description of its own links
to every other router in the area. Each router independently assembles the same
map and runs Dijkstra over it. Nobody configures a route; routes are computed.
Cost defaults to `reference bandwidth / interface bandwidth`, which on a
GigabitEthernet is `100 Mbps / 1000 Mbps`, floored at 1.

### BGP — `m05-trio-bgp/configs/r2.cfg`

```
router bgp 65002
 bgp router-id 10.0.0.2
 neighbor 10.1.12.1 remote-as 65001
 neighbor 10.1.23.2 remote-as 65003
```

BGP does not discover neighbours. Every session is configured explicitly on both
ends, and both ends must agree about each other's AS number — Module 8 breaks
exactly that. `remote-as` different from your own is **eBGP**; the same is
**iBGP**, and they behave very differently.

`network 192.168.1.0 mask 255.255.255.0` means "advertise this prefix" — and it
only works if the prefix is already in the routing table from somewhere else.
It does not create a route.

BGP chooses by policy (AS path length, local preference, and a long tie-break
list), not by cost. This is why it scales to the entire internet and why it is
the protocol that takes companies offline.

### ACLs — `m07-acl-good/configs/r3.cfg`

```
ip access-list extended SERVER_PROTECT
 permit tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq www
 permit tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq 443
 permit icmp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255
 deny   ip any any
```

applied with:

```
interface GigabitEthernet0/1
 ip access-group SERVER_PROTECT out
```

Four rules that decide everything:

1. **Top to bottom, first match wins.** Evaluation stops at the first matching
   line. Order is semantics, not style.
2. **Source before destination.** `permit tcp SRC SRCMASK DST DSTMASK eq PORT`.
   Swapping them is a bug that looks fine.
3. **Wildcard masks, again inverted.**
4. **There is an invisible `deny ip any any` at the end of every ACL.** Writing
   it explicitly, as here, is good practice because it makes the intent visible.
5. **`in` versus `out`** is relative to the interface. An ACL applied `in` sees
   packets arriving; `out` sees packets leaving. Module 10 shows what happens
   when you pick the wrong one.

## 4–8. Folder structure, files, commands, code, expected output

Nothing to run. Read these five files, in this order:

```
batfish\snapshots\m03-trio-static\configs\r1.cfg
batfish\snapshots\m03-trio-static\configs\r2.cfg
batfish\snapshots\m05-trio-ospf\configs\r1.cfg
batfish\snapshots\m05-trio-bgp\configs\r2.cfg
batfish\snapshots\m07-acl-good\configs\r3.cfg
```

## 9. Verification

Close the files and answer from memory. Write the answers in your notebook.

1. On `m03-trio-static/configs/r2.cfg`, why are there four `ip route` lines and
   not two?
2. What is the usable address range of `10.1.12.0/30`?
3. In `network 192.168.1.0 0.0.0.255 area 0`, what does `0.0.0.255` mean, and
   what is the equivalent subnet mask?
4. r1's Gi0/1 is `passive-interface`. What still happens, and what stops?
5. In `SERVER_PROTECT`, if a packet is TCP from 192.168.1.50 to 192.168.3.9 on
   port 22, which line decides its fate?
6. Why does `router ospf 1` on r1 and `router ospf 1` on r2 not have to match?

Answers: (1) two transit prefixes plus two loopbacks — reachability to a router's
own loopback needs its own route; (2) .1 and .2, with .0 the network and .3 the
broadcast; (3) a /24 wildcard, equivalent to 255.255.255.0; (4) 192.168.1.0/24
is still advertised into OSPF, but no hellos are sent out of Gi0/1 so no
adjacency can form there; (5) `deny ip any any` — the three permits are HTTP,
HTTPS and ICMP only; (6) the process number is a local label with no protocol
meaning.

## 10. Common mistakes

- Confusing subnet masks with wildcard masks. Constantly. Everyone.
- Assuming the filename sets the node name. `hostname` sets it.
- Assuming `network` under `router bgp` creates a route. It advertises one that
  already exists.
- Forgetting the implicit `deny ip any any`.
- Reading `permit tcp A B C D eq X` as destination-then-source.

## 11. Debugging steps

Not applicable — nothing executes. If a config looks wrong to you, note it in
`surprises.md` and check it in Module 3, when Batfish can answer.

## 12. Mini exercise

On paper, without running anything, write the config for a fourth router `r4`
attached to r3's `GigabitEthernet0/2` on subnet `10.1.34.0/30`, with loopback
`10.0.0.4/32`, running OSPF in area 0. Then write the two lines you must **add
to r3** for the link to work.

Keep it. Module 9 gives you a real four-router network to compare against.

## 13. Completion checklist

- [ ] I can read every line of a config in this repo and say what it does
- [ ] I can convert between subnet masks and wildcard masks without a calculator
- [ ] I can explain why loopbacks exist
- [ ] I can state the first-match rule and the implicit deny
- [ ] I answered the six verification questions from memory

---

# MODULE 3 — Snapshots

## 1. Learning objective

Create, load and switch snapshots, and know precisely what Batfish builds from
one — including the sanity gate you will run for the rest of your life.

## 2. Why we are doing it

The snapshot is the unit of everything. Also: this module introduces
`sanity()`, and the single most common cause of "Batfish gave me a wrong answer"
is a snapshot that did not fully parse and was never checked.

## 3. Theory — what Batfish builds, in order

```
  configs/*.cfg  (text)
        │
   [1]  ├─ vendor format detection      guesses IOS / EOS / Cumulus per file
        │                               from tell-tale lines
   [2]  ├─ vendor-specific parse tree   real grammar, per vendor
        │                               → anything unparsed lands in parseWarning
   [3]  ├─ vendor-independent model     one common representation: nodes, VRFs,
        │                               interfaces, filters, routing processes
   [4]  ├─ topology                     which interfaces are adjacent
        │                               (declared, or inferred from subnets)
        ├──────────── init_snapshot() returns here ────────────
   [5]  ├─ control plane                simulate OSPF/BGP/static to a fixed
        │                               point → a RIB per VRF per node
   [6]  └─ data plane (FIB)             the tables used to trace packets
                                        → generate_dataplane(), or lazily
```

Steps 5 and 6 are the expensive ones, which is why they are deferred.

**Step 1 is where generated configs die.** Vendor detection relies on header
lines that a real device emits and a script often does not. If
`Configuration_Format` says `UNKNOWN`, nothing downstream is meaningful.

**Step 4 has two modes and you must know which you are in:**

- *No `batfish/layer1_topology.json`* — adjacency is **inferred from subnet
  overlap**. Two interfaces in the same subnet are assumed to have a cable
  between them. Convenient, and a lie: two interfaces can share a subnet with no
  physical connection at all. The `m03`–`m08` snapshots work this way.
- *With a layer-1 file* — adjacency is **declared**. Only listed pairs are
  adjacent. The `m09` snapshots work this way, and it is what you want for
  anything you care about.

## 4. Folder structure

```
batfish/snapshots/m03-trio-static/
└── configs/
    ├── r1.cfg
    ├── r2.cfg
    └── r3.cfg
```

`configs/` is not a convention you can rename. Batfish looks for that exact
directory name immediately below the snapshot root.

## 5. Files to create

None — all present.

## 6. Commands to run

```powershell
cd C:\Users\karth\network-research-lab\batfish\scripts
python m03_snapshots.py
```

## 7. Code

`m03_snapshots.py`. Also read `bf_common.py` — specifically `sanity()`, which
runs `initIssues`, `fileParseStatus`, `parseWarning`, `undefinedReferences`,
`unusedStructures` and returns a verdict.

## 8. Configuration files

Already written; you read them in Module 2.

## 9. Expected output

Nine checks, all passing. Key intermediate results:

- `fileParseStatus` — 3 rows, all `PASSED`
- `nodeProperties` — nodes `r1`, `r2`, `r3`
- `interfaceProperties` — **9 rows** (3 devices × Loopback0 + 2 physical), every
  one `Active = True`
- `layer3Edges` — **4 rows**: r1↔r2 and r2↔r3, reported in both directions
- `ipOwners` — 9 rows
- `parseWarning` — **0 rows**

Then the script loads `m05-trio-ospf`, confirms 3 nodes, lists both snapshots in
the `phase1` network, and switches back.

Ends with `ALL CHECKS PASSED`.

## 10. Verification

- [ ] Exactly 4 layer-3 edge rows, and **no** r1↔r3 edge — they are two hops
      apart, and an edge there would mean the model is wrong
- [ ] Zero parse warnings
- [ ] `bf.list_snapshots()` shows both snapshots after the switch

## 11. Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| `0 rows` from every question | Configs are not under `configs/` | Move them |
| A node name you did not expect | `hostname` differs from the filename | `hostname` wins |
| `Configuration_Format = UNKNOWN` | Vendor detection failed | Add a realistic header (`version 15.2`, `hostname`, `ip cef`) |
| Edits to a `.cfg` seem to have no effect | Snapshot was cached | `load()` always passes `overwrite=True`; if you loaded it by hand, re-init |
| Two devices, one file | Two `hostname` lines in one file | One device per file, always |

## 12. Debugging steps

When a snapshot behaves strangely, in this exact order:

1. `bf.q.fileParseStatus()` — did every file get read?
2. `bf.q.parseWarning()` — **read every row.** Each is a line of your intent that
   the model does not contain.
3. `bf.q.nodeProperties(properties="Configuration_Format")` — right vendor?
4. `bf.q.interfaceProperties()` — do the interfaces have the addresses you wrote?
5. `bf.q.layer3Edges()` — is anything adjacent that should not be, or vice versa?

Only after all five should you start doubting your networking.

## 13. Mini exercise

1. Copy `m03-trio-static` to a new folder `m03-experiment`.
2. In `r2.cfg`, change `hostname r2` to `hostname core-01`. Predict what
   `layer3Edges` will show, then run `m03_snapshots.py` pointed at it (edit the
   `load(...)` call, or use a Python REPL).
3. Now delete `r2.cfg` entirely. Predict `fileParseStatus`, `layer3Edges`, and
   what happens to r1's route to 192.168.3.0/24. Run it.
4. Delete the folder.

Question 3 is the interesting one: what does Batfish do about a route whose next
hop belongs to a device that does not exist?

## 14. Completion checklist

- [ ] I can list the six things Batfish builds, in order
- [ ] I know which two are deferred and why
- [ ] I can state both topology-inference modes and the risk of the inferred one
- [ ] I run the sanity gate before believing any answer
- [ ] `m03_snapshots.py` passes

---

# MODULE 4 — Basic verification

## 1. Learning objective

Ask the five core question families and interpret the answers — including the
difference between testing one flow and proving a property over all flows.

## 2. Why we are doing it

Everything after this is a variation. And one idea in section 4.5 is the reason
formal verification exists at all.

## 3. Theory

### Testing versus verification

`traceroute` sends one flow through the model. If you did not think of the flow,
you did not test it.

`reachability` does something categorically different: it encodes the forwarding
behaviour of the entire network as a logical formula, adds your constraint
("source in 192.168.1.0/24, destination in 192.168.3.0/24, action = FAILURE"),
and asks a solver whether any satisfying assignment exists. Zero rows returned
is not "we tried a lot of packets and they all worked". It is a **proof** that no
such packet exists — over that model, within that header space.

Both halves of that qualification carry weight. Module 10 is about what they
cost.

### Dispositions

Every trace ends in exactly one:

| Disposition | Meaning | Success? |
|---|---|---|
| `ACCEPTED` | A modelled device owns the destination address | yes |
| `DELIVERED_TO_SUBNET` | Handed to a connected subnet with no modelled device on it | yes |
| `EXITS_NETWORK` | Left through a border interface | yes |
| `NO_ROUTE` | Nothing matched in the RIB | no |
| `NULL_ROUTED` | Matched a route pointing at Null0 | no |
| `DENIED_IN` / `DENIED_OUT` | An ACL dropped it | no |
| `LOOP` | Revisited a hop | no |
| `NEIGHBOR_UNREACHABLE` | Next hop did not resolve | no |
| `INSUFFICIENT_INFO` | Batfish cannot decide — usually a modelling gap | no |

`DELIVERED_TO_SUBNET` is the one that surprises people. There is no server in
this lab. Batfish stops at "I handed it to the wire; what happens next is outside
my model."

### Location specifiers

`startLocation="@enter(r1[GigabitEthernet0/1])"` means "the packet appears at
r1's Gi0/1 as if it arrived from outside". Be this specific. Passing just `"r1"`
means "any interface of r1", which multiplies your traces and hides the one you
meant.

## 4–5. Folder structure and files

Uses `m03-trio-static`. Nothing new.

## 6. Commands to run

```powershell
python m04_basic_verification.py
```

## 7–8. Code and configuration

`m04_basic_verification.py`; configs unchanged from Module 2.

## 9. Expected output

Fourteen checks. The parts worth reading rather than skimming:

**4.2 routing tables.** r1's route to 192.168.3.0/24 is `Protocol = static`,
`Next_Hop_IP = 10.1.12.2`, `Admin_Distance = 1`. The network-wide protocol
census shows only `connected`, `local` and `static` — no `ospf`, no `bgp`.

**4.3 neighbours.** r1↔r2 and r2↔r3 adjacent; r1↔r3 **not** adjacent.

**4.4 forwarding.** A three-hop trace, r1 → r2 → r3, ending
`DELIVERED_TO_SUBNET`. The script prints every hop and every step within it —
read that block properly, it is the clearest view of Batfish's model you will
get.

**4.5 reachability.** The `FAILURE` query returns **zero rows**. That is the
strong result. The `SUCCESS` query returns at least one example flow.

## 10. Verification

- [ ] Zero rows for the FAILURE reachability query
- [ ] The trace is exactly three hops
- [ ] No r1↔r3 adjacency
- [ ] I can explain why the disposition is `DELIVERED_TO_SUBNET` and not
      `ACCEPTED`

## 11. Common mistakes

- **Reading an empty DataFrame as success.** It means either "the property
  holds" or "nothing parsed". Only the sanity gate distinguishes them. This is
  why `m04` refuses to run if `sanity()` fails.
- Using `actions="SUCCESS"` when you meant `"FAILURE"`. Ask for counterexamples;
  a successful example proves almost nothing.
- Forgetting `applications=` and searching a much larger header space than
  intended.
- Reading only the `Flow` column and ignoring `Traces`. The verdict is the least
  informative part of the answer.

## 12. Debugging steps

`reachability` returned something you did not expect:

1. Run `traceroute` on one concrete flow from that answer. Print every hop.
2. Find the hop where the disposition is decided.
3. `bf.q.routes(nodes="<that node>", network="<dest prefix>")` — does it have a
   route at all?
4. If yes, `bf.q.testFilters(...)` on that node — is a filter eating it?
5. If neither, check `layer3Edges` around that node.

## 13. Mini exercise

1. Predict: from the PC LAN to **r2's loopback** `10.0.0.2`, what disposition?
   It is a real address owned by a modelled device — so which one?
2. Run it and check.
3. Now predict and run: from the PC LAN to `10.0.0.4`, which nobody owns.
4. Predict and run: from the **server LAN** back to the PC LAN. Is this network
   symmetric? Why can you not assume that in general?

Write all four predictions before running any of them.

## 14. Completion checklist

- [ ] I can state the difference between `traceroute` and `reachability` in one
      sentence
- [ ] I know all nine dispositions and which three are successes
- [ ] I always query `FAILURE`, not `SUCCESS`, when checking a property
- [ ] I understand exactly what "zero rows" proves, and what it does not
- [ ] `m04_basic_verification.py` passes

---

# MODULE 5 — Routing analysis

## 1. Learning objective

Read a RIB and explain why each route won: longest prefix match, administrative
distance, then metric — in that order.

## 2. Why we are doing it

"Why is this route in the table?" is the question every network debugging
session eventually reduces to.

## 3. Theory

### The selection order

A router picks a route in this order and **stops at the first difference**:

1. **Longest prefix match.** Decided first, before anything else.
2. **Lowest administrative distance.** connected 0, static 1, eBGP 20, OSPF 110,
   RIP 120, iBGP 200.
3. **Lowest protocol metric.** OSPF cost; or, for BGP, the full decision process.

The universal misconception is that admin distance comes first. It does not.
A /32 static and a /8 OSPF route are never compared — they match different
packets. LPM decides which routes are even candidates; only then does anything
else apply.

### The three protocols, compared

| | static | OSPF | BGP |
|---|---|---|---|
| How routes appear | typed by a human | computed from a flooded map | advertised by a neighbour |
| Adjacency | none | discovered via hellos | configured explicitly on both ends |
| Chooses by | nothing — it is an order | cost (Dijkstra) | policy: AS path, local pref, tie-breaks |
| Admin distance | 1 | 110 | 20 (eBGP) / 200 (iBGP) |
| Reacts to failure | **no** | yes | yes |
| Fails by | pointing at something that is gone | area/timer/MTU mismatch | AS mismatch, policy, next hop unreachable |

That "reacts to failure: no" is where blackholes come from. Module 6 builds one.

## 4–5. Folder structure and files

Uses `m03-trio-static`, `m05-trio-ospf`, `m05-trio-bgp` — the same topology and
addressing three times, differing only in the routing block.

## 6. Commands to run

```powershell
python m05_routing_analysis.py
```

## 7–8. Code and configuration

`m05_routing_analysis.py`. Diff the three r1 configs against each other; the
routing block is the only difference.

## 9. Expected output

**5.1 static.** r1 has exactly 4 static routes, all `Admin_Distance = 1`.

**5.2 OSPF.** `ospfSessionCompatibility` shows adjacent pairs exactly
`{r1,r2}` and `{r2,r3}`, all `ESTABLISHED`. r1 has an OSPF route to
192.168.3.0/24 with `Admin_Distance = 110`. Note the metric and work out where
it came from.

**5.3 BGP.** `bgpSessionCompatibility` returns **4 rows** — one per configured
neighbour: r1 has one, r2 has two, r3 has one. All `UNIQUE_MATCH`, all
`ESTABLISHED`. r1's AS path to 192.168.3.0/24 is **`65002 65003`**: r3
originated it, r2 prepended itself crossing the eBGP boundary.

**5.5 LPM.** `lpmRoutes` for 192.168.3.10 → 1 row. For 10.0.0.3 → 1 row. For
8.8.8.8 → **0 rows**, because there is no default route anywhere in this lab.
Zero rows here is not an error; it is the reason a packet to 8.8.8.8 gets
`NO_ROUTE`.

**5.6 differential.** The OSPF snapshot versus the static snapshot returns a
non-empty diff. The prefixes are largely identical; `Protocol`, `Metric` and
`Admin_Distance` are what moved. Same reachability, completely different failure
behaviour.

## 10. Verification

- [ ] I can explain the metric OSPF computed for 192.168.3.0/24 on r1
- [ ] I can explain why the AS path is `65002 65003` and not `65003`
- [ ] I can explain why `lpmRoutes(8.8.8.8)` returning 0 rows is correct
- [ ] I can state the three-step selection order without looking

## 11. Common mistakes

- Believing admin distance is compared before prefix length.
- Expecting `bgpSessionCompatibility` to have one row per link. It has one per
  configured neighbour, which is one per direction.
- Confusing `bgpSessionCompatibility` (are the configs mutually consistent?) with
  `bgpSessionStatus` (would the session actually come up?). Both matter; they
  fail for different reasons.
- Asking for OSPF routes without generating the data plane first.

## 12. Debugging steps

Route missing from a RIB:

1. Is it originated at all? Check the source device's RIB.
2. Is the protocol adjacency up? `ospfSessionCompatibility` /
   `bgpSessionCompatibility`.
3. For OSPF: is the interface in a `network` statement, and in the right area?
4. For BGP: does a `network` statement exist, and is the prefix already in the
   RIB from another source? `network` advertises, it does not create.
5. Is something else winning on LPM or admin distance? `lpmRoutes` for a
   concrete address in the prefix.

## 13. Mini exercise

1. In `m05-trio-ospf/configs/r2.cfg`, add `ip ospf cost 500` to `Gi0/1`.
2. Predict: does r1's route to 192.168.3.0/24 change? Does its *metric* change?
   Does its *next hop* change? These are three separate questions.
3. Run and check.
4. Now, in `m03-trio-static/configs/r1.cfg`, add
   `ip route 192.168.3.0 255.255.255.128 10.1.12.2`. You now have a /24 and a /25
   for overlapping space. Predict `lpmRoutes` for `192.168.3.10` and for
   `192.168.3.200`, then check. This is LPM with nothing else varying.
5. Revert both.

## 14. Completion checklist

- [ ] I can read any RIB row and name the protocol, distance, metric and next hop
- [ ] I can state the selection order and explain why LPM is first
- [ ] I can explain the difference between session *compatibility* and *status*
- [ ] `m05_routing_analysis.py` passes

---

# MODULE 6 — Forwarding analysis

## 1. Learning objective

Follow a packet rather than read a table, and distinguish the ways forwarding
fails — including the ones where every RIB looks perfectly healthy.

## 2. Why we are doing it

Routing is what each router *believes*. Forwarding is what a packet
*experiences*. Section 6.3 is a network where every device's routing table is
individually defensible and traffic still disappears.

## 3. Theory

### Recursive next-hop resolution

r1's RIB says `192.168.3.0/24 via 10.1.12.2`. That is an IP address, not an exit
port. r1 must look `10.1.12.2` up *again*, find it inside the connected route
`10.1.12.0/30` on Gi0/0, and only then does it have somewhere to send the frame.
Batfish performs that recursion. A next hop that does not resolve produces a
route that sits in the RIB looking healthy and forwards nothing.

### ECMP

When two paths tie on prefix length, admin distance and metric, both are
installed. Real hardware picks one per flow by hashing the five-tuple.

Batfish enumerates **every** path. That is a genuine strength — a real traceroute
picks one path and you could run it a hundred times and never see the broken
one. It is also a genuine limitation: Batfish does not model the hash, so it
cannot tell you which path *your* flow takes, only that both are possible.

### The blackhole

A static route has admin distance 1. OSPF has 110. So a static route wins over a
perfectly good OSPF route offering a working path — and a static route pointing
at `Null0` is a deliberate drop. One line on one router, and the routers on
either side see nothing wrong at all.

## 4–5. Folder structure and files

`m06-trio-ecmp` (OSPF plus a second equal-cost r1↔r2 link on 10.1.112.0/30) and
`m06-trio-blackhole` (OSPF plus one `ip route ... Null0` on r2).

## 6. Commands to run

```powershell
python m06_forwarding_analysis.py
```

## 7–8. Code and configuration

`m06_forwarding_analysis.py`. Diff `m06-trio-blackhole/configs/r2.cfg` against
`m05-trio-ospf/configs/r2.cfg` — one line.

## 9. Expected output

**6.2 ECMP.** r1 has **2** RIB entries for 192.168.3.0/24, identical metrics,
different `Next_Hop_Interface`. `traceroute` returns **2 traces**, not one.
`multipathConsistency` returns 0 rows; `detectLoops` returns 0 rows.

**6.3 blackhole.** r2's only route to 192.168.3.0/24 is `Protocol = static`. r1's
route is still an ordinary healthy-looking `ospf` route. The trace ends
`NULL_ROUTED`.

Stop and appreciate this: auditing every RIB device by device would have found
nothing wrong on r1. Only following the packet across devices exposes it.

**6.4 no route.** Trace to 8.8.8.8 ends `NO_ROUTE`.

**6.5 census.** At least three distinct dispositions across the four snapshots.

## 10. Verification

- [ ] I can explain `NO_ROUTE` versus `NULL_ROUTED` and why they are different
      bugs despite looking identical from a user's chair
- [ ] I can explain why r1's RIB looks healthy in the blackhole snapshot
- [ ] Two traces on the ECMP snapshot, not one

## 11. Common mistakes

- Auditing RIBs device by device and calling it verification. Blackholes and
  loops are properties of the *path*, not of any single table.
- Assuming a real traceroute would find the ECMP problem. It picks one path.
- Assuming Batfish tells you which ECMP path a flow takes. It does not model the
  hash.
- Forgetting `generate_dataplane()` before a forwarding question.

## 12. Debugging steps

A trace ends somewhere unexpected:

1. Print every hop and every step. The step names tell you what happened.
2. On the last hop, `bf.q.routes(nodes=..., network=...)`.
3. If the route exists but the packet died, `testFilters` on that node.
4. If the route is missing, go back to Module 5's debugging list.
5. If the disposition is `INSUFFICIENT_INFO`, that is a modelling gap, not your
   bug — record it in `surprises.md`.

## 13. Mini exercise

1. In `m06-trio-ecmp/configs/r1.cfg`, change `ip ospf cost` on Gi0/2 to 50 —
   you will need to add the line. Predict: how many RIB entries, how many traces?
2. Run and check.
3. In `m06-trio-blackhole/configs/r2.cfg`, change `Null0` to `10.1.23.2` (r3's
   real address). Predict the disposition, then check.
4. Harder: make the blackhole *partial*. Change r2's static route to
   `ip route 192.168.3.128 255.255.255.128 Null0`. Predict what happens to a
   packet to 192.168.3.10 versus 192.168.3.200. This is LPM and forwarding
   interacting, and it is the shape of a very common real-world outage.
5. Revert.

## 14. Completion checklist

- [ ] I can name all nine dispositions and give a cause for each
- [ ] I can explain recursive next-hop resolution
- [ ] I can explain both what ECMP handling buys me and what it does not
- [ ] I built and diagnosed a blackhole
- [ ] `m06_forwarding_analysis.py` passes

---

# MODULE 7 — ACL and firewall verification

## 1. Learning objective

Attack a policy from three directions and understand why only one of them finds
bugs you were not already looking for.

## 2. Why we are doing it

Section 7.2 contains the most instructive bug in Phase 1: an ACL that is
syntactically perfect, passes review, and does the opposite of what its own
comment says.

## 3. Theory

Three questions, three fundamentally different kinds of power:

| Question | Shape | Finds |
|---|---|---|
| `testFilters` | a **test** — one packet, one verdict, plus the deciding line | only what you already suspected |
| `searchFilters` | a **search** — find me a packet treated like X | flows in a space you named |
| `filterLineReachability` | a **proof** — is any line unreachable? | bugs you had no hypothesis for |

`filterLineReachability` needs no input beyond the ACL itself. It proves a line
can never match any packet, because earlier lines already cover everything it
matches. That is a property of the ACL alone. It is the only one of the three
that can surprise you.

And then there is the one that matters most for change review:

**`differentialReachability`** — give it two snapshots, get back exactly the
flows whose fate differs. You do not supply a list of flows to test. You do not
have to have thought of SSH. That is the difference between testing and
verification, in one query.

It still needs a header space to search, though. Give it
`srcIps=192.168.1.0/24, dstIps=192.168.3.0/24` and anything outside those two
ranges is never examined. Hold that thought until Module 10.

## 4–5. Folder structure and files

`m07-acl-good` and `m07-acl-bad`. Identical except for four lines on r3.

The ACL is applied **outbound on r3's server-LAN interface**, deliberately. An
inbound ACL on the transit interface would also eat OSPF hellos — which is a
real bug, and Module 10 demonstrates it separately rather than muddling it here.

## 6. Commands to run

```powershell
python m07_acl_verification.py
```

## 7. Code

`m07_acl_verification.py`.

## 8. Configuration files

The intended policy (`m07-acl-good`):

```
ip access-list extended SERVER_PROTECT
 permit tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq www
 permit tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq 443
 permit icmp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255
 deny   ip any any
```

The policy that was written (`m07-acl-bad`):

```
ip access-list extended SERVER_PROTECT
 remark INTENT: allow the host LAN to the server LAN, but never allow SSH
 permit ip  192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255
 deny   tcp 192.168.1.0 0.0.0.255 192.168.3.0 0.0.0.255 eq 22
 permit icmp any any
 deny   ip any any
```

Read the second one as a human before you run anything. The intent is stated in
the remark. Line 2 implements it. Line 1 was added first, by someone else, six
months earlier. Nothing looks wrong. Two people signed off.

## 9. Expected output

**7.1 good ACL.** `testFilters`: HTTP → `PERMIT`, HTTPS → `PERMIT`, SSH →
`DENY`, and an outsider on HTTP → `DENY`. Read the `Line_Content` column, not
just `Action` — it names the exact line that decided.

End to end: HTTPS reaches the server LAN, SSH does not. The SSH trace ends
`DENIED_OUT` — *out*, not *in*, because of where the ACL is applied. The packet
crossed r1 and r2 happily and died on the last hop on egress. From the PC you
would have blamed the network.

`filterLineReachability` on the good ACL: **0 rows**.

**7.2 bad ACL.** `testFilters` on SSH now returns **`PERMIT`**, contradicting the
remark directly above it. `filterLineReachability` returns **exactly 1 row**: the
`eq 22` deny is unreachable, blocked by the `permit ip` above it.

That is the module's point. `testFilters` only told you the truth because you
already suspected SSH and asked. `filterLineReachability` needed no hypothesis.

**7.3 differential.** Non-empty. Every row is a flow that succeeds in one
snapshot and fails in the other.

## 10. Verification

- [ ] `DENIED_OUT`, and I can explain why not `DENIED_IN`
- [ ] Exactly one unreachable line, and it is the SSH deny
- [ ] I can explain why `testFilters` could not have found this unprompted

## 11. Common mistakes

- Writing a specific deny *after* a broad permit. This is the bug in 7.2 and it
  is extremely common in production.
- Reversing source and destination.
- Wildcard masks — `0.0.0.0` is one host, `0.0.0.255` is a /24.
- Forgetting the implicit `deny ip any any`.
- Applying `in` where you meant `out`.
- Believing `filterLineReachability` finds all ACL bugs. It finds *dead lines*.
  Module 9's typo leaves every line reachable and it sails straight past.

## 12. Debugging steps

Traffic is blocked and you do not know where:

1. `traceroute` the exact flow; find the hop with `DENIED_IN` / `DENIED_OUT`.
2. `testFilters` on that node with that header. Read `Line_Content`.
3. If the deciding line surprises you, `filterLineReachability` on that filter.
4. If the ACL looks right, check `in` versus `out` and which interface.
5. If the flow is permitted but still fails, it is not the ACL — go back to
   Module 6.

## 13. Mini exercise

1. Fix `m07-acl-bad` by swapping lines 1 and 2. Predict what
   `filterLineReachability` and `testFilters` on SSH will say. Run it.
2. Now introduce a different bug: in `m07-acl-good`, change the HTTPS line's
   source wildcard from `0.0.0.255` to `0.0.255.255`. Predict — is this more or
   less permissive? Will `filterLineReachability` catch it? Run it.
3. Question 2 is the one to think hardest about. Write your answer in
   `surprises.md` whether you got it right or not.
4. Revert.

## 14. Completion checklist

- [ ] I can state what each of the three ACL questions can and cannot find
- [ ] I can explain why only `filterLineReachability` finds unsuspected bugs
- [ ] I understand what `differentialReachability` needs from me, and what it
      does not
- [ ] `m07_acl_verification.py` passes

---

# MODULE 8 — Configuration validation

## 1. Learning objective

Break configurations deliberately and learn *which layer* catches each kind of
break — parse, control plane, or data plane.

## 2. Why we are doing it

Because they are not the same layer, and a bug invisible at every layer you
happen to check is indistinguishable from a working network.

## 3. Theory

For every bug, ask three questions in order:

1. Does it fail to **parse**? (`initIssues`, `parseWarning`,
   `undefinedReferences`, `unusedStructures`)
2. Does the **control plane** notice? (`ospfSessionCompatibility`,
   `bgpSessionCompatibility`, `bgpSessionStatus`, `layer3Edges`)
3. Does the **data plane** notice? (`traceroute`, `reachability`)

The answers differ per bug, and the pattern is the lesson.

## 4–5. Folder structure and files

- `m08-broken-subnet` — r2's link to r3 renumbered to 10.1.24.1/30, r3 not
  updated. The OSPF `network` statement on r2 was updated to match, so the file
  is internally self-consistent and reads fine.
- `m08-broken-refs` — r1 applies `HOST_FILTER`, which is never defined, and
  defines `LEFTOVER_MGMT_ACL`, which is never applied.
- `m08-broken-bgp-as` — r3 says `remote-as 65099`; r2 is actually 65002.

## 6. Commands to run

```powershell
python m08_config_validation.py
```

## 7–8. Code and configuration

`m08_config_validation.py`. Diff each broken snapshot against its healthy
sibling before you run anything, and predict all three layers for each.

## 9. Expected output

**8.1 wrong IP.** Parse: **clean**. Zero `initIssues`, zero `parseWarning`. Every
line is valid IOS and Batfish has no idea what you *meant* the address to be.
Control plane: loud — r2 and r3 are no longer adjacent, only the r1↔r2 OSPF
session survives. Data plane: the packet no longer reaches the server LAN.

**8.2 dangling names.** `undefinedReferences` flags `HOST_FILTER`.
`unusedStructures` flags `LEFTOVER_MGMT_ACL`. These two questions are the
cheapest audit in the tool; on a real enterprise snapshot they routinely return
dozens of rows, each either dead configuration or a live bug.

Note the asymmetry: Batfish tells you `HOST_FILTER` does not exist. It cannot
tell you what `HOST_FILTER` was supposed to do. Detecting a missing
specification is not recovering it.

**8.3 wrong AS.** Parse: clean — 65099 is a perfectly legal AS number. Control
plane: at least one session incompatible and not established. Data plane: r1 has
lost the BGP route to 192.168.3.0/24.

**8.4 the pattern.**

| Bug | parse? | control plane? | data plane? |
|---|---|---|---|
| wrong IP / subnet | no | **yes** | **yes** |
| undefined ACL name | **yes** | no | no\* |
| wrong BGP remote-as | no | **yes** | **yes** |

\* The undefined ACL does not change forwarding in Batfish's model. On a real
Cisco device, applying a nonexistent ACL permits everything — the filter you
thought you had is simply absent. Batfish told you the name is undefined; it did
not tell you the security consequence. You had to know to care.

Copy that table into your lab notebook.

## 10. Verification

- [ ] I predicted all three layers for each bug before running
- [ ] I can explain why the IP typo produces zero parse warnings
- [ ] I can explain the footnote on the undefined ACL

## 11. Common mistakes

- Assuming "it parsed" means "it is correct". Parsing checks grammar, not intent.
- Never running `undefinedReferences` / `unusedStructures`. They cost nothing.
- Assuming a control-plane failure always shows up in the data plane. Sometimes
  a backup path hides it — Module 9.

## 12. Debugging steps

A snapshot behaves oddly and you do not know why:

1. `fileParseStatus`, then **read every row** of `parseWarning`.
2. `undefinedReferences` and `unusedStructures`.
3. `interfaceProperties` — are the addresses what you wrote?
4. `layer3Edges` — is anything adjacent that should not be?
5. Session compatibility for each protocol in use.
6. Only now, `traceroute`.

Top to bottom. A parse problem masquerades as a routing problem every time.

## 13. Mini exercise

Build a fourth broken snapshot yourself. Copy `m05-trio-ospf` to
`m08-broken-area`, and on r3 change `area 0` to `area 1` in the `network`
statement for the transit link.

1. Predict all three layers before running.
2. Write a short script (copy the shape of `m08_config_validation.py`) that
   checks your prediction.
3. Then predict which of Module 9's nine properties this bug would violate.

An area mismatch is a classic: it parses perfectly, the interfaces are up, the
addresses are right, and no adjacency forms.

## 14. Completion checklist

- [ ] I can name three questions per detection layer
- [ ] I built and diagnosed a broken snapshot of my own
- [ ] The detection-layer table is in my lab notebook
- [ ] `m08_config_validation.py` passes

---

# MODULE 9 — Our own network

## 1. Learning objective

Design a network from nothing, write a specification **before** running anything,
verify it, break it two ways, and observe that one of the breaks passes most of
the specification while being severely broken.

## 2. Why we are doing it

Every previous module handed you the answer's shape. This one does not. It is
also the first time you will see a network that is genuinely broken and looks
mostly fine — which is the phenomenon the rest of this project exists to study.

## 3. Theory — the topology

```
                        PC LAN 192.168.10.0/24
                               │
                          Gi0/1│
                             [ r1 ]  edge, lo0 10.255.0.1
                    Gi0/0 ╱          ╲ Gi0/2
              cost 10   ╱              ╲  cost 100
        10.0.12.0/30  ╱                  ╲  10.0.13.0/30
                   [ r2 ]              [ r3 ]
             core, lo0 .2          core, lo0 .3
             Gi0/1 │  cost 10        Gi0/1 │  cost 10
          10.0.24.0/30                10.0.34.0/30
                   ╲                    ╱
              Gi0/0  ╲                 ╱ Gi0/1
                          [ r4 ]  edge, lo0 10.255.0.4
                          Gi0/2 │
                        SERVER LAN 192.168.20.0/24
```

- **Primary path** r1 → r2 → r4, total OSPF cost **20**
- **Backup path** r1 → r3 → r4, total OSPF cost **110**

Filters:

- `r4 Gi0/2 out : SERVER_POLICY` — only the PC LAN, only HTTP/HTTPS/ICMP
- `r3 Gi0/1 out : BACKUP_PATH_FILTER` — the backup link is meant to be
  low-capacity, so only ICMP and plain HTTP

This snapshot also carries an explicit `batfish/layer1_topology.json`. Adjacency
is declared, not guessed from subnet overlap.

### The intent checklist — write this before running anything

| | Property |
|---|---|
| P1 | every configuration file parses with no warnings |
| P2 | no undefined or unused named structures |
| P3 | all four OSPF adjacencies are established |
| P4 | the PC LAN can reach the server LAN over HTTP |
| P5 | the PC LAN can reach the server LAN over HTTPS |
| P6 | the PC LAN **cannot** reach the server LAN over SSH |
| P7 | traffic to the server LAN takes the **primary** path through r2 |
| P8 | no ACL contains an unreachable line |
| P9 | there are no forwarding loops |

The ordering is not a stylistic preference. **A property invented after seeing
the output is not a specification, it is a description.** Freeze the list first.

## 4. Folder structure

```
batfish/snapshots/
├── m09-corp-base/
│   ├── configs/{r1,r2,r3,r4}.cfg
│   └── batfish/layer1_topology.json
├── m09-corp-acl-typo/       identical but one wildcard mask
└── m09-corp-link-down/      identical but one `shutdown`
```

## 5. Files to create

None. Read all four configs of `m09-corp-base` before running anything, and draw
the topology yourself from the `description` lines alone.

## 6. Commands to run

```powershell
python m09_corp_verify.py
python m09_frr_spike.py
```

Run the spike. It takes about a minute and its verdict determines how the
emulated lab gets built later. Do not defer it.

## 7. Code

`m09_corp_verify.py` evaluates all nine properties, then asserts each one against
what this manual predicts — including predicting *violations* for the broken
snapshots. `m09_frr_spike.py` is a separate decision script.

## 8. Configuration files

All four devices, plus the layer-1 topology, already on disk.

## 9. Expected output

**9.1 base.** All nine properties HOLD. HTTPS path is `r1 -> r2 -> r4`, ending
`DELIVERED_TO_SUBNET`. Primary wins because 20 < 110.

**9.2 fault A — primary link shut.** Predict before reading. Expected:

| | outcome | why |
|---|---|---|
| P1 | holds | still valid IOS |
| P2 | holds | no names broken |
| P3 | **violated** | the r1↔r2 adjacency is gone |
| P4 | holds | HTTP survives on the backup path |
| P5 | **violated** | HTTPS is dropped by `BACKUP_PATH_FILTER` |
| P6 | holds | SSH was blocked before and still is |
| P7 | **violated** | traffic now goes via r3 |
| P8 | holds | the ACLs are unchanged |
| P9 | holds | |

**This is the most important result in Phase 1.** Read it slowly:

- The network still converges. OSPF did its job.
- Every device is up. Every remaining adjacency is established.
- Ping works. HTTP works.
- HTTPS is silently dropped on the last hop of the backup path, because
  `BACKUP_PATH_FILTER` never contemplated it.

If your monitoring pings the server, it is green. If your verification checked
"can the PC LAN reach the server LAN" and "reach" meant ICMP, it passes. The
property that catches this — P5, HTTPS specifically, under failure of the
primary link — had to be written down in advance by a human who thought of it.

`differentialReachability` finds the regression without needing that human to
have guessed correctly.

**9.3 fault B — one wildcard mask.** `0.0.0.255` became `0.0.0.0` on the HTTP
permit line. That means "exactly the host 192.168.10.0", which is the network
address and belongs to nobody. Expected: only **P4** is violated.

Note which property does *not* fire: **P8 passes.** The line is still reachable —
one address matches it — so structural ACL analysis is blind to this bug
entirely. Only a reachability property catches it. Compare this against Module 7,
where the opposite was true.

**The FRR spike** prints a `GO` or `NOT YET` verdict across five checks. Check 3
(interface addresses) is the one that matters: FRR interface IPs live in the
`/etc/network/interfaces` section, not in `frr.conf`, and if the markers are
wrong Batfish builds a network with no addresses and answers every question
confidently and wrongly. Record the verdict in the lab notebook either way.

## 10. Verification

- [ ] All nine properties hold on the base snapshot
- [ ] Exactly P3, P5, P7 violated on link-down
- [ ] Exactly P4 violated on the ACL typo
- [ ] I can explain why P8 does not catch the typo
- [ ] The FRR spike verdict is recorded with a date

## 11. Common mistakes

- Writing properties after seeing results. Fatal to the whole exercise.
- Testing reachability with ICMP only. That is precisely the hole in 9.2.
- Believing a passing checklist means a healthy network. In 9.2 six of nine pass.
- Skipping the FRR spike because it is not "part of the module".
- Omitting the layer-1 file and then being surprised when subnet inference
  invents adjacencies you did not build.

## 12. Debugging steps

A property fails and you do not know why:

1. Which layer? Parse → control plane → data plane, in order.
2. `traceroute` the specific flow; find the deciding hop.
3. `differentialReachability` against `m09-corp-base` — what changed?
4. Change **one thing at a time**. Two simultaneous changes and you learn
   nothing from either.

## 13. Mini exercise

Design fault C yourself. Constraint: it must **violate P7 while leaving P4, P5
and P6 all holding** — traffic takes the wrong path and every application still
works.

1. Write it before touching a file. Predict all nine.
2. Build it as `m09-corp-fault-c`.
3. Extend `m09_corp_verify.py` with your expected profile.
4. Then answer, in `surprises.md`: **would any monitoring system notice?**

That last question is the one worth thinking about for ten minutes.

## 14. Completion checklist

- [ ] I designed and drew the topology unaided from the configs
- [ ] I froze the nine properties before running anything
- [ ] I predicted both faults in writing beforehand
- [ ] I built a third fault myself
- [ ] I can explain why P8 catches Module 7's bug and not Module 9's
- [ ] The FRR spike has run and its verdict is recorded
- [ ] `m09_corp_verify.py` passes

---

# MODULE 10 — Limitations

## 1. Learning objective

State exactly where Batfish's guarantee ends, and demonstrate three boundaries
rather than asserting them.

## 2. Why we are doing it

A verifier you trust past its boundary is more dangerous than no verifier at all.
This is the most important module in Phase 1 and the shortest to run.

## 3. Theory — the one sentence

> Batfish is **sound** with respect to the question you asked and the model it
> builds. It is not, and does not claim to be, a model of your network.

Three load-bearing parts, one demonstration each.

### The framing that gets this wrong

People say "the verifier was wrong." Almost always one of these happened
instead:

- **(a) Specification incompleteness.** The property that would have caught it
  was never written. Batfish proved what it was told to prove, soundly, and the
  network is still down.
- **(b) Model scope.** Batfish computes the network *after* routing settles. It
  does not model the 5–60 seconds of reconvergence during which routes flap and
  packets drop. Out of scope by design, not a defect.
- **(c) Model versus device.** Batfish models how devices *interpret*
  configuration, which is what lets it scale. Real hardware has ECMP hashing,
  TCAM limits, timer interactions and platform quirks the model does not
  reproduce.

None of these is a bug in Batfish, and this distinction matters more than it
might seem — a claim that the verifier is unsound is simply false, and everything
built on that claim collapses.

## 4–5. Folder structure and files

Uses `m09-corp-link-down`, `m05-trio-ospf`, and `m10-acl-blocks-ospf` — the last
being `m05-trio-ospf` with the ACL applied **inbound on r3's transit interface**
instead of outbound on the LAN side.

## 6. Commands to run

```powershell
python m10_limitations.py
```

## 7–8. Code and configuration

`m10_limitations.py`. Sections 10.4 and 10.5 are text you should read at the
terminal and then re-read in the source.

## 9. Expected output

**10.1 — the question you asked.** On `m09-corp-link-down`, an ICMP-only
reachability check **passes**. HTTPS is completely broken. Batfish was not wrong;
it was never asked. The failure is in the **specification**, not the verifier —
and no amount of improving Batfish fixes it.

**10.2 — converged steady state only.** `m09-corp-base` and `m09-corp-link-down`
are two static pictures, before and after. Between them live the OSPF dead
interval (typically 40 s), LSA flooding, every router re-running Dijkstra at
slightly different moments, FIB reprogramming lagging the RIB, micro-loops, and
BGP hold timers. For those seconds, packets drop and loop.

A change can be provably correct in the before state and the after state and
still cause a real, user-visible outage in between.

There is no query that demonstrates this, and **that absence is the
demonstration**. Try to think of one before moving on.

**10.3 — the model is not the device.** `m10-acl-blocks-ospf` applies
`deny ip any any` inbound on r3's transit interface. On real hardware this breaks
OSPF: hellos are IP protocol 89 to 224.0.0.5, they arrive inbound on that
interface, and the deny eats them. The adjacency drops within the dead interval
and r3 loses every route.

Batfish's verdict is **identical with and without the ACL**. It still reports the
adjacency established and r3's OSPF routes present. Its control-plane simulation
checks configuration compatibility — area, network type, MTU, timers, subnet — it
does not run adjacency-forming packets through data-plane filters.

Note the **direction** of the error: Batfish is *optimistic*. It says "fine"
about something that is broken. That direction is the dangerous one, and it is a
property of the model boundary, not a defect.

You cannot check this claim yet. Later, in an emulated lab, you will be able to.
Do check it. Do not take the script's word for it.

**10.4 — the inventory.** Printed in full by the script, in three categories that
must not be blurred: out of scope by design, model versus device, and
specification incompleteness.

**10.5 — why it was built this way.** Testing a firewall by sending traffic would
require enumerating 2³² × 2³² × 2¹⁶ × protocols. Not a large number — an
impossible one. So Batfish encodes the network as logic: configuration becomes
constraints, a question becomes a formula, a solver looks for a satisfying
assignment. The answer covers the entire header space at once, in seconds, on a
laptop.

Enormous win, exact price: **the formula only contains what the model contains.**
Time is not in it. Hardware is not in it. Traffic is not in it. Anything the
parser dropped is not in it.

## 10. Verification

Write these in your own words, in `notes/`, without looking at the script:

- [ ] Why Batfish does not send packets
- [ ] Why the analysis is mathematical rather than empirical
- [ ] Why Batfish only verifies the properties you ask for
- [ ] Why Batfish can disagree with a running network, and the three distinct
      reasons
- [ ] Why "Batfish has bugs" is the wrong description of all three

If you can write that page unaided, Phase 1 is complete.

## 11. Common mistakes

- Saying "the verifier was wrong" when the specification was incomplete.
- Blurring the three categories. They have different fixes: category (a) is fixed
  by writing more properties, (b) by a different tool entirely, (c) by testing
  against something that actually runs.
- Treating a passing verification as a passing network.
- Reading an empty DataFrame as proof without checking parse health.

## 12. Debugging steps

Not a debugging module. But the habit it should leave you with: whenever a
verification passes, ask **"what did I not ask?"** before you ask "is it right?"

## 13. Mini exercise

1. Take `m09-corp-base` and write down five properties that are true of it and
   are **not** in P1–P9.
2. For each, construct a config change that violates it while all of P1–P9
   continue to hold.
3. Build the easiest one. Confirm the checklist still passes.
4. Now the real question, for `surprises.md`: **how would you ever have known to
   write that property?**

There is no clean answer. Sitting with that is the point of the exercise.

## 14. Completion checklist

- [ ] I can state the one-sentence guarantee and unpack all three of its parts
- [ ] I can name the three categories of limitation and give an example of each
- [ ] I demonstrated the ACL-blocks-OSPF divergence and understand the direction
      of the error
- [ ] I wrote the Module 10 verification page in my own words
- [ ] I built a property outside P1–P9 and violated it undetected
- [ ] `m10_limitations.py` passes

---

# Phase 1 completion

## Run everything

```powershell
python run_all.py
```

Expected: nine `PASS` rows and `Phase 1 environment verified end to end.`

## Deliverables

- [ ] Working Batfish environment, image digest recorded
- [ ] Fifteen snapshots that all parse cleanly
- [ ] Nine module scripts, all passing
- [ ] `notes/lab-notebook.md` with a dated entry per session
- [ ] `notes/surprises.md` with at least five entries
- [ ] Three faults of your own design (Modules 8, 9, 10 exercises)
- [ ] FRR spike verdict recorded with a date
- [ ] The Module 10 limitations page in your own words

## The Phase 1 report

Write `batfish/docs/PHASE1-REPORT.md`. Six sections, roughly three to five pages:

1. **Environment** — architecture diagram, versions, image digest
2. **Method** — snapshot structure, the sanity gate, the question families
3. **Our network** — the Module 9 topology, the nine properties, why each
4. **Results** — the base verification, both faults, which properties fired
5. **Limitations** — the three categories, with your own demonstration of each
6. **Open questions** — what you now want to know and cannot answer yet

Section 6 matters more than it looks. Write it as questions, not conclusions.

## Self-assessment — answer without notes

1. What are the six things Batfish builds from a snapshot, in order?
2. Which two are deferred, and why?
3. What does "zero rows from a reachability question" prove? What does it not?
4. Name the nine dispositions and a cause for each.
5. What is the route selection order, and which step is decided first?
6. What can `filterLineReachability` find that `testFilters` cannot, and why?
7. Give a network that is severely broken and passes an ICMP reachability check.
8. Name the three categories of Batfish limitation and one example of each.
9. Why is "Batfish gives wrong answers" the wrong description of all three?
10. Where do FRR interface IP addresses live, and what happens if you feed
    Batfish only `frr.conf`?

Any answer you cannot give unaided points at the module to redo.

---

## Sources

- [Batfish getting started (pybatfish docs)](https://batfish.readthedocs.io/en/latest/getting_started.html)
- [Vendor and supplemental data formats — including the Cumulus/FRR concatenated markers](https://batfish.readthedocs.io/en/latest/formats.html)
- [batfish/docker — the allinone container](https://github.com/batfish/docker)
- [pybatfish on PyPI](https://pypi.org/project/pybatfish/)
