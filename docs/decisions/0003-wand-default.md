# 0003: Wand is the default app

Date: 2026-10-11. Status: accepted (Tom: "Go, but default to Wand").

WeMod 12.x is called Wand. It is still served from WeMod's CDN
(`storage-cdn.wemod.com`) and listed in Scoop as `wand.json`. Upstream says
11.x will soon reach end of life (upstream PR #318).

- `app = "wand"` by default; `"wemod"` remains for the 11.x client.
- Checked on the real Wand 12.62.0 package by reading only the zip listing
  and `package.json`: same `lib/net45/` layout, ships `Wand.exe` (plus a
  `WeMod.exe` stub), and Electron `productName` is `Wand`, so its login
  should live in `AppData/Roaming/Wand`.
- Both `Roaming/Wand` and `Roaming/WeMod` link to central folders, so Wand
  can find an old WeMod login if it migrates one.
- The Scoop manifest's SHA-256 is verified on download already (planned for
  Phase 3, but free here).

To check on the Deck: the login persists across two games.
