# reference/

`install-wemod-launcher.sh` is the installer Tom wrote and field-tested on his
Steam Deck (SteamOS 3.x, native Steam) against upstream wemod-launcher 1.543.

It is kept **verbatim** as the spec for install behaviour: GE-Proton asset naming,
the `releases/latest` tag lookup, the "WeMod + GE-Proton" compat tool that drops
`require_tool_appid` and starts the Steam Linux Runtime itself, and the verb
routing (only `waitforexitandrun` goes through WeMod).

Do not edit it. The repo's own `install.sh` (Phase 1) is ported from it.
It is excluded from shellcheck in CI for that reason.
