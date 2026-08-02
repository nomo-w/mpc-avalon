# Networked Trustless Avalon Prototype


## Current Scope

- 5 to 10 players, with 5-player games prioritized.
- Roles: Merlin, Assassin, Minion of Mordred, Loyal Servant of Arthur.
- One central game server for public state.
- One command-line client per player.
- Two role assignment modes:
  - `trusted`: old server-side role shuffle, useful for debugging.
  - `mental-poker`: secure role dealing between clients.
- Mission voting through custom GMW + OT by default.
- `Success = 0`, `Fail = 1`.
- Threshold 1 and threshold 2 mission rules.
- Team proposal, team approval, leader rotation, five rejected teams, mission
  scoring, assassination, and game over.

Not included: GUI, web UI, database, user accounts, multiple rooms.

## Install

Requires Python 3.11+.

## Run On One Computer

Open one terminal for the server:

```bash
python server.py --host SERVER_IP --port SERVER_PORT --players NUMBER_OF_PLAYER --role-protocol mental-poker
```

Open five more terminals, using one unique MPC port per client:

```bash
python client.py --host SERVER_IP --port SERVER_PORT --name PLAYER_NAME --advertise-host PLAYER_IP --listen-host 0.0.0.0 --mpc-port 11000
python client.py --host SERVER_IP --port SERVER_PORT --name PLAYER_NAME --advertise-host PLAYER_IP --listen-host 0.0.0.0 --mpc-port 11001
python client.py --host SERVER_IP --port SERVER_PORT --name PLAYER_NAME --advertise-host PLAYER_IP --listen-host 0.0.0.0 --mpc-port 11002
python client.py --host SERVER_IP --port SERVER_PORT --name PLAYER_NAME --advertise-host PLAYER_IP --listen-host 0.0.0.0 --mpc-port 11003
python client.py --host SERVER_IP --port SERVER_PORT --name PLAYER_NAME --advertise-host PLAYER_IP --listen-host 0.0.0.0 --mpc-port 11004
```

## Run On A LAN

Assume the server computer has IP `192.168.1.20`.

Server:

```bash
python server.py --host 0.0.0.0 --port 8765 --players 5 --role-protocol mental-poker
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

The secure role assignment mode is enabled with:

```bash
python server.py --players 5 --role-protocol mental-poker
```

In this mode the server does not shuffle and send roles. It only gives every
client the public player order and the peer-to-peer MPC addresses.

The role assignment flow is:

1. The server broadcasts `start_secure_role_assignment`.
2. All clients build the same role deck for the player count.
3. Each client encrypts and shuffles the deck once.
4. For card `i`, all clients help remove their encryption layer.
5. Only player `i` removes the final layer and learns that role card.
6. Clients run a GMW Boolean circuit for private role information.
7. Each client sends only `role_assignment_done` to the server.

During the game, the role stays local inside each client. For example, a good
client only submits Success for mission voting, and only the local Assassin
answers the assassination prompt.

At assassination time in `mental-poker` mode, the server still does not know
Merlin's identity. The selected target only answers one Boolean question:
`is_merlin`. This is enough to decide whether Good or Evil wins.

At game over, roles are public in Avalon, so clients reveal their final roles
for the final role table. The server checks that the revealed role multiset
matches the normal Avalon role list.

Important files:

```text
avalon/protocols/role_assignment/mental_poker_crypto.py
    small commutative encryption helper used by Mental Poker

avalon/protocols/role_assignment/network_mental_poker.py
    peer-to-peer encrypted role dealing

avalon/protocols/role_assignment/secure_role_information.py
    GMW computation for Merlin/evil private information

avalon/protocols/role_assignment/role_information.py
    plain Boolean role-information rules used by trusted and secure modes

avalon/protocols/mission_voting/secure_vote/gmw.py
    shared GMW runtime; role information uses reveal_to_party()
```

This is a semi-honest prototype. The code assumes clients follow the protocol.
It is intended to demonstrate the protocol idea for the project, not to stop a
modified malicious client.

## Project Layout

```text
server.py                         central game server
client.py                         one CLI client per player
avalon/game/                      rules, roles, state machine validation
avalon/networking/                newline-delimited JSON helpers
avalon/protocols/role_assignment/ trusted and Mental Poker role assignment
avalon/protocols/mission_voting/  mission voting interface and GMW adapter
avalon/protocols/mission_voting/secure_vote/
                                  custom Boolean GMW + RSA-OT implementation
```
