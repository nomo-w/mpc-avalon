# Networked Avalon Secure Protocol Prototype


## Current Scope

- 5 to 10 players, with 5-player games prioritized.
- Roles: Merlin, Assassin, Minion of Mordred, Loyal Servant of Arthur.
- One central game server for public state.
- One command-line client per player.
- Secure role assignment between clients with a Mental Poker style protocol.
- Mission voting with GMW and OT.
- `Success = 0`, `Fail = 1`.
- Threshold 1 and threshold 2 mission rules.
- Team proposal, team approval, leader rotation, five rejected teams, mission
  scoring, assassination, and game over.

Not included: GUI, web UI, database, user accounts, multiple rooms.

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run On One Computer

Open one terminal for the server:

```bash
python server.py --host 127.0.0.1 --port 8765 --players 5
```

Open five more terminals, using one unique MPC port per client:

```bash
python client.py --host 127.0.0.1 --port 8765 --name Alice --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11000
python client.py --host 127.0.0.1 --port 8765 --name Bob --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11001
python client.py --host 127.0.0.1 --port 8765 --name Charlie --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11002
python client.py --host 127.0.0.1 --port 8765 --name David --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11003
python client.py --host 127.0.0.1 --port 8765 --name Eve --advertise-host 127.0.0.1 --listen-host 127.0.0.1 --mpc-port 11004
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
connections, but any player may be selected on a later mission.

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

## Secure Role Assignment

Role assignment is always secure in the current version. The server does not
generate and send the full role list. It only sends public information, such as
the player order and peer-to-peer addresses.

The role assignment flow is:

1. The server broadcasts `start_secure_role_assignment`.
2. All clients build the same role deck for the player count.
3. Player 0 encrypts and shuffles the deck, then broadcasts it.
4. Player 1 receives that deck and does the same thing, then the next player
   continues.
5. After all players have added one layer, card position `i` belongs to player
   `i`.
6. For each card, the other players help remove their own encryption layer.
7. Only the owner removes the last layer and learns that role card.
8. Clients run a GMW Boolean circuit for private role information.
9. Each client sends only `role_assignment_done` to the server.

The role information circuit uses two private bits for each player:

```text
is_merlin
is_evil
```

For each viewer and target, it checks whether the viewer should see the target
as evil. Merlin can see evil players. Evil players can see other evil players.

During the game, the role stays local inside each client. For example, a good
client only submits Success for mission voting, and only the local Assassin
answers the assassination prompt.

At assassination time, the server still does not know Merlin's identity. The
selected target only answers one Boolean question: `is_merlin`. This is enough
to decide whether Good or Evil wins.

At game over, roles are public in Avalon, so clients reveal their final roles
for the final role table. The server checks that the revealed role multiset
matches the normal Avalon role list.

Important files:

```text
avalon/protocols/role_assignment/mental_poker_crypto.py
    commutative modular encryption helper used by role assignment

avalon/protocols/role_assignment/network_mental_poker.py
    peer-to-peer encrypted role assignment

avalon/protocols/role_assignment/secure_role_information.py
    GMW calculation for Merlin and evil private information

avalon/protocols/role_assignment/role_information.py
    small helper for role bits and private role text

avalon/protocols/mission_voting/secure_vote/gmw.py
    shared GMW runtime; role information uses reveal_to_party()
```

Security note: this is still a semi-honest prototype. It assumes clients follow
the protocol steps. It is meant to show the secure protocol idea for this
project, not to stop a modified malicious client.

## Project Layout

```text
server.py                         central game server
client.py                         one CLI client per player
avalon/game/                      rules, roles, state machine validation
avalon/networking/                newline-delimited JSON helpers
avalon/protocols/role_assignment/ Mental Poker role assignment and role info
avalon/protocols/mission_voting/  mission voting interface and GMW adapter
avalon/protocols/mission_voting/secure_vote/
                                  custom Boolean GMW + RSA-OT implementation
```
