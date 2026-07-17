# Networked Trustless Avalon Prototype

This is a playable command-line Avalon game for one server and multiple player
clients. The current role assignment is trusted, but mission voting uses the
custom Boolean GMW + RSA-OT protocol copied from the secure mission-voting
prototype.

The normal game path does not send plaintext mission votes to the server.

## Current Scope

- 5 to 10 players, with 5-player games prioritized.
- Roles: Merlin, Assassin, Minion of Mordred, Loyal Servant of Arthur.
- One central game server for public state.
- One command-line client per player.
- Trusted role assignment through a replaceable protocol interface.
- Mission voting through custom GMW + OT by default.
- `Success = 0`, `Fail = 1`.
- Threshold 1 and threshold 2 mission rules.
- Team proposal, team approval, leader rotation, five rejected teams, mission
  scoring, assassination, and game over.

Not included: GUI, web UI, database, user accounts, multiple rooms, TLS,
malicious security, NAT traversal, Mental Poker, or advanced Avalon roles.

## Install

Requires Python 3.11+.

macOS/Linux:

```bash
cd outputs/avalon_networked
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
cd outputs\avalon_networked
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For tests:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Run On One Computer

Open one terminal for the server:

```bash
python server.py --host 127.0.0.1 --port 8765 --players 5
```

Open five more terminals, using one unique MPC port per client:

```bash
python client.py --host 127.0.0.1 --port 8765 --name Alice --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11000
python client.py --host 127.0.0.1 --port 8765 --name Bob   --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11001
python client.py --host 127.0.0.1 --port 8765 --name Carol --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11002
python client.py --host 127.0.0.1 --port 8765 --name Dave  --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11003
python client.py --host 127.0.0.1 --port 8765 --name Eve   --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11004
```

## Run On A LAN

Assume the server computer has IP `192.168.1.20`.

Server:

```bash
python server.py --host 0.0.0.0 --port 8765 --players 5
```

Each player runs one client on their own computer. `--advertise-host` must be
that player's LAN IP, not the server IP:

```bash
python client.py \
  --host 192.168.1.20 \
  --port 8765 \
  --name Alice \
  --advertise-host 192.168.1.31 \
  --listen-host 0.0.0.0 \
  --mpc-port 11000
```

Every client should use an MPC port that is reachable by other clients. During
one mission vote, only the selected mission team opens peer-to-peer GMW/OT
connections, but any player may be selected on a later mission. On a LAN this
usually means allowing inbound connections for the chosen `--mpc-port` in the
operating-system firewall.

## Gameplay Notes

- The server assigns player IDs in join order.
- The current leader chooses a team by player ID.
- Everyone votes to approve or reject the team.
- Team approval votes are public: clients show who approved and who rejected.
- If a team is approved, mission team members first enter private mission votes.
- The mission team list is public and shown before the secure mission vote.
- The server receives only a readiness message, not the vote.
- After all mission team members are ready, those mission team clients run the
  GMW + OT computation.
- Good players can only submit Success.
- Evil players can submit Success or Fail.
- The server receives only the final `mission_failed` Boolean result.
- After three successful missions, the Assassin chooses a target.

## Common Errors

- `MPC endpoint is already in use`: two clients used the same `--advertise-host`
  and `--mpc-port`.
- `could not connect to party`: a client advertised the wrong IP, a firewall
  blocked the MPC port, or one client was started late.
- `Game has already started`: all expected players already joined.
- Clients hang during secure mission voting: check that every client can accept
  inbound TCP connections on its advertised MPC port.

## Project Layout

```text
server.py                         central game server
client.py                         one CLI client per player
avalon/game/                      rules, roles, state machine validation
avalon/networking/                newline-delimited JSON helpers
avalon/protocols/role_assignment/ replaceable role assignment interface
avalon/protocols/mission_voting/  mission voting interface and GMW adapter
avalon/protocols/mission_voting/secure_vote/
                                  custom Boolean GMW + RSA-OT implementation
tests/                            unit and integration tests
```

## Security Scope

The mission vote protocol is a teaching prototype under a semi-honest model. It
does not provide malicious security, TLS, endpoint authentication, OT extension,
or side-channel hardening. It is intentionally kept small and readable for the
dissertation project.
